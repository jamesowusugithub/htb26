# Alibaba Phase 1 findings

Verified: both CSVs were inspected before transformation. Jobs: 466,867 original and 466,867 harmonised rows. Nodes: 4,278 original and 4,278 harmonised rows. Every raw value survives a Parquet round trip unchanged. Source identifiers, data-record row numbers and file hashes are preserved. Full quality checks and the field dictionary are in `alibaba-quality.json` and `alibaba-dictionary.csv`.

## Measured workload differences

HP: 415,713 jobs (89.04%); Spot: 51,154 (10.96%). HP duration median 1,101.0s, P90 58,770.0s, P95 631,952.8s, P99 5,972,708.9s. Spot duration median 2,095.5s, P90 21,740.0s, P95 35,864.0s, P99 186,322.2s. Spot jobs have a higher median duration, while HP has a much longer upper tail. A mean alone would conceal this difference.

Multiworker jobs: HP 5.57%, Spot 31.53%. These are worker-instance requests, not measured GPU allocations. Fractional GPU requests occur in 49,238 records; they are preserved and do not establish actual fractional GPU utilisation.

Hardware catalogue: 4,278 nodes and 10,412 recorded GPUs across 6 labels. GPU-series-1 and GPU-series-2 are anonymised labels. Their architecture and compatibility with cloud offerings remain unknown. No job-to-node assignment key is provided.

The largest recorded-request × duration proxy is A10 (14,603,145.2 GPU-request hours). Under the separate worker-expanded sensitivity interpretation, the largest is A10 (14,672,215.3 proxy hours). These are alternate request-based proxies, not additive demand measures, measured GPU-hours, energy or utilisation. The README calls gpu_request a job request but does not clearly specify its relationship to worker_num. No total allocated GPU count is inferred.

## Arrivals, spikes and quiet periods

Submit time is relative seconds from the first source job. The maximum is 15,902,470s (184.06 days). No calendar origin, weekday, timezone, workday or local clock hour is fabricated. All UTC timestamps remain null. 3,588 jobs appear at time zero; source documentation does not explain this concentration, so the origin bin needs separate interpretation.

One-hour aggregation includes all 4,417 complete bins, including zero-count bins, and labels the final partial bin. Median full-hour arrivals: 89.0; P95 226.0; P99 500.8. 45 full bins exceed the empirical P99 threshold (1.02% of full bins). This empirical threshold describes observed extremes; its exceedance fraction is partly defined by the quantile and is not a predictive event probability. Highest full-hour count excluding the origin bin: 841.

There are 0 zero-arrival full hours and 2 with at most ten arrivals. HP has 0 zero-arrival hours and Spot has 1,151. Quiet arrivals do not establish idle GPUs because earlier jobs can remain active. Complete bins prevent the omission of quiet periods. There are 15 contiguous runs above the hourly P99 threshold. Descriptive Pearson arrival autocorrelation, including the origin bin: lag 1h 0.742, lag 24h 0.564, lag 168h 0.109. Excluding the origin hour: lag 1h 0.886, lag 24h 0.660, lag 168h 0.136. These describe serial association in this observed trace; they do not test future predictability or establish repeating calendar patterns. No fitted model or statistical-significance claim is made.

## Quality, units and limits

Raw blank fields: jobs 0; nodes 0. Duplicate full source rows: jobs 0, nodes 0. Duplicate source job IDs: 0; node IDs: 0. No negative submission times, nonpositive durations, nonpositive GPU requests or nonpositive worker counts were found. These bounded checks establish internal consistency for those fields; they do not prove complete or unbiased workload capture.

Source duration and submit time are already seconds. Figures convert seconds to hours or days only for display. Both demand proxies divide by 3600 to express request-hours. Raw numeric text remains available. Queue wait, actual allocation, starts, finishes, interruptions, checkpoints, SLO target values, time-varying cluster availability, measured power and measured GPU utilisation are absent. In particular, submit_time + duration is not labelled as a measured finish time. Source censoring semantics are unspecified; long durations and the time-zero concentration need sensitivity checks before scheduling evaluation.

Inference: compare HP and Spot separately when designing duration classes and admission controls. Spot's higher multiworker fraction supports testing gang-aware admission as a hypothesis. Long HP tails and short Spot tails support testing different policies per class. None of these measurements proves a policy improves throughput, cost, wait or SLO compliance. A simulator, fitted predictor or trained model was not created.

Licensing: downloaded source README requests paper citation but supplies no explicit licence grant. Reuse/redistribution terms are not established by the downloaded documents. Preserve the source README and attribution; do not silently label this data CC-BY. Other datasets remain separate tables; a shared hardware label never establishes the same physical GPU or data centre.

## Artefacts and reproduction

Run `python scripts/phase1/alibaba.py` from the repository root with pandas, NumPy, PyArrow and Matplotlib. Versions and hashes are recorded. Outputs: `harmonized/alibaba/jobs.parquet`, `nodes.parquet`, `arrival_hourly.parquet`; five PNG/PDF figure pairs under `analysis/figures/alibaba_*`; this report, source-preserving dictionary, quality checks and measured summary under `analysis/phase1/`.

Source: https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu
