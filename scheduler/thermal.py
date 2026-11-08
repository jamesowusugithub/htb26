"""Thermal/power *proxy* for the room visualisation.

There is no temperature or power data for the Alibaba GPUs. The only measured thermal data is for H100, B200 and
RTX 3060 (harmonised Phase 1 thermal archive, integrated/hardware/thermal_load_profiles.parquet). This module maps
utilisation -> temperature/power using the **measured H100 profiles pooled across workloads**
(reading-weighted band medians, forced monotone), then applies a first-order lag. Everything it outputs is a proxy:
  - source GPU: NVIDIA H100, not the simulated hardware
  - lag time-constant and alert threshold are ASSUMPTIONS (nothing in the data measures them)
Power is withheld (null) for pools whose hardware is too different from an H100 for the proxy to mean anything.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .data import ROOT

MID = np.array([10.0, 30.0, 50.0, 70.0, 90.0])      # utilisation-band midpoints (%)
NO_POWER_POOLS = ("a10",)                             # 150 W-class inference card: H100 watts would mislead
SOURCE_MODEL = "nvidia_h100"


@dataclass
class ThermalProxy:
    t50: np.ndarray
    t95: np.ndarray
    p50: np.ndarray
    readings: int
    tau_s: float = 300.0            # ASSUMPTION: thermal lag time-constant (trace seconds)
    threshold_c: float = 80.0       # ASSUMPTION: warning threshold; above every measured H100 P99
    measured_max_p99_c: float = 0.0

    @classmethod
    def load(cls, tau_s: float = 300.0, threshold_c: float = 80.0) -> "ThermalProxy":
        t = pd.read_parquet(ROOT / "integrated/hardware/thermal_load_profiles.parquet")
        h = t[t.gpu_model_identifier == SOURCE_MODEL]
        rows = []
        for _, g in h.groupby("load_band_index"):
            w = g.readings.to_numpy(float)
            rows.append([np.average(g[c], weights=w) for c in
                         ("temperature_p50_c", "temperature_p95_c", "power_p50_w")] + [w.sum()])
        a = np.array(rows)
        return cls(t50=np.maximum.accumulate(a[:, 0]), t95=np.maximum.accumulate(a[:, 1]),
                   p50=np.maximum.accumulate(a[:, 2]), readings=int(a[:, 3].sum()), tau_s=tau_s,
                   threshold_c=threshold_c, measured_max_p99_c=float(h.temperature_p99_c.max()))

    def target(self, util_pct):
        u = np.asarray(util_pct, dtype=float)
        return np.interp(u, MID, self.t50), np.interp(u, MID, self.t95), np.interp(u, MID, self.p50)

    def step(self, temp, util_pct, dt, delta_c=0.0):
        tgt = self.target(util_pct)[0] + delta_c
        return temp + (tgt - temp) * (1.0 - np.exp(-max(dt, 0.0) / self.tau_s))

    def util_cap_for_fault(self, delta_c: float, margin_c: float = 0.0) -> float:
        """Highest node utilisation (fraction) at which the proxy temperature stays below the alert threshold while a cooling fault of `delta_c` lasts.
        1.0 when no utilisation reaches the threshold (no derating needed); 0.0 if even an idle node would."""
        u = np.linspace(0.0, 100.0, 1001)
        ok = self.target(u)[0] + delta_c + margin_c < self.threshold_c
        if ok.all():
            return 1.0
        if not ok.any():
            return 0.0
        return float(u[np.flatnonzero(ok).max()] / 100.0)

    def meta(self) -> dict:
        return {"evidence": "proxy", "source_gpu": SOURCE_MODEL,
                "source": "measured H100 thermal profiles (Phase 1), pooled across workloads, reading-weighted, forced monotone",
                "readings_used": self.readings, "util_band_midpoints_pct": MID.tolist(),
                "temp_p50_c": np.round(self.t50, 1).tolist(), "temp_p95_c": np.round(self.t95, 1).tolist(),
                "power_p50_w": np.round(self.p50, 0).tolist(), "no_power_pools": list(NO_POWER_POOLS),
                "assumptions": {"lag_tau_s": self.tau_s, "alert_threshold_c": self.threshold_c},
                "measured_max_p99_c": self.measured_max_p99_c,
                "disclaimer": "Proxy from measured H100 data. Not measured on the simulated Alibaba hardware. "
                              "The alert threshold and lag are assumptions; no measured reading reaches the threshold."}
