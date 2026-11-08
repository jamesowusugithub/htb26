# Thermal dataset: harmonisation and findings

Verified: the original 95 CSV paths contain 2,424,786 timestamp-bearing sensor records. Exact file SHA256 deduplication leaves 72 sessions with 1,843,254 observations. These expand to 11,923,254 discrete-GPU telemetry rows: 5,760,000 H100,5,760,000 B200 and 403,254 RTX 3060 readings. Raw-wide Parquet also retains repeated headers and sensor-label footer records. No observed sensor rows are discarded for missing times.

The recordings are from September–October 2025. The dataset release is 2026. Node sessions span about 899.98 seconds with 20 ms median intervals. Workstation clocks have unknown timezones. Three workstation sessions contain only partial clock strings; their 30,258 sensor readings remain available, but absolute timestamp and elapsed seconds are null. No hours or timing offsets are invented.

## Measured distributions

| GPU model | Workload | n GPU readings | Temperature median / P95 (°C) | Power median / P95 (W) | Utilisation median / P95 (%) |
|---|---|---:|---:|---:|---:|
| NVIDIA B200 | Image Generation Diffusion Models | 2,520,000 | 37.0 / 55.0 | 240.4 / 746.3 | 96.0 / 100.0 |
| NVIDIA B200 | Text Generation LLMs | 3,240,000 | 50.0 / 69.0 | 640.1 / 921.0 | 99.0 / 100.0 |
| NVIDIA GeForce RTX 3060 | Feature Forecasting | 90,818 | 60.2 / 65.3 | 78.1 / 116.9 | 42.0 / 82.0 |
| NVIDIA GeForce RTX 3060 | Image Captioning | 70,621 | 49.4 / 56.7 | 46.4 / 83.8 | 19.0 / 91.0 |
| NVIDIA GeForce RTX 3060 | Image Classifications | 90,907 | 52.9 / 61.9 | 60.3 / 78.1 | 34.0 / 100.0 |
| NVIDIA GeForce RTX 3060 | Reinforcment Learning | 80,361 | 35.7 / 53.3 | 4.8 / 118.2 | 0.0 / 74.0 |
| NVIDIA GeForce RTX 3060 | Text Generation | 70,547 | 45.4 / 59.8 | 23.4 / 41.1 | 0.0 / 70.0 |
| NVIDIA H100 | Image Generation Diffusion Models | 2,520,000 | 40.0 / 59.0 | 132.3 / 573.3 | 98.0 / 100.0 |
| NVIDIA H100 | Text Generation LLMs | 3,240,000 | 53.0 / 63.0 | 528.2 / 684.5 | 100.0 / 100.0 |

Explicit workstation indicators: thermal limit active in 0 of 403,254 readings; power limit active in 2,400. Node recordings have no explicit thermal-limit indicator, so node throttling cannot be established from temperature alone. All node CPU temperature and CPU power fields are missing. Workstation CPU measurements remain in raw wide but are deliberately outside the selected GPU telemetry fields.

## Interpretation for scheduling

The temperature–utilisation and temperature–power density plots show the joint distributions of the recorded sensors. Temperature has persistence over a run; it is not an instantaneous measure of demand. The time plots show one-second medians and the observed range across all GPUs and readings for one representative run per model. Hardware and workload groups differ, and pooled averages can hide training phases.

Inference: workload-specific power envelopes and time-series thermal state could inform admission decisions under a power budget. The evidence supports descriptive profiling and future validation, not a claim that a scheduling policy improves outcomes. It does not establish energy per token, cooling demand, completion time under a cap, safe consolidation limits, thermal causality or effects on service deadlines. Throughput, progress, ambient conditions, cooling settings, concurrent jobs and controlled power interventions are absent.

## Quality, provenance and limits

The deduplication manifest preserves all 95 source paths and identifies 23 byte-identical baseline copies. Deduplicate before splitting experiments for any later analysis. Source row order, source CSV logical record number, archive member and full SHA256 remain available. Raw-wide positional fields preserve duplicated HWiNFO headers; no merged column values overwrite the originals. Missing values remain null, distinct from zero. Selected memory values retain the original MB-labelled units because decimal/binary conventions are not established; no byte conversion is made. GPU core-load and memory-activity sensors are not automatically equivalent across monitoring tools.

Figures use all discrete GPU indices, not only GPU0. They count recorded readings, not independent experiments. The 20 ms node cadence and approximately 100 ms workstation cadence produce different sample weights; driver sensor refresh can be slower than polling. Shared hardware model identifiers are descriptive and do not create a physical record-level relationship to the other datasets.

Licence conflict remains unresolved: Figshare API metadata identifies CC BY 4.0; the archive LICENSE and README identify CC BY-NC-ND 4.0. Clarify with the authors before redistributing source or adapted datasets or using them commercially.

Reproduce with `python scripts/phase1/thermal.py`. Dependencies are the root-local pandas, NumPy, PyArrow and Matplotlib packages. The script verifies all 72 session keys, every Parquet row count, all eight node GPU indices, the single workstation GPU index and node CPU null fields. Detailed missing counts and per-run/GPU percentiles are in `thermal-quality.json`; model/workload P50/P90/P95/P99 are in `thermal-summary.json`. No models or simulators are created.
