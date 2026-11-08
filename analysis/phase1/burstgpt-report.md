# BurstGPT Phase 1 findings

**Verified:** all six release CSVs were read (20,776,759 stored rows). Canonical full traces yield 10,632,194 Parquet rows. The 10,144,565 filtered-variant rows match ordered success-only subsets exactly and are not emitted a second time.

| Trace | Full rows | Zero response rows (%) | Span (days) | Input P50 / P95 / P99 (tokens) | Output P50 / P95 / P99 (tokens) | Extra identical raw rows |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| burstgpt_1 | 1,429,737 | 25,443 (1.7796%) | 60.995 | 251 / 2,461 / 3,387 | 34 / 460 / 1,491 | 54,040 |
| burstgpt_2 | 3,858,436 | 74,223 (1.9237%) | 60.000 | 215 / 558 / 1,038 | 7 / 160 / 478 | 150,150 |
| burstgpt_3 | 5,344,021 | 387,963 (7.2598%) | 109.999 | 327 / 1,405 / 3,354 | 14 / 324 / 876 | 347,285 |

## Arrival variation

- **Measured, burstgpt_1:** complete-minute median 2, P95 84, P99 206 requests/min; peak 1,250. Of 87,831 complete minutes, 26,988 have zero requests. 20,177 exceed the descriptive threshold of five times the median (10 requests/min).
  Hourly lag correlations: 1 hour 0.680; 24 hours 0.071; 168 hours 0.018. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.
- **Measured, burstgpt_2:** complete-minute median 2, P95 220, P99 356.03 requests/min; peak 1,104. Of 86,398 complete minutes, 32,884 have zero requests. 30,026 exceed the descriptive threshold of five times the median (10 requests/min).
  Hourly lag correlations: 1 hour 0.690; 24 hours 0.447; 168 hours 0.463. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.
- **Measured, burstgpt_3:** complete-minute median 4, P95 155, P99 494 requests/min; peak 1,048. Of 158,397 complete minutes, 39,360 have zero requests. 39,296 exceed the descriptive threshold of five times the median (20 requests/min).
  Hourly lag correlations: 1 hour 0.870; 24 hours 0.068; 168 hours -0.018. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.

A zero minute means no record within that observed trace window, not proof of idle GPU capacity. First and last minute bins can be partial; quiet/spike counts exclude them. The gap between trace 2 and trace 3 is unobserved and is not filled with zero-demand records. Relative days do not identify calendar weekdays. Arrival spikes alone do not establish predictability or a successful scheduling policy.

## Completion latency and size

**Measured:** traces 1 and 2 have no elapsed-time column. Trace 3 has 5,344,021 values: median 0 s, P90 6 s, P95 14 s, P99 39 s; maximum 714 s. 3,175,935 values (59.43%) are zero. Pearson correlation between input tokens and recorded elapsed time is 0.1064, using all trace-3 rows, including zero latencies and zero-response rows. The relationship is descriptive and can reflect request mix, service conditions or measurement resolution; it is not causal.

The size-versus-latency figures use all rows and show exact P50/P95/P99 within geometric input-size bins, both pooled and stratified by LLM model. Bins with fewer than 100 requests are excluded from quantile lines but retained in pooled count plots. Model-stratified counts, bin quantiles and correlations are in the quality report. Stratification does not control unknown hardware or service conditions. Latency is request-to-complete-response time, not time to first token. Integer-second values and frequent zeros prevent precise subsecond calibration.

## Quality, provenance and interpretation

Every Parquet shard was read back and compared with the in-memory Arrow table, including schema metadata. Row counts reconcile. All six files have nondecreasing timestamps; all token totals equal input plus output tokens. Missing raw values and absent fields are counted by trace in `burstgpt-quality.json`. Exact repeated raw tuples are retained with separate source row IDs, because they cannot reliably be classified as ingestion duplicates. The success-only variants are verified derived subsets and must not be concatenated into the canonical request table.

**Inference for scheduling:** the changing arrival rates and skewed token demand support replay experiments for queues, admission, batching and autoscaling. The model and log categories permit workload-specific descriptions. Such experiments require explicit hardware throughput, cost and SLO assumptions from other evidence. Observed final output lengths are unavailable at admission and must not serve as an oracle scheduling input.

**Unanswerable from this source:** GPU placement, thermal behaviour, energy, cloud cost, hardware service rates, pre-emption effects, failure causes and policy improvements. No physical GPU identifier, explicit deadline or target SLO exists. No unrelated Alibaba, thermal or cloud-price record is treated as the same request or device.

Licence: CC-BY-4.0. Keep source attribution and the supplied licence/citation. Source and field definitions: [BurstGPT](https://github.com/HPMLL/BurstGPT), [v2.0 release](https://github.com/HPMLL/BurstGPT/releases/tag/v2.0).

Reproduce: `python scripts/phase1/burstgpt.py`. Dependencies load from `.deps` when present. Outputs: per-trace Parquet shards, quality/schema JSON, this report, dictionary and six PNG/PDF figures. No model or simulator is created.
