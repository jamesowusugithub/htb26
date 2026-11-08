# Phase 1: GPU data harmonisation and trend analysis

Completed on 8 November 2026. All four retained sources were processed. Kestrel is excluded.
No prediction model, reinforcement-learning environment, simulator or frontend was built.

## Outcome and analytical boundaries

Normalisation standardises schemas, units, hardware identifiers and provenance. It does not
apply min-max scaling or z-scores. Missing values are not imputed. The source tables stay
separate: there is no claim that they describe the same GPU, job or data centre.

## Source records retained

| Source | Raw scope | Harmonised scope | Counting rule |
| --- | ---: | ---: | --- |
| Alibaba jobs | 466,867 jobs | 466,867 jobs | One job per source row |
| Alibaba nodes | 4,278 nodes | 4,278 nodes | One node per source row |
| BurstGPT | 20,776,759 rows across six files | 10,632,194 requests | The other 10,144,565 rows are verified filtered variants of the full traces |
| GPUCloudCompare plans | 131 plans | 131 plans | Eight providers; the 2,997 historical records form a separate series |
| Thermal | 2,424,786 timestamp-bearing records in 95 CSV paths | 1,843,254 sensor observations in 72 unique sessions | These expand to 11,923,254 per-GPU telemetry rows; 23 baseline copies are byte-identical |

These counts describe different entities. Do not add them into one workload total.

## Main measured findings

Alibaba's 415,713 high-priority jobs have a 1,101 s median duration, while 51,154
Spot jobs have a 2,095.5 s median. The high-priority P99 is 5,972,708.9 s, compared
with 186,322.2 s for Spot. The trace records requests, not actual allocation or wait time.

BurstGPT's three full traces have complete-minute median rates of 2, 2 and 4
requests/min and observed peaks of 1,250, 1,104 and 1,048 requests/min. Trace 3
has a 0 s median completion latency; 59.43% of values are zero at its recorded
precision. Latency and token counts do not measure GPU service time.

Among 18 identified current cloud plans with a stated GPU count and hourly USD
price, the median listed price is USD 4.175 per GPU-hour. The plans differ in
hardware and region, so this is a coverage summary, not a value ranking.

Thermal measurements vary by recorded hardware and workload. For example, the
B200 median temperature is 37 degrees C under image generation and 50 degrees C under text
generation, with different power distributions. These are sample-weighted sensor
readings from experiments, not independent jobs or controlled scheduling trials.

## Time and unit boundaries

Alibaba submits are seconds from its first recorded job. BurstGPT timestamps
support relative minute and hour bins, but no trustworthy calendar weekday.
Thermal node sessions use elapsed seconds; workstation clocks have unknown
timezones and three partial-clock sessions. Pricing uses offer snapshots and
daily index dates. No source clock is aligned with another source clock.
GPU-request hours are demand proxies, USD/GPU-hour is a listed price unit, and
temperature/power/utilisation are sampled telemetry. None is a common measure
of job energy or cost.

Alibaba and BurstGPT have source-relative time. Thermal recordings have local clocks with
unknown timezones and explicit parse failures. Pricing has snapshot/index dates. No shared
calendar timeline is invented. Raw values remain available with source rows and file hashes.

Full decoding passed for 210 Parquet files. PNG integrity and paired PDF
existence passed for 19 figure pairs. These checks establish output
readability; source-specific reconciliation and semantic checks are documented separately.
Graph appearance was inspected separately. PDF rendering was not independently verified.

- [Data dictionary and relationships](data-dictionary.md)
- [Full validation catalogue](phase1/validation.json)
- [Reproduction instructions](../harmonized/README.md)
- [Exact dependency versions](../requirements-phase1.lock.txt)

## Scheduling decisions supported for investigation

| Evidence | Decision worth investigating | Limit |
| --- | --- | --- |
| Alibaba priority, requests, duration and arrivals | Priority-aware admission, placement and backfilling | Actual starts, allocation and interruptions are absent; request scope is ambiguous |
| BurstGPT arrival and token variability | Batching, queue admission and serving-capacity changes | GPU service times and hardware are unknown; elapsed time is coarse end-to-end latency |
| Current cloud offers and daily indices | Cost sensitivity for explicitly specified hardware/region/billing scenarios | Price does not establish performance, availability or interruption risk |
| Experimental temperature, power and load | Workload power-budget and temperature monitoring hypotheses | Experiments are not causal scheduler comparisons; workloads and sampling rates differ |

