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

