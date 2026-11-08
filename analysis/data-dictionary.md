# Phase 1 data dictionary and relationships

## Common analytical contract

Tables remain separate by source. A source-row key is unique only within its documented source/file/trace.
Raw source values and provenance are retained alongside normalised fields. Missing information remains
null. Zero is retained only where the source records zero. No imputation or machine-learning scaling is used.

| Quantity | Analytical unit and interpretation |
| --- | --- |
| Arrival time | Relative seconds within Alibaba/BurstGPT origins; no invented calendar date |
| Thermal time | Local timestamp with unknown timezone; elapsed seconds within a run when parseable |
| Pricing time | Source snapshot/index date; daily prices cannot be aligned to unrelated jobs |
| Duration / latency | Seconds; observed end-to-end latency is not pure GPU execution time |
| GPU counts | Recorded requests or sensor indices, with scope explicitly documented |
| Temperature / power | Degrees Celsius / watts, preserving sensor definitions |
| Utilisation | Source sensor percent, not inferred from GPU requests |
| Memory | Source-labelled units retained where MB versus MiB cannot be established |
| Price | Original currency per stated billing unit and plan; per-GPU division only when count is known |

## Compatible field roles

| Source | Normalised field | Analytical role |
| --- | --- | --- |
| Alibaba | submit_relative_s | Job arrival in source-relative seconds |
| Alibaba | duration_s | Source-reported job duration in seconds |
| BurstGPT | relative_timestamp_s | Request arrival in original source-relative seconds |
| BurstGPT | elapsed_time_s | Observed end-to-end completion latency in seconds |
| Thermal | elapsed_seconds | Time since this session's first observation, when parseable |
| Thermal | temperature_c / utilisation_percent / power_w | Celsius / source utilisation percent / watts |
| Pricing | captured_date / date | Typed daily source dates, not job timestamps |
| Alibaba, thermal, pricing | gpu_model_identifier | Conservative shared hardware-label vocabulary |

These fields share documented units and roles, not a fabricated common clock. BurstGPT's GPU
model is unknown and stays null; its LLM model name is a different concept.

## Permitted relationships

Alibaba jobs and nodes share a hardware label, but no job-to-node placement key exists. BurstGPT filtered
variants map to canonical traces by source trace/row comparisons and are not additional requests. Thermal
GPU telemetry joins to sessions on `session_id` and raw rows on `(session_id, source_record_number)`.
Pricing offers join to current plans on `plan_record_id`; history is an independent aggregated index.

`harmonized/catalogue/hardware_aliases.parquet` maps original labels to conservative identifiers.
Alibaba and pricing tables use `gpu_model_identifier`; thermal sessions and telemetry do too.
Unknown/generic models remain null. Anonymised Alibaba GPU series retain source-specific identifiers.
GPU families support broad descriptive comparison only. For example, generic H100 and explicitly named
H100 memory/interconnect variants retain different identifiers. Compatibility requires extra evidence.
No shared identifier represents the same physical GPU, workload or data centre across sources.

`table_catalogue.parquet` lists all source Parquet files, schemas and metadata row counts.
`analysis/phase1/validation.json` separately records full-decode checks and file hashes.

## Source field dictionaries

### Alibaba

