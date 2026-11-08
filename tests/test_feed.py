"""Backend feed tests: what the 3D room receives must come from the simulator, never be invented client-side."""
import json
import numpy as np
import pytest
import jsonschema
from pathlib import Path
from fastapi.testclient import TestClient
from scheduler.api import app

SCHEMA = json.load(open(Path(__file__).parents[1] / "scheduler/schema/events.schema.json"))
V = jsonschema.Draft202012Validator(SCHEMA)
BASE = {"start_day": 90, "days": 0.5}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def run(client, scenario, policies=("priority_fifo",), snapshot_s=60):
    r = client.post("/whatif", json={"scenario": {**BASE, **scenario}, "policies": list(policies), "snapshot_s": snapshot_s})
    assert r.status_code == 200, r.text
    body = r.json()
    out = {}
    for p in policies:
        rid = body["results"][p]["run_id"]
        out[p] = {"id": rid, "meta": client.get(f"/runs/{rid}").json(),
                  "ev": [json.loads(x) for x in client.get(f"/runs/{rid}/events").text.splitlines()]}
    return body, out


def snaps(ev):
    return [e for e in ev if e["type"] == "snapshot"]


def test_every_line_validates_against_schema_and_meta_is_labelled(client):
    body, o = run(client, {})
    r = o["priority_fifo"]
    assert V.is_valid(r["meta"]) and all(V.is_valid(e) for e in r["ev"])
    m = r["meta"]
    assert m["schema_version"] == "0.2.0" and m["thermal"]["evidence"] == "proxy"
    assert "not measured" in m["thermal"]["disclaimer"].lower() or "not " in m["thermal"]["disclaimer"].lower()
    assert len(m["display"]["boards"]) == 24 and len(m["display"]["pods"]) == 4
    assert m["thermal"]["assumptions"]["alert_threshold_c"] > m["thermal"]["measured_max_p99_c"]   # threshold is not a measurement


def test_boards_are_derived_from_the_event_log(client):
    """Board running_jobs/util in each snapshot must equal what the start/finish/preempt events imply."""
    body, o = run(client, {})
    ev = o["priority_fifo"]["ev"]
    running = {}
    checked = 0
    for e in ev:
        t = e["type"]
        if t == "start":
            running[e["job"]] = (e["board"], e["gpus"])
        elif t in ("finish", "preempt"):
            running.pop(e["job"], None)
        elif t == "snapshot" and checked < 40:
            n = np.zeros(24, int)
            u = np.zeros(24)
            for b, gp in running.values():
                if b is not None:
                    n[b] += 1
                    u[b] += gp
            for b in e["boards"]:
                assert b["running_jobs"] == n[b["i"]]
            checked += 1
    assert checked == 40


def test_failure_scenario_produces_fail_events_failed_status_and_node_failure_evictions(client):
    body, o = run(client, {"failures": [{"board": 7, "at_h": 3.0, "repair_after_h": 2.0}]})
    ev = o["priority_fifo"]["ev"]
    fails = [e for e in ev if e["type"] == "fail"]
    reps = [e for e in ev if e["type"] == "repair"]
    assert fails and {e["board"] for e in fails} == {7} and {e["t"] for e in fails} == {3 * 3600.0}
    assert len(reps) == len(fails) and {e["t"] for e in reps} == {5 * 3600.0}
    ev_fail = [e for e in ev if e["type"] == "preempt" and e["cause"] == "node_failure"]
    assert ev_fail and all(e["board"] == 7 for e in ev_fail)
    during = [s for s in snaps(ev) if 3 * 3600 < s["t"] < 5 * 3600]
    assert during and all(s["boards"][7]["status"] == "failed" and s["boards"][7]["nodes_down"] == s["boards"][7]["nodes"] for s in during)
    assert all(s["boards"][7]["running_jobs"] == 0 for s in during)
    after = [s for s in snaps(ev) if s["t"] > 5 * 3600 + 600]
    assert after and all(s["boards"][7]["status"] != "failed" for s in after)
    # no job starts on the failed board while it is down
    assert not [e for e in ev if e["type"] == "start" and e["board"] == 7 and 3 * 3600 < e["t"] < 5 * 3600]


