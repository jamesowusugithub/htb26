# GPU scheduling: initial assessment

Inspected local downloads on 8 November 2026. The retained analysis covers four of the five downloaded sources.
Kestrel is excluded at the user's request because of data-quality concerns.
Measured file statistics are separate from proposed experiments. No scheduling
policy has been evaluated yet.

## Alibaba spot GPU traces

Verified: 466,867 jobs, 4,278 nodes, six GPU types and 10,412 listed GPUs.
There are 415,713 high-priority jobs and 51,154 spot jobs. Median job duration is
1,216 seconds, while the 95th percentile is 461,465 seconds. The submission range
spans about 184 days. No job identifiers repeat, and no fields are empty.

This is the best starting point for a simulator of priority scheduling,
backfilling and placement. Backfilling means running smaller jobs while a larger
job waits, subject to reservation rules. Compare first-come-first-served,
backfilling and priority with spot pre-emption. Measure queue delay, completion
time, allocated GPU-hours, unused capacity and fairness between organisations.

Limits: the trace has no observed start times, deadlines, interruption events or
checkpoint costs. Confirm whether resource requests apply per worker before
calculating job demand. Fractional GPU requests need a sharing model. Actual GPU
utilisation is not recorded. Known final durations must not become scheduler
inputs except in an explicitly labelled oracle baseline.

## Cloud pricing

Verified: current JSON and CSV contain the same 131 provider/plan keys, across
eight providers. Only 46 plans have hourly USD prices. History includes 181 daily
records and 2,997 records in 23 GPU-model series, with unequal date coverage.
Sixteen current plans have no GPU model; ten use the generic label `GPU`.

Use this source to estimate deployment cost under different scheduling scenarios.
Normalise model names, GPU count, currency and billing unit first. Prices describe
whole plans and do not establish hardware speed or capacity availability. The
history contains aggregate price statistics, not a complete per-plan price trace.
Provider coverage also changes. Do not interpret all price changes as changes in
the same hardware offering. [Source methodology](https://gpucloudcompare.com/data/).

## Temperature and power

Verified: 95 CSV paths reduce to 72 unique runs after content deduplication.
There are 1,843,254 measurement rows after excluding footer labels: 32 node runs
and 40 single-machine runs. The node runs each contain 45,000 samples over about
15 minutes. They include H100 and B200 experiments; single-machine runs include
RTX 3060. All 32 node runs have empty CPU power and temperature fields.

Use these measurements to build workload-specific GPU power profiles and test
whether staggering job starts can reduce aggregate peak power. Treat concurrent
power superposition as an assumption. The recordings do not prove that a power
cap improves completion time, or provide enough throughput information to rank
energy per token. They do not capture every production workload.

Licence conflict: Figshare metadata says CC BY 4.0, while the archive licence says
CC BY-NC-ND 4.0. Resolve this discrepancy before redistribution or commercial use.

## BurstGPT inference requests

Verified: the three full traces contain 10,632,194 requests. Files 1 and 2
have no elapsed-time or session fields; file 3 has both. File 3 contains
5,344,021 requests, of which 387,963 have zero response tokens (7.26%). Its
median elapsed time is zero seconds, indicating limited timing resolution.
All six CSVs were scanned (20,776,759 rows including alternative views).
Each failure-free file exactly matches its full file with zero-response rows
removed, using ordered canonical SHA-256 comparisons. There are 487,629
zero-response requests across the three full traces (4.5863%). All six files
have sorted timestamps and valid token sums. In file 3, 59.43% of elapsed-time
values are zero. Its timestamps begin around relative day 225, so preserve the
gap after file 2 rather than treating the periods as consecutive.

Use arrival bursts and token lengths to test dynamic batching, queue admission
and scaling policies. Measure throughput and tail completion latency in a
calibrated serving system or simulator. Do not use the recorded end-to-end
latency as pure GPU service time. Time to first token is unavailable. Failure-free
files are alternative views of the full traces and must not be added as new
traffic. [Release documentation](https://github.com/HPMLL/BurstGPT/releases/tag/v2.0).

## Recommended experiment

Start with a trace-driven Alibaba scheduling simulator. Compare first-come-first-served,
backfilling and priority with spot pre-emption, with explicit runtime and
checkpoint assumptions. Add pricing as a cost sensitivity analysis. Use the
power traces for a separate power-constrained extension, and BurstGPT for a
separate inference scheduling experiment.

These sources describe different systems, periods and workload types. They have
no shared job identifiers. Combining their distributions is scenario modelling,
not observation of one cluster. Report assumptions and sensitivity ranges.
