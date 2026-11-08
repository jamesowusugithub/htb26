"""Custom kitchens (per-chef GPU type + count) and the all-policy comparison."""
import pytest
from fastapi.testclient import TestClient
from scheduler.api import app

KIT = [{"pool": "a10", "gpus": 1}, {"pool": "a100", "gpus": 8}, {"pool": "a100", "gpus": 4}, {"pool": "h800", "gpus": 8}, {"pool": "series1", "gpus": 2}]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_custom_kitchen_declares_each_chef_with_its_type_and_gpu_count(client):
    r = client.post("/restaurant/trace", json={"policy": "sjf_hint", "kitchen": KIT})
    assert r.status_code == 200, r.text
    chefs = [g for n in r.json()["config"]["nodes"] for g in n["gpus"]]
    assert [c["vram_gb"] for c in chefs] == [1, 8, 4, 8, 2]                       # GPUs per node, chefs ordered by GPU type (a10, a100, a100, h800, series1)
    assert [c["id"].split("-")[0] for c in chefs] == ["a10", "a100", "a100", "h800", "series1"]


def test_jobs_larger_than_any_node_of_their_type_are_left_out(client):
    body = {"policy": "fifo", "kitchen": [{"pool": "a100", "gpus": 2}, {"pool": "a100", "gpus": 2}], "start_day": 145}
    rec = client.post("/restaurant/trace", json=body).json()
    arrivals = [e["job"] for e in rec["events"] if e["type"] == "JOB_ARRIVED"]
    assert arrivals and max(j["gpus"] for j in arrivals) <= 2                      # nothing that could never start is shown as a customer


def test_orders_can_target_a_gpu_type_and_oversized_orders_are_rejected(client):
    ok = client.post("/restaurant/trace", json={"policy": "rl_ppo", "kitchen": KIT, "orders": [{"at_min": 5, "gpus": 4, "priority": "high", "duration_min": 30, "pool": "h800"}]})
    assert ok.status_code == 200 and any(e["type"] == "JOB_ARRIVED" and e["job"]["id"].startswith("ORDER-") for e in ok.json()["events"])
    bad = client.post("/restaurant/trace", json={"policy": "rl_ppo", "kitchen": KIT, "orders": [{"at_min": 5, "gpus": 8, "priority": "high", "duration_min": 30, "pool": "a10"}]})
    assert bad.status_code == 422                                                  # an A10 chef has 1 GPU


def test_bad_kitchens_are_rejected(client):
    assert client.post("/restaurant/trace", json={"kitchen": [{"pool": "a100", "gpus": 8}]}).status_code == 422
    assert client.post("/restaurant/trace", json={"kitchen": [{"pool": "nope", "gpus": 8}, {"pool": "a100", "gpus": 8}]}).status_code == 422


def test_compare_runs_all_four_policies_on_identical_jobs(client):
    d = client.post("/restaurant/compare", json={"kitchen": KIT, "cloud": {"nodes": 1}}).json()
    assert set(d["policies"]) == {"fifo", "priority_fifo", "sjf_hint", "rl_ppo"}
    assert len({v["received"] for v in d["policies"].values()}) == 1              # same customers for every manager
    assert all(v["completed"] <= v["received"] for v in d["policies"].values())
    assert len(d["predictions"]) == d["policies"]["rl_ppo"]["received"] and all(p["predicted_min"] > 0 for p in d["predictions"])
    assert d["units"]["cost"].lower().startswith("usd") and "simulated" in d["units"]["cost"]
