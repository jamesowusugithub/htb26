# Common workload interface

`integrated/workloads/` contains 11,099,061 observed source records:466,867 Alibaba jobs and10,632,194 BurstGPT requests. Every Parquet file has one identical Arrow schema. The folder is an Arrow Dataset root; folder names are not Hive partitions.

`workload_id` is `source_series_id:source_row_id`, unique because source rows are unique within each original file/trace. `source_dataset`, `workload_type` (`batch_gpu_job` or `llm_inference_request`) and `source_series_id` preserve entity type. `source_harmonized_path`, `source_file`, `source_row_id` and optional `source_original_record_id` locate the untouched original harmonised record. Each Burst trace preserves its original row IDs across shards.

`arrival_relative_s` is original source-relative seconds, not a common physical clock. `time_origin_id` scopes the origin; `calendar_arrival_utc` stays null. The original Burst timestamps, including the unobserved gap before trace3, remain unchanged. Separate graphs subtract only the first displayed hourly-bin edge for display, not in the common table.

`job_duration_s` is available only for Alibaba. `request_end_to_end_latency_s` is available only when BurstGPT records it (trace3). Neither is called GPU service time. `gpu_model_identifier`, `gpu_request_recorded_count`, `worker_count`, `gpu_request_scope`, `priority_class`, `cpu_request_vcpus`, `organisation_id` retain Alibaba normalised values, with worker scope unresolved. They stay null for BurstGPT. `input_tokens`, `output_tokens`, `total_tokens`, `llm_model`, `log_type`, `conversation_session_id`, `zero_response_tokens` retain BurstGPT normalised values and stay null for Alibaba. A zero response-token flag is a source description, not a diagnosed failure cause.

`alibaba_original` and `burstgpt_original` are mutually exclusive nullable structs. Their fields preserve the exact original source string cells, including empty string versus null/absent fields from Phase1. They do not coerce GPU model names into LLM model names. The complete source-specific normalised fields remain reachable through `source_harmonized_path` and the source row key.

`integrated/workload_hourly.parquet` has one calculated aggregate per source series and original-relative hour. `arrival_count` counts source records. `gpu_request_recorded_count_sum` is a sum of recorded Alibaba request values, not occupied GPUs or GPU-hours. `input_tokens_sum` and `output_tokens_sum` count BurstGPT tokens. Missing/inapplicable quantities stay null; observed zero-count hours have zero aggregates. `partial_edge_bin` identifies hours extending beyond the first or last observed timestamp. The gap between source series is not filled with synthetic zero demand. No cross-source workload or device join exists.


## Alibaba demand/capacity scenario

`integrated/alibaba_daily_demand_capacity.parquet` retains one row per disclosed/anonymised hardware model and source-relative arrival day, including zero-arrival days. Static node/GPU counts are observed catalogue counts, not availability measurements. `catalogue_capacity_scenario_gpu_h_per_24h` assumes those GPUs are available continuously for24hours. Each request-duration proxy attributes its full source duration to its arrival day, not to execution time. The worker-expanded version is a separate sensitivity interpretation, never additive. Ratios compare offered proxy work with scenario capacity, not utilisation, concurrency, idle time or a feasible schedule. The final partial day is flagged and excluded from the figure.
