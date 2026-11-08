# Static cloud-cost scenario dictionary

`integrated/scenarios/rental_costs.parquet` contains one row per hourly offer × requested GPU count × rental duration.
`scenario_id` is a unique calculated-case key, not a job ID. `source_plan_record_id` joins to
`harmonized/pricing/plans.parquet`; add `source_price_field = price_hourly_usd` to join offers.
Source prices and GPU counts are observed snapshot values. Required GPU count and rental hours are explicit
scenario assumptions. Plans required, reserved capacity, spare capacity and USD rental cost are calculated.
`evidence_class` is always `calculated_static_scenario`. `observed_workload_id`, measured energy and workload
completion time remain null. This table never claims that an Alibaba job or BurstGPT request ran on an offer.

`integrated/scenarios/alibaba_cost_coverage.parquet` has one row per Alibaba hardware identifier. It records
job counts, recorded-request × duration proxies and exact identifier price coverage. Actual job cost stays
null. Family-only GPU matches are not silently treated as compatible. Zero offer count means unpriced, not free.
The request-duration proxy is not actual allocated GPU-hours and worker scope remains unresolved.

Units: hours, GPU counts, USD per listed plan-hour, calculated USD per scenario. No monthly price conversion,
exchange rate, measured service time or GPU throughput is invented. `assumptions.json` records the formula
and unmodelled constraints. Raw inputs remain in the unchanged harmonised pricing/Alibaba tables.