| table | field | dtype | unit | definition |
| --- | --- | --- | --- | --- |
| jobs | raw__job_name | str | source literal | Unchanged CSV field job_name stored as text, including empty text; see source README for source unit. |
| jobs | raw__organization | str | source literal | Unchanged CSV field organization stored as text, including empty text; see source README for source unit. |
| jobs | raw__gpu_model | str | source literal | Unchanged CSV field gpu_model stored as text, including empty text; see source README for source unit. |
| jobs | raw__cpu_request | str | source literal | Unchanged CSV field cpu_request stored as text, including empty text; see source README for source unit. |
| jobs | raw__gpu_request | str | source literal | Unchanged CSV field gpu_request stored as text, including empty text; see source README for source unit. |
| jobs | raw__worker_num | str | source literal | Unchanged CSV field worker_num stored as text, including empty text; see source README for source unit. |
| jobs | raw__submit_time | str | source literal | Unchanged CSV field submit_time stored as text, including empty text; see source README for source unit. |
| jobs | raw__duration | str | source literal | Unchanged CSV field duration stored as text, including empty text; see source README for source unit. |
| jobs | raw__job_type | str | source literal | Unchanged CSV field job_type stored as text, including empty text; see source README for source unit. |
| jobs | source_dataset | str | identifier | Constant source dataset name. |
| jobs | source_file | str | path | Original CSV basename. |
| jobs | source_url | str | URL | Source dataset directory URL. |
| jobs | source_sha256 | str | SHA256 | Hash of original source CSV bytes. |
| jobs | source_row_number | int64 | 1-based row index | CSV data record index, excluding header. |
| jobs | source_record_id | str | identifier | Dataset+filename+row index unique provenance key. |
| jobs | job_id | string | identifier | Exact source job_name string; not linked to other datasets. |
| jobs | organisation_id | string | identifier | Exact source organisation identifier. |
| jobs | gpu_model_identifier | string | identifier | Source-specific normalised label; NVIDIA prefix only for disclosed models; GPU-series labels stay Alibaba-specific. |
| jobs | gpu_model_source | string | label | Original hardware label. |
| jobs | gpu_model_identity_status | str | category | Anonymised unresolved versus source-model-specific. |
| jobs | priority_class | string | category | HP -> high_priority; Spot -> spot. |
| jobs | cpu_request_vcpus | float64 | vCPU | Numeric source CPU request; worker scope not resolved. |
| jobs | gpu_request_recorded_count | float64 | GPU request count | Numeric source GPU request, including fractions; worker scope unspecified. |
| jobs | worker_count | int64 | instances | Numeric source worker_num. |
| jobs | submit_relative_s | float64 | seconds | Seconds from first source job. No absolute calendar origin. |
| jobs | duration_s | float64 | seconds | Source job duration; missing censoring and lifecycle semantics cannot be reconstructed. |
| jobs | submit_time_basis | str | label | Explicit relative-time origin. |
| jobs | submitted_at_utc | datetime64[ns, UTC] | UTC timestamp | All null because source calendar origin is unknown. |
| jobs | gpu_request_scope | str | label | Explicit unresolved worker scope. |
| jobs | request_duration_proxy_gpu_h | float64 | GPU-request hours | gpu_request_recorded_count * duration_s / 3600; request-based proxy, not actual use. |
| jobs | worker_expanded_sensitivity_proxy_gpu_h | float64 | GPU-request hours | Recorded request * duration * worker_count / 3600; sensitivity interpretation only. |
| jobs | demand_proxy_status | str | label | Explicit request-proxy limitation. |
| nodes | raw__gpu_model | str | source literal | Unchanged CSV field gpu_model stored as text, including empty text; see source README for source unit. |
| nodes | raw__gpu_capacity_num | str | source literal | Unchanged CSV field gpu_capacity_num stored as text, including empty text; see source README for source unit. |
| nodes | raw__cpu_num | str | source literal | Unchanged CSV field cpu_num stored as text, including empty text; see source README for source unit. |
| nodes | raw__node_name | str | source literal | Unchanged CSV field node_name stored as text, including empty text; see source README for source unit. |
| nodes | source_dataset | str | identifier | Constant source dataset name. |
| nodes | source_file | str | path | Original CSV basename. |
| nodes | source_url | str | URL | Source dataset directory URL. |
| nodes | source_sha256 | str | SHA256 | Hash of original source CSV bytes. |
| nodes | source_row_number | int64 | 1-based row index | CSV data record index, excluding header. |
| nodes | source_record_id | str | identifier | Dataset+filename+row index unique provenance key. |
| nodes | node_id | string | identifier | Exact source node_name string. |
| nodes | gpu_model_identifier | string | identifier | Source-specific normalised label; NVIDIA prefix only for disclosed models; GPU-series labels stay Alibaba-specific. |
| nodes | gpu_model_source | string | label | Original hardware label. |
| nodes | gpu_capacity_count | int64 | GPUs | Numeric source gpu_capacity_num; node catalogue, not a time-varying availability trace. |
| nodes | cpu_capacity_vcpus | int64 | vCPU | Numeric source cpu_num. |
| nodes | gpu_model_identity_status | str | category | Anonymised unresolved versus source-model-specific. |
| arrival_hourly | relative_hour_bin | int64 | hour index | Floor(submit_relative_s / 3600), including empty bins. |
| arrival_hourly | HP | int64 | job arrivals | High-priority arrivals in bin. |
| arrival_hourly | Spot | int64 | job arrivals | Spot arrivals in bin. |
| arrival_hourly | total | int64 | job arrivals | All job arrivals in bin. |
| arrival_hourly | bin_start_relative_s | int64 | seconds | Relative start of bin. |
| arrival_hourly | bin_complete | bool | boolean | False for the final partially observed hour. |


# BurstGPT harmonised data dictionary

Canonical tables: `harmonized/burstgpt/burstgpt_1/`, `burstgpt_2/`, `burstgpt_3/`. Each contains bounded-size Parquet shards with one request per row. No request is discarded or imputed.

