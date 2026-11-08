# Unified analytical layer: dictionary and relationships

## Scope and evidence

The original harmonised tables remain unchanged. The common workload interface preserves
observed source rows and original fields; aggregate statistics and proxies are calculated.
Assumed rental windows and GPU requirements are scenario inputs. Rental costs are calculated
static scenarios, not measured job costs or scheduling simulations.

No common calendar, physical-device identifier or job identity is invented across sources.
Alibaba job duration and BurstGPT end-to-end request latency are different fields and units
remain explicit. Missing GPU identity or service time cannot be filled from a thermal session.

## Relationship rules

| Relationship | Key and scope | Cardinality and restriction |
| --- | --- | --- |
| Common workload to original record | Source harmonised path, source row identifier and series | One original event per common row; clocks remain source-scoped |
| Alibaba job hardware to node catalogue | GPU model identifier | Many jobs and many nodes per model; no placement key |
| Hardware to cloud offer | Explicit pricing bridge and plan record ID | Zero or many offers; label-level matches and family candidates stay distinct |
| Cloud scenario to source offer | Plan record ID plus price field | Many calculated cases per offer; whole plans charged |
| Hardware to thermal session | Explicit model/session bridge | Zero or many sessions; never a workload-to-sensor physical join |
| Thermal profile | Model, experimental workload and recorded utilisation band | Calculated summaries of measured readings; not causal response curves |

`functional_compatibility_confirmed` stays false in the hardware bridge. Exact model-label
matches support descriptive model-level comparisons, not claims about equal memory,
interconnect, performance or whether a specific job fits. Family candidates are ineligible
for automatic pricing of actual jobs. BurstGPT has no recorded GPU identity.


# Common workload interface

`integrated/workloads/` contains 11,099,061 observed source records:466,867 Alibaba jobs and10,632,194 BurstGPT requests. Every Parquet file has one identical Arrow schema. The folder is an Arrow Dataset root; folder names are not Hive partitions.

`workload_id` is `source_series_id:source_row_id`, unique because source rows are unique within each original file/trace. `source_dataset`, `workload_type` (`batch_gpu_job` or `llm_inference_request`) and `source_series_id` preserve entity type. `source_harmonized_path`, `source_file`, `source_row_id` and optional `source_original_record_id` locate the untouched original harmonised record. Each Burst trace preserves its original row IDs across shards.

`arrival_relative_s` is original source-relative seconds, not a common physical clock. `time_origin_id` scopes the origin; `calendar_arrival_utc` stays null. The original Burst timestamps, including the unobserved gap before trace3, remain unchanged. Separate graphs subtract only the first displayed hourly-bin edge for display, not in the common table.

`job_duration_s` is available only for Alibaba. `request_end_to_end_latency_s` is available only when BurstGPT records it (trace3). Neither is called GPU service time. `gpu_model_identifier`, `gpu_request_recorded_count`, `worker_count`, `gpu_request_scope`, `priority_class`, `cpu_request_vcpus`, `organisation_id` retain Alibaba normalised values, with worker scope unresolved. They stay null for BurstGPT. `input_tokens`, `output_tokens`, `total_tokens`, `llm_model`, `log_type`, `conversation_session_id`, `zero_response_tokens` retain BurstGPT normalised values and stay null for Alibaba. A zero response-token flag is a source description, not a diagnosed failure cause.

`alibaba_original` and `burstgpt_original` are mutually exclusive nullable structs. Their fields preserve the exact original source string cells, including empty string versus null/absent fields from Phase1. They do not coerce GPU model names into LLM model names. The complete source-specific normalised fields remain reachable through `source_harmonized_path` and the source row key.

`integrated/workload_hourly.parquet` has one calculated aggregate per source series and original-relative hour. `arrival_count` counts source records. `gpu_request_recorded_count_sum` is a sum of recorded Alibaba request values, not occupied GPUs or GPU-hours. `input_tokens_sum` and `output_tokens_sum` count BurstGPT tokens. Missing/inapplicable quantities stay null; observed zero-count hours have zero aggregates. `partial_edge_bin` identifies hours extending beyond the first or last observed timestamp. The gap between source series is not filled with synthetic zero demand. No cross-source workload or device join exists.


## Alibaba demand/capacity scenario

`integrated/alibaba_daily_demand_capacity.parquet` retains one row per disclosed/anonymised hardware model and source-relative arrival day, including zero-arrival days. Static node/GPU counts are observed catalogue counts, not availability measurements. `catalogue_capacity_scenario_gpu_h_per_24h` assumes those GPUs are available continuously for24hours. Each request-duration proxy attributes its full source duration to its arrival day, not to execution time. The worker-expanded version is a separate sensitivity interpretation, never additive. Ratios compare offered proxy work with scenario capacity, not utilisation, concurrency, idle time or a feasible schedule. The final partial day is flagged and excluded from the figure.


# Hardware relationship dictionary

All outputs are under `integrated/hardware/`. Original harmonised tables remain unchanged.

| Table | Grain and keys | Meaning |
| --- | --- | --- |
| gpu_models | One `gpu_model_identifier` | Conservative vocabulary from source aliases; no verified physical identity or full hardware specification |
| pricing_links | Origin source/model × candidate `plan_record_id`; null target for unavailable | Join pricing plans/offers by plan_record_id. Exact model label permits labelled what-if cost scenarios only. Family candidates are insufficient for automatic pricing. Functional compatibility is not confirmed for any link. |
| thermal_links | Model × `session_id` | Join thermal sessions by session_id; independent experimental model profile, never a measured job/device join |
| alibaba_catalogue_capacity | GPU model | Sum of source node GPU capacity; static catalogue, not available capacity over time |
| thermal_load_profiles | Model × workload × utilisation band | Recorded readings, distinct run count, source run IDs and sensor quantiles; observed, not calculated scheduling outcomes |

`exact_model_label` means identical conservative identifiers. `family_candidate_only` means a shared named family with unresolved variant details. `unavailable` means no supported price candidate. Exact labels do not establish memory size, interconnect, performance or placement compatibility.
Thermal utilisation bands are [0,20), [20,40), [40,60), [60,80), [80,100]. Temperature is Celsius; power is watts. Quantiles weight recorded GPU readings equally; they do not claim independent samples or equal run/time weights. Missing measurements are excluded only from the relevant metric quantiles and counted separately. Zeros are retained.
Pricing currencies and billing units remain in original pricing tables. No EUR/USD or monthly/hourly conversion is introduced here. No thermal reading identifies a particular Alibaba job, BurstGPT request or cloud machine. Source licences remain unchanged, including the thermal archive/metadata licence conflict.


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