These are hypotheses for later evaluation. No scheduling improvement or future predictability
has been demonstrated. Quiet arrivals do not establish idle GPUs, observed output token counts
are not known at request admission, and temperature correlations do not establish throttling.
Exact hardware variants and source-local identifiers must remain distinct.


## Alibaba Phase 1 findings

Verified: both CSVs were inspected before transformation. Jobs: 466,867 original and 466,867 harmonised rows. Nodes: 4,278 original and 4,278 harmonised rows. Every raw value survives a Parquet round trip unchanged. Source identifiers, data-record row numbers and file hashes are preserved. Full quality checks and the field dictionary are in `alibaba-quality.json` and `alibaba-dictionary.csv`.

### Measured workload differences

HP: 415,713 jobs (89.04%); Spot: 51,154 (10.96%). HP duration median 1,101.0s, P90 58,770.0s, P95 631,952.8s, P99 5,972,708.9s. Spot duration median 2,095.5s, P90 21,740.0s, P95 35,864.0s, P99 186,322.2s. Spot jobs have a higher median duration, while HP has a much longer upper tail. A mean alone would conceal this difference.

Multiworker jobs: HP 5.57%, Spot 31.53%. These are worker-instance requests, not measured GPU allocations. Fractional GPU requests occur in 49,238 records; they are preserved and do not establish actual fractional GPU utilisation.

Hardware catalogue: 4,278 nodes and 10,412 recorded GPUs across 6 labels. GPU-series-1 and GPU-series-2 are anonymised labels. Their architecture and compatibility with cloud offerings remain unknown. No job-to-node assignment key is provided.

The largest recorded-request × duration proxy is A10 (14,603,145.2 GPU-request hours). Under the separate worker-expanded sensitivity interpretation, the largest is A10 (14,672,215.3 proxy hours). These are alternate request-based proxies, not additive demand measures, measured GPU-hours, energy or utilisation. The README calls gpu_request a job request but does not clearly specify its relationship to worker_num. No total allocated GPU count is inferred.

### Arrivals, spikes and quiet periods

Submit time is relative seconds from the first source job. The maximum is 15,902,470s (184.06 days). No calendar origin, weekday, timezone, workday or local clock hour is fabricated. All UTC timestamps remain null. 3,588 jobs appear at time zero; source documentation does not explain this concentration, so the origin bin needs separate interpretation.

One-hour aggregation includes all 4,417 complete bins, including zero-count bins, and labels the final partial bin. Median full-hour arrivals: 89.0; P95 226.0; P99 500.8. 45 full bins exceed the empirical P99 threshold (1.02% of full bins). This empirical threshold describes observed extremes; its exceedance fraction is partly defined by the quantile and is not a predictive event probability. Highest full-hour count excluding the origin bin: 841.

There are 0 zero-arrival full hours and 2 with at most ten arrivals. HP has 0 zero-arrival hours and Spot has 1,151. Quiet arrivals do not establish idle GPUs because earlier jobs can remain active. Complete bins prevent the omission of quiet periods. There are 15 contiguous runs above the hourly P99 threshold. Descriptive Pearson arrival autocorrelation, including the origin bin: lag 1h 0.742, lag 24h 0.564, lag 168h 0.109. Excluding the origin hour: lag 1h 0.886, lag 24h 0.660, lag 168h 0.136. These describe serial association in this observed trace; they do not test future predictability or establish repeating calendar patterns. No fitted model or statistical-significance claim is made.

### Quality, units and limits

Raw blank fields: jobs 0; nodes 0. Duplicate full source rows: jobs 0, nodes 0. Duplicate source job IDs: 0; node IDs: 0. No negative submission times, nonpositive durations, nonpositive GPU requests or nonpositive worker counts were found. These bounded checks establish internal consistency for those fields; they do not prove complete or unbiased workload capture.

Source duration and submit time are already seconds. Figures convert seconds to hours or days only for display. Both demand proxies divide by 3600 to express request-hours. Raw numeric text remains available. Queue wait, actual allocation, starts, finishes, interruptions, checkpoints, SLO target values, time-varying cluster availability, measured power and measured GPU utilisation are absent. In particular, submit_time + duration is not labelled as a measured finish time. Source censoring semantics are unspecified; long durations and the time-zero concentration need sensitivity checks before scheduling evaluation.

