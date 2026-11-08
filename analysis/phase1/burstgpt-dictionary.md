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
