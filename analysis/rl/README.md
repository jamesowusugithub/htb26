# Phase 4: learned scheduler (masked PPO) - results

**Headline: the learned scheduler beats priority-FIFO and backfill on held-out windows, but does not beat the simple
"shortest predicted job first" rule (`sjf_hint`).** The large gap to the true-duration oracle is the value of knowing
job length; our runtime-hint model recovers about half of it.

## Setup
- **Decision:** after an event in a pool, start one of 8 candidates from that pool's queue: the 2 oldest (HP first) plus
  6 *fitting* jobs with the smallest runtime hint among the first 512 queued. Work-conserving (no idling while a job fits).
  HP-over-spot preemption stays rule-based and atomic (evict + start the HP head).
- **Hint:** gradient-boosted model of log duration from org, pool, priority, GPUs, CPUs, workers, hour, weekday.
  Trained only on jobs that had *finished* before day 40. Held-out rank correlation 0.26 (AUC for >1 day: 0.70).
- **Reward:** minus weighted queue-time (HP x1, spot x0.3) / fixed reference. Return is comparable to priority-FIFO via
  `qint_ratio_vs_priority_fifo` (1.0 = same, lower is better).
- **Training:** days 45-115, random 3-day windows, arrival x0.7-1.5, capacity x0.85-1.15; validation days 118-127;
  **test windows start at day >= 130 and were never used for training or checkpoint selection.**
- **Final policy:** behaviour-cloned from the hint rule (60 windows), then PPO fine-tuned (2M steps, lr 1e-4), `models/ppo_bc/best.zip`.
  From-scratch PPO (3M steps, `models/ppo_a`) is kept for comparison.

## Held-out results (mean over windows; lower is better; queue-time ratio is vs priority-FIFO)
| 17 observed test windows | queue-time ratio | HP wait mean (h) | HP wait p95 (h) | spot wait mean (h) |
|---|---|---|---|---|
| priority_fifo | 1.000 | 4.46 | 22.4 | 20.6 |
| backfill_median | 0.806 | 3.74 | 21.4 | 14.9 |
| rl_ppo from scratch | 0.724 | 3.47 | 21.5 | 9.4 |
| **rl_ppo (clone + PPO)** | **0.645** | 2.87 | 16.5 | 9.9 |
| sjf_hint | 0.585 | 2.37 | 15.6 | 12.1 |
| sjf_oracle (true durations, unattainable) | 0.323 | 0.97 | 3.5 | 6.8 |

| 16 what-if scenarios (growth, burst, spot-heavy, A10 capacity loss) | queue-time ratio | HP wait mean (h) | HP wait p95 (h) | spot wait mean (h) |
|---|---|---|---|---|
| priority_fifo | 1.000 | 12.5 | 38.2 | 52.5 |
| backfill_median | 0.794 | 9.6 | 36.2 | 39.4 |
| rl_ppo from scratch | 0.627 | 8.2 | 39.8 | 23.0 |
| **rl_ppo (clone + PPO)** | 0.561 | 7.1 | 37.8 | 23.8 |
| sjf_hint | **0.537** | 6.2 | 40.5 | 32.7 |
| sjf_oracle | 0.254 | 2.0 | 11.6 | 18.8 |

Paired windows where rl_ppo had less queue-time than sjf_hint: 5 of 17 observed, 7 of 16 what-if.

## What to claim, and what not to
- Claim: the learned policies beat backfill and priority-FIFO on unseen windows and what-ifs, and keep spot waits lowest of all realistic policies (both RL variants; the from-scratch one slightly lower).
- Claim: duration information is the lever. True durations cut waits ~3x versus our hint; our hint recovers about half of that gap.
- Do **not** claim RL beats the best heuristic. It is slightly behind `sjf_hint` (which sees the whole queue, not 8 candidates).
- PPO fine-tuning barely moved the cloned policy (validation ratio 0.651 -> 0.658). Gains came from the hint and the cloning.
- Caveats: one seed per policy; 3-day windows; waits are simulated (see `scheduler/assumptions.yaml`); the later
  trace period is quieter than training. Reproduce: `python -m scheduler.run_eval --model models/ppo_bc/best --out analysis/rl/ppo_bc`.
- Ideas with real upside: better hint features (organisation history), more candidates, a hold/reserve action for large jobs.
