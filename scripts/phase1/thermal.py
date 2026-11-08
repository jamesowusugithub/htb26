"""Harmonise the Figshare ZIP without changing source data. No model training."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.deps'))
import csv, io, json, zipfile, hashlib, collections
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

OUT = ROOT / 'harmonized/thermal'
REPORT = ROOT / 'analysis/phase1'
FIG = ROOT / 'analysis/figures'
SOURCE = ROOT / 'data/gpu-temperature-power-2026'
MODELS = ['NVIDIA GeForce RTX 3060', 'NVIDIA H100', 'NVIDIA B200']
MODEL_IDS = {'NVIDIA GeForce RTX 3060':'nvidia_geforce_rtx_3060', 'NVIDIA H100':'nvidia_h100', 'NVIDIA B200':'nvidia_b200'}

def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')

def savefig(fig, name, caption):
    fig.text(.015, .012, caption, fontsize=8, va='bottom', wrap=True)
    fig.tight_layout(rect=(0, .12, 1, .95))
    for ext in ('png', 'pdf'):
        fig.savefig(FIG / f'thermal_{name}.{ext}', dpi=300, bbox_inches='tight')
    plt.close(fig)

def main():
    for d in [OUT / 'raw_wide', OUT / 'gpu_telemetry', REPORT, FIG]:
        d.mkdir(parents=True, exist_ok=True)
    archive = next(SOURCE.glob('*.zip'))
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    seen, manifest, sessions, quality, schemas = {}, [], [], [], {}
    total_raw = total_obs = total_gpu = total_blank = 0
    hist_util = {m: np.zeros((100, 100), dtype=np.int64) for m in MODELS}
    hist_power = {m: np.zeros((100, 110), dtype=np.int64) for m in MODELS}
    hist_temp = {m: np.zeros(200, dtype=np.int64) for m in MODELS}
    pair_counts = {m: {'util': 0, 'power': 0, 'temp': 0} for m in MODELS}
    representatives = {}
    metric_names = ['temperature_c', 'hotspot_temperature_c', 'thermal_limit_c', 'utilisation_percent',
                    'power_w', 'memory_used_source_mb', 'memory_total_source_mb', 'memory_utilisation_percent',
                    'memory_controller_utilisation_percent', 'power_tdp_percent']
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith('.csv'):
                continue
            raw = z.read(info)
            sha = hashlib.sha256(raw).hexdigest()
            sid = sha[:16]
            item = {'archive_member': info.filename, 'member_sha256': sha, 'bytes': len(raw),
                    'session_id': sid, 'duplicate_of': seen.get(sha)}
            manifest.append(item)
            if sha in seen:
                continue
            seen[sha] = info.filename
            # Source CSVs are byte-preserved in the original ZIP. cp1252 is reversible here.
            records = list(csv.reader(io.StringIO(raw.decode('cp1252'), newline='')))
            header = records[0]
            schema_id = hashlib.sha256(json.dumps(header).encode()).hexdigest()[:16]
            schemas[schema_id] = {'encoding': 'cp1252', 'columns': [
                {'position_zero_based': i, 'raw_field': f'c{i:04d}', 'source_header': c}
                for i, c in enumerate(header)]}
            rows, rownums, types, blank = [], [], [], 0
            for pos, row in enumerate(records[1:], start=2):
                if not row:
                    blank += 1
                    continue
                if len(row) != len(header):
                    raise ValueError(f'Column count mismatch: {info.filename} record {pos}')
                rows.append(row); rownums.append(pos)
                types.append('observation' if row[0] and row[0] not in ('Date', 'timestamp') else 'sensor_labels' if not row[0] else 'repeated_header')
            wide = pd.DataFrame(rows, columns=[f'c{i:04d}' for i in range(len(header))], dtype='string')
            wide.insert(0, 'record_type', types)
            wide.insert(0, 'source_record_number', np.array(rownums, dtype=np.int32))
            wide.insert(0, 'member_sha256', sha)
            wide.insert(0, 'archive_member', info.filename)
            wide.insert(0, 'schema_id', schema_id)
            wide.insert(0, 'session_id', sid)
            raw_path=OUT / 'raw_wide' / f'{sid}.parquet'
            try:
                raw_cached=pq.ParquetFile(raw_path).metadata.num_rows==len(wide)
            except Exception:
                raw_cached=False
            if not raw_cached:
                wide.to_parquet(raw_path, index=False, compression='zstd')
            mask = np.array(types) == 'observation'
            obs = wide.loc[mask]
            source_rows = np.array(rownums, dtype=np.int32)[mask]
            node = '/Node_Dataset/' in info.filename
            model = 'NVIDIA B200' if '/B200/' in info.filename else 'NVIDIA H100' if '/H100/' in info.filename else 'NVIDIA GeForce RTX 3060'
            parts = info.filename.split('/')
            workload = parts[2]
            def source_col(name, starts=False):
                matches = [i for i,c in enumerate(header) if (c.startswith(name) if starts else c == name)]
                if not matches:
                    return pd.Series(np.nan, index=obs.index)
                if len(matches) != 1:
                    raise ValueError(f'Ambiguous selected sensor {name}: {matches}')
                return pd.to_numeric(obs[f'c{matches[0]:04d}'], errors='coerce')
            if node:
                local = pd.to_datetime(obs['c0000'], format='%Y-%m-%d %H:%M:%S.%f', errors='raise')
            else:
                local = pd.to_datetime(obs['c0000'] + ' ' + obs['c0001'], format='%d.%m.%Y %H:%M:%S.%f', errors='coerce')
            elapsed = (local - local.iloc[0]).dt.total_seconds().to_numpy()
            frames = []
            for gpu in range(8 if node else 1):
                data = {'session_id': sid, 'gpu_model': model, 'gpu_model_identifier':MODEL_IDS[model], 'workload': workload, 'gpu_index_within_run': gpu,
                        'timestamp_local': local.to_numpy(), 'timezone': 'unknown', 'elapsed_seconds': elapsed,
                        'timestamp_source_raw':obs['c0000'].to_numpy() if node else (obs['c0000']+' '+obs['c0001']).to_numpy(),
                        'timestamp_parse_status':np.where(local.notna(),'complete_local_timestamp','incomplete_source_clock'),
                        'source_record_number': source_rows, 'archive_member': info.filename, 'member_sha256': sha,
                        'source_gpu_sensor_label': f'gpu{gpu}' if node else next((row[next(i for i,c in enumerate(header) if c.startswith('GPU Temperature ['))] for row,kind in zip(rows,types) if kind=='sensor_labels'), None),
                        'cpu_power_w': source_col('cpu_power_W').to_numpy() if node else np.full(len(obs), np.nan),
                        'cpu_temperature_c': source_col('cpu_temp_C').to_numpy() if node else np.full(len(obs), np.nan)}
                if node:
                    mapping = {'temperature_c': f'gpu{gpu}_temp_C', 'utilisation_percent': f'gpu{gpu}_utilization_percent',
                               'power_w': f'gpu{gpu}_power_W', 'memory_used_source_mb': f'gpu{gpu}_mem_used_MB',
                               'memory_total_source_mb': f'gpu{gpu}_mem_total_MB', 'memory_controller_utilisation_percent': f'gpu{gpu}_mem_utilization',
                               'power_tdp_percent': f'gpu{gpu}_Power_TDP'}
                else:
                    mapping = {'temperature_c': 'GPU Temperature [', 'hotspot_temperature_c': 'GPU Hot Spot Temperature [',
                               'thermal_limit_c': 'GPU Thermal Limit [', 'utilisation_percent': 'GPU Core Load [%]',
                               'power_w': 'GPU Power [W]', 'memory_used_source_mb': 'GPU Memory Allocated [MB]',
                               'memory_utilisation_percent': 'GPU Memory Usage [%]',
                               'memory_controller_utilisation_percent': 'GPU Memory Controller Load [%]',
                               'power_tdp_percent': 'Total GPU Power [% of TDP] [%]'}
                for name in metric_names:
                    data[name] = source_col(mapping[name], starts=mapping[name].endswith('[')).to_numpy(dtype=float, na_value=np.nan) if name in mapping else np.full(len(obs), np.nan)
                for target, origin in [('thermal_limit_active', 'Performance Limit - Thermal [Yes/No]'), ('power_limit_active', 'Performance Limit - Power [Yes/No]')]:
                    if not node:
                        idx = header.index(origin)
                        values = obs[f'c{idx:04d}']
                        if not values.isin(['Yes', 'No']).all():
                            raise ValueError(f'Unexpected flag values in {origin}')
                        data[target] = values.map({'Yes': True, 'No': False}).to_numpy()
                    else:
                        data[target] = pd.array([pd.NA] * len(obs), dtype='boolean')
                frame = pd.DataFrame(data)
                frames.append(frame)
                metrics = {}
                for name in metric_names + ['cpu_power_w', 'cpu_temperature_c']:
                    a = frame[name].to_numpy(dtype=float, na_value=np.nan)
                    valid = a[np.isfinite(a)]
                    metrics[name] = {'missing': int(len(a)-len(valid)), 'n': len(valid)}
                    if len(valid):
                        metrics[name].update({'min': float(valid.min()), 'p50': float(np.quantile(valid,.5)),
                                              'p95': float(np.quantile(valid,.95)), 'p99': float(np.quantile(valid,.99)), 'max': float(valid.max())})
                temp = frame['temperature_c'].to_numpy()
                util = frame['utilisation_percent'].to_numpy()
                power = frame['power_w'].to_numpy()
                hist_util[model] += np.histogram2d(util, temp, bins=[np.linspace(0,100,101), np.linspace(0,100,101)])[0].astype(np.int64)
                hist_power[model] += np.histogram2d(power, temp, bins=[np.linspace(0,1100,111), np.linspace(0,100,101)])[0].astype(np.int64).T
                hist_temp[model] += np.histogram(temp[np.isfinite(temp)], bins=np.linspace(0,100,201))[0]
                pair_counts[model]['util'] += int(np.sum(np.isfinite(util)&np.isfinite(temp)))
                pair_counts[model]['power'] += int(np.sum(np.isfinite(power)&np.isfinite(temp)))
                pair_counts[model]['temp'] += int(np.sum(np.isfinite(temp)))
                quality.append({'session_id':sid, 'gpu_index_within_run':gpu, 'gpu_model':model, 'workload':workload,
                                'rows':len(frame), 'metrics': metrics,
                                'thermal_limit_active_count': int(frame['thermal_limit_active'].fillna(False).sum()) if not node else None,
                                'power_limit_active_count': int(frame['power_limit_active'].fillna(False).sum()) if not node else None})
            tidy = pd.concat(frames, ignore_index=True)
            # Force nullable flags to the same Arrow type on node and single-machine runs.
            for c in ['thermal_limit_active', 'power_limit_active']:
                tidy[c] = tidy[c].astype('boolean')
            tidy.to_parquet(OUT/'gpu_telemetry'/f'{sid}.parquet', index=False, compression='zstd')
            if model not in representatives:
                representatives[model] = tidy[['elapsed_seconds','temperature_c','gpu_index_within_run']].copy()
            sessions.append({'session_id':sid, 'schema_id':schema_id, 'archive_member': info.filename,
                             'member_sha256':sha, 'gpu_model': model, 'gpu_model_identifier':MODEL_IDS[model], 'gpu_count':len(frames), 'workload': workload,
                             'raw_records_excluding_header_and_blank_lines':len(wide), 'observation_rows':len(obs),
                             'non_observation_records':len(wide)-len(obs), 'blank_csv_records':blank,
                             'telemetry_rows':len(tidy), 'first_timestamp_local':str(local.iloc[0]),
                             'last_timestamp_local':str(local.iloc[-1]), 'elapsed_seconds':float(elapsed[-1]) if np.isfinite(elapsed[-1]) else None,
                             'timestamp_unparsed_rows':int(local.isna().sum()),
                             'median_interval_seconds':float(np.median(np.diff(elapsed))) if np.isfinite(elapsed).all() else None,
                             'repeated_observation_row_count':int(obs[[f'c{i:04d}' for i in range(len(header))]].duplicated().sum())})
            total_raw += len(wide); total_obs += len(obs); total_gpu += len(tidy); total_blank += blank
            print(f'{len(sessions):02d}/72 {model}: {len(obs):,} observations -> {len(tidy):,} GPU rows', flush=True)
            del records, rows, wide, obs, frames, tidy, raw
    session_lookup = {s['session_id']:s for s in sessions}
    for member in manifest:
        member['observation_rows'] = session_lookup[member['session_id']]['observation_rows']
        member['raw_records_excluding_header_and_blank_lines'] = session_lookup[member['session_id']]['raw_records_excluding_header_and_blank_lines']
    pd.DataFrame(manifest).to_parquet(OUT/'deduplication_manifest.parquet', index=False)
    pd.DataFrame(sessions).to_parquet(OUT/'sessions.parquet', index=False)
    write_json(OUT/'source_schemas.json', schemas)
    write_json(OUT/'source_manifest.json', {'source_doi':'10.6084/m9.figshare.31654879', 'archive_name':archive.name,
               'archive_sha256':archive_hash, 'csv_members':manifest})
    expected_gpu = sum(pq.ParquetFile(p).metadata.num_rows for p in (OUT/'gpu_telemetry').glob('*.parquet'))
    expected_raw = sum(pq.ParquetFile(p).metadata.num_rows for p in (OUT/'raw_wide').glob('*.parquet'))
    assert len(manifest)==95 and len(sessions)==72 and total_obs==1843254
    assert total_gpu==11923254 and expected_gpu==total_gpu and expected_raw==total_raw
    write_json(REPORT/'thermal-quality.json', {'source':'Figshare DOI 10.6084/m9.figshare.31654879',
               'archive_sha256':archive_hash, 'csv_paths':len(manifest), 'unique_sessions':len(sessions),
               'duplicate_csv_paths':len(manifest)-len(sessions),
               'original_observation_rows_across_all_95_paths':sum(m['observation_rows'] for m in manifest),
               'raw_wide_rows':total_raw,
               'observation_rows':total_obs, 'gpu_telemetry_rows':total_gpu, 'blank_csv_records_skipped':total_blank,
               'parquet_row_counts_verified':True, 'session_summary':sessions, 'gpu_summary':quality,
               'pair_counts':pair_counts, 'licence_conflict':'API CC BY 4.0; archive LICENSE and README CC BY-NC-ND 4.0'})
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    for label, counts, xedges, xlabel, field in [
        ('temperature_utilisation', hist_util, np.linspace(0,100,101), 'GPU utilisation (%)', 'util'),
        ('temperature_power', hist_power, np.linspace(0,1100,111), 'GPU power (W)', 'power')]:
        fig, axes=plt.subplots(1,3,figsize=(13,4.6), sharey=True)
        vmax=max(int(c.max()) for c in counts.values())
        for ax,model in zip(axes,MODELS):
            arr=counts[model].T if field=='util' else counts[model]
            mesh=ax.pcolormesh(xedges,np.linspace(0,100,101),np.ma.masked_equal(arr,0),norm=LogNorm(vmin=1,vmax=vmax),cmap='viridis',rasterized=True)
            ax.set(title=f'{model}\nn={pair_counts[model][field]:,} paired readings',xlabel=xlabel,ylim=(20,90))
        axes[0].set_ylabel('GPU temperature (°C)')
        fig.colorbar(mesh,ax=list(axes),label='Readings per bin (log scale)',fraction=.025,pad=.02)
        fig.suptitle('Training telemetry: temperature and '+('utilisation' if field=='util' else 'power'))
        # Reserve colourbar space manually rather than calling incompatible tight_layout.
        fig.subplots_adjust(bottom=.25,top=.77,right=.87,wspace=.22)
        caption='Source: Figshare 31654879, 72 unique sessions, all recorded GPUs. Bins count actual readings; no zero is substituted for missing data.\nRelationship is observational; workload phases and hardware differ. Density is sample-weighted (20 ms node / about 100 ms workstation).'
        fig.text(.02,.02,caption,fontsize=8)
        for ext in ('png','pdf'):fig.savefig(FIG/f'thermal_{label}.{ext}',dpi=300,bbox_inches='tight')
        plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(13,4.5),sharey=True)
    for ax,model in zip(axes,MODELS):
        d=representatives[model].copy();d['second']=np.floor(d.elapsed_seconds).astype(int)
        group=d.groupby('second').temperature_c.agg(['median','min','max'])
        ax.plot(group.index/60,group['median'],lw=1.4,label='Median')
        ax.fill_between(group.index/60,group['min'],group['max'],alpha=.25,label='Min–max across readings / GPUs')
        s=next(s for s in sessions if s['gpu_model']==model)
        ax.set(title=f'{model}\n{s["workload"]}\nn={len(d):,} readings',xlabel='Elapsed time (min)')
    axes[0].set_ylabel('GPU temperature (°C)');axes[0].legend(fontsize=7)
    fig.suptitle('Representative training sessions: temperature over time')
    savefig(fig,'temperature_time','Source: Figshare 31654879. First distinct archive session for each GPU model. One-second bins, all recorded GPUs.\nShading shows min–max; line shows median within each bin. Runs are separate experiments and local timestamps have unknown timezones.')
    fig,ax=plt.subplots(figsize=(8,4.8))
    mids=(np.linspace(0,100,201)[:-1]+np.linspace(0,100,201)[1:])/2
    for model in MODELS:
        h=hist_temp[model];ax.plot(mids,h/h.sum(),drawstyle='steps-mid',label=f'{model} (n={h.sum():,})')
    ax.set(xlabel='GPU temperature (°C)',ylabel='Fraction of readings per 0.5 °C bin',xlim=(20,90),title='Temperature distributions across all distinct training runs')
    ax.legend(fontsize=8)
    savefig(fig,'temperature_distribution','Source: Figshare 31654879, all GPUs from 72 distinct training sessions. Sample-weighted distributions.\nNode and workstation sampling rates differ. Model differences also reflect workload and environment differences.')
    print('VALIDATED',total_obs,total_gpu,total_raw,flush=True)

def finalise():
    """Validate every partition and add the shared descriptive hardware identifier."""
    sessions=pd.read_parquet(OUT/'sessions.parquet')
    sessions['gpu_model_identifier']=sessions.gpu_model.map(MODEL_IDS)
    assert sessions.session_id.nunique()==72
    sessions.to_parquet(OUT/'sessions.parquet',index=False,compression='zstd')
    schemas=json.loads((OUT/'source_schemas.json').read_text(encoding='utf-8'))
    for path in sorted((OUT/'gpu_telemetry').glob('*.parquet')):
        table=pq.read_table(path)
        models=table['gpu_model'].unique().to_pylist()
        assert len(models)==1
        sid=path.stem
        s=sessions.loc[sessions.session_id==sid].iloc[0]
        assert table.num_rows==s.telemetry_rows
        assert sorted(table['gpu_index_within_run'].unique().to_pylist())==list(range(int(s.gpu_count)))
        changed=False
        if 'gpu_model_identifier' not in table.column_names:
            table=table.append_column('gpu_model_identifier',pa.array([MODEL_IDS[models[0]]]*table.num_rows))
            changed=True
        if 'source_gpu_sensor_label' not in table.column_names:
            if models[0]==MODELS[0]:
                field=next(c['raw_field'] for c in schemas[s.schema_id]['columns'] if c['source_header'].startswith('GPU Temperature ['))
                raw=pq.read_table(OUT/'raw_wide'/f'{sid}.parquet',columns=['record_type',field]).to_pandas()
                sensor=raw.loc[raw.record_type=='sensor_labels',field].iloc[0]
                labels=[sensor]*table.num_rows
            else:
                labels=['gpu'+str(g) for g in table['gpu_index_within_run'].to_pylist()]
            table=table.append_column('source_gpu_sensor_label',pa.array(labels))
            changed=True
        if changed:
            pq.write_table(table,path,compression='zstd')
        if str(s.gpu_model)!='NVIDIA GeForce RTX 3060':
            assert table['cpu_power_w'].null_count==table.num_rows
            assert table['cpu_temperature_c'].null_count==table.num_rows
    manifest=pd.read_parquet(OUT/'deduplication_manifest.parquet')
    lookup=sessions.set_index('session_id')
    for col in ['observation_rows','raw_records_excluding_header_and_blank_lines']:
        manifest[col]=manifest.session_id.map(lookup[col])
    manifest.to_parquet(OUT/'deduplication_manifest.parquet',index=False,compression='zstd')
    quality=json.loads((REPORT/'thermal-quality.json').read_text(encoding='utf-8'))
    quality['original_observation_rows_across_all_95_paths']=int(manifest.observation_rows.sum())
    quality['all_partition_gpu_indices_validated']=True
    quality['shared_gpu_model_identifier_added']=True
    quality['session_summary']=sessions.astype(object).where(pd.notna(sessions),None).to_dict(orient='records')
    aggregates={}
    for model in MODELS:
        groups=[g for g in quality['gpu_summary'] if g['gpu_model']==model]
        metrics={}
        for name in groups[0]['metrics']:
            valid=[g['metrics'][name] for g in groups if g['metrics'][name]['n']]
            metrics[name]={'n':sum(g['metrics'][name]['n'] for g in groups),'missing':sum(g['metrics'][name]['missing'] for g in groups)}
            if valid:metrics[name].update({'min':min(v['min'] for v in valid),'max':max(v['max'] for v in valid)})
        aggregates[model]={'rows':sum(g['rows'] for g in groups),'session_count':len({g['session_id'] for g in groups}),
                          'metrics':metrics,'thermal_limit_active_count':sum(g['thermal_limit_active_count'] or 0 for g in groups) if model==MODELS[0] else None,
                          'power_limit_active_count':sum(g['power_limit_active_count'] or 0 for g in groups) if model==MODELS[0] else None}
    quality['model_aggregates']=aggregates
    write_json(REPORT/'thermal-quality.json',quality)
    grouped=collections.defaultdict(lambda:collections.defaultdict(list))
    for path in sorted((OUT/'gpu_telemetry').glob('*.parquet')):
        s=lookup.loc[path.stem]
        data=pq.read_table(path,columns=['temperature_c','power_w','utilisation_percent']).to_pandas()
        for metric in data:
            grouped[(s.gpu_model,s.workload)][metric].append(data[metric].to_numpy(dtype=float))
    summaries=[]
    for (model,workload),metrics in sorted(grouped.items()):
        record={'gpu_model':model,'workload':workload,'metrics':{}}
        for metric,chunks in metrics.items():
            a=np.concatenate(chunks);a=a[np.isfinite(a)]
            q=np.quantile(a,[0,.05,.5,.9,.95,.99,1])
            record['metrics'][metric]={'n':len(a),**{key:float(v) for key,v in zip(['min','p05','p50','p90','p95','p99','max'],q)}}
        summaries.append(record)
    write_json(REPORT/'thermal-summary.json',summaries)
    fig,ax=plt.subplots(figsize=(11,6.5))
    colours={MODELS[0]:'#0072B2',MODELS[1]:'#D55E00',MODELS[2]:'#009E73'}
    for i,s in enumerate(summaries):
        t=s['metrics']['temperature_c']
        ax.errorbar(t['p50'],i,xerr=[[t['p50']-t['p05']],[t['p95']-t['p50']]],fmt='o',color=colours[s['gpu_model']],capsize=4)
        ax.text(t['p95']+1,i,f'n={t["n"]:,}',va='center',fontsize=8)
    ax.set_yticks(range(len(summaries)),[s['gpu_model'].replace('NVIDIA ','')+' | '+s['workload'] for s in summaries])
    ax.invert_yaxis();ax.set(xlabel='GPU temperature (°C)',title='Temperature by GPU model and training workload',xlim=(20,95))
    savefig(fig,'temperature_workload','Source: Figshare 31654879, 72 distinct sessions, all recorded discrete GPUs. Dots show medians; whiskers show P5–P95.\nDistributions are sample-weighted. Different workloads, hardware and environments prevent causal hardware comparisons.')
    lines=['# Thermal dataset: harmonisation and findings','',
           'Verified: the original 95 CSV paths contain 2,424,786 timestamp-bearing sensor records. Exact file SHA256 deduplication leaves 72 sessions with 1,843,254 observations. These expand to 11,923,254 discrete-GPU telemetry rows: 5,760,000 H100,5,760,000 B200 and 403,254 RTX 3060 readings. Raw-wide Parquet also retains repeated headers and sensor-label footer records. No observed sensor rows are discarded for missing times.','',
           'The recordings are from September–October 2025. The dataset release is 2026. Node sessions span about 899.98 seconds with 20 ms median intervals. Workstation clocks have unknown timezones. Three workstation sessions contain only partial clock strings; their 30,258 sensor readings remain available, but absolute timestamp and elapsed seconds are null. No hours or timing offsets are invented.','',
           '## Measured distributions','',
           '| GPU model | Workload | n GPU readings | Temperature median / P95 (°C) | Power median / P95 (W) | Utilisation median / P95 (%) |',
           '|---|---|---:|---:|---:|---:|']
    for s in summaries:
        t=s['metrics']['temperature_c'];p=s['metrics']['power_w'];u=s['metrics']['utilisation_percent']
        lines.append(f'| {s["gpu_model"]} | {s["workload"]} | {t["n"]:,} | {t["p50"]:.1f} / {t["p95"]:.1f} | {p["p50"]:.1f} / {p["p95"]:.1f} | {u["p50"]:.1f} / {u["p95"]:.1f} |')
    rtx=aggregates[MODELS[0]]
    lines += ['',f'Explicit workstation indicators: thermal limit active in {rtx["thermal_limit_active_count"]:,} of 403,254 readings; power limit active in {rtx["power_limit_active_count"]:,}. Node recordings have no explicit thermal-limit indicator, so node throttling cannot be established from temperature alone. All node CPU temperature and CPU power fields are missing. Workstation CPU measurements remain in raw wide but are deliberately outside the selected GPU telemetry fields.','',
              '## Interpretation for scheduling','',
              'The temperature–utilisation and temperature–power density plots show the joint distributions of the recorded sensors. Temperature has persistence over a run; it is not an instantaneous measure of demand. The time plots show one-second medians and the observed range across all GPUs and readings for one representative run per model. Hardware and workload groups differ, and pooled averages can hide training phases.','',
              'Inference: workload-specific power envelopes and time-series thermal state could inform admission decisions under a power budget. The evidence supports descriptive profiling and future validation, not a claim that a scheduling policy improves outcomes. It does not establish energy per token, cooling demand, completion time under a cap, safe consolidation limits, thermal causality or effects on service deadlines. Throughput, progress, ambient conditions, cooling settings, concurrent jobs and controlled power interventions are absent.','',
              '## Quality, provenance and limits','',
              'The deduplication manifest preserves all 95 source paths and identifies 23 byte-identical baseline copies. Deduplicate before splitting experiments for any later analysis. Source row order, source CSV logical record number, archive member and full SHA256 remain available. Raw-wide positional fields preserve duplicated HWiNFO headers; no merged column values overwrite the originals. Missing values remain null, distinct from zero. Selected memory values retain the original MB-labelled units because decimal/binary conventions are not established; no byte conversion is made. GPU core-load and memory-activity sensors are not automatically equivalent across monitoring tools.','',
              'Figures use all discrete GPU indices, not only GPU0. They count recorded readings, not independent experiments. The 20 ms node cadence and approximately 100 ms workstation cadence produce different sample weights; driver sensor refresh can be slower than polling. Shared hardware model identifiers are descriptive and do not create a physical record-level relationship to the other datasets.','',
              'Licence conflict remains unresolved: Figshare API metadata identifies CC BY 4.0; the archive LICENSE and README identify CC BY-NC-ND 4.0. Clarify with the authors before redistributing source or adapted datasets or using them commercially.','',
              'Reproduce with `python scripts/phase1/thermal.py`. Dependencies are the root-local pandas, NumPy, PyArrow and Matplotlib packages. The script verifies all 72 session keys, every Parquet row count, all eight node GPU indices, the single workstation GPU index and node CPU null fields. Detailed missing counts and per-run/GPU percentiles are in `thermal-quality.json`; model/workload P50/P90/P95/P99 are in `thermal-summary.json`. No models or simulators are created.']
    (REPORT/'thermal-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'original_observation_rows':quality['original_observation_rows_across_all_95_paths'], 'model_aggregates':aggregates},indent=2))

if __name__=='__main__':
    if '--finalise' in sys.argv:
        finalise()
    else:
        main()
        finalise()

