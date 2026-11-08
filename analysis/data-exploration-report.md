# GPU data harmonisation and exploration: interim Phase 1 report

Status: 8 November 2026. Alibaba and GPUCloudCompare transformations have executed locally. Their measured findings are reported below. BurstGPT and thermal harmonisation are still running and are not claimed complete in this interim publication. Supporting Parquet files, graphs, scripts and dictionaries are being validated for the next integration commit; this initial commit publishes this report only.

Kestrel is excluded from Phase 1. No model, reinforcement-learning environment, simulator or frontend has been built.

## Analytical boundaries

The four sources describe different systems. Their rows are not linked as observations from the same GPU or data centre. Hardware labels support a labelled catalogue, not proof of workload compatibility. Missing measurements stay missing. Measured findings and scheduling hypotheses are separate.

Alibaba time is relative to the first source job. It has no known calendar origin. BurstGPT clocks, cloud price dates and thermal run times must retain their own meanings. No joint calendar timeline is inferred.

## Alibaba: measured findings

Source: [Alibaba 2026 Spot GPU](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu).

| Table | Original rows | Harmonised rows | Validation |
|---|---:|---:|---|
| Jobs | 466,867 | 466,867 | Every raw field identical after Parquet round trip |
| Nodes | 4,278 | 4,278 | Every raw field identical after Parquet round trip |

There are 415,713 high-priority jobs (89.04%) and 51,154 Spot jobs (10.96%).

| Source job class | Median duration, seconds | P90, seconds | P95, seconds | P99, seconds | Multiple workers |
|---|---:|---:|---:|---:|---:|
| High priority | 1,101.0 | 58,770.0 | 631,952.8 | 5,972,708.9 | 5.57% |
| Spot | 2,095.5 | 21,740.0 | 35,864.0 | 186,322.2 | 31.53% |

Spot has a higher median duration, but high-priority jobs have a much longer upper tail. Spot jobs more frequently request multiple worker instances. Neither observation establishes occupied GPUs or performance.

The node catalogue lists 10,412 GPUs across six model labels. GPU-series-1 and GPU-series-2 remain anonymised and cannot be assigned architectures. Job-to-node assignments are absent.

Arrival analysis includes every one-hour bin: 4,417 complete bins and one labelled final partial bin over 184.06 relative days. Median complete-hour arrivals are 89; P95 is 226; P99 is 500.84. There are 45 hours strictly above P99, in 15 contiguous runs. This is a descriptive threshold; its roughly 1% exceedance rate is partly defined by the quantile.

There are no zero-arrival complete hours across both classes. Spot alone has 1,151 zero-arrival hours. Quiet arrivals do not establish idle GPUs. At relative time zero, 3,588 jobs are recorded. The first hour contains 3,740 arrivals. Its origin concentration is unexplained in source documentation; graphs show both the full trace and a separate post-origin detail. The largest hourly count after the first hour is 841.

Descriptive hourly arrival autocorrelation is 0.742 at lag 1h, 0.564 at lag 24h and 0.109 at lag 168h. Excluding the first hour changes these to 0.886, 0.660 and 0.136. These are serial associations in the observed trace. They are not tests of future prediction, calendar cycles or significance.

The 49,238 fractional GPU requests remain fractional requests. The source does not clearly define GPU request scope relative to worker count. Two alternative demand proxies are retained: recorded GPU request times duration, and a separate sensitivity proxy that also multiplies by worker count. They are not added together or called measured GPU-hours. A10 has the largest recorded-request-duration proxy, at 14.60 million GPU-request hours. Neither proxy measures actual allocation, utilisation, energy or completed computational work.

Quality: there are no raw blank fields, duplicate source IDs or exact duplicate rows in either CSV. No negative relative submission time, nonpositive duration, nonpositive GPU request or nonpositive worker count was found. These bounded checks do not prove complete or unbiased trace capture. Raw values, source rows and file hashes are retained. Seconds are already the source time unit; plots convert to hours/days for display only. Absolute UTC timestamps remain null.

