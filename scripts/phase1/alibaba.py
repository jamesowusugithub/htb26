"""Harmonise Alibaba spot-GPU data and draw measured Phase 1 figures.
Run from repository root: python scripts/phase1/alibaba.py
Requires pandas, numpy, matplotlib, pyarrow; local .deps is supported.
"""
from pathlib import Path
import sys, json, hashlib, re, platform
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.deps'))
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

SOURCE = 'https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2026-spot-gpu'
RAW = ROOT/'data/alibaba-2026-spot-gpu'
OUT = ROOT/'harmonized/alibaba'
FIG = ROOT/'analysis/figures'
ANA = ROOT/'analysis/phase1'
for d in [OUT, FIG, ANA]: d.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10, 'axes.titlesize':13, 'axes.labelsize':10, 'figure.dpi':140, 'savefig.dpi':220, 'axes.spines.top':False, 'axes.spines.right':False, 'axes.grid':True, 'grid.alpha':.2, 'pdf.fonttype':42, 'ps.fonttype':42})
COLORS={'HP':'#275D8C','Spot':'#C75B12'}

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def key(s):
    v=str(s).strip()
    if v.startswith('GPU-series-'):return 'alibaba_'+re.sub(r'[^a-z0-9]+','_',v.lower()).strip('_')
    return 'nvidia_'+re.sub(r'[^a-z0-9]+','_',v.lower()).strip('_')
def pct(a):
    a=pd.to_numeric(a,errors='coerce').dropna()
    if not len(a):return {'n':0}
    q=a.quantile([0,.25,.5,.75,.9,.95,.99,1])
    return {'n':int(len(a)), 'min':float(q.loc[0]), 'p25':float(q.loc[.25]), 'p50':float(q.loc[.5]), 'p75':float(q.loc[.75]), 'p90':float(q.loc[.9]), 'p95':float(q.loc[.95]), 'p99':float(q.loc[.99]), 'max':float(q.loc[1]), 'mean':float(a.mean())}
