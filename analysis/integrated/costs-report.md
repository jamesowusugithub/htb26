# Calculated cloud-rental scenarios

Observed inputs: 131 current plan records, 393 billing/currency slots; 18 identified hourly USD offers
have positive stated GPU counts. The source snapshot date is 7 November 2026. All source plan IDs and the
offers Parquet SHA256 are retained.

Calculated outcomes: 180 static cases cover requested counts 1, 2, 4, 8 and 16 GPUs and rental windows
1 and 24 hours. Cost = ceil(required GPU count / GPUs per plan) × listed hourly plan price × hours.
The whole plan is charged even when capacity is unused. These are arithmetic rental cases, not simulated
or observed scheduling outcomes. They do not imply equal workload performance across hardware.

For the 8-GPU/24-hour scenario, listed-offer rental estimates range from USD 145.92
to USD 3,072.00. This mixes GPU models and is not a cost-effectiveness ranking.
The demand sensitivity graph separates H100, L40S and MI300X exact source model labels.

Alibaba has 6 hardware labels covering 466,867 jobs, with no exact identifier match to the
eligible hourly offers. Generic A100 prices cannot establish compatibility with A100-SXM4-80GB jobs.
Actual Alibaba cloud job costs remain null. BurstGPT has no recorded GPU model or GPU service time;
its end-to-end elapsed time is not used as GPU rental time. No cost per request/token is invented.

Limitations: linear hourly billing is assumed because minimum billing periods/rounding are not supplied.
CPU/RAM/disk feasibility, region availability, interconnect, taxes, egress, setup time, discounts and workload
performance are unmodelled. No monthly-to-hourly or currency conversion is performed. Runtime under
another hardware configuration would require separate evidence.

Source/attribution: GPU Cloud Price Index, https://gpucloudcompare.com/data/, CC-BY-4.0. Alibaba source
licence coverage remains unresolved as documented in Phase 1. Existing harmonised tables remain unchanged.
Reproduce: `python scripts/integrated/costs.py`.
