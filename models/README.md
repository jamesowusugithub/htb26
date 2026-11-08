# Models

| Directory | Status | Notes |
|---|---|---|
| `ppo_u6_shuf_s12` | **SERVED (default API model)** | masked PPO, K=16, candidate slots randomly permuted (`--shuffle`), hint v3. Best validation of 3 seeds. |
| `ppo_u6_shuf_s11`, `ppo_u6_shuf_s13` | current, same recipe | other seeds; test scores 0.513 / 0.509 vs 0.510 for s12 (see `analysis/rl/README.md`) |
| `ppo_u7_offload_shuf` | experimental | cost-aware agent that also decides when to rent SIMULATED cloud capacity; not served |
| `ppo_u4_hpfirst_s11/12/13` | ablation | fixed candidate selection but slots NOT shuffled: a random-weights network scores the same as these (0.452 vs 0.455), i.e. they only reproduce the rule |
| `ppo_a`, `ppo_bc`, `ppo_combined`, `ppo_k16`, `ppo_u1_v3hint` | **superseded - do not use** | trained on a candidate list that ignored priority (found 2026-11-08); results in `analysis/rl/superseded/` |
| `duration_hint_v3.joblib`, `demand_forecaster_v2_h1800.joblib`, `thermal_model.joblib` | cached, gitignored | refit automatically on first use (about a minute) |

A policy trained with `--shuffle` must be run with `SchedulingEnv(shuffle_slots=True)`; the API and the evaluators read this from `history.json` next to the model.
