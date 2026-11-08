"""Judge mode: one visitor workload through all four managers on the same busy kitchen."""
import pytest
from fastapi.testclient import TestClient
from scheduler.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_submit_returns_every_manager_with_consistent_times(client):
    d = client.post("/judge/submit", json={"gpu_type": "a100", "gpus": 1, "priority": "high", "duration_min": 15}).json()
    assert set(d["results"]) == {"fifo", "priority_fifo", "sjf_hint", "rl_ppo"} and d["window_min"] > 400
    started = [v for v in d["results"].values() if v["started"]]
    assert started and all(abs(v["turnaround_min"] - (v["wait_min"] + 15)) < 0.11 for v in started)          # turnaround = wait + run time
    assert d["best"] in d["results"] and d["results"][d["best"]]["turnaround_min"] == min(v["turnaround_min"] for v in started)


def test_input_is_validated(client):
    assert client.post("/judge/submit", json={"gpu_type": "a10", "gpus": 8, "priority": "high", "duration_min": 30}).status_code == 422     # an A10 node has 4 GPUs
    assert client.post("/judge/submit", json={"gpu_type": "tpu", "gpus": 1, "priority": "high", "duration_min": 30}).status_code == 422
    assert client.post("/judge/submit", json={"gpu_type": "a100", "gpus": 1, "priority": "vip", "duration_min": 30}).status_code == 422
    assert client.post("/judge/submit", json={"gpu_type": "a100", "gpus": 1, "priority": "high", "duration_min": 99999}).status_code == 422


def test_board_counts_submissions_and_pages_are_served(client):
    n0 = client.get("/judge/board").json()["submissions"]
    client.post("/judge/submit", json={"gpu_type": "a800", "gpus": 2, "priority": "spot", "duration_min": 15})
    assert client.get("/judge/board").json()["submissions"] == n0 + 1
    assert "Submit a workload" in client.get("/judge").text and "GPU Scheduling Lens" in client.get("/").text
    qr = client.get("/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg") and "<svg" in qr.text
