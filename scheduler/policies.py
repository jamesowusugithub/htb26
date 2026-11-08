"""Named baseline policies. Each entry says how to configure the simulator."""
from __future__ import annotations
from dataclasses import dataclass
from .sim import FIFO, PRIO_FIFO, BACKFILL, SJF


@dataclass(frozen=True)
class PolicySpec:
    name: str
    policy: int
    preempt: bool
    est_mode: str | None = None      # runtime-estimate source for backfill
    realistic: bool = True            # False = uses true durations (a ceiling, not achievable)
    description: str = ""


POLICIES: dict[str, PolicySpec] = {p.name: p for p in [
    PolicySpec("fifo", FIFO, False, None, True, "First come first served, ignores priority, no preemption"),
    PolicySpec("priority_fifo", PRIO_FIFO, True, None, True, "HP before spot, FIFO within class, HP may evict spot"),
    PolicySpec("backfill_median", BACKFILL, True, "median", True,
               "Priority + EASY backfill using pool/priority median runtime as the estimate"),
    PolicySpec("backfill_oracle", BACKFILL, True, "oracle", False,
               "Priority + EASY backfill with perfect runtime estimates (ceiling)"),
    PolicySpec("sjf_oracle", SJF, True, None, False,
               "HP first, shortest true job first within class, greedy (ceiling)"),
]}
