# Unified analytical layer

This layer reads the four harmonised sources without changing them. Its tables
share a documented analytical interface, not a shared physical cluster or clock.

## Evidence classes

| Class | Meaning |
| --- | --- |
| Observed | A recorded job, request, catalogue offer or sensor reading |
| Calculated from observations | A count, percentile, aggregate or request-work proxy |
| Assumption | A stated scenario requirement, rental duration or capacity interpretation |
| Calculated scenario | Arithmetic under those assumptions, not an observed outcome |

There are no scheduling simulations or trained models in this layer.

## Relationships

Alibaba jobs and BurstGPT requests share a common workload schema. Source-local
time origins, workload types and missing fields remain explicit. Their original
fields are preserved; references point back to the unchanged harmonised records.
Job duration and request completion latency remain different quantities.

Hardware bridges distinguish model-label matches, broader family candidates and
unavailable links. A family candidate does not establish variant, memory,
interconnect or performance compatibility. BurstGPT has no recorded GPU model.

Thermal links operate at the recorded GPU model level. No thermal reading is
assigned to an Alibaba job, BurstGPT request or cloud machine. Cloud prices
retain the offer's provider, region, currency, billing unit and GPU count.

## Reproduce

From the repository root, using the existing local datasets:

```powershell
python -m pip install --target .deps -r requirements-phase1.lock.txt
python scripts/integrated/run.py
```

The integrated report and dictionary are under `analysis/integrated/`. Graphs
are in `analysis/integrated/figures/`, with PNG and PDF versions. Quality results
include output row counts and confirmation that the harmonised files are intact.
