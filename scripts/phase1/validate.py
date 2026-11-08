"""Validate required Phase 1 outputs, decode Parquet and reconcile manifests.

This integration check does not replace source-specific raw-value or semantic checks,
nor visual review. PDF files are required to exist; they are not rendered here.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import hashlib
import json
from datetime import datetime, timezone
import pyarrow.parquet as pq
from PIL import Image

REQUIRED_FIGURES={
    'alibaba':['alibaba_arrivals','alibaba_priority_counts','alibaba_duration_distribution',
               'alibaba_hardware_demand','alibaba_resource_requests'],
    'burstgpt':['burstgpt_request_rates','burstgpt_token_distributions','burstgpt_size_latency',
                'burstgpt_latency_distribution','burstgpt_size_latency_by_model','burstgpt_daily_profiles'],
    'pricing':['pricing_hourly_prices','pricing_history','pricing_coverage'],
    'thermal':['thermal_temperature_utilisation','thermal_temperature_power',
               'thermal_temperature_time','thermal_temperature_distribution'],
}


def require(condition,message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(name):
    path=ROOT/'analysis/phase1'/name
    require(path.is_file(),f'Missing source quality manifest: {path.relative_to(ROOT)}')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def expected_outputs():
    """Return source-declared file rows plus grouped roles for sharded traces."""
    expected={}
    groups=[]
    manifest_paths=[]
    for source in REQUIRED_FIGURES:
        require((ROOT/'harmonized'/source).is_dir(),f'Missing source output directory: {source}')
        for stem in REQUIRED_FIGURES[source]:
            for extension in ['png','pdf']:
                path=ROOT/'analysis/figures'/f'{stem}.{extension}'
                require(path.is_file() and path.stat().st_size>0,
                        f'Missing or empty required figure: {path.relative_to(ROOT)}')
    alibaba=load_manifest('alibaba-quality.json');manifest_paths.append('alibaba-quality.json')
    for role in ['jobs','nodes']:
        row_counts=alibaba['row_counts'][role]
        require(row_counts['original']==row_counts['harmonized']==row_counts['parquet_metadata'],
                f'Alibaba {role} source/harmonised row declaration mismatch')
        expected[f'harmonized/alibaba/{role}.parquet']=int(row_counts['harmonized'])
    alibaba_summary=load_manifest('alibaba-summary.json');manifest_paths.append('alibaba-summary.json')
    bins=alibaba_summary['arrival_bins']
    expected['harmonized/alibaba/arrival_hourly.parquet']=int(bins['full_bins']+bins['final_partial_bins'])

    pricing=load_manifest('pricing-quality.json');manifest_paths.append('pricing-quality.json')
    for role in ['plans','offers','current_csv_raw','history']:
        expected[f'harmonized/pricing/{role}.parquet']=int(pricing['harmonized_rows'][role])
    require(pricing['original_rows']['current_json_plans']==pricing['harmonized_rows']['plans'],
            'Pricing current JSON source/plan row declaration mismatch')
    require(pricing['original_rows']['current_csv_plans']==pricing['harmonized_rows']['current_csv_raw'],
            'Pricing CSV source/raw row declaration mismatch')
    require(pricing['harmonized_rows']['offers']==3*pricing['harmonized_rows']['plans'],
            'Pricing must retain three price-field slots per plan')
    require(pricing['harmonized_rows']['history']==3*(pricing['original_rows']['history_daily']+pricing['original_rows']['history_by_model']),
            'Pricing history row declaration does not preserve three price-field slots')

    burst=load_manifest('burstgpt-quality.json');manifest_paths.append('burstgpt-quality.json')
    declared_traces={q['trace_id']:q for q in burst['traces']}
    require(set(declared_traces)=={'burstgpt_1','burstgpt_2','burstgpt_3'},
            'BurstGPT requires all three canonical full traces')
    for trace_id,q in declared_traces.items():
        shards=sorted((ROOT/'harmonized/burstgpt'/trace_id).glob('part-*.parquet'))
        require(shards,f'Missing Parquet shards for {trace_id}')
        require(len(shards)==int(q['parquet_shards']),f'Shard count mismatch for {trace_id}')
        require(q['original_rows']==q['harmonised_rows'],f'Source/harmonised rows differ for {trace_id}')
        groups.append({'role':trace_id,'paths':[p.relative_to(ROOT).as_posix() for p in shards],
                       'expected_rows':int(q['harmonised_rows'])})
    require(sum(q['harmonised_rows'] for q in declared_traces.values())==burst['harmonised_rows']==burst['canonical_rows'],
            'BurstGPT canonical aggregate row declaration mismatch')

    thermal=load_manifest('thermal-quality.json');manifest_paths.append('thermal-quality.json')
    sessions=thermal['session_summary'];session_ids=[s['session_id'] for s in sessions]
    require(len(set(session_ids))==len(sessions)==thermal['unique_sessions'],
            'Thermal session identifiers are missing, repeated or inconsistent')
    require(bool(sessions),'No thermal sessions declared')
    for folder,field in [('raw_wide','raw_records_excluding_header_and_blank_lines'),('gpu_telemetry','telemetry_rows')]:
        actual={p.stem for p in (ROOT/'harmonized/thermal'/folder).glob('*.parquet')}
        require(actual==set(session_ids),f'Thermal {folder} session file set differs from manifest')
        for session in sessions:
            expected[f'harmonized/thermal/{folder}/{session["session_id"]}.parquet']=int(session[field])
    expected['harmonized/thermal/sessions.parquet']=int(thermal['unique_sessions'])
    expected['harmonized/thermal/deduplication_manifest.parquet']=int(thermal['csv_paths'])
    require(sum(s['telemetry_rows'] for s in sessions)==thermal['gpu_telemetry_rows'],
            'Thermal telemetry aggregate row declaration mismatch')
    require(sum(s['raw_records_excluding_header_and_blank_lines'] for s in sessions)==thermal['raw_wide_rows'],
            'Thermal raw-wide aggregate row declaration mismatch')
    require(sum(s['observation_rows'] for s in sessions)==thermal['observation_rows'],
            'Thermal observation aggregate row declaration mismatch')
    for relative in expected:
        require((ROOT/relative).is_file(),f'Missing required Parquet role: {relative}')
    manifests=[{'path':'analysis/phase1/'+name,'sha256':sha256(ROOT/'analysis/phase1'/name)} for name in manifest_paths]
    return expected,groups,manifests,alibaba


def main():
    expected,groups,manifests,alibaba=expected_outputs()
    records=[]
    for path in sorted((ROOT/'harmonized').rglob('*.parquet')):
        relative=path.relative_to(ROOT).as_posix()
        pf=pq.ParquetFile(path)
        decoded=sum(batch.num_rows for batch in pf.iter_batches(batch_size=16384))
        require(decoded==pf.metadata.num_rows,f'Parquet decoded/metadata row mismatch: {relative}')
        if relative in expected:
            require(decoded==expected[relative],f'Source quality manifest row mismatch: {relative}: {decoded} != {expected[relative]}')
        record=dict(path=relative,rows=decoded,columns=len(pf.schema_arrow),schema=str(pf.schema_arrow),
                    bytes=path.stat().st_size,sha256=sha256(path))
        if relative in expected:
            record['expected_rows_from_source_quality_manifest']=expected[relative]
        records.append(record)
        print(f'Decoded {relative}: {decoded:,} rows',flush=True)
    require(records,'No Parquet outputs')
    row_lookup={r['path']:r['rows'] for r in records}
    for group in groups:
        group['decoded_rows']=sum(row_lookup[path] for path in group['paths'])
        require(group['decoded_rows']==group['expected_rows'],f'Grouped shard row mismatch: {group["role"]}')
    # Alibaba also records output hashes after its source-preserving round trip.
    hashes={r['path']:r['sha256'] for r in records}
    for role in ['jobs','nodes']:
        relative=f'harmonized/alibaba/{role}.parquet'
        require(hashes[relative]==alibaba['raw_preservation'][role]['output_sha256'],
                f'Alibaba output changed since its source-preservation check: {role}')
    figures=[]
    required={name for names in REQUIRED_FIGURES.values() for name in names}
    for path in sorted((ROOT/'analysis/figures').glob('*.png')):
        with Image.open(path) as picture:
            picture.verify()
        with Image.open(path) as picture:
            size=picture.size
        require(min(size)>=500,f'Figure too small: {path.relative_to(ROOT)}')
        pdf=path.with_suffix('.pdf')
        require(pdf.is_file() and pdf.stat().st_size>0,f'Missing or empty paired PDF: {pdf.relative_to(ROOT)}')
        figures.append(dict(path=path.relative_to(ROOT).as_posix(),width=size[0],height=size[1],
                            required=path.stem in required,png_sha256=sha256(path),pdf_sha256=sha256(pdf),
                            pdf_check='nonempty file exists; not rendered or parsed'))
    result=dict(validated_at=datetime.now(timezone.utc).isoformat(),
                method='Required source tables, trace/session partitions and named figures checked. Full Parquet decode, metadata and source quality manifest row reconciliation, and SHA-256 of outputs. PNG integrity/dimensions and nonempty paired PDF existence.',
                limitations=['Source quality manifests are declarations from source-specific scripts; this integration step does not independently rederive every source value or validate every unit.',
                             'Semantic correctness, plot captions and interpretation require source-specific checks and visual review.',
                             'PDF files are hashed and required to exist; their rendering and internal structure are not checked here.'],
                required_figures=REQUIRED_FIGURES,quality_manifests=manifests,grouped_row_checks=groups,
                tables=records,figures=figures)
    destination=ROOT/'analysis/phase1/validation.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(records)} Parquet files; {len(figures)} PNG/PDF figure pairs; all {len(required)} named figures present')


if __name__=='__main__':
    main()
