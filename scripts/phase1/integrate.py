"""Build the source catalogue and conservative shared hardware vocabulary."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import csv
import json
import re
import pandas as pd
import pyarrow.parquet as pq


def gpu_family(identifier):
    if pd.isna(identifier) or not identifier:
        return None
    found=re.search(r'(?:^|_)(a10|a100|a800|h100nvl|h100|h800|h200|b200|b300|l40s|l4|a2|mi300x)(?:_|$)',identifier)
    return found.group(1).upper() if found else None


def main():
    destination=ROOT/'harmonized/catalogue'
    destination.mkdir(parents=True,exist_ok=True)
    aliases=[]
    nodes=pd.read_parquet(ROOT/'harmonized/alibaba/nodes.parquet')
    for _,row in nodes[['gpu_model_source','gpu_model_identifier']].drop_duplicates().iterrows():
        aliases.append(dict(source_id='alibaba',source_label_field='gpu_model_source',source_label=row.gpu_model_source,
            gpu_model_identifier=row.gpu_model_identifier,identity_status='source_anonymised' if 'series' in row.gpu_model_identifier else 'source_named'))
    plans=pd.read_parquet(ROOT/'harmonized/pricing/plans.parquet')
    for _,row in plans[['gpu_model_raw','gpu_model_identifier']].drop_duplicates().iterrows():
        aliases.append(dict(source_id='gpucloudcompare',source_label_field='gpu_model_raw',source_label=row.gpu_model_raw,
            gpu_model_identifier=row.gpu_model_identifier,identity_status='unknown' if pd.isna(row.gpu_model_identifier) else 'source_named'))
    sessions=pd.read_parquet(ROOT/'harmonized/thermal/sessions.parquet')
    for _,row in sessions[['gpu_model','gpu_model_identifier']].drop_duplicates().iterrows():
        aliases.append(dict(source_id='thermal',source_label_field='gpu_model',source_label=row.gpu_model,
            gpu_model_identifier=row.gpu_model_identifier,identity_status='experiment_metadata'))
    hardware=pd.DataFrame(aliases)
    hardware['gpu_family']=hardware.gpu_model_identifier.map(gpu_family)
    hardware['relationship_scope']='Descriptive model vocabulary only; no physical-device or performance equivalence'
    hardware.to_parquet(destination/'hardware_aliases.parquet',index=False,compression='zstd')
    tables=[]
    for p in sorted((ROOT/'harmonized').rglob('*.parquet')):
        if 'catalogue' in p.parts:
            continue
        pf=pq.ParquetFile(p)
        tables.append(dict(path=p.relative_to(ROOT).as_posix(),source_group=p.relative_to(ROOT/'harmonized').parts[0],
            rows=pf.metadata.num_rows,columns=len(pf.schema_arrow),schema=str(pf.schema_arrow)))
    pd.DataFrame(tables).to_parquet(destination/'table_catalogue.parquet',index=False,compression='zstd')
    dictionary='''# Phase 1 data dictionary and relationships

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

'''
    alibaba=ROOT/'analysis/phase1/alibaba-dictionary.csv'
    with alibaba.open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f)
        dictionary+='### Alibaba\n\n'
        dictionary+='| '+' | '.join(reader.fieldnames)+' |\n'
        dictionary+='| '+' | '.join('---' for _ in reader.fieldnames)+' |\n'
        for row in reader:
            dictionary+='| '+' | '.join(str(row[c]).replace('|','\\|').replace('\n',' ') for c in reader.fieldnames)+' |\n'
    for source in ('burstgpt','pricing','thermal'):
        path=ROOT/'analysis/phase1'/f'{source}-dictionary.md'
        dictionary+='\n\n'+path.read_text(encoding='utf-8')
    (ROOT/'analysis/data-dictionary.md').write_text(dictionary,encoding='utf-8')
    print(f'Integrated {len(tables)} source Parquet files and {len(hardware)} hardware aliases')


if __name__=='__main__':
    main()