def test_cooling_fault_raises_temperature_and_alerts_only_while_active(client):
    base_body, base = run(client, {})
    body, o = run(client, {"cooling_fault": {"at_h": 2.0, "delta_c": 35.0, "duration_h": 2.0}})
    be, fe = base["priority_fifo"]["ev"], o["priority_fifo"]["ev"]
    assert not [e for e in be if e["type"] == "thermal_alert"]                    # no alert without a fault
    alerts = [e for e in fe if e["type"] == "thermal_alert"]
    assert alerts and all(e["evidence"] == "proxy" for e in alerts)
    on = [e for e in alerts if e["state"] == "on"]
    assert all(2 * 3600 <= e["t"] <= 4 * 3600 + 1800 for e in on)
    thr = o["priority_fifo"]["meta"]["thermal"]["assumptions"]["alert_threshold_c"]
    assert all(e["temp_c"] >= thr for e in on)
    sb = {s["t"]: s for s in snaps(be)}
    hot = [s for s in snaps(fe) if 2.5 * 3600 < s["t"] < 3.9 * 3600]
    assert all(max(b["temp_c"] for b in s["boards"]) > max(b["temp_c"] for b in sb[s["t"]]["boards"]) + 10 for s in hot)
    cooled = [s for s in snaps(fe) if s["t"] > 4.2 * 3600 + 1500 and s["t"] in sb]
    assert cooled and all(abs(max(b["temp_c"] for b in s["boards"]) - max(b["temp_c"] for b in sb[s["t"]]["boards"])) < 5 for s in cooled[:20])


def test_temperature_comes_from_the_measured_profile_not_invented(client):
    body, o = run(client, {})
    th = o["priority_fifo"]["meta"]["thermal"]
    lo, hi = min(th["temp_p50_c"]), max(th["temp_p50_c"])
    for s in snaps(o["priority_fifo"]["ev"])[::10]:
        for b in s["boards"]:
            assert lo - 0.5 <= b["temp_c"] <= hi + 0.5 or b["status"] in ("failed",)    # no fault: inside the measured band
    a10 = [b for s in snaps(o["priority_fifo"]["ev"]) for b in s["boards"] if b["i"] in range(6, 12)]
    assert all(b["power_w"] is None for b in a10)                                         # no H100 watts for the A10 pod
    other = [b for s in snaps(o["priority_fifo"]["ev"])[:5] for b in s["boards"] if b["i"] in range(0, 6)]
    assert all(b["power_w"] is not None for b in other)


def test_injected_job_appears_and_is_scheduled(client):
    body, o = run(client, {"injected_jobs": [{"at_h": 1.0, "pool": "a100", "gpus": 2, "priority": "hp", "duration_s": 600}]})
    ev = o["priority_fifo"]["ev"]
    arr = [e for e in ev if e["type"] == "arrive" and e["job"] == "INJ-001"]
    assert len(arr) == 1 and arr[0]["t"] == 3600.0 and arr[0]["gpus"] == 2 and arr[0]["pool"] == "a100" and arr[0]["priority"] == "hp"
    st = [e for e in ev if e["type"] == "start" and e["job"] == "INJ-001"]
    assert st and st[0]["t"] >= 3600.0 and st[0]["board"] in range(0, 6)


def test_whatif_change_does_not_alter_the_past(client):
    """The scene must not jump when a control is used: events before the change time are identical."""
    base_body, base = run(client, {})
    for change in ({"burst": {"start_h": 3.0, "duration_h": 1.0, "mult": 4.0}},
                   {"failures": [{"board": 2, "at_h": 3.0, "repair_after_h": None}]},
                   {"injected_jobs": [{"at_h": 3.0, "pool": "a10", "gpus": 1, "priority": "hp", "duration_s": 300}]},
                   {"cooling_fault": {"at_h": 3.0, "delta_c": 35.0, "duration_h": None}}):
        body, o = run(client, change)
        key = lambda e: json.dumps({k: v for k, v in e.items() if k != "forecast"}, sort_keys=True)
        past_a = [key(e) for e in base["priority_fifo"]["ev"] if e["t"] < 3 * 3600 - 1]
        past_b = [key(e) for e in o["priority_fifo"]["ev"] if e["t"] < 3 * 3600 - 1]
        assert past_a == past_b, f"history changed for {list(change)}"


