---
language:
- en
datacard_version: 0.1.0
name: Datacard for NLR HPC Kestrel Jobs Data
tags:
- project:genesis
- science:hpc
- keywords: [HPC, computing, job-trace, jobs, supercomputer, computational-science, high-performance-computing, processed-data, slurm, Kestrel]
- risk:general
license: other
license_name: nlr-data-1.0
license_link: LICENSE.md

---

# Datacard for NLR HPC Kestrel Jobs Data

## Dataset Description

This dataset contains anonymized job-level records from the Kestrel high-performance computing (HPC) system. Each record represents a Slurm batch job and includes scheduling metadata, resource requests, resource utilization, energy consumption estimates, and computed efficiency metrics. Personally identifiable fields (user, account, job name, submit line, working directory, submit script, and job type) have been replaced with cryptographic hashes.

### Developed by

National Laboratory of the Rockies (NLR), [ROR: https://ror.org/036266993](https://ror.org/036266993)

### Contributed by

HPC Operations and Data Analytics teams at NLR.

### Dataset short description

Anonymized Slurm job records from the NLR Kestrel HPC system, including job scheduling, resource allocation, energy estimates, and efficiency metrics.

### Over what timeframe was the data collected or generated? Does this timeframe align with when the underlying phenomena or events occurred?

The sample data covers jobs submitted between **2023-08 and 2025-12**, with timestamps in the Mountain Time zone (UTC-7). The data reflects real-time job scheduling events as they occurred on the Kestrel system, so the collection timeframe aligns directly with the underlying phenomena.

### What resources were used?

#### Facilities:

- **Kestrel HPC System**, National Laboratory of the Rockies (NLR), [ROR: https://ror.org/036266993](https://ror.org/036266993)

#### Funding:

U.S. Department of Energy, Office of Energy Efficiency and Renewable Energy (EERE).

#### Other Supporting Entities:

N/A

## Sharing/Access Information

### Reuse restrictions placed on the data:

The dataset has been anonymized by hashing sensitive fields (user, account, job name, submit line, working directory, submit script, and job type). Reuse is subject to the license specified in this datacard. Users should not attempt to re-identify individuals from hashed fields.

### Provide DOIs, and bibtex citations to publications that cite or use the data.

N/A

### Provide DOIs, citations, or links to other publicly accessible locations of the data.

N/A

### Provide DOIs, citations, or links and descriptions of relationships to ancillary data sets.

This dataset is derived from the Kestrel schema of the NLR HPC job database.

### Recommended citation for this dataset (in bibtex format):

```txt
@misc{NLR_Kestrel_Anonymized_Jobs_2026,
  title        = "{Anonymized HPC Job Records from the NLR Kestrel System}",
  author       = "{National Laboratory of the Rockies}",
  howpublished = "[Data set]",
  year         = 2026,
  note         = "Anonymized extract of Slurm job records from the Kestrel HPC system"
}
```

## Data & File Overview

### List all files contained in the dataset.

| File | Description |
|------|-------------|
| `esif.hpc.kestrel.job-anon.zip` | Zipped Hive-partitioned Apache Parquet dataset containing anonymized job records from the Kestrel Slurm scheduler. Each row is a parent job record with scheduling metadata, resource requests/usage, energy estimates, and computed efficiency metrics. |
| `datacard.md` | This datacard file describing the dataset. |

### Describe the relationship(s) between files.

The ZIP file is the primary data file. The datacard provides documentation. In the source database, each job record may have associated job_step records (not included here) that contain finer-grained resource usage data per step.

### Describe any additional related data collected that was not included in the current data package.

The source database contains additional tables not included in this extract including job_step (per-step resource usage including TRESUsage fields). Raw Slurm `slurm_data` JSONB fields have also been excluded.

### Are there multiple versions of this dataset?

N/A

## Methodological Information

### How was the data for each instance obtained or generated?

Each instance is a parent job record collected from the Slurm workload manager on the Kestrel HPC system via the `sacct` command. The data represents real job submissions, scheduling decisions, and resource consumption. Calculated fields (efficiency metrics, energy estimates, shared job information) are derived from the raw Slurm data through database functions and triggers.

### For each instrument, facility, or source used to generate and collect the data, what mechanisms or procedures were used?

Data is collected by periodically running the Slurm `sacct` command with the timestamp format `SLURM_TIME_FORMAT="%Y-%m-%dT%H:%M:%S%z"` to ensure correct timezone offsets. The output is loaded into a PostgreSQL database via the `load_slurm` function. Calculated columns are updated by database triggers (`set_job_calc`) and batch functions (`upd_calc_cols`, `upd_sharednodes`).

### To create the final dataset, was any preprocessing/cleaning/labeling of raw data done?

Yes. The following preprocessing was applied:

1. **Anonymization**: The fields `name`, `user`, `account`, `submit_line`, `work_dir`, `submit_script`, and `job_type` were replaced with truncated cryptographic hashes (7-character hex strings) to prevent re-identification.
2. **Column derivation**: Several columns are calculated from raw Slurm fields, including `queue_wait` (start_time − submit_time), `cpu_eff` (TotalCPU / CPUTime), `max_mem_eff`, `min_mem_eff`, `avg_mem_eff`, and energy estimates.
3. **State simplification**: A `state_simple` column maps detailed Slurm states (e.g., "CANCELLED by 132357") to simplified labels (e.g., "CANCELLED").
4. **Boolean tagging**: `python_job` and `reframe_job` boolean flags were derived (methodology not specified in schema; both are `false` in this sample).
5. **Temporal decomposition**: `year`, `month`, `day`, `day_of_week`, `hour`, and `minute` columns were extracted from `submit_time`.

### Is the software that was used to preprocess/clean/label the data available?

The data is loaded and processed using PostgreSQL functions. These are internal to the NLR HPC operations database and are not publicly released at this time.

### Describe any standards and calibration information, if appropriate.

Timestamps are exported from Slurm with timezone offsets (Mountain Time, UTC-6 or UTC-7 depending on daylight saving). The `timestamptz` PostgreSQL datatype is used to store correct offsets. Energy consumption values (`consumed_energy_joules`, `consumed_energy_raw_joules`) are reported by Slurm from node-level power monitoring. TDP-estimated energy values are calculated from hardware specifications rather than direct measurement.

### Describe the environmental and experimental conditions relevant to the dataset.

The Kestrel system is located at the NLR campus. Standard compute nodes have 104 cores and 256 GB of memory; bigmem nodes have 2000 GB of memory. GPU nodes (partition `gpu-h100`) are equipped with NVIDIA H100 GPUs. Jobs in this sample span the `short`, `standard`, `debug`, and `gpu-h100` partitions.

### Describe any quality-assurance procedures performed on the data.

The data have been cleaned and validated through the standard data processes used to support Kestrel operations. While these preprocessing and quality-control steps are integral to the dataset, the underlying software and pipelines are not publicly available

## Data-Specific Information

### What data does each instance within the dataset consist of?

Each instance (row) represents a single parent Slurm job on the Kestrel system. The data includes raw Slurm scheduling fields (timestamps, resource requests, resource usage, state), anonymized identifiers, and derived/calculated efficiency and energy metrics.

### Number of variables:

50

### Number of cases/rows:

Approximately 11,000,000

### Variable descriptions:

| Variable Name | Description | Unit | Value Labels | Slurm sacct Field |
|---|---|---|---|---|
| id | Unique primary key (full job ID string) | N/A | | JobID |
| job_id | Numeric job ID in Slurm | N/A | | JobIDRaw |
| array_pos | Array index if job array, else null | N/A | | ArrayTaskID |
| array_range | Slurm array notation for array jobs | N/A | | ArrayTaskString |
| name_hash | Anonymized hash of the job name | N/A | 7-char hex | JobName |
| user_hash | Anonymized hash of the submitting user | N/A | 7-char hex | User |
| account_hash | Anonymized hash of the allocation account | N/A | 7-char hex | Account |
| submit_line_hash | Anonymized hash of the submit command line | N/A | 7-char hex | SubmitLine |
| work_dir_hash | Anonymized hash of the working directory | N/A | 7-char hex | WorkDir |
| submit_script_hash | Anonymized hash of the submit script | N/A | 7-char hex (null if not captured) | *(not a standard sacct field)* |
| job_type_hash | Anonymized hash of the job type | N/A | 7-char hex (null if not captured) | *(not a standard sacct field)* |
| python_job | Whether the job is a Python job | N/A | true / false | *(derived)* |
| reframe_job | Whether the job is a ReFrame job | N/A | true / false | *(derived)* |
| partition | HPC queue/partition requested | N/A | e.g., short, standard, debug, gpu-h100 | Partition |
| state | Full Slurm job state string | N/A | e.g., COMPLETED, FAILED, PENDING, RUNNING, CANCELLED by {uid} | State |
| state_simple | Simplified job state | N/A | COMPLETED, FAILED, PENDING, RUNNING, CANCELLED | *(derived from State)* |
| submit_time | Timestamp when the job was submitted | timestamptz | | Submit |
| start_time | Timestamp when the job started (null if PENDING) | timestamptz | | Start |
| end_time | Timestamp when the job ended (null if PENDING/RUNNING) | timestamptz | | End |
| nodes_req | Number of nodes requested | count | | ReqNodes |
| processors_req | Number of CPUs requested | count | | ReqCPUS |
| memory_req | Memory requested | string (e.g., "2366M", "85G") | | ReqMem |
| wallclock_req | Maximum wall time requested | HH:MM:SS or interval | | Timelimit |
| nodes_used | Number of nodes utilized | count | | NNodes |
| processors_used | Number of CPUs utilized | count | | NCPUS |
| wallclock_used | Wall time actually used | HH:MM:SS | | Elapsed |
| cpu_used | CPU time utilized | HH:MM:SS | | TotalCPU |
| nodelist | Array of node names used (empty if PENDING) | N/A | Slurm node names | NodeList |
| cpu_energy_tdp_estimated_max_watt_hours | Estimated max CPU energy based on TDP | Wh | | *(derived from TotalCPU)* |
| cpu_energy_tdp_estimated_used_watt_hours | Estimated CPU energy used based on TDP | Wh | | *(derived from TotalCPU, CPUTime)* |
| consumed_energy_joules | Energy consumed (formatted string) | Joules | May contain "K" suffix for thousands | ConsumedEnergy |
| consumed_energy_raw_joules | Raw energy consumed | Joules | | ConsumedEnergyRaw |
| consumed_energy_raw_watt_hours | Raw energy consumed in watt-hours | Wh | | *(derived from ConsumedEnergyRaw)* |
| qos | Quality of Service of the job | N/A | e.g., normal, high | QOS |
| queue_wait | Time the job waited in queue | HH:MM:SS | start_time − submit_time | *(derived from Start − Submit)* |
| cpu_eff | CPU efficiency (TotalCPU / CPUTime) | ratio (0–1) | | *(derived from TotalCPU / CPUTime)* |
| max_mem_eff | Max memory efficiency across job steps | ratio (0–1) | | *(derived from MaxRSS / ReqMem)* |
| min_mem_eff | Min memory efficiency across job steps | ratio (0–1) | | *(derived from MaxRSS / ReqMem)* |
| avg_mem_eff | Avg memory efficiency across job steps | ratio (0–1) | | *(derived from MaxRSS / ReqMem)* |
| gpus_requested | Number of GPUs requested | count | | ReqTRES |
| gpu_nodes_occupied | Number of GPU nodes occupied | count | | *(derived)* |
| shared_job_count | Number of jobs sharing the same nodes concurrently | count | | *(derived)* |
| nodes_shared | Array of nodes shared with other jobs | N/A | | *(derived)* |
| jobs_shared | Array of job IDs sharing the same nodes | N/A | | *(derived)* |
| year | Year extracted from submit_time | N/A | | *(derived from Submit)* |
| month | Month extracted from submit_time | N/A | | *(derived from Submit)* |
| day | Day extracted from submit_time | N/A | | *(derived from Submit)* |
| day_of_week | Day of week extracted from submit_time | N/A | 0=Sunday through 6=Saturday | *(derived from Submit)* |
| hour | Hour extracted from submit_time | N/A | 0–23 | *(derived from Submit)* |
| minute | Minute extracted from submit_time | N/A | 0–59 | *(derived from Submit)* |

### Codes used for missing data:

| Code | Description |
|------|-------------|
| (empty/null) | Field not applicable for the job's current state (e.g., start_time is null for PENDING jobs, end_time is null for PENDING and RUNNING jobs) |
| 0 | Zero values in numeric fields (e.g., processors_used = 0 for PENDING jobs, energy = 0 for jobs that have not run) |

### Specialized formats or other abbreviations used:

- **File format**: Zipped Hive-partitioned Apache Parquet dataset (`esif.hpc.kestrel.job-anon.zip`). Can be read with tools such as Apache Spark, PyArrow, pandas, DuckDB, or any Parquet-compatible reader.
- **Timestamps**: ISO 8601 format with timezone offset, e.g., `2026-02-19 16:17:31-07`.
- **Intervals**: Displayed as `HH:MM:SS` or `D days` format.
- **Node names**: Slurm HPE Cray EX naming convention, e.g., `x1004c3s0b1n1`.
- **Nodelist**: PostgreSQL array format, e.g., `{x1004c3s0b1n1}` or `{}` for empty.
- **Memory request**: String with unit suffix, e.g., `2366M` (megabytes), `85G` (gigabytes), `246064M`.
- **Energy strings**: `consumed_energy_joules` may use "K" suffix for thousands (e.g., `34.45K` = 34,450 J).
- **Hash fields**: 7-character hexadecimal strings representing anonymized values.

### Sample of the dataset:

The dataset contains approximately 11 million job records spanning multiple years across states PENDING, RUNNING, COMPLETED, FAILED, and CANCELLED across partitions including short, standard, debug, and gpu-h100.

## More information (optional)

**Note on timestamps**: The Kestrel data collection exports Slurm timestamps with timezone offsets using `SLURM_TIME_FORMAT="%Y-%m-%dT%H:%M:%S%z"`. This ensures correct handling of daylight saving transitions. Adding intervals to timestamps across DST boundaries requires offset adjustment (see schema documentation for details).

**Note on shared jobs**: The `shared_job_count` field reflects whether other jobs were physically co-resident on the same nodes, not whether the job used the `shared` partition. A job may use the shared partition but have no co-resident jobs.