Unavailable fields include queue waits, measured starts and finishes, interruptions, checkpoints, SLO target values, time-varying availability, GPU utilisation and power. Censoring semantics are undocumented. Submission plus duration is not presented as a measured finish time.

Five figure pairs have been generated locally: arrivals, priority counts, duration distribution, hardware-demand proxies and resource-request distributions. PNGs have been visually checked. Each figure states source, sample size, units and interpretation.

## GPUCloudCompare: measured findings

Source and attribution: [GPU Cloud Price Index](https://gpucloudcompare.com/data/), CC-BY-4.0.

There are 131 current plans from eight providers. CSV and JSON plan keys agree. Prices are available for 46 plans in hourly USD, 109 in monthly USD and 76 in monthly EUR. Billing units and currencies remain separate. Missing prices are not zero. No monthly-to-hourly or EUR-to-USD conversion is assumed.

| Output | Rows | Meaning |
|---|---:|---|
| Plans | 131 | Current JSON source plans |
| Price offers | 393 | Three billing/currency slots per plan, including null prices |
| Preserved CSV rows | 131 | Original current CSV records |
| History observations | 9,534 | Three separate price-unit series across aggregate/model entries |

History contains 181 all-model daily records and 2,997 records across 23 model series, with unequal date coverage. There are 16 absent hardware labels and 10 generic GPU labels. Five current plans lack GPU counts. There are three repeated plan keys; source-record identifiers preserve distinct rows rather than silently merging them.

Hourly per-GPU prices can be calculated for 18 identified plans with stated GPU counts. Median is USD 4.1755/GPU-hour; observed range is USD 0.76 to 16.00/GPU-hour. This combines different hardware and is not a cost-effectiveness ranking. CPU, RAM, region, interconnect, GPU count and model variant need checking before options are called compatible. Historical medians reflect changing plan/provider composition, not a per-plan spot-price process.

Three local figure pairs show identified hourly offers, exact-model historical trends and missing billing/currency coverage. The next integration commit will publish validated artefacts.

## BurstGPT and thermal: pending

Harmonisation, quality manifests, figures and measured interpretations are still being prepared. This interim report does not establish request-rate trends, latency relationships, thermal correlations or temperature limits. Their conclusions must wait for completed source-specific checks.

## Scheduling hypotheses and unanswered questions

Inference: Alibaba class differences justify testing separate HP/Spot duration classes and gang-aware admission. They do not prove any policy improves throughput, waiting time or SLO compliance. Source-specific requested hardware is insufficient to estimate actual use without allocation semantics.

Inference: Pricing can support transparent scenario cost accounting after hardware and billing compatibility checks. Price alone does not establish the best placement. No workload performance benchmark links these plans to Alibaba jobs.

No combined energy-saving or thermal-aware policy claim is supported yet. Training and policy optimisation remain out of scope.

## Reproducibility and next integration

Executed Alibaba script: `scripts/phase1/alibaba.py`. Local outputs: `harmonized/alibaba/jobs.parquet`, `nodes.parquet`, `arrival_hourly.parquet`; five `analysis/figures/alibaba_*` PNG/PDF pairs; `analysis/phase1/alibaba-summary.json`, `alibaba-quality.json`, `alibaba-dictionary.csv`, `alibaba-report.md` and `alibaba-figures.json`.

Pricing findings and field meanings are recorded locally in `analysis/phase1/pricing-report.md`, `pricing-quality.json` and `pricing-dictionary.md`. These paths describe pending supporting artefacts, not files included in this report-only commit.

Alibaba's downloaded README requests citation but provides no explicit licence grant. Its redistribution terms have not been established from those local documents. Do not silently assign a permissive licence. GPUCloudCompare requires CC-BY-4.0 attribution. BurstGPT and thermal licence details will be recorded with their completed manifests.

Next: validate all four source outputs, integrate source dictionaries and graphs, replace this interim status with a final measured report, then commit and push the supporting artefacts. Preserve all original datasets.
