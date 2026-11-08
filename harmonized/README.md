# Harmonised analytical tables

The four sources remain separate. Source record identifiers are local to each
source. No job, request, GPU index or timestamp links records across sources.

Alibaba and BurstGPT times are relative seconds with source-specific origins.
Thermal timestamps are local recording times with an unknown timezone; elapsed
seconds link observations only within a session. Pricing dates are published
snapshot/index dates. No common calendar timeline is invented.

GPU family labels support broad descriptive comparisons only. Different GPU
variants, memory capacities and interconnects are not assumed interchangeable.
Hardware labels do not establish a job's performance on another GPU.

Source-specific data dictionaries and quality reports are in `analysis/phase1/`.
The combined dictionary is `analysis/data-dictionary.md`. Retained raw fields
and provenance permit inspection of the original values. Original downloads in
`data/` remain unchanged. Kestrel is excluded from all Phase 1 outputs.

Regenerate from the project root:

```powershell
python -m pip install --target .deps -r requirements-phase1.lock.txt
python scripts/phase1/run.py
```

The scripts read existing local downloads. They do not train a model or build a
scheduling simulator. Outputs use Parquet with Zstandard compression.
