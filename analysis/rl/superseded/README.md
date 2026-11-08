# Superseded results - do not quote

Everything in this folder was produced by RL models trained and evaluated with the **old candidate selection**
(`scheduler/rl_core.py::build_decision` filled the candidate slots by smallest runtime hint only, ignoring priority, so spot jobs crowded
HP jobs out of the candidate list). Found and fixed on 2026-11-08 (commit 4f50a4e). The numbers here are ~0.07 worse in queue-time ratio than
the corrected environment gives, and conclusions drawn from them (e.g. "RL wastes the least compute", the cloud Pareto for `ppo_u1`) do not hold.
Current results: `analysis/rl/README.md`. Kept for the audit trail only.