Inference: compare HP and Spot separately when designing duration classes and admission controls. Spot's higher multiworker fraction supports testing gang-aware admission as a hypothesis. Long HP tails and short Spot tails support testing different policies per class. None of these measurements proves a policy improves throughput, cost, wait or SLO compliance. A simulator, fitted predictor or trained model was not created.

Licensing: downloaded source README requests paper citation but supplies no explicit licence grant. Reuse/redistribution terms are not established by the downloaded documents. Preserve the source README and attribution; do not silently label this data CC-BY. Other datasets remain separate tables; a shared hardware label never establishes the same physical GPU or data centre.

### Artefacts and reproduction

Run `python scripts/phase1/alibaba.py` from the repository root with pandas, NumPy, PyArrow and Matplotlib. Versions and hashes are recorded. Outputs: `harmonized/alibaba/jobs.parquet`, `nodes.parquet`, `arrival_hourly.parquet`; five PNG/PDF figure pairs under `analysis/figures/alibaba_*`; this report, source-preserving dictionary, quality checks and measured summary under `analysis/phase1/`.

Source: https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu

## BurstGPT Phase 1 findings

**Verified:** all six release CSVs were read (20,776,759 stored rows). Canonical full traces yield 10,632,194 Parquet rows. The 10,144,565 filtered-variant rows match ordered success-only subsets exactly and are not emitted a second time.

| Trace | Full rows | Zero response rows (%) | Span (days) | Input P50 / P95 / P99 (tokens) | Output P50 / P95 / P99 (tokens) | Extra identical raw rows |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| burstgpt_1 | 1,429,737 | 25,443 (1.7796%) | 60.995 | 251 / 2,461 / 3,387 | 34 / 460 / 1,491 | 54,040 |
| burstgpt_2 | 3,858,436 | 74,223 (1.9237%) | 60.000 | 215 / 558 / 1,038 | 7 / 160 / 478 | 150,150 |
| burstgpt_3 | 5,344,021 | 387,963 (7.2598%) | 109.999 | 327 / 1,405 / 3,354 | 14 / 324 / 876 | 347,285 |

### Arrival variation

- **Measured, burstgpt_1:** complete-minute median 2, P95 84, P99 206 requests/min; peak 1,250. Of 87,831 complete minutes, 26,988 have zero requests. 20,177 exceed the descriptive threshold of five times the median (10 requests/min).
  Hourly lag correlations: 1 hour 0.680; 24 hours 0.071; 168 hours 0.018. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.
- **Measured, burstgpt_2:** complete-minute median 2, P95 220, P99 356.03 requests/min; peak 1,104. Of 86,398 complete minutes, 32,884 have zero requests. 30,026 exceed the descriptive threshold of five times the median (10 requests/min).
  Hourly lag correlations: 1 hour 0.690; 24 hours 0.447; 168 hours 0.463. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.
- **Measured, burstgpt_3:** complete-minute median 4, P95 155, P99 494 requests/min; peak 1,048. Of 158,397 complete minutes, 39,360 have zero requests. 39,296 exceed the descriptive threshold of five times the median (20 requests/min).
  Hourly lag correlations: 1 hour 0.870; 24 hours 0.068; 168 hours -0.018. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.

A zero minute means no record within that observed trace window, not proof of idle GPU capacity. First and last minute bins can be partial; quiet/spike counts exclude them. The gap between trace 2 and trace 3 is unobserved and is not filled with zero-demand records. Relative days do not identify calendar weekdays. Arrival spikes alone do not establish predictability or a successful scheduling policy.

### Completion latency and size

**Measured:** traces 1 and 2 have no elapsed-time column. Trace 3 has 5,344,021 values: median 0 s, P90 6 s, P95 14 s, P99 39 s; maximum 714 s. 3,175,935 values (59.43%) are zero. Pearson correlation between input tokens and recorded elapsed time is 0.1064, using all trace-3 rows, including zero latencies and zero-response rows. The relationship is descriptive and can reflect request mix, service conditions or measurement resolution; it is not causal.

The size-versus-latency figures use all rows and show exact P50/P95/P99 within geometric input-size bins, both pooled and stratified by LLM model. Bins with fewer than 100 requests are excluded from quantile lines but retained in pooled count plots. Model-stratified counts, bin quantiles and correlations are in the quality report. Stratification does not control unknown hardware or service conditions. Latency is request-to-complete-response time, not time to first token. Integer-second values and frequent zeros prevent precise subsecond calibration.

### Quality, provenance and interpretation

