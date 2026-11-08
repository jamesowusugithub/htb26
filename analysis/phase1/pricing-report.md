# Pricing findings

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
