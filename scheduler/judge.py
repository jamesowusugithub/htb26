"""Judge mode: a visitor submits ONE workload and sees how fast each manager (FIFO, priority, predicted-runtime rule, trained RL) would have completed it.

The workload is injected (as ORDER-001, at minute 45, when the queue is building) into a busy demo kitchen replaying REAL Alibaba trace jobs; every manager schedules the same jobs.
Times are simulated minutes. Nothing here is a measurement of a real cluster.
"""
from __future__ import annotations
import threading, time
from collections import deque
from fastapi import HTTPException
from pydantic import BaseModel, Field

POLICIES = ("fifo", "priority_fifo", "sjf_hint", "rl_ppo")
LABEL = {"fifo": "First come, first served", "priority_fifo": "Priority first", "sjf_hint": "Shortest predicted job", "rl_ppo": "Trained RL"}
# a busy mixed kitchen: chef = node. Largest job a type can take = its node size.
KITCHEN = [{"pool": "a10", "gpus": 4}, {"pool": "a100", "gpus": 8}, {"pool": "a100", "gpus": 8}, {"pool": "a800", "gpus": 8}, {"pool": "h800", "gpus": 8}]
NODE_GPUS = {"a10": 4, "a100": 8, "a800": 8, "h800": 8}
TYPE_LABEL = {"a10": "NVIDIA A10", "a100": "NVIDIA A100 80GB", "a800": "NVIDIA A800", "h800": "NVIDIA H800"}
START_DAY, WINDOW_MIN, ARRIVE_MIN = 133.0, 480.0, 45.0


class JudgeJob(BaseModel):
    gpu_type: str = Field("a100", description="a10, a100, a800 or h800")
    gpus: int = Field(2, ge=1, le=8)
    priority: str = Field("high", pattern="^(high|spot)$")
    duration_min: int = Field(30, ge=1, le=240, description="how long the job runs once started (minutes)")


_board: deque = deque(maxlen=200)
_lock = threading.Lock()


def run(job: JudgeJob, restaurant, RestaurantReq, OrderIn, KitchenIn) -> dict:
    if job.gpu_type not in NODE_GPUS:
        raise HTTPException(422, f"gpu_type must be one of {list(NODE_GPUS)}")
    if job.gpus > NODE_GPUS[job.gpu_type]:
        raise HTTPException(422, f"a {TYPE_LABEL[job.gpu_type]} node has {NODE_GPUS[job.gpu_type]} GPUs; ask for at most that many")
    base = RestaurantReq(start_day=START_DAY, minutes=WINDOW_MIN, kitchen=[KitchenIn(**c) for c in KITCHEN],
                         orders=[OrderIn(at_min=ARRIVE_MIN, gpus=job.gpus, priority=job.priority, duration_min=job.duration_min, pool=job.gpu_type)])
    out = {}
    for pol in POLICIES:
        rec = restaurant(base.model_copy(update={"policy": pol}))
        ev = rec["events"]
        arrive = next((e["t"] for e in ev if e["type"] == "JOB_ARRIVED" and e["job"]["id"] == "ORDER-001"), None)
        starts = [e for e in ev if e["type"] == "JOB_STARTED" and e["job_id"] == "ORDER-001"]
        evict = sum(1 for e in ev if e["type"] == "JOB_FAILED" and e["job_id"] == "ORDER-001")
        if arrive is None or not starts:
            out[pol] = {"label": LABEL[pol], "started": False, "wait_min": None, "finish_min": None, "turnaround_min": None, "ran_on": None, "evictions": evict}
            continue
        st = starts[-1]; start_t = st["t"] - 0
        gpu_id = st["gpu_ids"][0]
        cloud = gpu_id.startswith("cloud")
        ran_on = "the simulated cloud takeaway" if cloud else next((g["name"] for n in rec["config"]["nodes"] for g in n["gpus"] if g["id"] == gpu_id), gpu_id)
        wait = max(0.0, start_t - arrive)
        out[pol] = {"label": LABEL[pol], "started": True, "wait_min": round(wait, 1), "finish_min": round(start_t + job.duration_min, 1),
                    "turnaround_min": round(wait + job.duration_min, 1), "ran_on": ran_on, "evictions": evict}
    done = {k: v for k, v in out.items() if v["started"]}
    best = min(done, key=lambda k: done[k]["turnaround_min"]) if done else None
    res = {"job": job.model_dump(), "arrives_at_min": ARRIVE_MIN, "window_min": int(WINDOW_MIN + 60), "results": out, "best": best,
           "kitchen": ", ".join(f"{TYPE_LABEL[c['pool']]} x{c['gpus']}" for c in KITCHEN),
           "note": "Simulated minutes on a small demo kitchen replaying real Alibaba trace jobs. Every manager faces the same jobs; your workload arrives at minute 45, when the cluster is busy."}
    if "rl_ppo" in done and "fifo" in done:
        f, r = done["fifo"]["turnaround_min"], done["rl_ppo"]["turnaround_min"]
        res["rl_vs_fifo_pct_faster"] = round(100.0 * (f - r) / f, 1) if f > 0 else 0.0
        with _lock:
            _board.appendleft({"t": time.time(), "gpus": job.gpus, "type": job.gpu_type, "priority": job.priority, "rl_wait": done["rl_ppo"]["wait_min"], "fifo_wait": done["fifo"]["wait_min"],
                               "rl_turnaround": r, "fifo_turnaround": f})
    return res


def board() -> dict:
    with _lock:
        rows = list(_board)
    n = len(rows)
    return {"submissions": n, "recent": [{k: v for k, v in r.items() if k != "t"} for r in rows[:10]],
            "avg_rl_turnaround_min": round(sum(r["rl_turnaround"] for r in rows) / n, 1) if n else None,
            "avg_fifo_turnaround_min": round(sum(r["fifo_turnaround"] for r in rows) / n, 1) if n else None}
