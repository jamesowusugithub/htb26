"""Conservative hardware relationships and measured thermal load profiles."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import json,re,collections
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=ROOT/'integrated/hardware'
REPORT=ROOT/'analysis/integrated'
FIG=REPORT/'figures'

def family(identifier):
    if pd.isna(identifier):return None
    m=re.search(r'(?:^|_)(a100|a10|a800|h100nvl|h100|h800|h200|b200|b300|l40s|l4|a2|mi300x)(?:_|$)',identifier)
    return m.group(1) if m else identifier

def write(name,df):
    path=OUT/f'{name}.parquet';df.to_parquet(path,index=False,compression='zstd')
    assert pq.read_table(path).num_rows==len(df)
    return df

def save(fig,name,caption):
    fig.text(.01,.01,caption,fontsize=8,va='bottom',wrap=True)
    fig.tight_layout(rect=(0,.17,1,.95))
    for ext in ('png','pdf'):fig.savefig(FIG/f'hardware_{name}.{ext}',dpi=240,bbox_inches='tight')
    plt.close(fig)

def main():
    for p in (OUT,REPORT,FIG):p.mkdir(parents=True,exist_ok=True)
    aliases=pd.read_parquet(ROOT/'harmonized/catalogue/hardware_aliases.parquet')
    nodes=pd.read_parquet(ROOT/'harmonized/alibaba/nodes.parquet')
    plans=pd.read_parquet(ROOT/'harmonized/pricing/plans.parquet')
    sessions=pd.read_parquet(ROOT/'harmonized/thermal/sessions.parquet')
    ids=sorted(aliases.gpu_model_identifier.dropna().unique())
    dim=[]
    for identifier in ids:
        a=aliases[aliases.gpu_model_identifier==identifier]
        dim.append(dict(gpu_model_identifier=identifier,gpu_family=family(identifier),
            original_labels_json=json.dumps(sorted(a.source_label.dropna().unique().tolist())),
            source_ids_json=json.dumps(sorted(a.source_id.unique().tolist())),
            identifier_scope='model_label_only_not_physical_device',
            hardware_specification_verified=False))
    dimension=write('gpu_models',pd.DataFrame(dim))
    candidates=[]
    origins=aliases[aliases.source_id.isin(['alibaba','thermal'])].drop_duplicates(['source_id','gpu_model_identifier'])
    for _,origin in origins.iterrows():
        identifier=origin.gpu_model_identifier
        matching=plans[plans.gpu_model_identifier==identifier]
        status='exact_model_label'
        if matching.empty:
            matching=plans[plans.gpu_model_identifier.map(family)==family(identifier)] if family(identifier) else plans.iloc[:0]
            status='family_candidate_only'
        if matching.empty:
            candidates.append(dict(origin_source=origin.source_id,gpu_model_identifier=identifier,
                plan_record_id=None,pricing_gpu_model_identifier=None,match_status='unavailable',
                eligible_for_label_level_scenario=False,functional_compatibility_confirmed=False,
                relationship='No price record supported by model labels'))
        else:
            for _,plan in matching.iterrows():
                candidates.append(dict(origin_source=origin.source_id,gpu_model_identifier=identifier,
                    plan_record_id=plan.plan_record_id,pricing_gpu_model_identifier=plan.gpu_model_identifier,
                    match_status=status,eligible_for_label_level_scenario=status=='exact_model_label',
                    functional_compatibility_confirmed=False,
                    relationship='Model-label relationship only; memory,variant,interconnect and performance require independent evidence'))
    bridge=write('pricing_links',pd.DataFrame(candidates))
    thermal_links=[]
    for identifier in ids:
        exact=sessions[sessions.gpu_model_identifier==identifier]
        status='exact_model_label'
        if exact.empty:
            exact=sessions[sessions.gpu_model_identifier.map(family)==family(identifier)] if family(identifier) else sessions.iloc[:0]
            status='family_candidate_only'
        for _,session in exact.iterrows():
            thermal_links.append(dict(gpu_model_identifier=identifier,session_id=session.session_id,
                thermal_gpu_model_identifier=session.gpu_model_identifier,match_status=status,
                relationship_scope='Independent experimental model-level profile; not same job or machine',
                eligible_for_measured_profile=status=='exact_model_label'))
    tl=write('thermal_links',pd.DataFrame(thermal_links))
    cap=nodes.groupby('gpu_model_identifier',as_index=False).agg(catalogue_gpu_capacity=('gpu_capacity_count','sum'),node_count=('node_id','size'))
    cap['evidence_class']='observed_static_source_catalogue'
    cap['capacity_time_history_available']=False
    write('alibaba_catalogue_capacity',cap)
    # Keep all readings but stratify descriptive profiles by model/workload/load band.
    grouped=collections.defaultdict(lambda:dict(temperature=[],power=[],sessions=set(),rows=0))
    total=0;missing=collections.Counter();invalid_load=0
    labels=['0–<20','20–<40','40–<60','60–<80','80–100']
    for path in sorted((ROOT/'harmonized/thermal/gpu_telemetry').glob('*.parquet')):
        df=pd.read_parquet(path,columns=['session_id','gpu_model_identifier','workload','utilisation_percent','temperature_c','power_w'])
        total+=len(df)
        for column in ('utilisation_percent','temperature_c','power_w'):missing[column]+=int(df[column].isna().sum())
        valid=df.utilisation_percent.between(0,100)
        invalid_load+=int((~valid & df.utilisation_percent.notna()).sum())
        df=df[valid].copy()
        df['load_band_index']=np.minimum((df.utilisation_percent/20).astype(int),4)
        for key,g in df.groupby(['gpu_model_identifier','workload','load_band_index'],sort=False):
            bucket=grouped[key];bucket['rows']+=len(g);bucket['sessions'].update(g.session_id.unique())
            bucket['temperature'].append(g.temperature_c.dropna().to_numpy(dtype=float))
            bucket['power'].append(g.power_w.dropna().to_numpy(dtype=float))
    profiles=[]
    for (model,workload,band),bucket in grouped.items():
        row=dict(gpu_model_identifier=model,workload=workload,load_band_index=int(band),
            utilisation_band_percent=labels[int(band)],readings=bucket['rows'],sessions=len(bucket['sessions']),
            session_ids_json=json.dumps(sorted(bucket['sessions'])),evidence_class='observed_sensor_summary',
            weighting='one_weight_per_recorded_GPU_reading_not_independent_samples')
        for metric in ('temperature','power'):
            a=np.concatenate(bucket[metric]);unit='c' if metric=='temperature' else 'w'
            row[metric+'_valid_count']=len(a)
            for q in (.5,.9,.95,.99):row[f'{metric}_p{int(q*100)}_{unit}']=float(np.quantile(a,q)) if len(a) else None
        profiles.append(row)
    profile=write('thermal_load_profiles',pd.DataFrame(profiles))
    assert total==11923254
    assert bridge.plan_record_id.dropna().isin(plans.plan_record_id).all()
    assert tl.session_id.isin(sessions.session_id).all()
    coverage=[]
    for _,origin in origins.iterrows():
        p=bridge[(bridge.origin_source==origin.source_id)&(bridge.gpu_model_identifier==origin.gpu_model_identifier)]
        coverage.append(dict(source=origin.source_id,model=origin.gpu_model_identifier,
            exact_price_labels=int((p.match_status=='exact_model_label').sum()),
            family_price_candidates=int((p.match_status=='family_candidate_only').sum()),
            exact_thermal_sessions=int((sessions.gpu_model_identifier==origin.gpu_model_identifier).sum())))
    coverage=pd.DataFrame(coverage)
    fig,ax=plt.subplots(figsize=(11,6))
    arr=coverage[['exact_price_labels','family_price_candidates','exact_thermal_sessions']].to_numpy()
    ax.imshow(arr,aspect='auto',cmap='Blues');ax.set_yticks(range(len(coverage)),coverage.source+' | '+coverage.model)
    ax.set_xticks(range(3),['Exact-label price offers','Family-only price candidates','Exact-label thermal sessions'])
    for (r,c),value in np.ndenumerate(arr):ax.text(c,r,str(value),ha='center',va='center',color='white' if value>25 else 'black')
    ax.set_title('Hardware relationships reveal where cross-source links are supported')
    save(fig,'link_coverage',f'Sources: Alibaba catalogue, GPUCloudCompare current plans, Figshare thermal sessions. n={len(origins)} source/model pairs;131 plans;72 runs.\nCounts are model-label links, not verified job compatibility or evidence of the same machine. Family candidates are not automatic matches.')
    fig,axes=plt.subplots(2,3,figsize=(14,8),sharex=True)
    for col,model in enumerate(sorted(profile.gpu_model_identifier.unique())):
        sub=profile[profile.gpu_model_identifier==model]
        for workload,g in sub.groupby('workload'):
            g=g.sort_values('load_band_index')
            axes[0,col].plot(g.load_band_index,g.temperature_p50_c,marker='o',label=workload)
            axes[1,col].plot(g.load_band_index,g.power_p50_w,marker='o',label=workload)
        axes[0,col].set_title(model.replace('nvidia_','').replace('_',' ')+f'\nn={int(sub.readings.sum()):,} readings;{sessions[sessions.gpu_model_identifier==model].shape[0]} runs',fontsize=10)
        axes[0,col].set_ylabel('Median temperature (°C)');axes[1,col].set_ylabel('Median GPU power (W)')
        axes[1,col].set_xticks(range(5),labels,rotation=30);axes[1,col].set_xlabel('Recorded utilisation band (%)')
        axes[0,col].legend(fontsize=6)
        for row in range(2):axes[row,col].grid(alpha=.2)
    fig.suptitle('Measured temperature and power under different recorded GPU loads')
    save(fig,'thermal_load_profiles','Source: Figshare31654879;all11,923,254 GPU readings,72 unique runs. Lines connect descriptive workload-specific load bins.\nSampling rates and sensor cadence differ; observations are not independent experiments. These are measured associations, not effects of changing a scheduler.\nP50/P90/P95/P99, valid metric counts and session counts are retained in thermal_load_profiles.parquet; no job-level join is asserted.')
    quality=dict(complete=True,gpu_models=len(dimension),pricing_links=len(bridge),thermal_links=len(tl),
        thermal_input_readings=total,thermal_profile_rows=len(profile),thermal_profile_readings=int(profile.readings.sum()),
        missing_thermal_metrics=dict(missing),out_of_range_utilisation=invalid_load,
        pricing_link_status_counts=bridge.match_status.value_counts().to_dict(),
        relationship_checks='All nonnull price foreign keys and all thermal session foreign keys resolve; every output readable with reconciled row count.')
    (REPORT/'hardware-quality.json').write_text(json.dumps(quality,indent=2)+'\n',encoding='utf-8')
    (REPORT/'hardware-dictionary.md').write_text('''# Hardware relationship dictionary

All outputs are under `integrated/hardware/`. Original harmonised tables remain unchanged.

| Table | Grain and keys | Meaning |
| --- | --- | --- |
| gpu_models | One `gpu_model_identifier` | Conservative vocabulary from source aliases; no verified physical identity or full hardware specification |
| pricing_links | Origin source/model × candidate `plan_record_id`; null target for unavailable | Join pricing plans/offers by plan_record_id. Exact model label permits labelled what-if cost scenarios only. Family candidates are insufficient for automatic pricing. Functional compatibility is not confirmed for any link. |
| thermal_links | Model × `session_id` | Join thermal sessions by session_id; independent experimental model profile, never a measured job/device join |
| alibaba_catalogue_capacity | GPU model | Sum of source node GPU capacity; static catalogue, not available capacity over time |
| thermal_load_profiles | Model × workload × utilisation band | Recorded readings, distinct run count, source run IDs and sensor quantiles; observed, not calculated scheduling outcomes |

`exact_model_label` means identical conservative identifiers. `family_candidate_only` means a shared named family with unresolved variant details. `unavailable` means no supported price candidate. Exact labels do not establish memory size, interconnect, performance or placement compatibility.
Thermal utilisation bands are [0,20), [20,40), [40,60), [60,80), [80,100]. Temperature is Celsius; power is watts. Quantiles weight recorded GPU readings equally; they do not claim independent samples or equal run/time weights. Missing measurements are excluded only from the relevant metric quantiles and counted separately. Zeros are retained.
Pricing currencies and billing units remain in original pricing tables. No EUR/USD or monthly/hourly conversion is introduced here. No thermal reading identifies a particular Alibaba job, BurstGPT request or cloud machine. Source licences remain unchanged, including the thermal archive/metadata licence conflict.
''',encoding='utf-8')
    (REPORT/'hardware-report.md').write_text(f'''# Cross-source hardware relationships

Verified: {len(dimension)} named GPU identifiers, {len(bridge)} origin-to-price rows and {len(tl)} model-to-thermal-session links.
Alibaba's A100-SXM4-80GB has generic A100 family price candidates only, not a confirmed exact variant match. Other Alibaba models have no supported cloud price match in these sources. Do not use candidate prices as measured job costs.
Thermal H100 and B200 have exact model-label pricing records; RTX3060 has no price match. H100 memory/interconnect variants remain distinct. No link establishes physical-device identity or full functional compatibility.

All {total:,} thermal GPU readings were used. They produce {len(profile)} workload/model/load-band profiles with observed P50/P90/P95/P99 temperature and power, valid counts and distinct session counts. These are experimental load associations, not measured effects of a scheduling policy.
Figures: `hardware_link_coverage` makes missing links visible; `hardware_thermal_load_profiles` compares recorded temperature and power across utilisation bands while preserving hardware and workload strata. Sources and counts are stated on each figure.
Raw timestamps are not aligned across datasets. Static Alibaba catalogue capacity does not describe maintenance, reservations or available GPUs over time. Additional performance and resource-compatibility evidence is needed before hardware substitution decisions.
''',encoding='utf-8')
    print(json.dumps(quality,indent=2))

if __name__=='__main__':main()
