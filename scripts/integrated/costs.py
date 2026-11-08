"""Calculate static cloud rental scenarios, preserving evidence boundaries."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import hashlib
import json
import math
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT=ROOT/'integrated/scenarios'
REPORT=ROOT/'analysis/integrated'
FIG=REPORT/'figures'


def write(name,rows):
    frame=pd.DataFrame(rows)
    path=OUT/f'{name}.parquet'
    frame.to_parquet(path,index=False,compression='zstd')
    actual=pq.read_table(path)
    assert actual.num_rows==len(frame)
    return frame


def save(fig,name,caption):
    fig.text(.015,.012,caption,fontsize=8,va='bottom',wrap=True)
    fig.tight_layout(rect=(0,.17,1,.95))
    for extension in ('png','pdf'):
        fig.savefig(FIG/f'costs_{name}.{extension}',dpi=240,bbox_inches='tight')
    plt.close(fig)


def main():
    for directory in (OUT,REPORT,FIG):
        directory.mkdir(parents=True,exist_ok=True)
    plans=pd.read_parquet(ROOT/'harmonized/pricing/plans.parquet')
    offers=pd.read_parquet(ROOT/'harmonized/pricing/offers.parquet')
    jobs=pd.read_parquet(ROOT/'harmonized/alibaba/jobs.parquet')
    source_hash=hashlib.sha256((ROOT/'harmonized/pricing/offers.parquet').read_bytes()).hexdigest()
    eligible=offers[(offers.currency=='USD')&(offers.billing_unit=='hour')&offers.price_per_plan.notna()
                    &offers.gpu_model_identifier.notna()&offers.gpu_count.notna()&(offers.gpu_count>0)].copy()
    assumptions={
        'evidence_class':'calculated_static_scenario',
        'gpu_counts':[1,2,4,8,16], 'rental_hours':[1.0,24.0],
        'formula':'ceil(required_gpu_count / offer_gpu_count) * offer_price_usd_per_hour * rental_hours',
        'billing_assumption':'Linear hourly billing for the stated rental window, without unknown minimum periods or rounding.',
        'allocation_assumption':'Whole listed plans rented exclusively; no fractional rental or sharing credit.',
        'hardware_assumption':'Each scenario requests the exact source model label of its offer; comparisons across labels do not assume equal work or speed.',
        'not_modelled':['GPU execution time','LLM throughput','job-to-hardware speedup','network/interconnect requirements',
                       'CPU/RAM/disk feasibility','tax','egress','setup time','availability','discounts','interruptions'],
        'price_snapshot':'2026-11-07',
        'no_monthly_hourly_conversion':True,'no_currency_conversion':True,
        'no_actual_job_cost_estimate':True,
    }
    (OUT/'assumptions.json').write_text(json.dumps(assumptions,indent=2)+'\n',encoding='utf-8')
    rows=[]
    for offer in eligible.to_dict('records'):
        for gpu_count in assumptions['gpu_counts']:
            for hours in assumptions['rental_hours']:
                instances=math.ceil(gpu_count/int(offer['gpu_count']))
                capacity=instances*int(offer['gpu_count'])
                rows.append(dict(scenario_id=f"rental_{gpu_count}gpu_{hours:g}h:{offer['plan_record_id']}",
                    scenario_kind='whole_plan_gpu_rental',evidence_class='calculated_static_scenario',
                    workload_type='hypothetical_reserved_gpu_capacity',source_dataset='gpucloudcompare',
                    source_plan_record_id=offer['plan_record_id'],source_price_field='price_hourly_usd',
                    source_offers_sha256=source_hash,provider=offer['provider'],plan_id=offer['plan_id'],
                    locations=offer['locations'],gpu_model_identifier=offer['gpu_model_identifier'],
                    gpu_model_raw=offer['gpu_model_raw'],required_gpu_count=gpu_count,rental_hours=hours,
                    offer_gpu_count=int(offer['gpu_count']),observed_price_usd_per_plan_hour=offer['price_per_plan'],
                    whole_plans_required=instances,rented_gpu_capacity=capacity,
                    unused_reserved_gpu_capacity=capacity-gpu_count,
                    calculated_rental_cost_usd=instances*float(offer['price_per_plan'])*hours,
                    cost_basis='full listed plan, not fractional per-GPU charge',
                    performance_equivalence='not established',availability='unknown',
                    observed_workload_id=None,measured_energy_kwh=None,estimated_workload_completion_s=None))
    costs=write('rental_costs',rows)
    assert len(costs)==len(eligible)*len(assumptions['gpu_counts'])*len(assumptions['rental_hours'])
    assert not costs.scenario_id.duplicated().any()
    assert (costs.rented_gpu_capacity>=costs.required_gpu_count).all()
    assert np.allclose(costs.calculated_rental_cost_usd,
        costs.whole_plans_required*costs.observed_price_usd_per_plan_hour*costs.rental_hours)
    coverage=[]
    exact_known=set(eligible.gpu_model_identifier)
    for model,group in jobs.groupby('gpu_model_identifier',dropna=False):
        exact=eligible[eligible.gpu_model_identifier==model]
        candidates=offers[offers.gpu_model_identifier==model]
        coverage.append(dict(source_dataset='alibaba',gpu_model_identifier=model,observed_jobs=len(group),
            recorded_request_duration_proxy_gpu_h=float(group.request_duration_proxy_gpu_h.sum()),
            exact_identifier_price_offer_count=len(exact),all_billing_exact_identifier_offer_count=len(candidates),
            price_status='exact_label_candidate_not_execution_compatibility' if len(exact) else 'unpriced_no_exact_identifier',
            calculated_actual_job_cost_usd=None,
            reason='No measured job runtime on a cloud offer; no family-only substitution is applied.'))
    coverage=write('alibaba_cost_coverage',coverage)
    assert coverage.observed_jobs.sum()==len(jobs)
    subset=costs[(costs.required_gpu_count==8)&(costs.rental_hours==24)].sort_values('calculated_rental_cost_usd')
    labels=subset.gpu_model_raw+' | '+subset.provider+' | '+subset.offer_gpu_count.astype(str)+' GPU/plan | '+subset.locations
    fig,ax=plt.subplots(figsize=(12,8))
    ax.barh(range(len(subset)),subset.calculated_rental_cost_usd,color='#2166ac')
    ax.set_yticks(range(len(subset)),labels,fontsize=7)
    ax.set_xscale('log');ax.set_xlabel('Calculated whole-plan rental cost (USD; log scale)')
    ax.set_title('Static scenario: reserve at least 8 GPUs for 24 hours')
    ax.grid(axis='x',alpha=.2)
    save(fig,'rental_scenarios',f"Observed inputs: GPUCloudCompare snapshot 2026-11-07, n={len(eligible)} identified hourly offers.\nCalculated scenario: ceil(8 / GPUs per plan) × plan USD/hour × 24. Different hardware is not performance-equivalent.\nAssumes linear hourly rental and exclusive whole plans; taxes, availability, CPU/RAM, network and execution time are unknown.")
    fig,axes=plt.subplots(1,3,figsize=(14,5),sharey=False)
    selected=['nvidia_h100','nvidia_l40s','amd_mi300x']
    observations=0
    for ax,model in zip(axes,selected):
        group=costs[(costs.gpu_model_identifier==model)&(costs.rental_hours==1)]
        for key,line in group.groupby('source_plan_record_id'):
            line=line.sort_values('required_gpu_count')
            first=line.iloc[0]
            ax.plot(line.required_gpu_count,line.calculated_rental_cost_usd,linestyle='none',marker='o',
                    label=f"{first.provider}, {first.offer_gpu_count} GPU/plan")
            observations+=len(line)
        ax.set_title(model.replace('nvidia_','').replace('amd_','').upper())
        ax.set_xlabel('Requested reserved GPUs');ax.set_xticks(assumptions['gpu_counts'])
        ax.set_ylabel('Calculated cost (USD for 1 hour)');ax.grid(alpha=.2);ax.legend(fontsize=7)
    fig.suptitle('Whole-plan cost sensitivity to reserved GPU count, within exact model labels')
    save(fig,'demand_sensitivity',f"Observed inputs: GPUCloudCompare 2026-11-07; n={observations} calculated offer/scenario points.\nOnly exact model labels shown; no cross-model speed equivalence. Points show whole-plan charges at the five stated GPU counts.\nGPU counts are explicit hypothetical capacity demands; no Alibaba/BurstGPT job is assigned to these offers.")
    quality=dict(status='complete',evidence_class='calculated_static_scenario',observed_plan_rows=len(plans),
        source_offer_rows=len(offers),eligible_hourly_identified_offers=len(eligible),
        rental_scenario_rows=len(costs),alibaba_coverage_rows=len(coverage),
        alibaba_jobs_reconciled=int(coverage.observed_jobs.sum()),
        alibaba_jobs_with_exact_identifier_hourly_price=int(coverage.loc[coverage.exact_identifier_price_offer_count>0,'observed_jobs'].sum()),
        missing_or_other_billing_rows_not_priced=len(offers)-len(eligible),
        formula_validated=True,parquet_readback_rows_validated=True,
        source_offers_sha256=source_hash,
        observed_input_fields=['source_plan_record_id','provider','gpu_model_identifier','offer_gpu_count','observed_price_usd_per_plan_hour'],
        calculated_fields=['whole_plans_required','rented_gpu_capacity','unused_reserved_gpu_capacity','calculated_rental_cost_usd'])
    (REPORT/'costs-quality.json').write_text(json.dumps(quality,indent=2)+'\n',encoding='utf-8')
    dictionary='''# Static cloud-cost scenario dictionary

`integrated/scenarios/rental_costs.parquet` contains one row per hourly offer × requested GPU count × rental duration.
`scenario_id` is a unique calculated-case key, not a job ID. `source_plan_record_id` joins to
`harmonized/pricing/plans.parquet`; add `source_price_field = price_hourly_usd` to join offers.
Source prices and GPU counts are observed snapshot values. Required GPU count and rental hours are explicit
scenario assumptions. Plans required, reserved capacity, spare capacity and USD rental cost are calculated.
`evidence_class` is always `calculated_static_scenario`. `observed_workload_id`, measured energy and workload
completion time remain null. This table never claims that an Alibaba job or BurstGPT request ran on an offer.

`integrated/scenarios/alibaba_cost_coverage.parquet` has one row per Alibaba hardware identifier. It records
job counts, recorded-request × duration proxies and exact identifier price coverage. Actual job cost stays
null. Family-only GPU matches are not silently treated as compatible. Zero offer count means unpriced, not free.
The request-duration proxy is not actual allocated GPU-hours and worker scope remains unresolved.

Units: hours, GPU counts, USD per listed plan-hour, calculated USD per scenario. No monthly price conversion,
exchange rate, measured service time or GPU throughput is invented. `assumptions.json` records the formula
and unmodelled constraints. Raw inputs remain in the unchanged harmonised pricing/Alibaba tables.
'''
    (REPORT/'costs-dictionary.md').write_text(dictionary,encoding='utf-8')
    report=f'''# Calculated cloud-rental scenarios

Observed inputs: 131 current plan records, 393 billing/currency slots; {len(eligible)} identified hourly USD offers
have positive stated GPU counts. The source snapshot date is 7 November 2026. All source plan IDs and the
offers Parquet SHA256 are retained.

Calculated outcomes: {len(costs)} static cases cover requested counts 1, 2, 4, 8 and 16 GPUs and rental windows
1 and 24 hours. Cost = ceil(required GPU count / GPUs per plan) × listed hourly plan price × hours.
The whole plan is charged even when capacity is unused. These are arithmetic rental cases, not simulated
or observed scheduling outcomes. They do not imply equal workload performance across hardware.

For the 8-GPU/24-hour scenario, listed-offer rental estimates range from USD {subset.calculated_rental_cost_usd.min():,.2f}
to USD {subset.calculated_rental_cost_usd.max():,.2f}. This mixes GPU models and is not a cost-effectiveness ranking.
The demand sensitivity graph separates H100, L40S and MI300X exact source model labels.

Alibaba has {len(coverage)} hardware labels covering {len(jobs):,} jobs, with no exact identifier match to the
eligible hourly offers. Generic A100 prices cannot establish compatibility with A100-SXM4-80GB jobs.
Actual Alibaba cloud job costs remain null. BurstGPT has no recorded GPU model or GPU service time;
its end-to-end elapsed time is not used as GPU rental time. No cost per request/token is invented.

Limitations: linear hourly billing is assumed because minimum billing periods/rounding are not supplied.
CPU/RAM/disk feasibility, region availability, interconnect, taxes, egress, setup time, discounts and workload
performance are unmodelled. No monthly-to-hourly or currency conversion is performed. Runtime under
another hardware configuration would require separate evidence.

Source/attribution: GPU Cloud Price Index, https://gpucloudcompare.com/data/, CC-BY-4.0. Alibaba source
licence coverage remains unresolved as documented in Phase 1. Existing harmonised tables remain unchanged.
Reproduce: `python scripts/integrated/costs.py`.
'''
    (REPORT/'costs-report.md').write_text(report,encoding='utf-8')
    print(json.dumps(quality,indent=2))


if __name__=='__main__':
    main()
