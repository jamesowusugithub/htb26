"""Simulated cloud overflow ("takeaway"): a clearly labelled FALLBACK, not a measured Alibaba behaviour.

The Alibaba trace contains no cloud assignments, so nothing here is observed. Cloud capacity (nodes per pool, GPUs per node) and the
overflow trigger (wait threshold) are configurable assumptions. Prices come from the harmonised pricing data where a related offer exists:
no Alibaba GPU model has an exact price match (integrated/scenarios/alibaba_cost_coverage.parquet: all six 'unpriced_no_exact_identifier'),
so each pool is mapped to a price TIER anchored to a real offer, and a multiplier lets us test sensitivity:
  premium  = cheapest hourly H100-80GB offer  (proxy for H800 / A100 / A800 / unidentified series)
  standard = cheapest hourly L40S offer       (proxy for the A10 inference class)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .data import ROOT

TIER_OFFER = {"premium": "nvidia_h100_80gb", "standard": "nvidia_l40s"}
POOL_TIER = {"a10": "standard", "a100": "premium", "a800": "premium", "h800": "premium", "series1": "premium", "series2": "premium"}
_cache: dict = {}


def tier_prices() -> dict[str, float]:
    """USD per GPU-hour for each tier, read from the pricing data (not typed)."""
    if not _cache:
        o = pd.read_parquet(ROOT / "harmonized/pricing/offers.parquet")
        h = o[(o.price_field == "price_hourly_usd") & o.price_per_gpu.notna()]
        for tier, model in TIER_OFFER.items():
            _cache[tier] = float(h[h.gpu_model_identifier == model].price_per_gpu.min())
    return dict(_cache)


def pool_prices(pool_ids: list[str], multiplier: float = 1.0) -> np.ndarray:
    tp = tier_prices()
    return np.array([tp[POOL_TIER.get(p, "premium")] * multiplier for p in pool_ids])


DEFAULT_MAX_JOB_COST_USD = 30.0    # ASSUMPTION: a job is only sent to the cloud if its PREDICTED rental cost is at most this (about 1 h of an 8-GPU premium node)


def provenance() -> dict:
    return {"evidence": "assumption", "tier_prices_usd_per_gpu_hour": tier_prices(), "pool_tier": POOL_TIER, "tier_offer_model": TIER_OFFER,
            "note": "No Alibaba GPU model has an exact price in the pricing data; tiers are anchored to the cheapest hourly offer of a related model. "
                    "Cloud capacity, overflow trigger and price multiplier are configurable scenario assumptions; no Alibaba cloud assignment is observed."}