| Field | Type / unit | Meaning |
| --- | --- | --- |
| source_dataset | string | `burstgpt`. |
| source_file | string | Original full-trace CSV filename. |
| source_row_id | int64 | One-based data-row position, excluding header. Unique with source_file. |
| trace_id | string | File-local trace identifier. |
| relative_timestamp_s | float64, seconds | Original Timestamp parsed numerically. Relative source origin is unknown as a calendar date. |
| trace_local_timestamp_s | float64, seconds | Original timestamp minus the first request timestamp of that trace. Never used to join traces. |
| calendar_timestamp_utc | timestamp UTC, nullable | Always null because the release does not establish a reliable absolute origin. |
| input_tokens / output_tokens / total_tokens | int64, token count | Parsed original request / response / total tokens. Zero is preserved. |
| elapsed_time_s | float64, seconds, nullable | Submission to complete final response. Null for traces 1 and 2; not TTFT. Zero is retained for trace 3. |
| llm_model | string | Original model category, ChatGPT or GPT-4. Not a GPU model. |
| log_type | string | Original API log or Conversation log. |
| session_id | string, nullable | Original nonempty session ID, available only for conversation rows in trace 3. |
| gpu_model | string, nullable | Always null: physical GPU is unobserved. |
| zero_response_tokens | bool | Response token count equals zero. Publisher calls these failures; cause is unavailable. |
| raw_timestamp / raw_session_id / raw_elapsed_time / raw_model / raw_request_tokens / raw_response_tokens / raw_total_tokens / raw_log_type | string, nullable | Exact parsed CSV field strings before numeric conversion. Absent columns are null; present empty fields remain empty strings. |

Missing and absent fields remain null in normalised columns; raw fields distinguish absent columns from present empty values. Token totals are checked; no correction is applied. No GPU identifier, price, utilisation, power, deadline or TTFT is invented. No calendar, weekday or cross-source identity join is possible from these fields.

The success-only release files are derived views, not additional independent requests. All six files are read. Exact ordered canonical hashes verify each success-only file against its full trace with zero-response rows removed. Their counts and source filenames are in quality reports. Filter them from canonical Parquet with `zero_response_tokens == false`.

Exact identical raw tuples are counted within each trace with external merge sort. They are retained because identical timestamp/token/model records can still represent separate real requests. Source row IDs preserve distinct observations. Cross-trace duplicate identity is not established.

Licence: CC-BY-4.0. Preserve source attribution, `data/burstgpt/LICENSE`, `CITATION.cff` and the BurstGPT paper citation. Source: https://github.com/HPMLL/BurstGPT ; release: https://github.com/HPMLL/BurstGPT/releases/tag/v2.0 .


# Pricing data dictionary

`plans`: one row per current JSON plan. `plan_record_id` is a local key, not a cross-source job key.
`offers`: three rows per plan, one for each original price field, including missing prices.
`current_csv_raw`: all original CSV records as string-valued JSON, to preserve raw values independently.
`history`: one row per original daily/series record and possible price field; absent fields remain null.

`gpu_model_raw` preserves the source label. `gpu_model_id` is a conservative lower-case slug of that label;
unknown/generic labels are null. `gpu_family` is a broad family only, not evidence of compatibility.
`price_per_plan` has the stated `currency` and `billing_unit`. `price_per_gpu` divides only by a positive
stated GPU count. No currency conversion or month-to-hour conversion is applied. History prices are
per-plan statistics, with the original observation count. Dates use Parquet date32; no intraday time is invented.
`raw_record_json` preserves the entire source record. Source file, source series and 1-based row identify provenance.
`captured_date` records the source snapshot date, not the download time. `locations` preserves listed regions.
Provider/plan alone is not unique: Latitude repeats one plan across four regions with different prices.
No price identifies GPU performance, availability, interruption probability or negotiated rates.


# Thermal data dictionary

Source: Figshare DOI 10.6084/m9.figshare.31654879. All tables belong to these experiments only. They have no record-level join to Alibaba, BurstGPT or cloud price records.

## Tables and keys

- `sessions.parquet`: one row per SHA256-distinct CSV session. `session_id` is the first 16 hexadecimal characters of the full member SHA256. Full hashes are retained and uniqueness is validated. Workload and GPU model identify experiment metadata, not a globally identified physical GPU.
- `deduplication_manifest.parquet`: all 95 CSV archive paths. `duplicate_of` identifies the canonical archive member if a path contains identical file bytes. Files are deduplicated only on full SHA256 equality, never on matching time or measurement values.
- `raw_wide/<session_id>.parquet`: every nonempty CSV record after the initial header, including repeated headers and final sensor-label records. `record_type` distinguishes observations, repeated headers and sensor labels. All original data cells are retained as strings. Positional names `c0000` onward avoid merging identical header names. `source_schemas.json` maps each position to its exact decoded original header. CSV parsing removes quoting syntax, not the original cell value. The unchanged ZIP preserves byte-level originals. Blank CSV records are counted separately.
- `gpu_telemetry/<session_id>.parquet`: one row per valid timestamp and recorded GPU index. Join to a raw record using `(session_id, source_record_number)`. `gpu_index_within_run` ranges 0–7 for nodes, 0 for RTX 3060. It identifies a local sensor index; it does not assert physical continuity between runs.
- `source_manifest.json`: original archive name, SHA256, DOI, and every CSV path, size and member SHA256.