def native(x):
    if isinstance(x,dict):return {str(k):native(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [native(v) for v in x]
    if isinstance(x,np.generic):return x.item()
    return x

def base(raw,name):
    result=raw.add_prefix('raw__').copy()
    result['source_dataset']='alibaba_2026_spot_gpu'
    result['source_file']=name
    result['source_url']=SOURCE
    result['source_sha256']=digest(RAW/name)
    result['source_row_number']=np.arange(1,len(raw)+1,dtype=np.int64)
    result['source_record_id']=['alibaba:'+name+':'+str(i) for i in range(1,len(raw)+1)]
    return result

def savefig(fig,name,caption):
    fig.text(.06,.02,caption,ha='left',va='bottom',fontsize=8,color='#333333')
    fig.tight_layout(rect=(0,.16,1,1))
    paths=[]
    for ext in ['png','pdf']:
        p=FIG/(name+'.'+ext);fig.savefig(p,bbox_inches='tight');paths.append(str(p.relative_to(ROOT)))
    plt.close(fig)
    return {'name':name,'files':paths,'caption':caption,'source':SOURCE}

rj=pd.read_csv(RAW/'job_info_df.csv',dtype=str,keep_default_na=False)
rn=pd.read_csv(RAW/'node_info_df.csv',dtype=str,keep_default_na=False)
j=base(rj,'job_info_df.csv');n=base(rn,'node_info_df.csv')
j['job_id']=rj.job_name.astype('string');j['organisation_id']=rj.organization.astype('string')
j['gpu_model_identifier']=rj.gpu_model.map(key).astype('string')
j['gpu_model_source']=rj.gpu_model.astype('string')
j['gpu_model_identity_status']=np.where(rj.gpu_model.str.startswith('GPU-series-'),'anonymised_unresolved','source_model_specific')
j['priority_class']=rj.job_type.map({'HP':'high_priority','Spot':'spot'}).astype('string')
for source,target in [('cpu_request','cpu_request_vcpus'),('gpu_request','gpu_request_recorded_count'),('worker_num','worker_count'),('submit_time','submit_relative_s'),('duration','duration_s')]:j[target]=pd.to_numeric(rj[source],errors='coerce')
j['submit_time_basis']='seconds_since_first_source_job; calendar_origin_unknown'
j['submitted_at_utc']=pd.Series(pd.NaT,index=j.index,dtype='datetime64[ns, UTC]')
j['gpu_request_scope']='recorded_request; worker_scope_not_explicitly_defined'
j['request_duration_proxy_gpu_h']=j.gpu_request_recorded_count*j.duration_s/3600
j['worker_expanded_sensitivity_proxy_gpu_h']=j.request_duration_proxy_gpu_h*j.worker_count
j['demand_proxy_status']='request-duration proxy; not measured allocation or utilisation'
n['node_id']=rn.node_name.astype('string');n['gpu_model_identifier']=rn.gpu_model.map(key).astype('string');n['gpu_model_source']=rn.gpu_model.astype('string')
n['gpu_capacity_count']=pd.to_numeric(rn.gpu_capacity_num,errors='coerce');n['cpu_capacity_vcpus']=pd.to_numeric(rn.cpu_num,errors='coerce')
n['gpu_model_identity_status']=np.where(rn.gpu_model.str.startswith('GPU-series-'),'anonymised_unresolved','source_model_specific')
quality={'source':SOURCE,'row_counts':{},'raw_preservation':{},'missing':{},'duplicates':{},'invalid':{},'schemas':{},'licensing':'Downloaded source README requests citation but supplies no explicit licence grant. Redistribution terms not established from local source files; do not assume CC-BY or another licence.','relationships':'Jobs and nodes share source-specific GPU model identifiers, not job-to-node allocation keys. No job-to-node join or cross-dataset record linkage is inferred.'}
for label,raw,table in [('jobs',rj,j),('nodes',rn,n)]:
    p=OUT/(label+'.parquet');table.to_parquet(p,index=False,engine='pyarrow',compression='zstd');back=pd.read_parquet(p)
    preserved=all(back['raw__'+c].astype(str).equals(raw[c].astype(str)) for c in raw)
    assert len(back)==len(raw) and preserved
    assert back.source_record_id.is_unique
    quality['row_counts'][label]={'original':len(raw),'harmonized':len(back),'parquet_metadata':pq.ParquetFile(p).metadata.num_rows}
    quality['raw_preservation'][label]={'all_raw_fields_identical_after_parquet_roundtrip':preserved,'raw_columns':list(raw.columns),'source_sha256':digest(RAW/('job_info_df.csv' if label=='jobs' else 'node_info_df.csv')),'output_sha256':digest(p)}
    quality['missing'][label]={'raw_blank_fields':{c:int(raw[c].eq('').sum()) for c in raw},'harmonized_null_fields':{c:int(back[c].isna().sum()) for c in back}}
    quality['duplicates'][label]={'exact_raw_duplicate_rows':int(raw.duplicated().sum()),'duplicate_source_ids':int(raw['job_name' if label=='jobs' else 'node_name'].duplicated().sum())}
    quality['schemas'][label]=str(pq.ParquetFile(p).schema_arrow)
quality['invalid']={'negative_submit_relative_s':int(j.submit_relative_s.lt(0).sum()),'nonpositive_duration_s':int(j.duration_s.le(0).sum()),'nonpositive_gpu_request':int(j.gpu_request_recorded_count.le(0).sum()),'nonpositive_worker_count':int(j.worker_count.le(0).sum()),'unmapped_priority_class':int(j.priority_class.isna().sum()),'nonpositive_node_gpu_capacity':int(n.gpu_capacity_count.le(0).sum()),'job_models_absent_from_node_catalogue':sorted(set(j.gpu_model_identifier)-set(n.gpu_model_identifier))}

# Complete hourly bins include zero arrivals; final partial bin is explicitly marked.
last_hour=int(np.floor(j.submit_relative_s.max()/3600));counts=pd.crosstab(np.floor(j.submit_relative_s/3600).astype(int),rj.job_type).reindex(range(last_hour+1),fill_value=0).reindex(columns=['HP','Spot'],fill_value=0)
counts.index.name='relative_hour_bin';counts['total']=counts.sum(axis=1);counts['bin_start_relative_s']=counts.index*3600;counts['bin_complete']=counts.index<last_hour
counts.reset_index().to_parquet(OUT/'arrival_hourly.parquet',index=False,engine='pyarrow',compression='zstd')
full=counts.loc[counts.bin_complete];threshold=float(full.total.quantile(.99));nonorigin=full.iloc[1:]
spike_mask=full.total.gt(threshold)
spike_runs=int((spike_mask & ~spike_mask.shift(1,fill_value=False)).sum())
daily_full=full.total.iloc[:(len(full)//24)*24].groupby(np.arange((len(full)//24)*24)//24).sum()
temporal={'hourly_pearson_autocorrelation_full_bins':{str(lag):float(full.total.autocorr(lag)) for lag in [1,24,168]},'hourly_pearson_autocorrelation_excluding_origin_hour':{str(lag):float(nonorigin.total.autocorr(lag)) for lag in [1,24,168]},'complete_relative_days':len(daily_full),'daily_pearson_autocorrelation':{str(lag):float(daily_full.autocorr(lag)) for lag in [1,7]},'contiguous_runs_above_hourly_p99':spike_runs,'interpretation':'Descriptive serial association only; no out-of-sample predictability test, timezone or weekday inference.'}
summary={'source':SOURCE,'jobs':len(j),'nodes':len(n),'types':{},'gpu_capacity_by_model':n.groupby('gpu_model_source').gpu_capacity_count.sum().to_dict(),'arrival_bins':{'bin_width_s':3600,'full_bins':len(full),'final_partial_bins':1,'last_submit_relative_s':float(j.submit_relative_s.max()),'zero_submit_time_jobs':int(j.submit_relative_s.eq(0).sum()),'all_full_hour_counts':pct(full.total),'p99_threshold_jobs_per_hour':threshold,'hours_strictly_above_p99':int(full.total.gt(threshold).sum()),'zero_arrival_full_hours':int(full.total.eq(0).sum()),'quiet_full_hours_at_most_10_jobs':int(full.total.le(10).sum()),'zero_HP_full_hours':int(full.HP.eq(0).sum()),'zero_Spot_full_hours':int(full.Spot.eq(0).sum()),'max_full_hour_excluding_origin':int(nonorigin.total.max()),'top_10_full_bins':full.nlargest(10,'total')[['HP','Spot','total','bin_start_relative_s']].reset_index().to_dict('records')},'temporal_description':temporal,'fractional_gpu_requests':int(j.gpu_request_recorded_count.mod(1).ne(0).sum()),'hardware_job_counts':rj.gpu_model.value_counts().to_dict(),'hardware_demand_proxy':j.groupby('gpu_model_source')[['request_duration_proxy_gpu_h','worker_expanded_sensitivity_proxy_gpu_h']].sum().to_dict(),'worker_count':pct(j.worker_count),'gpu_request_recorded_count':pct(j.gpu_request_recorded_count),'versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'pyarrow':pa.__version__,'matplotlib':matplotlib.__version__}}
for label,mask in [('HP',rj.job_type.eq('HP')),('Spot',rj.job_type.eq('Spot'))]:
    a=j.loc[mask];summary['types'][label]={'n':len(a),'fraction':float(len(a)/len(j)),'duration_s':pct(a.duration_s),'gpu_request_recorded_count':pct(a.gpu_request_recorded_count),'worker_count':pct(a.worker_count),'multiworker_fraction':float(a.worker_count.gt(1).mean()),'request_duration_proxy_gpu_h':float(a.request_duration_proxy_gpu_h.sum()),'worker_expanded_sensitivity_proxy_gpu_h':float(a.worker_expanded_sensitivity_proxy_gpu_h.sum())}

figs=[]
fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True)
for ax,frame,title in [(axes[0],counts,'All observed bins, including the origin concentration'),(axes[1],counts.iloc[1:],'Detail after the first hour, on its own vertical scale')]:
 for typ in ['HP','Spot']:ax.plot(frame.index/24,frame[typ],label=typ,color=COLORS[typ],lw=.9)
 ax.set(title=title,ylabel='Job arrivals per 1-hour bin');ax.legend(frameon=False,loc='upper right')
axes[1].set_xlabel('Days since first source job (calendar origin unknown)')
fig.suptitle('Alibaba GPU job arrivals across relative time')
figs.append(savefig(fig,'alibaba_arrivals',f'Source: Alibaba 2026 Spot GPU | n={len(j):,} jobs; {len(full):,} full hourly bins plus one partial bin.\nLower panel excludes first-hour n={int(counts.iloc[0].total):,}; zero bins retained. Arrivals do not measure idle GPU capacity.'))
fig,ax=plt.subplots(figsize=(7.6,4.6));vc=rj.job_type.value_counts().reindex(['HP','Spot']);bars=ax.bar(vc.index,vc.values,color=[COLORS[x] for x in vc.index],width=.55)
for b,v in zip(bars,vc):ax.text(b.get_x()+b.get_width()/2,v+len(j)*.012,f'{v:,}\n({v/len(j):.1%})',ha='center',fontsize=10)
ax.set(title='High-priority jobs dominate submission counts',xlabel='Source job priority class',ylabel='Number of job records',ylim=(0,vc.max()*1.22));ax.yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:,.0f}'))
figs.append(savefig(fig,'alibaba_priority_counts',f'Source: Alibaba 2026 Spot GPU | n={len(j):,} job records; no missing priority labels.\nCounts show submission volume, not occupied GPU capacity or computational work.'))
fig,ax=plt.subplots(figsize=(8.5,4.8))
for typ in ['HP','Spot']:
    a=np.sort(j.loc[rj.job_type.eq(typ),'duration_s'].dropna().values);ax.plot(a/3600,np.arange(1,len(a)+1)/len(a),label=f'{typ} (n={len(a):,})',color=COLORS[typ],lw=1.7)
ax.set_xscale('log');ax.set(title='Spot jobs have a higher median but a shorter upper tail',xlabel='Source job duration (hours, logarithmic scale)',ylabel='Cumulative fraction of jobs',ylim=(0,1));ax.legend(frameon=False);ax.axhline(.95,color='grey',ls=':',lw=.8)
figs.append(savefig(fig,'alibaba_duration_distribution',f'Source: Alibaba 2026 Spot GPU | n={len(j):,} jobs; all durations positive and present.\nEmpirical cumulative distributions retain the full duration range. Duration is source reported; censoring is not documented.'))
agg=j.groupby('gpu_model_source')[['request_duration_proxy_gpu_h','worker_expanded_sensitivity_proxy_gpu_h']].sum().sort_values('request_duration_proxy_gpu_h')
fig,ax=plt.subplots(figsize=(10,5.3));pos=np.arange(len(agg));ax.barh(pos-.18,agg.iloc[:,0],height=.34,label='Recorded request × duration',color='#275D8C');ax.barh(pos+.18,agg.iloc[:,1],height=.34,label='Sensitivity: × worker count',color='#C75B12');ax.set_yticks(pos,agg.index);ax.set_xscale('log');ax.set(title='Requested demand proxies by source hardware model',xlabel='Request-duration proxy (GPU-request hours, logarithmic scale)',ylabel='Source hardware label');ax.legend(frameon=False,loc='lower right',fontsize=9)
figs.append(savefig(fig,'alibaba_hardware_demand',f'Source: Alibaba 2026 Spot GPU | n={len(j):,} jobs; two alternate interpretations, not additive.\nNeither proxy is measured GPU use. Worker scope is ambiguous; anonymised GPU-series labels remain unresolved.'))
fig,axes=plt.subplots(1,2,figsize=(10,4.7))
for ax,col,xlabel in [(axes[0],'gpu_request_recorded_count','Recorded GPU request (count or fractional request)'),(axes[1],'worker_count','Requested worker instances (count)')]:
 for typ in ['HP','Spot']:
  a=np.sort(j.loc[rj.job_type.eq(typ),col].values);ax.step(a,np.arange(1,len(a)+1)/len(a),where='post',color=COLORS[typ],label=typ)
 ax.set_xscale('log');ax.set(xlabel=xlabel,ylabel='Cumulative fraction of jobs',ylim=(0,1));ax.legend(frameon=False)
fig.suptitle('Priority classes differ in requested resources')
figs.append(savefig(fig,'alibaba_resource_requests',f'Source: Alibaba 2026 Spot GPU | HP n={vc.HP:,}; Spot n={vc.Spot:,}; all requests present.\nFractional GPU requests are retained as requests. Worker counts do not establish occupied GPU counts.'))

(ANA/'alibaba-summary.json').write_text(json.dumps(native(summary),indent=2,allow_nan=False)+'\n',encoding='utf-8')
(ANA/'alibaba-quality.json').write_text(json.dumps(native(quality),indent=2,allow_nan=False)+'\n',encoding='utf-8')
(ANA/'alibaba-figures.json').write_text(json.dumps(figs,indent=2)+'\n',encoding='utf-8')
# Field-level dictionary covers every raw and normalised output field.
entries=[]
normal={
 'job_id':('identifier','Exact source job_name string; not linked to other datasets.'),'organisation_id':('identifier','Exact source organisation identifier.'),'gpu_model_identifier':('identifier','Source-specific normalised label; NVIDIA prefix only for disclosed models; GPU-series labels stay Alibaba-specific.'),'gpu_model_source':('label','Original hardware label.'),'gpu_model_identity_status':('category','Anonymised unresolved versus source-model-specific.'),'priority_class':('category','HP -> high_priority; Spot -> spot.'),'cpu_request_vcpus':('vCPU','Numeric source CPU request; worker scope not resolved.'),'gpu_request_recorded_count':('GPU request count','Numeric source GPU request, including fractions; worker scope unspecified.'),'worker_count':('instances','Numeric source worker_num.'),'submit_relative_s':('seconds','Seconds from first source job. No absolute calendar origin.'),'duration_s':('seconds','Source job duration; missing censoring and lifecycle semantics cannot be reconstructed.'),'submit_time_basis':('label','Explicit relative-time origin.'),'submitted_at_utc':('UTC timestamp','All null because source calendar origin is unknown.'),'gpu_request_scope':('label','Explicit unresolved worker scope.'),'request_duration_proxy_gpu_h':('GPU-request hours','gpu_request_recorded_count * duration_s / 3600; request-based proxy, not actual use.'),'worker_expanded_sensitivity_proxy_gpu_h':('GPU-request hours','Recorded request * duration * worker_count / 3600; sensitivity interpretation only.'),'demand_proxy_status':('label','Explicit request-proxy limitation.'),'node_id':('identifier','Exact source node_name string.'),'gpu_capacity_count':('GPUs','Numeric source gpu_capacity_num; node catalogue, not a time-varying availability trace.'),'cpu_capacity_vcpus':('vCPU','Numeric source cpu_num.'),'source_dataset':('identifier','Constant source dataset name.'),'source_file':('path','Original CSV basename.'),'source_url':('URL','Source dataset directory URL.'),'source_sha256':('SHA256','Hash of original source CSV bytes.'),'source_row_number':('1-based row index','CSV data record index, excluding header.'),'source_record_id':('identifier','Dataset+filename+row index unique provenance key.')}
for table_name,frame,raw in [('jobs',j,rj),('nodes',n,rn)]:
 for col in frame:
  unit,desc=('source literal','Unchanged CSV field '+col[5:]+' stored as text, including empty text; see source README for source unit.') if col.startswith('raw__') else normal[col]
  entries.append({'table':table_name,'field':col,'dtype':str(frame[col].dtype),'unit':unit,'definition':desc})
entries.extend([{'table':'arrival_hourly','field':c,'dtype':str(counts.reset_index()[c].dtype),'unit':('seconds' if c=='bin_start_relative_s' else 'boolean' if c=='bin_complete' else 'hour index' if c=='relative_hour_bin' else 'job arrivals'),'definition':{'relative_hour_bin':'Floor(submit_relative_s / 3600), including empty bins.','HP':'High-priority arrivals in bin.','Spot':'Spot arrivals in bin.','total':'All job arrivals in bin.','bin_start_relative_s':'Relative start of bin.','bin_complete':'False for the final partially observed hour.'}[c]} for c in counts.reset_index()])
pd.DataFrame(entries).to_csv(ANA/'alibaba-dictionary.csv',index=False)

hp=summary['types']['HP'];sp=summary['types']['Spot'];ab=summary['arrival_bins'];dem=j.groupby('gpu_model_source').request_duration_proxy_gpu_h.sum().sort_values(ascending=False);expanded=j.groupby('gpu_model_source').worker_expanded_sensitivity_proxy_gpu_h.sum().sort_values(ascending=False)
report=f'''# Alibaba Phase 1 findings

Verified: both CSVs were inspected before transformation. Jobs: {len(rj):,} original and {len(j):,} harmonised rows. Nodes: {len(rn):,} original and {len(n):,} harmonised rows. Every raw value survives a Parquet round trip unchanged. Source identifiers, data-record row numbers and file hashes are preserved. Full quality checks and the field dictionary are in `alibaba-quality.json` and `alibaba-dictionary.csv`.

## Measured workload differences

HP: {hp['n']:,} jobs ({hp['fraction']:.2%}); Spot: {sp['n']:,} ({sp['fraction']:.2%}). HP duration median {hp['duration_s']['p50']:,.1f}s, P90 {hp['duration_s']['p90']:,.1f}s, P95 {hp['duration_s']['p95']:,.1f}s, P99 {hp['duration_s']['p99']:,.1f}s. Spot duration median {sp['duration_s']['p50']:,.1f}s, P90 {sp['duration_s']['p90']:,.1f}s, P95 {sp['duration_s']['p95']:,.1f}s, P99 {sp['duration_s']['p99']:,.1f}s. Spot jobs have a higher median duration, while HP has a much longer upper tail. A mean alone would conceal this difference.

Multiworker jobs: HP {hp['multiworker_fraction']:.2%}, Spot {sp['multiworker_fraction']:.2%}. These are worker-instance requests, not measured GPU allocations. Fractional GPU requests occur in {summary['fractional_gpu_requests']:,} records; they are preserved and do not establish actual fractional GPU utilisation.

Hardware catalogue: {len(n):,} nodes and {n.gpu_capacity_count.sum():,.0f} recorded GPUs across {n.gpu_model_source.nunique()} labels. GPU-series-1 and GPU-series-2 are anonymised labels. Their architecture and compatibility with cloud offerings remain unknown. No job-to-node assignment key is provided.

The largest recorded-request × duration proxy is {dem.index[0]} ({dem.iloc[0]:,.1f} GPU-request hours). Under the separate worker-expanded sensitivity interpretation, the largest is {expanded.index[0]} ({expanded.iloc[0]:,.1f} proxy hours). These are alternate request-based proxies, not additive demand measures, measured GPU-hours, energy or utilisation. The README calls gpu_request a job request but does not clearly specify its relationship to worker_num. No total allocated GPU count is inferred.

## Arrivals, spikes and quiet periods

Submit time is relative seconds from the first source job. The maximum is {j.submit_relative_s.max():,.0f}s ({j.submit_relative_s.max()/86400:.2f} days). No calendar origin, weekday, timezone, workday or local clock hour is fabricated. All UTC timestamps remain null. {ab['zero_submit_time_jobs']:,} jobs appear at time zero; source documentation does not explain this concentration, so the origin bin needs separate interpretation.

One-hour aggregation includes all {ab['full_bins']:,} complete bins, including zero-count bins, and labels the final partial bin. Median full-hour arrivals: {ab['all_full_hour_counts']['p50']:,.1f}; P95 {ab['all_full_hour_counts']['p95']:,.1f}; P99 {ab['all_full_hour_counts']['p99']:,.1f}. {ab['hours_strictly_above_p99']:,} full bins exceed the empirical P99 threshold ({ab['hours_strictly_above_p99']/ab['full_bins']:.2%} of full bins). This empirical threshold describes observed extremes; its exceedance fraction is partly defined by the quantile and is not a predictive event probability. Highest full-hour count excluding the origin bin: {ab['max_full_hour_excluding_origin']:,}.

There are {ab['zero_arrival_full_hours']:,} zero-arrival full hours and {ab['quiet_full_hours_at_most_10_jobs']:,} with at most ten arrivals. HP has {ab['zero_HP_full_hours']:,} zero-arrival hours and Spot has {ab['zero_Spot_full_hours']:,}. Quiet arrivals do not establish idle GPUs because earlier jobs can remain active. Complete bins prevent the omission of quiet periods. There are {spike_runs:,} contiguous runs above the hourly P99 threshold. Descriptive Pearson arrival autocorrelation, including the origin bin: lag 1h {temporal['hourly_pearson_autocorrelation_full_bins']['1']:.3f}, lag 24h {temporal['hourly_pearson_autocorrelation_full_bins']['24']:.3f}, lag 168h {temporal['hourly_pearson_autocorrelation_full_bins']['168']:.3f}. Excluding the origin hour: lag 1h {temporal['hourly_pearson_autocorrelation_excluding_origin_hour']['1']:.3f}, lag 24h {temporal['hourly_pearson_autocorrelation_excluding_origin_hour']['24']:.3f}, lag 168h {temporal['hourly_pearson_autocorrelation_excluding_origin_hour']['168']:.3f}. These describe serial association in this observed trace; they do not test future predictability or establish repeating calendar patterns. No fitted model or statistical-significance claim is made.

## Quality, units and limits

Raw blank fields: jobs {sum(quality['missing']['jobs']['raw_blank_fields'].values()):,}; nodes {sum(quality['missing']['nodes']['raw_blank_fields'].values()):,}. Duplicate full source rows: jobs {quality['duplicates']['jobs']['exact_raw_duplicate_rows']:,}, nodes {quality['duplicates']['nodes']['exact_raw_duplicate_rows']:,}. Duplicate source job IDs: {quality['duplicates']['jobs']['duplicate_source_ids']:,}; node IDs: {quality['duplicates']['nodes']['duplicate_source_ids']:,}. No negative submission times, nonpositive durations, nonpositive GPU requests or nonpositive worker counts were found. These bounded checks establish internal consistency for those fields; they do not prove complete or unbiased workload capture.

Source duration and submit time are already seconds. Figures convert seconds to hours or days only for display. Both demand proxies divide by 3600 to express request-hours. Raw numeric text remains available. Queue wait, actual allocation, starts, finishes, interruptions, checkpoints, SLO target values, time-varying cluster availability, measured power and measured GPU utilisation are absent. In particular, submit_time + duration is not labelled as a measured finish time. Source censoring semantics are unspecified; long durations and the time-zero concentration need sensitivity checks before scheduling evaluation.

Inference: compare HP and Spot separately when designing duration classes and admission controls. Spot's higher multiworker fraction supports testing gang-aware admission as a hypothesis. Long HP tails and short Spot tails support testing different policies per class. None of these measurements proves a policy improves throughput, cost, wait or SLO compliance. A simulator, fitted predictor or trained model was not created.

Licensing: downloaded source README requests paper citation but supplies no explicit licence grant. Reuse/redistribution terms are not established by the downloaded documents. Preserve the source README and attribution; do not silently label this data CC-BY. Other datasets remain separate tables; a shared hardware label never establishes the same physical GPU or data centre.

## Artefacts and reproduction

Run `python scripts/phase1/alibaba.py` from the repository root with pandas, NumPy, PyArrow and Matplotlib. Versions and hashes are recorded. Outputs: `harmonized/alibaba/jobs.parquet`, `nodes.parquet`, `arrival_hourly.parquet`; five PNG/PDF figure pairs under `analysis/figures/alibaba_*`; this report, source-preserving dictionary, quality checks and measured summary under `analysis/phase1/`.

Source: {SOURCE}
'''
(ANA/'alibaba-report.md').write_text(report,encoding='utf-8')
print(json.dumps(native({'rows':quality['row_counts'],'invalid':quality['invalid'],'arrival_bins':summary['arrival_bins'],'figure_count':len(figs)}),indent=2))
