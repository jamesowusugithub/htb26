"""Essential new-output checks plus hashes proving harmonised data are intact."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import hashlib
import json
from datetime import datetime, timezone
import pyarrow.parquet as pq
from PIL import Image


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):
            h.update(block)
    return h.hexdigest()


def main():
    old=json.loads((ROOT/'analysis/phase1/validation.json').read_text(encoding='utf-8'))
    expected={r['path']:r for r in old['tables']}
    actual={p.relative_to(ROOT).as_posix() for p in (ROOT/'harmonized').rglob('*.parquet')}
    assert actual==set(expected),'Harmonised file set changed'
    for path, record in expected.items():
        assert digest(ROOT/path)==record['sha256'],f'Harmonised source changed: {path}'
    print(f'Unchanged: {len(expected)} harmonised Parquet files',flush=True)
    records=[]
    for p in sorted((ROOT/'integrated').rglob('*.parquet')):
        file=pq.ParquetFile(p)
        rows=sum(b.num_rows for b in file.iter_batches(batch_size=32768))
        assert rows==file.metadata.num_rows,p
        records.append(dict(path=p.relative_to(ROOT).as_posix(),rows=rows,
                            schema=str(file.schema_arrow),bytes=p.stat().st_size,sha256=digest(p)))
    paths={r['path']:r['rows'] for r in records}
    workload_rows=sum(n for path,n in paths.items() if path.startswith('integrated/workloads/'))
    assert workload_rows==466867+10632194,(workload_rows,'Workload count mismatch')
    required=['integrated/workload_hourly.parquet','integrated/alibaba_daily_demand_capacity.parquet']
    required += ['integrated/hardware/'+name+'.parquet' for name in
                 ['gpu_models','pricing_links','thermal_links','alibaba_catalogue_capacity','thermal_load_profiles']]
    required += ['integrated/scenarios/rental_costs.parquet','integrated/scenarios/alibaba_cost_coverage.parquet']
    assert all(path in paths for path in required),'Missing required analytical table'
    figures=[]
    for p in sorted((ROOT/'analysis/integrated/figures').glob('*.png')):
        with Image.open(p) as img:
            img.verify()
        assert p.with_suffix('.pdf').is_file(),p
        figures.append(p.relative_to(ROOT).as_posix())
    for prefix in ['workloads_','hardware_','costs_']:
        assert sum(Path(p).name.startswith(prefix) for p in figures)>=2,('Missing required graphs',prefix)
    quality={}
    for source in ['workloads','hardware','costs']:
        p=ROOT/'analysis/integrated'/f'{source}-quality.json'
        quality[source]=dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p))
        json.loads(p.read_text(encoding='utf-8'))
    result=dict(validated_at=datetime.now(timezone.utc).isoformat(),
        checks='Full new Parquet decode; source row conservation; required tables; PNG integrity and paired PDF existence; original harmonised SHA-256 equality. Source-specific checks cover field meanings and calculations. PDF rendering not independently verified.',
        unchanged_harmonized_files=len(expected),workload_rows=workload_rows,tables=records,figures=figures,source_quality=quality)
    (ROOT/'analysis/integrated/validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(records)} new Parquet files, {workload_rows:,} workload records, {len(figures)} graph pairs')


if __name__=='__main__':
    main()