Every Parquet shard was read back and compared with the in-memory Arrow table, including schema metadata. Row counts reconcile. All six files have nondecreasing timestamps; all token totals equal input plus output tokens. Missing raw values and absent fields are counted by trace in `burstgpt-quality.json`. Exact repeated raw tuples are retained with separate source row IDs, because they cannot reliably be classified as ingestion duplicates. The success-only variants are verified derived subsets and must not be concatenated into the canonical request table.

**Inference for scheduling:** the changing arrival rates and skewed token demand support replay experiments for queues, admission, batching and autoscaling. The model and log categories permit workload-specific descriptions. Such experiments require explicit hardware throughput, cost and SLO assumptions from other evidence. Observed final output lengths are unavailable at admission and must not serve as an oracle scheduling input.

**Unanswerable from this source:** GPU placement, thermal behaviour, energy, cloud cost, hardware service rates, pre-emption effects, failure causes and policy improvements. No physical GPU identifier, explicit deadline or target SLO exists. No unrelated Alibaba, thermal or cloud-price record is treated as the same request or device.

Licence: CC-BY-4.0. Keep source attribution and the supplied licence/citation. Source and field definitions: [BurstGPT](https://github.com/HPMLL/BurstGPT), [v2.0 release](https://github.com/HPMLL/BurstGPT/releases/tag/v2.0).

Reproduce: `python scripts/phase1/burstgpt.py`. Dependencies load from `.deps` when present. Outputs: per-trace Parquet shards, quality/schema JSON, this report, dictionary and six PNG/PDF figures. No model or simulator is created.

## Pricing findings

Verified: 131 plans from 8 providers. JSON and CSV plan keys agree.
Hourly USD prices exist for 46 plans, monthly USD for 109, monthly EUR for 76.
There are 16 missing model labels and 10 generic `GPU` labels.
The history has 181 all-model days and 2,997 records in 23 model series, with unequal coverage.
Three repeated provider/plan keys represent four regional Latitude offers. They are retained, not silently deleted.
Their listed prices differ (USD48–66/hour for the same 8-GPU model label), a 37.5% range above the minimum.
Hourly prices for 18 identified plans can be divided by their stated GPU count; the
median is USD 4.175/GPU-hour. This mixes distinct hardware and is not a value ranking.

Figures: `pricing_hourly_prices` compares identified current plans; `pricing_history` shows four exact
model labels over time with separate hourly USD, monthly USD and monthly EUR panels;
`pricing_coverage` exposes missing billing/currency coverage. All contain source captions.
Missing GPU counts or prices remain null. No month/hour or EUR/USD conversion is assumed.
CPU, RAM, region, interconnect and model variants must be checked before declaring options compatible.
Historical medians reflect changing plan/provider composition and are not per-plan spot-price histories.
This supports scenario cost accounting, not workload placement without performance measurements.

Licence: CC-BY-4.0. Attribution: GPU Cloud Price Index, https://gpucloudcompare.com/data/.
All records retain raw JSON, original source identifiers and source-file hashes in the quality manifest.

## Thermal dataset: harmonisation and findings

Verified: the original 95 CSV paths contain 2,424,786 timestamp-bearing sensor records. Exact file SHA256 deduplication leaves 72 sessions with 1,843,254 observations. These expand to 11,923,254 discrete-GPU telemetry rows: 5,760,000 H100,5,760,000 B200 and 403,254 RTX 3060 readings. Raw-wide Parquet also retains repeated headers and sensor-label footer records. No observed sensor rows are discarded for missing times.

The recordings are from September–October 2025. The dataset release is 2026. Node sessions span about 899.98 seconds with 20 ms median intervals. Workstation clocks have unknown timezones. Three workstation sessions contain only partial clock strings; their 30,258 sensor readings remain available, but absolute timestamp and elapsed seconds are null. No hours or timing offsets are invented.

### Measured distributions

| GPU model | Workload | n GPU readings | Temperature median / P95 (°C) | Power median / P95 (W) | Utilisation median / P95 (%) |
|---|---|---:|---:|---:|---:|
| NVIDIA B200 | Image Generation Diffusion Models | 2,520,000 | 37.0 / 55.0 | 240.4 / 746.3 | 96.0 / 100.0 |
| NVIDIA B200 | Text Generation LLMs | 3,240,000 | 50.0 / 69.0 | 640.1 / 921.0 | 99.0 / 100.0 |
| NVIDIA GeForce RTX 3060 | Feature Forecasting | 90,818 | 60.2 / 65.3 | 78.1 / 116.9 | 42.0 / 82.0 |
| NVIDIA GeForce RTX 3060 | Image Captioning | 70,621 | 49.4 / 56.7 | 46.4 / 83.8 | 19.0 / 91.0 |
| NVIDIA GeForce RTX 3060 | Image Classifications | 90,907 | 52.9 / 61.9 | 60.3 / 78.1 | 34.0 / 100.0 |
| NVIDIA GeForce RTX 3060 | Reinforcment Learning | 80,361 | 35.7 / 53.3 | 4.8 / 118.2 | 0.0 / 74.0 |
| NVIDIA GeForce RTX 3060 | Text Generation | 70,547 | 45.4 / 59.8 | 23.4 / 41.1 | 0.0 / 70.0 |
| NVIDIA H100 | Image Generation Diffusion Models | 2,520,000 | 40.0 / 59.0 | 132.3 / 573.3 | 98.0 / 100.0 |
| NVIDIA H100 | Text Generation LLMs | 3,240,000 | 53.0 / 63.0 | 528.2 / 684.5 | 100.0 / 100.0 |

Explicit workstation indicators: thermal limit active in 0 of 403,254 readings; power limit active in 2,400. Node recordings have no explicit thermal-limit indicator, so node throttling cannot be established from temperature alone. All node CPU temperature and CPU power fields are missing. Workstation CPU measurements remain in raw wide but are deliberately outside the selected GPU telemetry fields.

### Interpretation for scheduling

The temperature–utilisation and temperature–power density plots show the joint distributions of the recorded sensors. Temperature has persistence over a run; it is not an instantaneous measure of demand. The time plots show one-second medians and the observed range across all GPUs and readings for one representative run per model. Hardware and workload groups differ, and pooled averages can hide training phases.

Inference: workload-specific power envelopes and time-series thermal state could inform admission decisions under a power budget. The evidence supports descriptive profiling and future validation, not a claim that a scheduling policy improves outcomes. It does not establish energy per token, cooling demand, completion time under a cap, safe consolidation limits, thermal causality or effects on service deadlines. Throughput, progress, ambient conditions, cooling settings, concurrent jobs and controlled power interventions are absent.

### Quality, provenance and limits

The deduplication manifest preserves all 95 source paths and identifies 23 byte-identical baseline copies. Deduplicate before splitting experiments for any later analysis. Source row order, source CSV logical record number, archive member and full SHA256 remain available. Raw-wide positional fields preserve duplicated HWiNFO headers; no merged column values overwrite the originals. Missing values remain null, distinct from zero. Selected memory values retain the original MB-labelled units because decimal/binary conventions are not established; no byte conversion is made. GPU core-load and memory-activity sensors are not automatically equivalent across monitoring tools.

Figures use all discrete GPU indices, not only GPU0. They count recorded readings, not independent experiments. The 20 ms node cadence and approximately 100 ms workstation cadence produce different sample weights; driver sensor refresh can be slower than polling. Shared hardware model identifiers are descriptive and do not create a physical record-level relationship to the other datasets.

Licence conflict remains unresolved: Figshare API metadata identifies CC BY 4.0; the archive LICENSE and README identify CC BY-NC-ND 4.0. Clarify with the authors before redistributing source or adapted datasets or using them commercially.

Reproduce with `python scripts/phase1/thermal.py`. Dependencies are the root-local pandas, NumPy, PyArrow and Matplotlib packages. The script verifies all 72 session keys, every Parquet row count, all eight node GPU indices, the single workstation GPU index and node CPU null fields. Detailed missing counts and per-run/GPU percentiles are in `thermal-quality.json`; model/workload P50/P90/P95/P99 are in `thermal-summary.json`. No models or simulators are created.

## Graphs

Each graph carries its source, units, observation counts and interpretation limits. PDF versions are linked for export.

### Hourly arrivals, including the origin concentration and a separate post-origin view.

![Hourly arrivals, including the origin concentration and a separate post-origin view.](figures/alibaba_arrivals.png)

[PDF](figures/alibaba_arrivals.pdf)

### Full job-duration distributions by priority, with skew retained.

![Full job-duration distributions by priority, with skew retained.](figures/alibaba_duration_distribution.png)

[PDF](figures/alibaba_duration_distribution.pdf)

### Two explicitly separate request-duration proxies by hardware, not measured GPU use.

![Two explicitly separate request-duration proxies by hardware, not measured GPU use.](figures/alibaba_hardware_demand.png)

[PDF](figures/alibaba_hardware_demand.pdf)

### High-priority and spot submission volumes.

![High-priority and spot submission volumes.](figures/alibaba_priority_counts.png)

[PDF](figures/alibaba_priority_counts.pdf)

### Recorded GPU requests and worker counts by priority.

![Recorded GPU requests and worker counts by priority.](figures/alibaba_resource_requests.png)

[PDF](figures/alibaba_resource_requests.pdf)

### Relative 24-hour demand profiles; calendar clock and weekday are unknown.

![Relative 24-hour demand profiles; calendar clock and weekday are unknown.](figures/burstgpt_daily_profiles.png)

[PDF](figures/burstgpt_daily_profiles.pdf)

### Completion-latency distributions for trace 3.

![Completion-latency distributions for trace 3.](figures/burstgpt_latency_distribution.png)

[PDF](figures/burstgpt_latency_distribution.pdf)

### Traffic and spikes across observed trace spans, retaining quiet bins.

![Traffic and spikes across observed trace spans, retaining quiet bins.](figures/burstgpt_request_rates.png)

[PDF](figures/burstgpt_request_rates.pdf)

### Input size versus recorded completion latency, including zero latency.

![Input size versus recorded completion latency, including zero latency.](figures/burstgpt_size_latency.png)

[PDF](figures/burstgpt_size_latency.pdf)

### Size and latency within each recorded LLM model category.

![Size and latency within each recorded LLM model category.](figures/burstgpt_size_latency_by_model.png)

[PDF](figures/burstgpt_size_latency_by_model.pdf)

### Input and output token distributions across canonical full traces.

![Input and output token distributions across canonical full traces.](figures/burstgpt_token_distributions.png)

[PDF](figures/burstgpt_token_distributions.pdf)

### Recorded and missing billing/currency coverage across providers.

![Recorded and missing billing/currency coverage across providers.](figures/pricing_coverage.png)

[PDF](figures/pricing_coverage.pdf)

### Selected hardware price indices with billing units and currencies in separate panels.

![Selected hardware price indices with billing units and currencies in separate panels.](figures/pricing_history.png)

[PDF](figures/pricing_history.pdf)

### Identified current hourly offers, divided by recorded GPU count and labelled by provider and region.

![Identified current hourly offers, divided by recorded GPU count and labelled by provider and region.](figures/pricing_hourly_prices.png)

[PDF](figures/pricing_hourly_prices.pdf)

### Sample-weighted temperature distributions by GPU model.

![Sample-weighted temperature distributions by GPU model.](figures/thermal_temperature_distribution.png)

[PDF](figures/thermal_temperature_distribution.pdf)

### Joint GPU temperature and power observations.

![Joint GPU temperature and power observations.](figures/thermal_temperature_power.png)

[PDF](figures/thermal_temperature_power.pdf)

### Temperature over elapsed time in explicitly selected training sessions.

![Temperature over elapsed time in explicitly selected training sessions.](figures/thermal_temperature_time.png)

[PDF](figures/thermal_temperature_time.pdf)

### Joint GPU temperature and utilisation observations.

![Joint GPU temperature and utilisation observations.](figures/thermal_temperature_utilisation.png)

[PDF](figures/thermal_temperature_utilisation.pdf)

### Temperature distributions separated by recorded hardware and workload groups.

![Temperature distributions separated by recorded hardware and workload groups.](figures/thermal_temperature_workload.png)

[PDF](figures/thermal_temperature_workload.pdf)

## Findings that cannot be established

These data do not establish a feasible replay of a production cluster without further capacity,
placement and policy information. They do not provide causal evidence for scheduler speed-ups,
carbon savings or energy savings. There are no measured cross-hardware completion-time curves
for the same submitted jobs. There is no joint job-to-power-to-price record across the four sources.
Before any later modelling, define the decision time, available input fields, train/test time
boundaries, feasible actions and failure/overrun handling. Do not leak final duration or output
token count into an admission-time predictor.

## Licensing and redistribution

BurstGPT and GPUCloudCompare identify CC-BY-4.0 terms; preserve their attribution and citations.
The downloaded Alibaba README provides citation instructions but no explicit licence grant.
Figshare metadata says CC BY 4.0 while the thermal archive says CC BY-NC-ND 4.0. These are
unresolved source terms, not a new licence applied to all repository contents. The private
repository and preserved source notices do not resolve those discrepancies.
