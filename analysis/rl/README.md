# Learned scheduler, forecaster and cloud overflow: results (final, 2026-11-08)

Every number here comes from a script in this repo run on **held-out data** (trace days >= 130; BurstGPT trace 3). Waits, queues, evictions,
temperatures and cloud spend are **simulated** (the trace has no queue, start, wait or eviction data); see `scheduler/assumptions.yaml`.
Older results built on a flawed candidate list are in `superseded/` and must not be quoted.
Charts of everything below (data used, policies, RL controls, forecast, cloud, runtime prediction): `analysis/graphs/index.html` (regenerate: `python scripts/graphs/make_graphs.py`).

## 1. The scheduler (masked PPO)
**Served model:** `models/ppo_u6_shuf_s12` (seed 12 had the best validation score of three seeds; chosen before any test number was seen).

**Decision:** after an event in a pool, start one of 16 candidates from that pool's queue (2 oldest + the 14 fitting jobs with the best
(priority, runtime-hint) among the first 512 queued) or wait. Work-conserving. HP-over-spot preemption stays rule-based and atomic.
**Candidate slots are randomly permuted at every decision** (`SchedulingEnv(shuffle_slots=True)`), so the slot index carries no information and the network
must read the job features (priority, size, wait, predicted runtime, fits). Trained by behaviour-cloning the hint rule (150 windows) then PPO (1.2M steps, 5-7 min on CPU).
Reward: minus weighted queue time (HP x1, spot x0.3) / fixed reference.

### Does it learn anything? (17 held-out windows, queue-time ratio vs priority FIFO, lower is better; `rl_shuffle_eval.json`)
| | ratio |
|---|---|
| random valid choice | 0.602 |
| network with random weights | 0.574 |
| **trained RL, seeds 11 / 12 / 13** | **0.513 / 0.510 / 0.509** |
| hint rule on the same 16 candidates | 0.509 |
| shortest-predicted-job over the whole queue (`sjf_hint`) | 0.507 |

Training takes the same network from 0.574 to rule-level quality, and the three seeds agree. **It ties the rule; it does not beat it.**
(Evaluation noise from the random slot order is about +-0.01: `run_eval` below reports 0.522 for the same model.)

*Why this control exists:* an earlier version let candidates arrive pre-sorted by the hint, so "pick slot 2" **was** the rule: a random-weights network scored
0.452 and the trained one 0.455. That version looked fine and learned nothing. A second bug (candidate slots filled by hint only, ignoring priority, so spot jobs
crowded HP jobs out) cost every earlier model ~0.07; both are fixed and covered by tests.

### Full held-out evaluation (served model; `python -m scheduler.run_eval --model models/ppo_u6_shuf_s12/best --out analysis/rl/ppo_u6_shuf_s12 --K 16`)
| 17 observed windows | q ratio | HP wait (h) | HP p95 (h) | spot wait (h) | preemptions | wasted GPU-h |
|---|---|---|---|---|---|---|
| fifo | 1.448 | 6.98 | 37.0 | 11.1 | 0 | 0 |
| priority_fifo | 1.000 | 4.46 | 22.4 | 20.6 | 344 | 795 |
| backfill (median estimate) | 0.806 | 3.74 | 21.4 | 14.9 | 379 | 859 |
| sjf_hint (rule) | 0.507 | 1.78 | 9.4 | 11.6 | 482 | 1,022 |
| **rl_ppo** | **0.522** | 1.91 | 10.6 | **9.3** | 326 | 842 |
| sjf_oracle (true durations, unattainable) | 0.323 | 0.97 | 3.5 | 6.8 | 490 | 1,032 |

RL beats FIFO in 17/17 windows and backfill in 15/17; it is worse than `sjf_hint` in 11/17.

| other held-out sets | priority | backfill | sjf_hint | **rl_ppo** | oracle |
|---|---|---|---|---|---|
| 16 busy what-ifs (growth, burst, spot-heavy, A10 loss) | 1.000 | 0.794 | 0.444 | **0.422** (better in 11/16) | 0.254 |
| 8 held-out BurstGPT trace-3 arrival shapes | 1.000 | 0.804 | 0.596 | **0.583** (better in 4/8) | 0.296 |

**What RL buys:** about 20% lower spot waits than the rule and ~30% fewer preemptions, slightly ahead on what-ifs and burst shapes. **What it costs:** HP waits are slightly higher (1.91 vs 1.78 h mean; p95 10.6 vs 9.4 h).
The big lever is duration knowledge: true durations (oracle, 0.32) cut queue time by about a third again relative to our predicted durations (0.51).

### Cluster size
`scripts/exp/rl_capacity_sweep.py`, 4 held-out windows, node counts x0.3 ... x3 (training saw x0.85-1.15): RL minus rule is between -0.017 and 0.000 at every size
(0.3x: 0.743 vs 0.745; 1x: 0.525 vs 0.532; 2x: 0.141 vs 0.144). **Cluster size generalises.** The number of pools is fixed at 6 by the observation (pool one-hot): a different GPU mix needs a retrain (open item).

