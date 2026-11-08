"""Load the harmonised Alibaba tables and build workloads and clusters."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
UNIT = 100  # hundredths of a GPU per physical GPU
MAX_GPUS_PER_NODE = 8


def load_pool_config(path: Path | None = None) -> list[dict]:
    with open(path or Path(__file__).with_name("pools.yaml")) as f:
        return yaml.safe_load(f)["pools"]


def load_assumptions() -> dict:
    with open(Path(__file__).with_name("assumptions.yaml")) as f:
        return yaml.safe_load(f)


@dataclass
class Workload:
    """Jobs sorted by submit time. All arrays are aligned."""
    job_id: np.ndarray        # str, original trace id
    submit: np.ndarray        # float64 seconds
    dur: np.ndarray           # float64 seconds (observed)
    pool: np.ndarray          # int64 pool index
    req: np.ndarray           # int64 hundredths of a GPU
    prio: np.ndarray          # int64 0 = high priority, 1 = spot
    org: np.ndarray           # str organisation id
    eval_mask: np.ndarray     # bool: counted in metrics (False = lookback/warm-up)
    t0: float = 0.0           # window start in trace seconds
    elapsed0: np.ndarray | None = None   # seconds a carry-over job had already run when the window opened (else 0)

    def __len__(self):
        return len(self.submit)


def load_jobs(pools: list[dict]) -> pd.DataFrame:
    cols = ["job_id", "organisation_id", "gpu_model_identifier", "priority_class",
            "gpu_request_recorded_count", "submit_relative_s", "duration_s", "cpu_request_vcpus", "worker_count"]
    j = pd.read_parquet(ROOT / "harmonized/alibaba/jobs.parquet", columns=cols)
    pidx = {p["gpu_model_identifier"]: i for i, p in enumerate(pools)}
    j["pool"] = j.gpu_model_identifier.map(pidx).astype("int64")
    j["req"] = np.rint(j.gpu_request_recorded_count.astype(float) * UNIT).astype("int64").clip(lower=1)
    j["prio"] = (j.priority_class == "spot").astype("int64")
    return j.sort_values(["submit_relative_s", "job_id"], kind="stable").reset_index(drop=True)


def load_nodes(pools: list[dict]) -> pd.DataFrame:
    n = pd.read_parquet(ROOT / "harmonized/alibaba/nodes.parquet",
                        columns=["node_id", "gpu_model_identifier", "gpu_capacity_count"])
    pidx = {p["gpu_model_identifier"]: i for i, p in enumerate(pools)}
    n["pool"] = n.gpu_model_identifier.map(pidx).astype("int64")
    return n.rename(columns={"gpu_capacity_count": "ngpu"}).sort_values(["pool", "node_id"]).reset_index(drop=True)


def make_workload(jobs: pd.DataFrame, start: float = 0.0, end: float | None = None,
                  carryover: bool = True) -> Workload:
    """Jobs submitted in [start, end) are evaluated. With `carryover`, jobs submitted earlier that are
    still running at `start` (assuming they started at submit, i.e. zero historic wait) enter at t=0 with
    their remaining time and are excluded from metrics. This is policy-independent and matters because
    ~5% of jobs hold ~95% of the GPU-seconds."""
    sub = jobs.submit_relative_s.to_numpy(dtype=np.float64)
    dur = jobs.duration_s.to_numpy(dtype=np.float64)
    end = float(sub.max()) + 1 if end is None else end
    inwin = (sub >= start) & (sub < end)
    carry = (sub < start) & (sub + dur > start) if (carryover and start > 0) else np.zeros(len(sub), dtype=bool)
    sel = np.flatnonzero(inwin | carry)
    t_sub = np.where(carry[sel], 0.0, sub[sel] - start)
    t_dur = np.where(carry[sel], sub[sel] + dur[sel] - start, dur[sel])
    order = np.argsort(t_sub, kind="stable")      # carry-over (t=0) first, then window jobs
    sel, t_sub, t_dur = sel[order], t_sub[order], t_dur[order]
    w = jobs.iloc[sel]
    return Workload(
        job_id=w.job_id.to_numpy(), submit=t_sub, dur=t_dur, pool=w.pool.to_numpy(), req=w.req.to_numpy().copy(),
        prio=w.prio.to_numpy(), org=w.organisation_id.to_numpy(), eval_mask=inwin[sel], t0=start,
        elapsed0=np.where(carry[sel], start - sub[sel], 0.0))


@dataclass
class Cluster:
    pools: list[dict]
    node_pool: np.ndarray     # int64, nodes sorted by pool
    node_ngpu: np.ndarray     # int64 GPUs per node
    scale: np.ndarray         # per-pool node-count multiplier applied (1.0 = observed)
    node_cloud: np.ndarray | None = None   # int64 flags: 1 = simulated cloud (takeaway) node, hidden from normal placement

    @property
    def n_pools(self):
        return len(self.pools)

    def cloud_mask(self) -> np.ndarray:
        return np.zeros(len(self.node_pool), dtype=bool) if self.node_cloud is None else self.node_cloud.astype(bool)

    def capacity_gpus(self) -> np.ndarray:
        own = ~self.cloud_mask()
        return np.bincount(self.node_pool[own], weights=self.node_ngpu[own], minlength=self.n_pools)

    def node_counts(self) -> np.ndarray:
        return np.bincount(self.node_pool[~self.cloud_mask()], minlength=self.n_pools)

    def cloud_capacity_gpus(self) -> np.ndarray:
        c = self.cloud_mask()
        return np.bincount(self.node_pool[c], weights=self.node_ngpu[c], minlength=self.n_pools)

    def max_node_gpus(self) -> np.ndarray:
        out = np.zeros(self.n_pools, dtype=np.int64)
        own = ~self.cloud_mask()
        np.maximum.at(out, self.node_pool[own], self.node_ngpu[own])
        return out


def add_cloud(cluster: "Cluster", nodes_per_pool, gpus_per_node: int = 8) -> "Cluster":
    """Append simulated cloud (takeaway) nodes at the end of each pool's block. nodes_per_pool: int or {pool_id: int}."""
    ids = [p["id"] for p in cluster.pools]
    npp = np.array([nodes_per_pool.get(i, 0) if isinstance(nodes_per_pool, dict) else int(nodes_per_pool) for i in ids])
    pool_o, ngpu_o, cloud_o = [], [], []
    base_cloud = cluster.cloud_mask()
    for p in range(cluster.n_pools):
        m = cluster.node_pool == p
        pool_o += [p] * int(m.sum()); ngpu_o += cluster.node_ngpu[m].tolist(); cloud_o += base_cloud[m].astype(int).tolist()
        pool_o += [p] * int(npp[p]); ngpu_o += [gpus_per_node] * int(npp[p]); cloud_o += [1] * int(npp[p])
    return Cluster(cluster.pools, np.array(pool_o, dtype=np.int64), np.array(ngpu_o, dtype=np.int64), cluster.scale.copy(),
                   np.array(cloud_o, dtype=np.int64))