## Tidy telemetry fields

| Field | Meaning and unit |
|---|---|
| session_id | SHA256-derived experiment key |
| gpu_model_identifier | Shared descriptive model labels: nvidia_h100, nvidia_b200, nvidia_geforce_rtx_3060. These labels do not establish hardware compatibility or match physical devices across sources |
| gpu_model | NVIDIA H100, NVIDIA B200 or NVIDIA GeForce RTX 3060, from experiment paths and supplied hardware documentation |
| workload | Original task directory label; no cross-source task mapping is asserted |
| gpu_index_within_run | Zero-based source GPU sensor index |
| timestamp_local | Naive local timestamp parsed without timezone conversion |
| timezone | Literal `unknown`; no UTC or cross-source time alignment |
| elapsed_seconds | Seconds since the first observation in the same run |
| source_record_number | One-based CSV logical record number, including the initial header; not a physical text line number |
| archive_member, member_sha256 | Exact source archive path and full SHA256 provenance |
| temperature_c | GPU temperature in degrees Celsius; node `gpuN_temp_C`, workstation `GPU Temperature` sensor |
| hotspot_temperature_c | Workstation hot-spot Celsius sensor; absent for nodes |
| thermal_limit_c | Workstation reported Celsius thermal limit; absent for nodes |
| utilisation_percent | Node GPU utilisation or workstation GPU Core Load; their sensor implementations differ |
| power_w | Source GPU power in watts, preserved without scaling; does not include whole-server or cooling power |
| memory_used_source_mb | Node memory-used field or workstation allocated memory, retaining original MB-labelled numeric values |
| memory_total_source_mb | Node total-memory MB-labelled field; absent for workstation, not inferred from specifications |
| memory_utilisation_percent | Workstation memory-usage percentage only; absent for nodes |
| memory_controller_utilisation_percent | Source node `gpuN_mem_utilization` or workstation GPU Memory Controller Load. Node percentage semantics derive from pynvml monitoring documentation; not interchangeable with allocated-memory fraction |
| power_tdp_percent | Source node Power_TDP or workstation Total GPU Power percentage; copied, not recomputed |
| cpu_power_w, cpu_temperature_c | Node CPU fields; all observed node values missing. Workstation CPU fields remain available in raw wide and are not selected into these GPU telemetry fields |
| thermal_limit_active | Workstation explicit `Performance Limit - Thermal [Yes/No]` mapped to nullable boolean; null on nodes |
| power_limit_active | Workstation explicit `Performance Limit - Power [Yes/No]` mapped to nullable boolean; null on nodes |

No numeric MB-to-byte conversion is made: the raw headers do not establish a common decimal or binary base. No TDP-to-watt conversion is made. Null means missing, unavailable or deliberately unharmonised; it never means zero. CPU fields on workstation are not harmonised into the selected GPU table. Original fields remain in the raw-wide files.

Source headers use Windows-1252 degree characters. The original decoded Celsius headers are retained without correction. Single-machine source headers contain duplicated sensor names, so raw-wide consumers must use positional column names.

## Licence discrepancy

Figshare API metadata identifies CC BY 4.0. The archive LICENSE and README identify CC BY-NC-ND 4.0. Both statements are preserved. Resolve this discrepancy with the authors before redistribution or commercial use of source data or adapted datasets.


## Incomplete source clocks

Three RTX 3060 experiment files contain minute/second-only clock strings, for example `29.9.2025 52:26.7`. They cannot establish an hour or an absolute local timestamp. These original strings remain in raw wide and `timestamp_source_raw`; `timestamp_parse_status` identifies `incomplete_source_clock`. `timestamp_local` and `elapsed_seconds` are null for those records. No hour, rollover or sample-rate-based duration is invented. All their temperature, power and utilisation readings remain in distribution and paired-sensor plots. Their missing time coordinates exclude them from time plots.

`gpu_index_within_run` is a canonical zero-based analysis index, not the workstation's physical HWiNFO index. `source_gpu_sensor_label` preserves the original node prefix (`gpu0` to `gpu7`) or the workstation sensor-footer label (for example `GPU [#1]: NVIDIA GeForce RTX 3060`). The workstation's integrated-GPU fields remain in raw wide; they are not represented as RTX 3060 telemetry. The tidy table covers all eight source discrete GPUs on each node and the single source discrete GPU on the workstation.

