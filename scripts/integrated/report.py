"""Assemble the integrated analytical dictionary and source-based report."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'analysis/integrated'
FIGURES={
    'workloads_arrivals':'Source-scoped batch and inference arrivals, with separate clocks and workload types.',
    'workloads_demand_capacity':'Calculated offered-work proxies versus a stated static catalogue-capacity scenario.',
    'workloads_time_quantities':'Job duration and request completion latency, shown as different measured quantities.',
    'hardware_link_coverage':'Hardware links and gaps across workload, cloud-price and thermal sources.',
    'hardware_thermal_load_profiles':'Measured temperature and power distributions under different recorded GPU loads.',
    'costs_rental_scenarios':'Calculated whole-plan rental costs for explicit GPU-count and rental-hour scenarios.',
    'costs_demand_sensitivity':'Calculated rental cost as required GPU count changes within exact cloud model labels.',
}


def main():
    validation=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    dictionary='''# Unified analytical layer: dictionary and relationships

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

'''
    for source in ('workloads','hardware','costs'):
        dictionary+='\n'+(OUT/f'{source}-dictionary.md').read_text(encoding='utf-8')+'\n'
    (OUT/'data-dictionary.md').write_text(dictionary,encoding='utf-8')
    report=f'''# Unified GPU analytical layer

All four sources are available through a common workload view, explicit model-level bridges
and separately labelled scenario tables. The original harmonised tables are intact.
No model, scheduler, scheduling simulator or frontend was built.

## Delivered structure

- `integrated/workloads/`: {validation['workload_rows']:,} observed events with a common schema,
  including 466,867 Alibaba jobs and 10,632,194 BurstGPT requests. Workload type, source time
  origin, original fields and missing information remain explicit.
- `integrated/workload_hourly.parquet`: source-scoped arrival and demand summaries.
- `integrated/hardware/`: hardware vocabulary, pricing and thermal links, static catalogue
  capacity and observed thermal-load profiles.
- `integrated/scenarios/`: explicit rental assumptions, calculated costs and missing job-price coverage.

There are {len(validation['tables'])} new readable Parquet files and {len(validation['figures'])}
PNG/PDF graph pairs. Hash comparisons confirm that all {validation['unchanged_harmonized_files']}
original harmonised Parquet files are unchanged. Source checks reconcile workload rows, linked
records and rental arithmetic. PNG integrity and PDF existence were checked; PDFs were not
independently rendered.

## How the sources relate

```mermaid
flowchart LR
  A[Alibaba jobs] --> W[Common workload interface]
  B[BurstGPT requests] --> W
  A --> H[Source GPU hardware labels]
  H --> C[Static node catalogue capacity]
  H --> P[Explicit cloud-price bridge]
  T[Thermal GPU models and sessions] --> P
  T --> M[Measured load and temperature profiles]
  P --> S[Separate assumed rental scenarios]
```

Arrows show analytical relationships, not evidence that records describe the same machine.
BurstGPT has no GPU identity and therefore no observed hardware-price or thermal join.
The pricing bridge retains unavailable and family-only matches. H100 and B200 thermal labels
have descriptive price links; Alibaba A100-SXM4-80GB has generic A100 candidates only.

## Observed, calculated and assumed

Observed events, sensor measurements and source catalogue prices retain source references.
Counts, conditional percentiles and request-duration proxies are calculations from those
observations. Static node capacity is not time-varying available capacity. Request-work
versus catalogue-capacity comparisons do not measure concurrency, idle GPUs or utilisation.

Rental scenarios specify GPU count and elapsed rental hours. Cost uses whole-plan rounding
and listed USD/hour prices. They do not estimate actual Alibaba or BurstGPT costs, transfer
runtime across hardware, or convert end-to-end request latency into GPU service time.

## Source-specific findings and assumptions

'''
    for source in ('workloads','hardware','costs'):
        body=(OUT/f'{source}-report.md').read_text(encoding='utf-8')
        report+='\n'+'\n'.join('#'+line if line.startswith('#') else line for line in body.splitlines())+'\n'
    report+='\n## Integrated graphs\n\nEach graph labels its sources, units, counts and assumptions.\n\n'
    for path in sorted((OUT/'figures').glob('*.png')):
        caption=FIGURES.get(path.stem,path.stem.replace('_',' ').capitalize())
        report+=f'### {caption}\n\n![{caption}](figures/{path.name})\n\n[PDF](figures/{path.stem}.pdf)\n\n'
    report+='''## What can be examined now

Compare batch and inference arrival patterns within their own observed periods. Inspect
priority differences, recorded requests and offered-work proxies against a stated static
capacity assumption. Compare whole-plan rental costs for explicit resource requirements.
Inspect measured thermal and power distributions within hardware/workload/load groups.

These comparisons do not establish better scheduling policies, future prediction accuracy,
cross-hardware execution performance, actual cloud placement feasibility or thermal causality.
No unrelated job is assigned an experimental temperature or cloud bill.

## Dictionary, validation and reproduction

- [Dictionary and precise relationships](data-dictionary.md)
- [Validation results and table schemas](validation.json)
- [Analytical-layer guide](../../integrated/README.md)

Run `python scripts/integrated/run.py` from the repository root with the pinned Phase 1
dependencies. It reads existing local harmonised tables and writes only the new layer and
its analysis artefacts. Source licences remain separate: preserve BurstGPT and pricing
attribution; Alibaba licence coverage and the thermal archive/metadata licence conflict
remain unresolved as documented in Phase 1. The private repository does not resolve them.
'''
    (OUT/'report.md').write_text(report,encoding='utf-8')
    print('Wrote integrated report and data dictionary')


if __name__=='__main__':
    main()
