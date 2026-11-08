"""HTTP/WebSocket service for the frontend.

    uvicorn scheduler.api:app --reload --port 8000        # docs at http://localhost:8000/docs

All waits/starts/evictions are SIMULATED; every response carries the assumptions list so the UI can label them.
"""
from __future__ import annotations
import asyncio, bisect, json, math, threading, time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import data
from .export import export_ndjson, SCHEMA_VERSION
from .display import Display, DEFAULT_PODS
from .thermal import ThermalProxy
from .forecast import SurvivalCurves
from . import demand_forecast as dfc
from .metrics import timeline
from .policies import POLICIES
from .run_baselines import setup
from .whatif import PRESETS, Scenario, run_scenario, compare_table
from .env import SchedulingEnv
from . import restaurant_export as rx
from .eval_rl import run_agent
from .duration_model import load_or_fit

import os
import json
_MODELS = Path(__file__).resolve().parents[1] / "models"
# u6 = trained with randomly permuted candidate slots (slot position carries no information); s12 had the best validation score. Override with HTB_RL_MODEL
RL_MODEL = Path(os.environ["HTB_RL_MODEL"]) if os.environ.get("HTB_RL_MODEL") else next(
    (p for p in (_MODELS / "ppo_u6_shuf_s12/best.zip", _MODELS / "ppo_u6_shuf_s13/best.zip", _MODELS / "ppo_u6_shuf_s11/best.zip", _MODELS / "ppo_u4_hpfirst_s11/best.zip") if p.exists()), _MODELS / "ppo_u6_shuf_s12/best.zip")
RL_NAME = "rl_ppo"
_rl: dict = {}
_thermal: dict = {}

RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"
MAX_DAYS = 7.0
MAX_CACHED_RUNS = 16