## 2. Simulated cloud overflow ("takeaway") and cost
Flagged cloud nodes are hidden from the scheduler's capacity/utilisation; jobs waiting >= 2 h are offloaded if their **hint-predicted** rental cost (never the true duration) is under $30. Price tiers are
anchored to the pricing offers data (premium = cheapest H100-80GB offer, standard = cheapest L40S): **an assumption**, no Alibaba GPU has an exact price match. All of it is simulated and labelled.

`cloud_pareto.json` (6 held-out windows; queue ratio vs priority FIFO **without** cloud; spend per day = committed rental of started jobs):
| 5 cloud nodes / pool (240 GPUs) | q ratio | HP p95 (h) | cloud jobs / window | spend $/day |
|---|---|---|---|---|
| priority_fifo | 0.359 | 9.2 | 612 | 35,693 |
| backfill | 0.271 | 8.6 | 381 | 35,118 |
| sjf_hint | 0.190 | 9.8 | 377 | 34,834 |
| **rl_ppo** | **0.183** | 11.4 | **303** | **34,057** |

With no cloud the same set gives priority 1.000, backfill 0.843, rule 0.468, RL 0.451. Cloud buys a lot of queue time at a stated price; RL reaches the best ratio with the fewest offloaded jobs
and ~2% less spend than the rule, **but its HP tail is worse (p95 11.4 h vs 9.8 h)**.
`offload_eval.json`: an agent that decides *when to offload itself* (`ppo_u7_offload_shuf`, cost-aware reward) reaches 0.227 at ~$30.9k/day versus the same-action-space rule at 0.287 and ~$24.2k/day, and the
RL + 2 h-overflow-rule at 0.177 and ~$33.9k/day: these are points on one cost/queue curve, **not** a dominance claim. The served API uses the rule overflow.

Outcomes beside queue time (`cost_thermal.json`, 6 held-out windows, no cloud): wasted compute from evictions (GPU-h, window + carry-over jobs): priority 2,581, backfill 2,690, rule 2,612, **RL 2,507**.
Thermal (proxy): 0 node-hours above the assumed 80 C alert threshold in normal ambient for every policy; under a +35 C cooling fault ~95k node-hours for every policy (policies cannot fix a cooling fault),
and capping utilisation while overheated (`thermal_derating.json`) cut it only 2.5% while queue time rose. **Scheduling does not solve overheating in this model; it only makes it visible.**

## 3. Forecasting (`scheduler/demand_forecast.py`)
**Demand forecast:** GPUs requested by jobs arriving in the next 10 / 30 / 60 min, per pool, with a conformally calibrated P10-P90 band. Trained on days < 100, band calibrated on days 100-129, tested on days >= 130.
Gradient boosting on recent arrival volume, time of day, same-time-yesterday / last-week volume and organisation spread. Leakage tests in `tests/test_demand_forecast.py`; an API test checks the feed's
"realised" demand equals the `arrive` events.

| horizon | error vs "same rate as the last horizon" | P10-P90 coverage (aim 80%) |
|---|---|---|
| 10 min | -11% | 89% |
| 30 min | -18% | 82% |
| 60 min | -27% | 82% |

Per pool at 30 min: A100 -21%, A800 -18%, H800 -14%, series 1 -19%, series 2 -17%, **A10 -2.5% (no skill; coverage 56% because A10 demand fell between validation and test)**. In the busiest decile of half-hours persistence is better
for most pools: **sudden spikes are not anticipated.** It is shown in the 3D room as forecast vs what actually arrived, including the misses.

**Utilisation / queue-length forecast: negative result.** A learned state forecaster did not beat persistence at 30 min, 2 h or 6 h (`state_forecast_*.json`; helps only the A100 pool), because the simulated
cluster sits near saturation. The displayed utilisation forecast stays persistence. A Kaplan-Meier survival projection was also worse.

## 4. What to claim, and what not to
- Claim: a learned scheduler, with a random-weights control, that beats FIFO / priority-FIFO / backfill on held-out windows and ties the best rule, with ~20% lower spot waits and ~30% fewer preemptions.
- Claim: duration information is the lever (oracle ~0.32 vs ~0.51 with our hint).
- Claim: forecasts evaluated on unseen days against fair baselines, with intervals whose coverage we measured, and a negative result reported.
- Do **not** claim RL beats the best rule decisively, that cloud numbers are real prices or real assignments, that temperatures are Alibaba measurements, or any number from `superseded/`.
- Open: a permutation-equivariant (shared-weights) network would make the policy independent of K and the pool count; a retrain on randomised clusters would cover other GPU mixes.

Reproduce: `scripts/exp/*.py` and `python -m scheduler.run_eval` (see headers); training: `python -m scheduler.train_rl --steps 1200000 --out models/ppo_u6_shuf_s12 --K 16 --bc-episodes 150 --wide --ent 0.001 --burst-prob 0.6 --lr 0.0001 --net 256 256 --seed 12 --shuffle`.
