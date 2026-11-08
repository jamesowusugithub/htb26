import json
import jsonschema
import pytest
from fastapi.testclient import TestClient
from scheduler.api import app

SCHEMA = json.load(open(__import__("pathlib").Path(__file__).parents[1] / "scheduler/schema/events.schema.json"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def result(client):
    r = client.post("/whatif", json={"preset": "baseline", "scenario": {"start_day": 60, "days": 1},
                                     "policies": ["fifo", "priority_fifo"], "snapshot_s": 600})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_meta_presets(client):
    assert client.get("/health").json()["status"] == "ok"
    m = client.get("/meta").json()
    assert len(m["pools"]) == 6 and {p["name"] for p in m["policies"]} >= {"fifo", "sjf_oracle"}
    assert any(a["evidence"] == "assumption" for a in m["assumptions"])
    assert {p["name"] for p in client.get("/presets").json()} >= {"baseline", "growth_30"}


def test_whatif_returns_comparison_and_is_cached(client, result):
    assert {r["policy"] for r in result["comparison"]} == {"fifo", "priority_fifo"}
    again = client.post("/whatif", json={"preset": "baseline", "scenario": {"start_day": 60, "days": 1},
                                         "policies": ["fifo", "priority_fifo"], "snapshot_s": 600}).json()
    assert again["scenario_id"] == result["scenario_id"] and again["compute_seconds"] == result["compute_seconds"]


def test_events_slice_validates_against_schema(client, result):
    run_id = result["results"]["priority_fifo"]["run_id"]
    v = jsonschema.Draft202012Validator(SCHEMA)
    txt = client.get(f"/runs/{run_id}/events", params={"t_from": 0, "t_to": 3600}).text
    lines = [json.loads(x) for x in txt.splitlines()]
    assert lines and all(v.is_valid(o) for o in lines)
    assert all(0 <= o["t"] <= 3600 for o in lines)
    only = client.get(f"/runs/{run_id}/events", params={"types": "snapshot"}).text.splitlines()
    assert only and all(json.loads(x)["type"] == "snapshot" for x in only)


def test_timeline_and_meta(client, result):
    run_id = result["results"]["fifo"]["run_id"]
    tl = client.get(f"/runs/{run_id}/timeline").json()
    assert len(tl["t"]) > 3 and set(tl["pools"]) == {"a10", "a100", "a800", "h800", "series1", "series2"}
    assert len(tl["pools"]["a10"]["busy_gpus"]) == len(tl["t"])
    assert client.get(f"/runs/{run_id}").json()["type"] == "meta"


def test_websocket_streams_meta_batches_then_end(client, result):
    run_id = result["results"]["fifo"]["run_id"]
    with client.websocket_connect(f"/runs/{run_id}/stream?speed=200000&tick=0.001") as ws:
        assert ws.receive_json()["type"] == "meta"
        got = ws.receive_json()
        assert got["type"] == "batch"
        n = 1
        while True:
            m = ws.receive_json()
            if m["type"] == "end":
                break
            n += 1
        assert n >= 2


def test_errors(client):
    assert client.post("/whatif", json={"preset": "nope"}).status_code == 404
    assert client.post("/whatif", json={"policies": ["bogus"]}).status_code == 422
    assert client.post("/whatif", json={"scenario": {"days": 30}}).status_code == 422
    assert client.get("/runs/doesnotexist-fifo/events").status_code == 404


def test_nan_metrics_are_sent_as_null(client):
    # spot_share=0 -> no spot jobs arrive -> spot wait statistics are NaN internally
    r = client.post("/whatif", json={"scenario": {"start_day": 60, "days": 1, "spot_share": 0.0},
                                     "policies": ["fifo"], "snapshot_s": 3600})
    assert r.status_code == 200
    assert r.json()["comparison"][0]["spot_wait_mean_h"] is None
    assert r.json()["results"]["fifo"]["metrics"]["spot"]["wait_mean_s"] is None


def test_rl_policy_selectable_and_exports_valid_events(client):
    from pathlib import Path
    if not (Path(__file__).parents[1] / "models/ppo_bc/best.zip").exists():
        pytest.skip("trained model not present")
    r = client.post("/whatif", json={"scenario": {"start_day": 130, "days": 1}, "policies": ["priority_fifo", "rl_ppo"],
                                     "snapshot_s": 1800})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {c["policy"] for c in body["comparison"]} == {"priority_fifo", "rl_ppo"}
    run_id = body["results"]["rl_ppo"]["run_id"]
    v = jsonschema.Draft202012Validator(SCHEMA)
    lines = [json.loads(x) for x in client.get(f"/runs/{run_id}/events", params={"t_to": 7200}).text.splitlines()]
    assert lines and all(v.is_valid(o) for o in lines)
    assert any(p["name"] == "rl_ppo" for p in client.get("/meta").json()["policies"])


def test_demand_forecast_block_matches_the_arrivals_in_the_feed(client):
    """meta.demand_forecast: 'realised' must equal the GPUs of the arrive events in the next horizon (checked on a what-if with a 2x arrival burst)."""
    r = client.post("/whatif", json={"scenario": {"start_day": 140, "days": 1, "arrival_mult": 2.0}, "policies": ["priority_fifo"], "snapshot_s": 900})
    assert r.status_code == 200, r.text
    run_id = next(iter(r.json()["results"].values()))["run_id"]
    lines = [json.loads(x) for x in client.get(f"/runs/{run_id}/events").text.splitlines()]
    d = client.get(f"/runs/{run_id}").json()["demand_forecast"]
    assert d["available"] and d["in_training_period"] is False and d["trained_on"].startswith("trace days <")
    assert d["heldout_skill"] is None or "a100" in d["heldout_skill"]["per_pool"]
    arr = [x for x in lines if x["type"] == "arrive" and not x.get("carryover") and x["t"] > 0]
    H = d["horizon_s"]
    checked = 0
    for pt in d["series"][:20]:
        for pid, v in pt["pools"].items():
            real = sum(x["gpus"] for x in arr if x["pool"] == pid and pt["t"] < x["t"] <= pt["t"] + H + 1e-6)
            assert abs(real - v["realised_gpus"]) < 0.51, (pid, pt["t"], real, v)       # 5-min binning allows boundary slack
            assert v["p10"] <= v["next_gpus"] <= v["p90"]
            checked += 1
    assert checked > 50
