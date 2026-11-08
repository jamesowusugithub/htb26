import json
from pathlib import Path
import numpy as np
import pytest
from scheduler import restaurant_export as rx
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit

ORDERS = [{"at_min": 20 + i, "gpus": 8, "priority": "high", "duration_min": 120} for i in range(6)]
CLOUD = {"nodes": 1, "gpus_per_node": 8, "overflow_wait_min": 30}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def parts():
    pools, jobs, base, cl = setup(0.85)
    return jobs, pools, load_or_fit(jobs, 40)


def decisions(rec):
    return [e for e in rec["events"] if e["type"] == "DECISION"]


def test_new_orders_are_jobs_not_in_the_trace_and_get_scheduled(parts):
    jobs, pools, hint = parts
    rec = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS)
    arrivals = {e["job"]["id"] for e in rec["events"] if e["type"] == "JOB_ARRIVED"}
    assert {f"ORDER-{i:03d}" for i in range(1, 7)} <= arrivals
    assert not ({f"ORDER-{i:03d}" for i in range(1, 7)} & set(map(str, jobs.job_id)))      # genuinely new ids
    assert {e["job_id"] for e in decisions(rec)} >= {f"ORDER-{i:03d}" for i in range(1, 5)}
    assert rec["trace_meta"]["orders"] == 6


def test_orders_only_change_the_future_not_the_past(parts):
    jobs, pools, hint = parts
    base = rx.make_recording(jobs, pools, hint, "priority_fifo")
    with_o = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=[{"at_min": 60, "gpus": 8, "priority": "high", "duration_min": 120}])
    strip = lambda rec: [json.dumps({k: v for k, v in e.items() if k != "seq"}, sort_keys=True) for e in rec["events"] if e["t"] < 60 and e["type"] != "METRICS"]
    assert strip(base) == strip(with_o)                       # the animation does not jump when an order is placed at minute 60


def test_takeaway_is_off_by_default_and_declared_simulated_when_on(parts):
    jobs, pools, hint = parts
    off = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS)
    on = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS, cloud=CLOUD)
    assert not any(e["action"] == "cloud" for e in decisions(off))
    assert not any(g["id"] == "cloud-0" for n in off["config"]["nodes"] for g in n["gpus"])
    cloud_nodes = [g for n in on["config"]["nodes"] for g in n["gpus"] if g["id"] == "cloud-0"]
    assert cloud_nodes and "SIMULATED" in cloud_nodes[0]["name"]
    assert on["trace_meta"]["cloud"]["evidence"].startswith("SIMULATED")
    assert "SIMULATED cloud fallback" in on["trace_meta"]["scale_note"]


def test_cloud_decisions_follow_the_wait_threshold_and_cost_is_charged(parts):
    jobs, pools, hint = parts
    rec = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS, cloud=CLOUD)
    cl = [e for e in decisions(rec) if e["action"] == "cloud"]
    assert cl and all(e["target_gpu_ids"] == ["cloud-0"] for e in cl)
    assert all(e["factors"]["waited_min"] >= 30 - 1e-6 for e in cl)                     # only jobs that waited past the threshold
    price = rec["trace_meta"]["cloud"]["price_usd_per_gpu_hour"]
    assert price > 0 and rec["trace_meta"]["cloud"]["evidence"].startswith("SIMULATED")
    done_cost = sum(e["cost"] for e in rec["events"] if e["type"] == "JOB_COMPLETED")
    final = [e for e in rec["events"] if e["type"] == "METRICS"][-1]["cost"]
    assert final > 0 and final >= done_cost - 1e-6                                       # running total includes jobs still on the cloud
    started_cloud = {e["job_id"] for e in rec["events"] if e["type"] == "JOB_STARTED" and e["gpu_ids"] == ["cloud-0"]}
    assert started_cloud == {e["job_id"] for e in cl}


def test_price_and_capacity_are_configurable(parts):
    jobs, pools, hint = parts
    a = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS, cloud={**CLOUD, "price_multiplier": 1.0})
    b = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS, cloud={**CLOUD, "price_multiplier": 2.0})
    c = rx.make_recording(jobs, pools, hint, "priority_fifo", orders=ORDERS, cloud={**CLOUD, "nodes": 3})
    cost = lambda r: [e for e in r["events"] if e["type"] == "METRICS"][-1]["cost"]
    assert b["trace_meta"]["cloud"]["price_usd_per_gpu_hour"] == pytest.approx(2 * a["trace_meta"]["cloud"]["price_usd_per_gpu_hour"])
    assert cost(b) >= cost(a) - 1e-6
    assert c["trace_meta"]["cloud"]["gpus"] == 24 and a["trace_meta"]["cloud"]["gpus"] == 8


def test_invalid_orders_are_rejected(parts):
    jobs, pools, hint = parts
    for bad in ({"at_min": 5, "gpus": 99}, {"at_min": 5, "gpus": 1, "duration_min": 99999}, {"at_min": -1, "gpus": 1}, {"at_min": 5, "gpus": 1, "priority": "vip"}):
        with pytest.raises(ValueError):
            rx.make_recording(jobs, pools, hint, "fifo", orders=[bad])


@pytest.mark.skipif(not (ROOT / "models/ppo_combined/best.zip").exists(), reason="trained model not present")
def test_the_trained_rl_policy_schedules_new_orders_without_retraining(parts):
    from sb3_contrib import MaskablePPO
    jobs, pools, hint = parts
    model = MaskablePPO.load(ROOT / "models/ppo_combined/best", device="cpu")
    rec = rx.make_recording(jobs, pools, hint, "rl_ppo", model, 16, orders=ORDERS, cloud=CLOUD)
    d = decisions(rec)
    assert {e["scheduler"] for e in d} == {"rl"}
    assert sum(e["job_id"].startswith("ORDER-") for e in d) >= 5                          # the policy decided new orders
    assert any(e["action"] == "cloud" for e in d)