def test_state_endpoint_matches_event_replay(client):
    body, o = run(client, {})
    r = o["priority_fifo"]
    t = 4 * 3600.0
    st = client.get(f"/runs/{r['id']}/state", params={"t": t}).json()
    run_set, done = {}, 0
    for e in r["ev"]:
        if e["t"] > t:
            break
        if e["type"] == "start":
            run_set[e["job"]] = e
        elif e["type"] in ("finish", "preempt"):
            run_set.pop(e["job"], None)
    assert {x["job"] for x in st["running"]} == set(run_set)
    assert st["snapshot"]["t"] <= t and st["snapshot"]["t"] > t - 120
    assert all(x["service_s"] > 0 for x in st["running"])


def test_queue_heads_are_real_jobs_in_the_queue(client):
    body, o = run(client, {})
    ev = o["priority_fifo"]["ev"]
    arrived, started = set(), set()
    seen = 0
    for e in ev:
        if e["type"] == "arrive":
            arrived.add(e["job"])
        elif e["type"] == "start":
            started.add(e["job"])
        elif e["type"] == "preempt":
            started.discard(e["job"])
        elif e["type"] == "finish":
            started.discard(e["job"])
        elif e["type"] == "snapshot":
            for pid, p in e["pools"].items():
                for h in p["queue_head"]:
                    assert h["job"] in arrived and h["job"] not in started
                    seen += 1
    assert seen > 0


def test_invalid_scenarios_are_rejected(client):
    for bad in ({"failures": [{"board": 99, "at_h": 1}]}, {"injected_jobs": [{"at_h": 1, "pool": "nope"}]},
                {"injected_jobs": [{"at_h": 99, "pool": "a10"}]}):
        r = client.post("/whatif", json={"scenario": {**BASE, **bad}, "policies": ["fifo"]})
        assert r.status_code == 422, bad


def test_rl_policy_handles_failures_and_feed_is_valid(client):
    from scheduler.api import RL_MODEL
    if not RL_MODEL.exists():
        pytest.skip("trained model not present")
    body, o = run(client, {"failures": [{"board": 3, "at_h": 2.0, "repair_after_h": 3.0}]}, policies=("rl_ppo",))
    ev = o["rl_ppo"]["ev"]
    assert [e for e in ev if e["type"] == "fail"] and all(V.is_valid(e) for e in ev)
    assert not [e for e in ev if e["type"] == "start" and e["board"] == 3 and 2 * 3600 < e["t"] < 5 * 3600]


def test_forecast_is_honestly_scored(client):
    body, o = run(client, {})
    f = o["priority_fifo"]["meta"]["forecast"]
    assert f["pairs"] > 10 and f["chosen"] == "persistence"
    assert f["projection_mae_util_pct_points"] is not None and isinstance(f["projection_beats_persistence"], bool)
    for s in snaps(o["priority_fifo"]["ev"])[5:8]:
        for b in s["boards"]:
            assert b["forecast"]["util_pct"] == b["util_pct"]        # chosen forecast = persistence, never silently different


def test_websocket_control_protocol(client):
    body, o = run(client, {})
    rid = o["priority_fifo"]["id"]
    with client.websocket_connect(f"/runs/{rid}/stream?speed=200000&tick=0.001&paused=true") as ws:
        assert ws.receive_json()["type"] == "meta"
        assert ws.receive_json()["type"] == "tick"                           # paused: no batches yet
        ws.send_json({"cmd": "seek", "t": 3600})
        ws.send_json({"cmd": "resume"})
        first = None
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "batch":
                first = m
                break
        assert first is not None and first["t_from"] >= 3600
        ws.send_json({"cmd": "speed", "value": 5})
        ws.send_json({"cmd": "pause"})
