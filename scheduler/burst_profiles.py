"""Arrival-burst shapes from the combined layer (James's integrated/workload_hourly.parquet, BurstGPT series).

BurstGPT is real LLM-serving traffic: far burstier than Alibaba's batch arrivals (busiest hour typically 3-5x the daily
mean, up to ~17x, vs ~1.8x for Alibaba). We use only its *shape* (hourly arrival rate relative to its mean) as a stress
pattern for the cluster scheduler. It carries no GPU, duration or clock information, and its clock is unrelated to
Alibaba's, so nothing is joined record-to-record.

Honest split: shapes from burstgpt_1 and burstgpt_2 are for TRAINING; burstgpt_3 shapes are held out for TESTING.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .data import ROOT

TRAIN_SERIES = ("burstgpt_1", "burstgpt_2")
TEST_SERIES = ("burstgpt_3",)
CAP = 8.0                       # no hour may exceed 8x the mean (keeps a single hour from dominating a 3-day window)
_cache: dict[str, np.ndarray] = {}


def hourly(series: str) -> np.ndarray:
    """Complete-hour arrival counts, in original order."""
    if series not in _cache:
        h = pd.read_parquet(ROOT / "integrated/workload_hourly.parquet")
        x = h[(h.source_series_id == series) & (~h.partial_edge_bin)].sort_values("hour_index_original_relative")
        _cache[series] = x.arrival_count.to_numpy(float)
    return _cache[series]


def window_profile(series: str, start_hour: int, hours: int, cap: float = CAP) -> list[float]:
    """Hourly multipliers (mean 1) for `hours` consecutive hours of a BurstGPT series."""
    c = hourly(series)[start_hour:start_hour + hours]
    if len(c) < hours or c.mean() <= 0:
        raise ValueError("window outside the series")
    p = np.minimum(c / c.mean(), cap)
    return (p / p.mean()).round(4).tolist()


def sample(rng: np.random.Generator, series=TRAIN_SERIES, hours: int = 72) -> tuple[list[float], str]:
    s = series[int(rng.integers(len(series)))]
    n = len(hourly(s))
    a = int(rng.integers(0, n - hours))
    return window_profile(s, a, hours), f"{s} hours {a}-{a + hours}"


def burstiest(series: str, hours: int = 72, k: int = 3, stride: int = 24) -> list[tuple[int, float]]:
    """The k most bursty (peak / mean) windows, non-overlapping-ish, for deterministic held-out tests."""
    c = hourly(series)
    out = []
    for a in range(0, len(c) - hours, stride):
        w = c[a:a + hours]
        out.append((a, float(w.max() / w.mean())))
    out.sort(key=lambda x: -x[1])
    picked = []
    for a, r in out:
        if all(abs(a - b) >= hours for b, _ in picked):
            picked.append((a, r))
        if len(picked) == k:
            break
    return picked