app = FastAPI(title="GPU Scheduling Lens", version=SCHEMA_VERSION,
              description="Replay the Alibaba GPU trace through a simulated cluster and compare schedulers under what-if scenarios.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()
_env: dict[str, Any] = {}
_runs: "OrderedDict[str, RunIndex]" = OrderedDict()
_results: dict[str, dict] = {}


class RunIndex:
    """An exported run held in memory: lines sorted by time, with a parsed time index."""
    def __init__(self, path: Path):
        self.path = path
        self.meta: dict = {}
        self.times: list[float] = []
        self.lines: list[str] = []
        self.types: list[str] = []
        self.objs: list[dict] = []
        with open(path) as f:
            for k, line in enumerate(f):
                o = json.loads(line)
                if k == 0:
                    self.meta = o
                    continue
                self.times.append(o["t"])
                self.lines.append(line.rstrip("\n"))
                self.types.append(o["type"])
                self.objs.append(o)

    def state_at(self, t: float) -> dict:
        """Authoritative replay state at time t, so a client can jump (seek / what-if re-run) without replaying events."""
        j = bisect.bisect_right(self.times, t)
        running: dict[str, dict] = {}
        queued: dict[str, dict] = {}
        last_snap = None
        down_nodes: dict[int, int] = {}
        for o in self.objs[:j]:
            typ = o["type"]
            if typ == "snapshot":
                last_snap = o
            elif typ == "arrive":
                queued[o["job"]] = {"job": o["job"], "pool": o["pool"], "priority": o["priority"], "gpus": o["gpus"], "t": o["t"]}
            elif typ == "start":
                queued.pop(o["job"], None)
                running[o["job"]] = {"job": o["job"], "pool": o["pool"], "board": o.get("board"), "gpus": o["gpus"],
                                     "priority": o["priority"], "start_t": o["t"], "service_s": o["service_s"], "attempt": o["attempt"]}
            elif typ == "finish":
                running.pop(o["job"], None)
            elif typ == "preempt":
                r = running.pop(o["job"], None)
                if r:
                    queued[o["job"]] = {"job": o["job"], "pool": o["pool"], "priority": r["priority"], "gpus": r["gpus"], "t": o["t"]}
        return {"t": t, "snapshot": last_snap, "running": list(running.values()), "queued_total": len(queued),
                "queued_sample": list(queued.values())[:200]}

    def slice(self, t0: float, t1: float, types: set[str] | None):
        i = bisect.bisect_left(self.times, t0)
        j = bisect.bisect_right(self.times, t1)
        for k in range(i, j):
            if types is None or self.types[k] in types:
                yield self.lines[k]


def _json_safe(o):
    """NaN/inf are not valid JSON (e.g. spot wait in a pool with no spot jobs): send null instead."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


def thermal() -> ThermalProxy:
    if "p" not in _thermal:
        _thermal["p"] = ThermalProxy.load()
    return _thermal["p"]


def rl_policy():
    """Lazy-load the trained masked-PPO policy (behaviour-cloned from the hint heuristic, PPO fine-tuned)."""
    if "model" not in _rl:
        if not RL_MODEL.exists():
            raise HTTPException(422, f"{RL_NAME} unavailable: {RL_MODEL.name} not found")
        from sb3_contrib import MaskablePPO
        _rl["model"] = MaskablePPO.load(RL_MODEL, device="cpu")
        dim = int(_rl["model"].observation_space.shape[0])
        _rl["K"] = (dim - 12) // 8                      # obs = 6 pool one-hot + 6 globals + 8 features per candidate slot
        try:                                            # models trained with shuffled candidate slots must be served with shuffled slots
            _rl["shuffle"] = bool(json.loads((RL_MODEL.parent / "history.json").read_text())["args"].get("shuffle", False))
        except (OSError, ValueError, KeyError):
            _rl["shuffle"] = False
    return _rl["model"]


def env():
    with _lock:
        if not _env:
            pools, jobs, base, cluster = setup(0.85)
            _env.update(pools=pools, jobs=jobs, base=base, cluster=cluster)
        return _env


@app.on_event("startup")
def _startup():
    env()


# ---------------------------------------------------------------------------- models
class WhatIfRequest(BaseModel):
    preset: str | None = Field(None, description="Name from GET /presets; overridden by `scenario` fields")
    scenario: dict | None = Field(None, description="Scenario fields (see GET /presets for examples)")
    policies: list[str] = Field(default_factory=lambda: ["fifo", "priority_fifo", "backfill_median", "sjf_oracle"])
    snapshot_s: float = Field(60.0, ge=10, description="Seconds between snapshot lines in the exported run")


def _scenario_from(req: WhatIfRequest) -> Scenario:
    d: dict = {}
    if req.preset:
        if req.preset not in PRESETS:
            raise HTTPException(404, f"unknown preset {req.preset!r}")
        d.update(PRESETS[req.preset].to_dict())
    if req.scenario:
        d.update(req.scenario)
    sc = Scenario.from_dict(d)
    if not (0 < sc.days <= MAX_DAYS):
        raise HTTPException(422, f"days must be in (0, {MAX_DAYS}]")
    return sc


# ---------------------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


@app.get("/meta")
def meta():
    e = env()
    cl = e["cluster"]
    return {"schema_version": SCHEMA_VERSION, "time_unit": "seconds_since_window_start",
            "pools": [{"id": p["id"], "label": p["label"], "identity": p["identity"],
                       "nodes": int(cl.node_counts()[i]), "capacity_gpus": float(cl.capacity_gpus()[i]),
                       "observed_nodes": int(e["base"].node_counts()[i]), "scale_vs_observed": float(cl.scale[i])}
                      for i, p in enumerate(e["pools"])],
            "policies": [{"name": s.name, "realistic": s.realistic, "description": s.description} for s in POLICIES.values()]
            + ([{"name": RL_NAME, "realistic": True, "description": f"Learned scheduler: masked PPO over hint-ranked candidates ({RL_MODEL.parent.name}; see analysis/rl)"}]
               if RL_MODEL.exists() else []),
            "assumptions": data.load_assumptions()["items"],
            "trace_days": float(e["jobs"].submit_relative_s.max() / 86400),
            "display": Display().describe(cl), "thermal": thermal().meta(),
            "scenario_controls": {"burst": "arrival spike", "failures": "board (node slice) failure with optional repair",
                                  "cooling_fault": "ambient shift on every board", "injected_jobs": "single job at a chosen time",
                                  "time_unit": "hours since window start"},
            "websocket": "/runs/{run_id}/stream?speed=600&start=0&paused=false sends meta, then {type:'batch', t_from, t_to, speed, paused, items:[...]} then {type:'end'}; "
                         "send {cmd:'pause'|'resume'|'speed'(value)|'seek'(t)} to control it"}


@app.get("/presets")
def presets():
    return [{"name": k, **v.to_dict()} for k, v in PRESETS.items()]


@app.post("/whatif")
def whatif(req: WhatIfRequest):
    sc = _scenario_from(req)
    bad = [p for p in req.policies if p not in POLICIES and p != RL_NAME]
    if bad:
        raise HTTPException(422, f"unknown policies {bad}; choose from {list(POLICIES)}")
    key = f"{sc.scenario_id}-{req.snapshot_s:g}-{','.join(req.policies)}"
    if key in _results:
        return _results[key]
    e = env()
    t0 = time.time()
    with _lock:
        sim_policies = [p for p in req.policies if p != RL_NAME]
        try:
            res = run_scenario(sc, e["jobs"], e["cluster"], sim_policies, log_events=True, snapshot_dt=req.snapshot_s)
        except (ValueError, KeyError) as ex:
            raise HTTPException(422, f"invalid scenario: {ex}")
        if RL_NAME in req.policies:
            model = rl_policy()
            renv = SchedulingEnv(e["jobs"], e["cluster"], load_or_fit(e["jobs"], 40), K=_rl["K"], shuffle_slots=_rl["shuffle"], log_events=True, snapshot_dt=req.snapshot_s)
            m, _, _ = run_agent(renv, lambda o, mk: model.predict(o, action_masks=mk, deterministic=True)[0], sc)
            res["policies"][RL_NAME] = {"realistic": True, "metrics": m}
            res["_states"][RL_NAME] = renv.S
            res["_rl_workload"] = (renv.w, renv.cluster)
    out_dir = RUNS_DIR / sc.scenario_id
    hint = load_or_fit(e["jobs"], 40)
    surv = SurvivalCurves.fit(e["jobs"], sc.start_day * 86400.0, e["cluster"].n_pools)
    display = Display(tuple(sc.display_pools))
    try:     # demand forecast vs realised arrivals for this scenario (same for every policy); never allowed to break the feed
        dem = dfc.forecast_series(dfc.load_or_fit(e["jobs"], e["cluster"].n_pools), e["jobs"], res["_workload"],
                                  [p["id"] for p in e["cluster"].pools], sc.start_day * 86400.0, sc.days * 86400.0)
    except Exception as ex:                      # noqa: BLE001
        dem = {"available": False, "reason": f"forecast failed: {type(ex).__name__}"}
    results = {}
    for name in req.policies:
        S = res["_states"][name]
        path = out_dir / f"{name}.ndjson"
        w_, c_ = res["_rl_workload"] if name == RL_NAME else (res["_workload"], res["_cluster"])
        spec = POLICIES.get(name)
        hint_est = hint.predict_seconds(w_.job_id)
        export_ndjson(path, S, w_, c_, policy_name=name, realistic=spec.realistic if spec else True,
                      preempt=spec.preempt if spec else True, resume=sc.resume_preempted, window_len_s=sc.days * 86400,
                      display=display, thermal=thermal(), hint_est=hint_est, scenario=sc.to_dict(), survival=surv,
                      extra_meta={"scenario": sc.to_dict(), "scenario_id": sc.scenario_id, "demand_forecast": dem})
        tl = timeline(S, c_)
        tl = tl[tl.t <= sc.days * 86400]
        results[name] = {
            "run_id": f"{sc.scenario_id}-{name}", "realistic": spec.realistic if spec else True,
            "metrics": res["policies"][name]["metrics"],
            "events_url": f"/runs/{sc.scenario_id}-{name}/events", "timeline_url": f"/runs/{sc.scenario_id}-{name}/timeline",
            "stream_url": f"/runs/{sc.scenario_id}-{name}/stream", "state_url": f"/runs/{sc.scenario_id}-{name}/state"}
    cmp_ = compare_table(res).round(4).to_dict(orient="records")
    body = {"scenario_id": sc.scenario_id, "scenario": sc.to_dict(), "workload": res["workload"],
            "comparison": cmp_, "results": results, "compute_seconds": round(time.time() - t0, 2),
            "labels": {"waits": "simulated", "workload": "observed trace window, perturbed per scenario"}}
    body = _json_safe(body)
    _results[key] = body
    return body


def _run(run_id: str) -> RunIndex:
    if run_id in _runs:
        _runs.move_to_end(run_id)
        return _runs[run_id]
    sid, _, policy = run_id.partition("-")
    path = RUNS_DIR / sid / f"{policy}.ndjson"
    if not path.is_file() or ".." in run_id or "/" in run_id:
        raise HTTPException(404, f"unknown run {run_id!r}; POST /whatif first")
    _runs[run_id] = RunIndex(path)
    while len(_runs) > MAX_CACHED_RUNS:
        _runs.popitem(last=False)
    return _runs[run_id]


@app.get("/runs/{run_id}")
def run_meta(run_id: str):
    return _run(run_id).meta


@app.get("/runs/{run_id}/events", response_class=PlainTextResponse,
         description="NDJSON slice of events with t_from <= t <= t_to (one JSON object per line).")
def run_events(run_id: str, t_from: float = Query(0.0), t_to: float = Query(float("inf")),
               types: str | None = Query(None, description="comma list: arrive,start,finish,preempt,snapshot"),
               limit: int = Query(1000000, ge=1)):
    r = _run(run_id)
    tset = set(types.split(",")) if types else None
    out = []
    for line in r.slice(t_from, t_to, tset):
        out.append(line)
        if len(out) >= limit:
            break
    return PlainTextResponse("\n".join(out) + ("\n" if out else ""), media_type="application/x-ndjson")


@app.get("/runs/{run_id}/state")
def run_state(run_id: str, t: float = Query(0.0, ge=0.0)):
    """Replay state at time t: latest snapshot, running jobs (with start/service for progress) and queue totals."""
    return _run(run_id).state_at(t)


@app.get("/runs/{run_id}/timeline")
def run_timeline(run_id: str):
    """Compact per-pool series built from the snapshot lines (for charts)."""
    r = _run(run_id)
    ts, pools = [], {}
    for line, typ in zip(r.lines, r.types):
        if typ != "snapshot":
            continue
        o = json.loads(line)
        ts.append(o["t"])
        for pid, v in o["pools"].items():
            d = pools.setdefault(pid, {k: [] for k in v})
            for k, x in v.items():
                d[k].append(x)
    return {"t": ts, "pools": pools}


@app.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str, speed: float = 600.0, start: float = 0.0, tick: float = 0.1,
                 paused: bool = False):
    """Paced replay. Clock = trace seconds; `speed` trace-seconds per real second. Client controls:
    {cmd:'pause'} {cmd:'resume'} {cmd:'speed', value:N} {cmd:'seek', t:T} (client fetches /state?t=T first)."""
    await ws.accept()
    try:
        r = _run(run_id)
    except HTTPException as ex:
        await ws.send_json({"type": "error", "detail": ex.detail})
        await ws.close()
        return
    st = {"t": start, "speed": max(speed, 1.0), "paused": paused, "stop": False}

    async def reader():
        try:
            while True:
                m = await ws.receive_json()
                c = m.get("cmd")
                if c == "pause":
                    st["paused"] = True
                elif c == "resume":
                    st["paused"] = False
                elif c == "speed":
                    st["speed"] = max(float(m.get("value", 1)), 1.0)
                elif c == "seek":
                    st["t"] = max(float(m.get("t", 0)), 0.0)
        except (WebSocketDisconnect, RuntimeError):
            st["stop"] = True
    task = asyncio.create_task(reader())
    try:
        await ws.send_json(r.meta)
        end = r.times[-1] if r.times else 0.0
        while not st["stop"] and st["t"] <= end:
            if st["paused"]:
                await ws.send_json({"type": "tick", "t": st["t"], "paused": True, "speed": st["speed"]})
                await asyncio.sleep(0.25)
                continue
            t0 = st["t"]
            t1 = t0 + st["speed"] * tick
            st["t"] = t1
            items = [json.loads(x) for x in r.slice(t0, t1 - 1e-9, None)]
            await ws.send_json({"type": "batch", "t_from": t0, "t_to": t1, "speed": st["speed"], "paused": False,
                                "items": items})
            await asyncio.sleep(tick)
        if not st["stop"]:
            await ws.send_json({"type": "end"})
            await ws.close()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        task.cancel()


# ------------------------------------------------------------------ restaurant demo (2D animation) -------------------------------------------
class OrderIn(BaseModel):
    at_min: float = Field(0.0, ge=0, description="minutes after the start of the kitchen window")
    gpus: float = Field(1.0, gt=0, le=8)
    priority: str = Field("high", pattern="^(high|spot)$")
    duration_min: float = Field(15.0, ge=1, le=720)


class CloudIn(BaseModel):
    nodes: int = Field(1, ge=0, le=20, description="simulated takeaway nodes")
    gpus_per_node: int = Field(8, ge=1, le=8)
    overflow_wait_min: float = Field(30.0, ge=1, description="a job that has waited this long may be sent to the takeaway")
    price_multiplier: float = Field(1.0, gt=0, le=10)
    max_job_cost_usd: float | None = Field(None, gt=0, description="predicted rental cost cap per job (default from scheduler/cloud.py)")


class RestaurantReq(BaseModel):
    policy: str = "rl_ppo"
    start_day: float = Field(145.0, ge=0, le=183)
    minutes: float = Field(150.0, ge=30, le=480)
    nodes: int = Field(5, ge=2, le=5)
    orders: list[OrderIn] = Field(default_factory=list, max_length=200)
    cloud: CloudIn | None = None


_rest_cache: "OrderedDict[str, dict]" = OrderedDict()


def _restaurant(req: RestaurantReq) -> dict:
    key = req.model_dump_json()
    if key in _rest_cache:
        _rest_cache.move_to_end(key)
        return _rest_cache[key]
    e = env()
    model = rl_policy() if req.policy == RL_NAME or req.policy == "rl_ppo" else None
    cloud = req.cloud.model_dump(exclude_none=True) if req.cloud else None
    try:
        with _lock:
            rec = rx.make_recording(e["jobs"], e["pools"], load_or_fit(e["jobs"], 40), "rl_ppo" if model else req.policy, model, _rl.get("K", 16),
                                    req.start_day, req.minutes, 60.0, req.nodes, [o.model_dump() for o in req.orders], cloud, _rl.get("shuffle", False))
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    _rest_cache[key] = rec
    while len(_rest_cache) > 24:
        _rest_cache.popitem(last=False)
    return rec


@app.post("/restaurant/trace")
def restaurant_trace_post(req: RestaurantReq):
    """Recording for the 2D animation: REAL trace jobs on a small kitchen, scheduled by the chosen policy (the trained RL policy for rl_ppo).
    `orders` are NEW jobs that are not in the trace; `cloud` enables the SIMULATED takeaway fallback (configurable capacity and price)."""
    return _restaurant(req)


@app.get("/restaurant/trace")
def restaurant_trace_get(policy: str = "rl_ppo", takeaway: bool = True):
    return _restaurant(RestaurantReq(policy=policy, cloud=CloudIn() if takeaway else None))
