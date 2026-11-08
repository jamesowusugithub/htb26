"""Source-preserving common workload interface. No shared physical clock is inferred."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import json
import hashlib
import collections
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=ROOT/'integrated/workloads'
REPORT=ROOT/'analysis/integrated'
FIG=REPORT/'figures'
ALI_RAW=['job_name','organization','gpu_model','cpu_request','gpu_request','worker_num','submit_time','duration','job_type']
BURST_RAW=['timestamp','session_id','elapsed_time','model','request_tokens','response_tokens','total_tokens','log_type']
ALI_STRUCT=pa.struct([(name,pa.string()) for name in ALI_RAW])
BURST_STRUCT=pa.struct([(name,pa.string()) for name in BURST_RAW])
SCHEMA=pa.schema([
 ('workload_id',pa.string()),('source_dataset',pa.string()),('workload_type',pa.string()),
 ('source_series_id',pa.string()),('source_harmonized_path',pa.string()),('source_file',pa.string()),
 ('source_row_id',pa.int64()),('source_original_record_id',pa.string()),
 ('time_origin_id',pa.string()),('arrival_relative_s',pa.float64()),
 ('calendar_arrival_utc',pa.timestamp('us',tz='UTC')),('job_duration_s',pa.float64()),
 ('request_end_to_end_latency_s',pa.float64()),('gpu_model_identifier',pa.string()),
 ('gpu_request_recorded_count',pa.float64()),('worker_count',pa.int64()),
 ('gpu_request_scope',pa.string()),('priority_class',pa.string()),('cpu_request_vcpus',pa.float64()),
 ('organisation_id',pa.string()),('input_tokens',pa.int64()),('output_tokens',pa.int64()),
 ('total_tokens',pa.int64()),('llm_model',pa.string()),('log_type',pa.string()),
 ('conversation_session_id',pa.string()),('zero_response_tokens',pa.bool_()),
 ('alibaba_original',ALI_STRUCT),('burstgpt_original',BURST_STRUCT),
],metadata={b'entity':'Source-local workload, not common execution or physical-GPU observation',
 b'original_fields':'Nested structs preserve original CSV strings; source path and row preserve full harmonized record',
 b'time':'Relative clocks remain scoped; calendar arrival is unknown and null',
 b'observation_kind':b'observed_source_record'})


def constant(value,n,type=pa.string()):
    return pa.array([value]*n,type=type)


def column(table,name,type=None):
    value=table[name].combine_chunks()
    return pc.cast(value,type) if type is not None else value


def original_struct(table,fields,prefix):
    return pa.StructArray.from_arrays([column(table,prefix+field,pa.string()) for field in fields],names=fields)


def common(table,source,path,series):
    n=len(table)
    fields={field.name:pa.nulls(n,type=field.type) for field in SCHEMA}
    fields.update(source_dataset=constant(source,n),source_series_id=constant(series,n),
                  source_harmonized_path=constant(path.relative_to(ROOT).as_posix(),n),
                  source_file=column(table,'source_file',pa.string()))
    if source=='alibaba':
        ids=column(table,'source_row_number',pa.int64())
        fields.update(workload_type=constant('batch_gpu_job',n),source_row_id=ids,
            source_original_record_id=column(table,'source_record_id',pa.string()),
            time_origin_id=constant('alibaba:first_recorded_job:unknown_calendar',n),
            arrival_relative_s=column(table,'submit_relative_s',pa.float64()),
            alibaba_original=original_struct(table,ALI_RAW,'raw__'))
        for dest,original in [('job_duration_s','duration_s'),('gpu_model_identifier','gpu_model_identifier'),
            ('gpu_request_recorded_count','gpu_request_recorded_count'),('worker_count','worker_count'),
            ('gpu_request_scope','gpu_request_scope'),('priority_class','priority_class'),
            ('cpu_request_vcpus','cpu_request_vcpus'),('organisation_id','organisation_id')]:
            fields[dest]=column(table,original,SCHEMA.field(dest).type)
    else:
        ids=column(table,'source_row_id',pa.int64())
        fields.update(workload_type=constant('llm_inference_request',n),source_row_id=ids,
            time_origin_id=constant(series+':original_relative_seconds:unknown_calendar',n),
            arrival_relative_s=column(table,'relative_timestamp_s',pa.float64()),
            request_end_to_end_latency_s=column(table,'elapsed_time_s',pa.float64()),
            conversation_session_id=column(table,'session_id',pa.string()),
            burstgpt_original=original_struct(table,BURST_RAW,'raw_'))
        for name in ['input_tokens','output_tokens','total_tokens','llm_model','log_type','zero_response_tokens']:
            fields[name]=column(table,name,SCHEMA.field(name).type)
    fields['workload_id']=pc.binary_join_element_wise(constant(series,n),pc.cast(ids,pa.string()),':')
    return pa.Table.from_arrays([fields[field.name] for field in SCHEMA],schema=SCHEMA)


def save(fig,stem,caption):
    fig.text(.02,.012,caption,fontsize=8,va='bottom')
    fig.tight_layout(rect=(0,.15,1,.96))
    for ext in ['png','pdf']:
        fig.savefig(FIG/f'workloads_{stem}.{ext}',dpi=220,bbox_inches='tight')
    plt.close(fig)


def main():
    for folder in [OUT,REPORT,FIG]:folder.mkdir(parents=True,exist_ok=True)
    inputs=[('alibaba','alibaba_jobs',ROOT/'harmonized/alibaba/jobs.parquet')]
    for trace in ['burstgpt_1','burstgpt_2','burstgpt_3']:
        inputs.extend(('burstgpt',trace,path) for path in sorted((ROOT/'harmonized/burstgpt'/trace).glob('part-*.parquet')))
    records=[];aggregates={};null_counts=collections.Counter();source_counts=collections.Counter()
    duration_samples=[];latency_hist=np.zeros(10000,dtype=np.int64)
    for source,series,path in inputs:
        original=pq.read_table(path)
        result=common(original,source,path,series)
        target=OUT/series/path.name
        target.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(result,target,compression='zstd')
        check=pq.read_table(target)
        assert check.equals(result,check_metadata=True),target
        assert len(result)==len(original)
        assert result['calendar_arrival_utc'].null_count==len(result)
        if source=='burstgpt':
            for name in ['job_duration_s','gpu_model_identifier','gpu_request_recorded_count','priority_class','alibaba_original']:
                assert result[name].null_count==len(result),(target,name)
        else:
            assert result['request_end_to_end_latency_s'].null_count==len(result)
        for name in result.column_names:null_counts[name]+=result[name].null_count
        source_counts[source]+=len(result)
        times=result['arrival_relative_s'].to_numpy()
        bins=np.floor(times/3600).astype(np.int64)
        if series not in aggregates:
            aggregates[series]={'source':source,'min':float(times.min()),'max':float(times.max()),'count':collections.Counter(),
                'gpu':collections.Counter(),'input':collections.Counter(),'output':collections.Counter()}
        agg=aggregates[series];agg['min']=min(agg['min'],float(times.min()));agg['max']=max(agg['max'],float(times.max()))
        bincount=np.bincount(bins)
        agg['count'].update({i:int(v) for i,v in enumerate(bincount) if v})
        for field,key in [('gpu_request_recorded_count','gpu'),('input_tokens','input'),('output_tokens','output')]:
            values=result[field].to_numpy(zero_copy_only=False)
            if result[field].null_count==len(result):continue
            sums=np.bincount(bins,weights=values)
            agg[key].update({i:float(v) for i,v in enumerate(sums) if v})
        if source=='alibaba':duration_samples.append(result['job_duration_s'].to_numpy())
        if series=='burstgpt_3':
            values=result['request_end_to_end_latency_s'].to_numpy()
            finite=values[np.isfinite(values)]
            assert np.all(finite==finite.astype(int)) and finite.max()<len(latency_hist)
            latency_hist+=np.bincount(finite.astype(int),minlength=len(latency_hist))
        records.append(dict(path=target.relative_to(ROOT).as_posix(),source_path=path.relative_to(ROOT).as_posix(),rows=len(result),source=source,series=series))
        print(f'Written {target.relative_to(ROOT)}: {len(result):,}',flush=True)
    assert source_counts=={'alibaba':466867,'burstgpt':10632194},source_counts
    hourly=[]
    for series,agg in aggregates.items():
        low=int(agg['min']//3600);high=int(agg['max']//3600)
        for hour in range(low,high+1):
            hourly.append(dict(source_dataset=agg['source'],source_series_id=series,
                workload_type='batch_gpu_job' if agg['source']=='alibaba' else 'llm_inference_request',
                hour_index_original_relative=hour,hour_start_relative_s=hour*3600,
                time_origin_id=('alibaba:first_recorded_job:unknown_calendar' if agg['source']=='alibaba' else series+':original_relative_seconds:unknown_calendar'),
                arrival_count=agg['count'].get(hour,0),partial_edge_bin=hour*3600<agg['min'] or (hour+1)*3600>agg['max'],
                gpu_request_recorded_count_sum=agg['gpu'].get(hour,0.) if agg['source']=='alibaba' else None,
                input_tokens_sum=agg['input'].get(hour,0.) if agg['source']=='burstgpt' else None,
                output_tokens_sum=agg['output'].get(hour,0.) if agg['source']=='burstgpt' else None,
                value_kind='calculated_aggregate_of_observed_records'))
    hourly=pd.DataFrame(hourly)
    hourly.to_parquet(ROOT/'integrated/workload_hourly.parquet',index=False,compression='zstd')
    assert hourly.arrival_count.sum()==sum(source_counts.values())
    assert pq.read_table(ROOT/'integrated/workload_hourly.parquet').num_rows==len(hourly)
    fig,axes=plt.subplots(4,1,figsize=(11,10))
    for ax,(series,group) in zip(axes,hourly.groupby('source_series_id',sort=False)):
        offset=group.hour_start_relative_s.min()
        ax.plot((group.hour_start_relative_s-offset)/86400,group.arrival_count,lw=.7,color='#225ea8')
        ax.set_ylabel('Arrivals/hour');ax.set_title(f'{series}: n={group.arrival_count.sum():,}; separate origin',fontsize=10)
        ax.grid(alpha=.2)
    axes[-1].set_xlabel('Days from first hourly bin in this series (independent origins)')
    fig.suptitle('Common workload interface: source-scoped observed arrivals')
    save(fig,'arrivals','Sources: Alibaba 2026 Spot GPU and BurstGPT v2.0; n=11,099,061 workloads. All hourly bins within each observed span retained.\nEach panel has its own origin and workload unit; the sources are not simultaneous traffic. Partial edge bins are flagged in the table.')
    duration=np.sort(np.concatenate(duration_samples));latencies=np.flatnonzero(latency_hist)
    fig,axes=plt.subplots(1,2,figsize=(11,5))
    stride=max(1,len(duration)//20000)
    indices=np.r_[np.arange(0,len(duration),stride),len(duration)-1]
    axes[0].plot(duration[indices],(indices+1)/len(duration),color='#225ea8')
    axes[0].set_xscale('log');axes[0].set_xlabel('Source job duration (seconds)');axes[0].set_title(f'Alibaba batch jobs (n={len(duration):,})')
    axes[1].step(latencies,np.cumsum(latency_hist)[latencies]/latency_hist.sum(),where='post',color='#d95f0e')
    axes[1].set_xscale('symlog',linthresh=1);axes[1].set_xlabel('Observed end-to-end latency (seconds)');axes[1].set_title(f'BurstGPT trace 3 (n={latency_hist.sum():,})')
    for ax in axes:ax.set_ylabel('Cumulative fraction');ax.set_ylim(0,1.01);ax.grid(alpha=.2)
    fig.suptitle('Different time quantities remain separate in the common interface')
    save(fig,'time_quantities','Sources: Alibaba job durations and BurstGPT v2.0 trace-3 response latency. Alibaba curve displays evenly spaced empirical ranks.\nThese are not comparable GPU service times. Burst traces 1–2 lack latency; zero latencies are retained, not treated as missing.')
    quality=dict(source_counts=dict(source_counts),total_workload_rows=sum(source_counts.values()),output_files=records,
        parquet_files=len(records),hourly_rows=len(hourly),hourly_arrivals=int(hourly.arrival_count.sum()),
        null_counts=dict(null_counts),checks=['Every output read back exactly equal to constructed Arrow table including schema',
        'All source row counts reconciled','Identical schema across workload partitions','Inapplicable fields remain null',
        'No calendar timestamp fabricated','Hourly totals reconcile; all within-span zero hours retained'],
        original_harmonized_tables_modified=False)
    (REPORT/'workloads-quality.json').write_text(json.dumps(quality,indent=2)+'\n',encoding='utf-8')
    (REPORT/'workloads-schema.json').write_text(json.dumps({'arrow_schema':str(SCHEMA)},indent=2)+'\n',encoding='utf-8')
    dictionary='''# Common workload interface

`integrated/workloads/` contains 11,099,061 observed source records:466,867 Alibaba jobs and10,632,194 BurstGPT requests. Every Parquet file has one identical Arrow schema. The folder is an Arrow Dataset root; folder names are not Hive partitions.

`workload_id` is `source_series_id:source_row_id`, unique because source rows are unique within each original file/trace. `source_dataset`, `workload_type` (`batch_gpu_job` or `llm_inference_request`) and `source_series_id` preserve entity type. `source_harmonized_path`, `source_file`, `source_row_id` and optional `source_original_record_id` locate the untouched original harmonised record. Each Burst trace preserves its original row IDs across shards.

`arrival_relative_s` is original source-relative seconds, not a common physical clock. `time_origin_id` scopes the origin; `calendar_arrival_utc` stays null. The original Burst timestamps, including the unobserved gap before trace3, remain unchanged. Separate graphs subtract only the first displayed hourly-bin edge for display, not in the common table.

`job_duration_s` is available only for Alibaba. `request_end_to_end_latency_s` is available only when BurstGPT records it (trace3). Neither is called GPU service time. `gpu_model_identifier`, `gpu_request_recorded_count`, `worker_count`, `gpu_request_scope`, `priority_class`, `cpu_request_vcpus`, `organisation_id` retain Alibaba normalised values, with worker scope unresolved. They stay null for BurstGPT. `input_tokens`, `output_tokens`, `total_tokens`, `llm_model`, `log_type`, `conversation_session_id`, `zero_response_tokens` retain BurstGPT normalised values and stay null for Alibaba. A zero response-token flag is a source description, not a diagnosed failure cause.

`alibaba_original` and `burstgpt_original` are mutually exclusive nullable structs. Their fields preserve the exact original source string cells, including empty string versus null/absent fields from Phase1. They do not coerce GPU model names into LLM model names. The complete source-specific normalised fields remain reachable through `source_harmonized_path` and the source row key.

`integrated/workload_hourly.parquet` has one calculated aggregate per source series and original-relative hour. `arrival_count` counts source records. `gpu_request_recorded_count_sum` is a sum of recorded Alibaba request values, not occupied GPUs or GPU-hours. `input_tokens_sum` and `output_tokens_sum` count BurstGPT tokens. Missing/inapplicable quantities stay null; observed zero-count hours have zero aggregates. `partial_edge_bin` identifies hours extending beyond the first or last observed timestamp. The gap between source series is not filled with synthetic zero demand. No cross-source workload or device join exists.
'''
    (REPORT/'workloads-dictionary.md').write_text(dictionary,encoding='utf-8')
    (REPORT/'workloads-report.md').write_text('''# Unified workload layer

Verified: all466,867 Alibaba jobs and10,632,194 canonical BurstGPT requests are represented once in an identical common schema, for11,099,061 records. Original source strings are retained in separate nullable structs, alongside source table/row references. Different clocks, workload types, job duration and completion latency remain explicitly distinct.

The source-scoped arrival graph shows bursts and changing traffic volumes without assuming simultaneous operation. The time-quantity graph deliberately separates Alibaba job duration from BurstGPT completion latency. Missing GPU identity and resource demand for inference remain null, so the common interface does not invent GPU-hours per token or a placement target. Hardware/cost scenarios require separately declared assumptions rather than a record-level join.

No original harmonised tables changed. All output files were read back and compared with their constructed Arrow tables; counts and hourly aggregates reconcile. No ML/RL model, scheduler, simulator or frontend was built.
''',encoding='utf-8')
    print(f'COMPLETE {sum(source_counts.values()):,} workload rows in {len(records)} files; {len(hourly):,} hourly rows')


def capacity_proxy():
    """Work submitted on each day versus a static full-catalogue capacity scenario."""
    jobs=pd.read_parquet(ROOT/'harmonized/alibaba/jobs.parquet',columns=['gpu_model_identifier','submit_relative_s',
        'request_duration_proxy_gpu_h','worker_expanded_sensitivity_proxy_gpu_h'])
    nodes=pd.read_parquet(ROOT/'harmonized/alibaba/nodes.parquet',columns=['gpu_model_identifier','gpu_capacity_count'])
    jobs['arrival_day']=np.floor(jobs.submit_relative_s/86400).astype(int)
    grouped=jobs.groupby(['gpu_model_identifier','arrival_day']).agg(arrival_count=('submit_relative_s','size'),
        recorded_request_duration_proxy_gpu_h=('request_duration_proxy_gpu_h','sum'),
        worker_expanded_request_duration_proxy_gpu_h=('worker_expanded_sensitivity_proxy_gpu_h','sum'))
    catalogue=nodes.groupby('gpu_model_identifier').gpu_capacity_count.agg(['sum','size'])
    maxday=int(jobs.arrival_day.max());records=[]
    for model,row in catalogue.iterrows():
        for day in range(maxday+1):
            values=grouped.loc[(model,day)] if (model,day) in grouped.index else None
            capacity=float(row['sum'])*24
            demand=0. if values is None else float(values.recorded_request_duration_proxy_gpu_h)
            expanded=0. if values is None else float(values.worker_expanded_request_duration_proxy_gpu_h)
            records.append(dict(source_dataset='alibaba',gpu_model_identifier=model,arrival_day_relative=day,
                arrival_count=0 if values is None else int(values.arrival_count),static_catalogue_gpu_count=int(row['sum']),
                static_catalogue_node_count=int(row['size']),catalogue_capacity_scenario_gpu_h_per_24h=capacity,
                recorded_request_duration_proxy_gpu_h=demand,worker_expanded_request_duration_proxy_gpu_h=expanded,
                recorded_request_work_to_capacity_ratio=demand/capacity,worker_expanded_work_to_capacity_ratio=expanded/capacity,
                partial_edge_day=(day+1)*86400>jobs.submit_relative_s.max(),
                value_kind='calculated_offered_work_and_static_capacity_scenario',
                assumptions='Full source duration attributed to arrival day; full node catalogue continuously available; worker scope unresolved'))
    table=pd.DataFrame(records)
    target=ROOT/'integrated/alibaba_daily_demand_capacity.parquet'
    table.to_parquet(target,index=False,compression='zstd')
    assert pq.read_table(target).num_rows==len(table)
    assert table.arrival_count.sum()==len(jobs)
    fig,axes=plt.subplots(3,2,figsize=(12,10),sharex=True)
    for ax,(model,group) in zip(axes.flat,table.groupby('gpu_model_identifier')):
        group=group[~group.partial_edge_day]
        ax.plot(group.arrival_day_relative,group.recorded_request_work_to_capacity_ratio,label='Recorded request scope',lw=.9)
        ax.plot(group.arrival_day_relative,group.worker_expanded_work_to_capacity_ratio,label='Worker-expanded sensitivity',lw=.9,alpha=.7)
        ax.axhline(1,color='black',ls=':',lw=.8,label='24h static catalogue capacity')
        ax.set_yscale('symlog',linthresh=.1);ax.set_title(model,fontsize=9)
        ax.set_ylabel('Request-work / capacity');ax.set_ylim(bottom=0);ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=7)
    for ax in axes[-1]:ax.set_xlabel('Source-relative arrival day')
    fig.suptitle('Alibaba offered GPU-request work versus static catalogue capacity scenario')
    save(fig,'demand_capacity','Source: Alibaba2026 Spot GPU; n=466,867 jobs and4,278 catalogue nodes,10,412 GPUs. Final partial day excluded.\nCalculated scenario: entire source-reported duration is charged to its arrival day; all catalogue GPUs assumed available24h/day.\nTwo alternate request scopes are not additive. Ratios are NOT observed utilisation, concurrency, queue feasibility or idle capacity.')
    quality_path=REPORT/'workloads-quality.json'
    quality=json.loads(quality_path.read_text())
    quality['capacity_proxy_table']={'path':target.relative_to(ROOT).as_posix(),'rows':len(table),'arrival_count':int(table.arrival_count.sum()),
        'static_catalogue_gpus':int(nodes.gpu_capacity_count.sum()),'static_catalogue_nodes':len(nodes),
        'calculated_not_observed_capacity':True}
    quality_path.write_text(json.dumps(quality,indent=2)+'\n',encoding='utf-8')
    dictionary_path=REPORT/'workloads-dictionary.md'
    dictionary_path.write_text(dictionary_path.read_text(encoding='utf-8').split('\n\n## Alibaba demand/capacity scenario')[0],encoding='utf-8')
    with dictionary_path.open('a',encoding='utf-8') as f:
        f.write('\n\n## Alibaba demand/capacity scenario\n\n`integrated/alibaba_daily_demand_capacity.parquet` retains one row per disclosed/anonymised hardware model and source-relative arrival day, including zero-arrival days. Static node/GPU counts are observed catalogue counts, not availability measurements. `catalogue_capacity_scenario_gpu_h_per_24h` assumes those GPUs are available continuously for24hours. Each request-duration proxy attributes its full source duration to its arrival day, not to execution time. The worker-expanded version is a separate sensitivity interpretation, never additive. Ratios compare offered proxy work with scenario capacity, not utilisation, concurrency, idle time or a feasible schedule. The final partial day is flagged and excluded from the figure.\n')
    print(f'Capacity scenario ready: {len(table)} rows')


if __name__=='__main__':
    if '--capacity-only' in sys.argv:capacity_proxy()
    else:
        main()
        capacity_proxy()