def observed_cluster(nodes: pd.DataFrame, pools: list[dict]) -> Cluster:
    return Cluster(pools, nodes.pool.to_numpy(), nodes.ngpu.to_numpy(dtype=np.int64), np.ones(len(pools)))


def scale_cluster(base: Cluster, factors, min_nodes: int = 8) -> Cluster:
    """Add/remove whole nodes of the observed shapes. Keeps the shape mix and at least one node of
    the largest shape, so an 8-GPU job can always fit somewhere."""
    factors = np.broadcast_to(np.asarray(factors, dtype=float), (base.n_pools,))
    pools_out, ngpu_out = [], []
    for p in range(base.n_pools):
        shapes = base.node_ngpu[base.node_pool == p]
        vals, cnts = np.unique(shapes, return_counts=True)
        total = max(int(round(len(shapes) * factors[p])), min(min_nodes, len(shapes)) if factors[p] < 1 else 1)
        total = max(total, 1)
        new = np.floor(cnts / cnts.sum() * total).astype(int)
        rem = total - new.sum()
        order = np.argsort(-(cnts / cnts.sum() * total - new))
        for k in range(rem):
            new[order[k % len(new)]] += 1
        new[np.argmax(vals)] = max(new[np.argmax(vals)], 1)
        for v, c in zip(vals, new):
            pools_out += [p] * int(c)
            ngpu_out += [int(v)] * int(c)
    return Cluster(base.pools, np.array(pools_out, dtype=np.int64), np.array(ngpu_out, dtype=np.int64),
                   factors.copy())


def offered_load(base: Cluster, jobs: pd.DataFrame) -> np.ndarray:
    """Per-pool offered load = sum(request x duration clipped at trace end) / (GPUs x trace span)."""
    T = float(jobs.submit_relative_s.max()) + 1
    clipped = np.minimum(jobs.duration_s.to_numpy(float), T - jobs.submit_relative_s.to_numpy(float))
    work = np.bincount(jobs.pool.to_numpy(), weights=jobs.req.to_numpy() / UNIT * clipped, minlength=base.n_pools)
    return work / (base.capacity_gpus() * T)


def calibrate_cluster(base: Cluster, jobs: pd.DataFrame, target_load: float = 0.85, min_nodes: int = 8) -> Cluster:
    """Scale each pool so its offered load equals target_load (proxy: request x duration)."""
    rho = offered_load(base, jobs)
    return scale_cluster(base, rho / target_load, min_nodes=min_nodes)
