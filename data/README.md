# Source datasets

Original downloads collected on 8 November 2026. Each dataset has its own folder.
Archives are kept in their original compressed form.

| Folder | Source | Contents |
| --- | --- | --- |
| `alibaba-2026-spot-gpu` | [Alibaba](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu) | Job and node CSV files, original README, download manifest |
| `gpucloudcompare` | [GPU Cloud Price Index](https://gpucloudcompare.com/data/) | Current JSON and CSV snapshots, daily history JSON, download manifest |
| `gpu-temperature-power-2026` | [Figshare](https://doi.org/10.6084/m9.figshare.31654879) | Original dataset ZIP, source metadata and verification |
| `burstgpt` | [BurstGPT](https://github.com/HPMLL/BurstGPT) | Release CSV files, documentation, licence and metadata |
| `kestrel-h100` | [NLR Kestrel](https://data.nlr.gov/submissions/302) | Original Parquet dataset ZIP, datacard, licence and metadata |

The Kestrel download contains the full jobs dataset, including CPU partitions and
the `gpu-h100` partition. It is not filtered to GPU jobs.

Source: GPU Cloud Price Index — [gpucloudcompare.com](https://gpucloudcompare.com/data/)
(CC-BY 4.0). Retain the original source licences and attribution when reusing data.

`../fetch_public_data.py` refreshes the Alibaba and GPUCloudCompare downloads.
Per-source metadata records download URLs and verification details where available.
