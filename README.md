# GPU scheduling data exploration

Phase 1 harmonises four independent data sources and explores their scheduling
relevance. It does not train models or build a simulator. Kestrel is excluded.

- [Exploration report and graphs](analysis/data-exploration-report.md)
- [Data dictionary and relationships](analysis/data-dictionary.md)
- [Output validation catalogue](analysis/phase1/validation.json)
- [Harmonised table guide](harmonized/README.md)

## Reproduce

The original downloads are in `data/`. Large datasets and Parquet outputs use
Git LFS. To clone with the data, install Git LFS before cloning, or run
`git lfs pull` in an existing clone.

Python 3.13 was used for the recorded run. From the repository root:

```powershell
python -m pip install --target .deps -r requirements-phase1.lock.txt
python scripts/phase1/run.py
```

The pipeline reads the existing downloads and writes `harmonized/`,
`analysis/figures/` and source-specific quality reports in `analysis/phase1/`.
Each dataset can also be rebuilt separately with its script in `scripts/phase1/`.

## Interpretation

Raw values and source identifiers are retained. Missing values stay missing.
Relative timestamps do not become invented calendar dates. The sources have no
shared job, request or physical-device key. A common hardware vocabulary supports
descriptive comparisons, not claims of performance or physical equivalence.

Source licences and attribution remain separate. Alibaba licence coverage is
unresolved in the downloaded documents. The thermal archive and Figshare metadata
state conflicting licence terms. See the report before reuse or redistribution.
