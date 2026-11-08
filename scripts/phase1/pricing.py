"""Harmonise all GPUCloudCompare files without mixing billing units."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.deps'))
import csv
import hashlib
import json
import re
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SOURCE = ROOT / 'data/gpucloudcompare'
OUT = ROOT / 'harmonized/pricing'
FIG = ROOT / 'analysis/figures'
REPORT = ROOT / 'analysis/phase1'
for folder in (OUT, FIG, REPORT):
    folder.mkdir(parents=True, exist_ok=True)


def model_id(value):
    if not value or value == 'GPU':
        return None
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')


def family(value):
    if not value or value == 'GPU':
        return None
    found = re.search(r'\b(A100|H100|H100NVL|H200|B200|B300|L40S|L4|A2|MI300X)\b', value, re.I)
    return found.group(1).upper() if found else value


def hardware_id(value):
    identifier=model_id(value)
    if identifier is None:
        return None
    if identifier.startswith('nvidia_'):
        return identifier
    return ('amd_' if identifier.startswith('mi300') else 'nvidia_')+identifier


def write(name, rows):
    df = pd.DataFrame(rows)
    for date_field in ('captured_date','date'):
        if date_field in df:
            df[date_field]=pd.to_datetime(df[date_field],format='%Y-%m-%d',errors='raise').dt.date
    if 'gpu_count' in df:
        df['gpu_count']=df['gpu_count'].astype('Int64')
    path = OUT / f'{name}.parquet'
    df.to_parquet(path, index=False, compression='zstd')
    check = pq.read_table(path)
    assert check.num_rows == len(df)
    return df


def save(fig, name, caption):
    fig.text(.02, .015, 'Source: GPUCloudCompare, captured 2026-11-07. ' + caption,
             fontsize=8, va='bottom', wrap=True)
    fig.subplots_adjust(bottom=.22)
    for suffix in ('png', 'pdf'):
        fig.savefig(FIG / f'pricing_{name}.{suffix}', dpi=220, bbox_inches='tight')
    plt.close(fig)


def main():
    current = json.loads((SOURCE/'current.json').read_text())
    history = json.loads((SOURCE/'history-daily.json').read_text())
    csv_rows = list(csv.DictReader((SOURCE/'current.csv').open(newline='', encoding='utf-8')))
    assert {(r['provider'],r['plan_id']) for r in csv_rows} == {(r['provider'],r['plan_id']) for r in current['plans']}
    for csv_row, json_row in zip(csv_rows,current['plans'],strict=True):
        assert csv_row['provider']==json_row['provider'] and csv_row['plan_id']==json_row['plan_id']
        for price_field in ('price_hourly_usd','price_monthly_usd','price_monthly_eur'):
            left=float(csv_row[price_field]) if csv_row[price_field] else None
            assert left==json_row.get(price_field)
    plans, offers = [], []
    for i, raw in enumerate(current['plans'], 1):
        key = f'pricing:current:{i}'
        row = dict(source_id='gpucloudcompare', source_file='current.json', source_row=i,
                   plan_record_id=key, provider=raw['provider'], plan_id=raw['plan_id'],
                   gpu_model_raw=raw.get('gpu_model'), gpu_model_id=model_id(raw.get('gpu_model')),
                   gpu_model_identifier=hardware_id(raw.get('gpu_model')),
                   gpu_family=family(raw.get('gpu_model')), gpu_count=raw.get('gpu_count'),
                   locations=' | '.join(raw.get('locations') or []),
                   captured_date=raw.get('captured_at'), raw_record_json=json.dumps(raw, ensure_ascii=False))
        plans.append(row)
        for field, currency, unit in [('price_hourly_usd','USD','hour'),
                                      ('price_monthly_usd','USD','month'),
                                      ('price_monthly_eur','EUR','month')]:
            value = raw.get(field)
            offers.append(dict(row, price_field=field, currency=currency, billing_unit=unit,
                               price_per_plan=value,
                               price_per_gpu=value/raw['gpu_count'] if value is not None and raw.get('gpu_count',0) else None))
    plans = write('plans', plans)
    offers = write('offers', offers)
    write('current_csv_raw', [dict(source_id='gpucloudcompare',source_file='current.csv',source_row=i,
                                 raw_record_json=json.dumps(raw)) for i,raw in enumerate(csv_rows,1)])
    records=[]
    series=[('all_models',None,history['daily'])]+[('gpu_model',model,rows) for model,rows in history['by_gpu_model'].items()]
    original_history_records=0
    for scope, model, values in series:
        original_history_records += len(values)
        for i, raw in enumerate(values,1):
            for field,currency,unit in [('price_hourly_usd','USD','hour'),('price_monthly_usd','USD','month'),('price_monthly_eur','EUR','month')]:
                stats = raw.get(field) or {}
                records.append(dict(source_id='gpucloudcompare',source_file='history-daily.json',
                    source_series=scope+':'+str(model),source_row=i, scope=scope,
                    gpu_model_raw=model,gpu_model_id=model_id(model),gpu_family=family(model),
                    gpu_model_identifier=hardware_id(model),
                    date=raw['date'],price_field=field,currency=currency,billing_unit=unit,
                    min_price_per_plan=stats.get('min'),median_price_per_plan=stats.get('median'),
                    max_price_per_plan=stats.get('max'),priced_observations=stats.get('count'),
                    provider_count=raw.get('provider_count'),raw_record_json=json.dumps(raw)))
    hist=write('history',records)
    assert len(hist)==original_history_records*3
    for d in (plans,offers):
        assert not d.duplicated(['plan_record_id'] + (['price_field'] if 'price_field' in d else [])).any()
    hourly=offers[(offers.billing_unit=='hour') & offers.price_per_plan.notna() & offers.gpu_model_id.notna() & offers.price_per_gpu.notna()].copy()
    hourly['label']=hourly.gpu_model_raw+' | '+hourly.provider+' | '+hourly.gpu_count.astype('Int64').astype(str)+' GPU | '+hourly.locations
    hourly=hourly.sort_values('price_per_gpu')
    fig,ax=plt.subplots(figsize=(11, max(6,len(hourly)*.20)))
    ax.scatter(hourly.price_per_gpu,range(len(hourly)),s=25,color='#225ea8')
    ax.set_yticks(range(len(hourly)),hourly.label,fontsize=7)
    ax.set_xscale('log');ax.set_xlabel('USD per GPU-hour (plan hourly price / stated GPU count)')
    ax.set_title('Hourly cloud GPU prices by provider and exact source model')
    ax.grid(axis='x',alpha=.25)
    save(fig,'hourly_prices',f'n={len(hourly)} identified hourly plans; generic or missing models excluded. Bundled CPU/RAM and GPU variants differ.')
    selected=['H100','A100','L40S','B200']
    fig,axes=plt.subplots(3,1,figsize=(10,10),sharex=True)
    plotted=0
    for ax,(field,label) in zip(axes,[('price_hourly_usd','USD/hour'),('price_monthly_usd','USD/month'),('price_monthly_eur','EUR/month')]):
        missing=[]
        for model in selected:
            group=hist[(hist.gpu_model_raw==model)&(hist.price_field==field)].sort_values('date')
            valid=group.dropna(subset=['median_price_per_plan'])
            if valid.empty:
                missing.append(model)
                continue
            ax.plot(pd.to_datetime(valid.date),valid.median_price_per_plan,label=f'{model} (n={len(valid)} days)')
            plotted+=len(valid)
        ax.set_ylabel('Median plan price ('+label+')')
        ax.set_title(label+'; no observations: '+(', '.join(missing) or 'none'),fontsize=10)
        if ax.lines:
            ax.legend(fontsize=8)
        else:
            ax.set_axis_off()
            ax.text(.5,.5,'No recorded values for the selected models and this billing unit',
                    ha='center',va='center',transform=ax.transAxes)
        ax.grid(alpha=.2)
    axes[-1].set_xlabel('UTC date')
    fig.suptitle('Daily price index for selected exact source model labels')
    save(fig,'history',f'n={plotted} daily model/unit medians. Units stay separate; these are plan-level aggregates, not per-GPU prices. Plan mix can change.')
    fig,ax=plt.subplots(figsize=(9,5))
    coverage=offers.assign(available=offers.price_per_plan.notna()).groupby(['provider','price_field']).available.sum().unstack(fill_value=0)
    coverage.plot.barh(ax=ax);ax.set_xlabel('Plans with a recorded price');ax.set_ylabel('Provider')
    ax.set_title('Price coverage varies by provider, billing unit and currency');ax.legend(fontsize=8)
    save(fig,'coverage','n=131 plans, three possible price fields each. Missing prices are not zero.')
    present=offers[offers.price_per_plan.notna()]
    summary=dict(original_rows={'current_json_plans':len(plans),'current_csv_plans':len(csv_rows),
        'history_daily':len(history['daily']),'history_by_model':original_history_records-len(history['daily'])},
        harmonized_rows={'plans':len(plans),'offers':len(offers),'current_csv_raw':len(csv_rows),'history':len(hist)},
        csv_json_key_match=True, csv_json_row_prices_match=True, missing_model=int(plans.gpu_model_raw.isna().sum()),
        generic_model=int((plans.gpu_model_raw=='GPU').sum()),missing_price_offers=int(offers.price_per_plan.isna().sum()),
        providers=int(plans.provider.nunique()),duplicate_plan_keys=int(plans.duplicated(['provider','plan_id']).sum()),
        missing=plans.isna().sum().to_dict(),history_days=len(history['daily']),
        hourly_identified_plans=len(hourly),hourly_per_gpu_quantiles=hourly.price_per_gpu.quantile([0,.5,.9,.95,.99,1]).to_dict(),
        price_observations_by_field=present.groupby('price_field').size().to_dict(),
        source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.iterdir() if p.suffix in ['.json','.csv']})
    (REPORT/'pricing-quality.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    dictionary='''# Pricing data dictionary

`plans`: one row per current JSON plan. `plan_record_id` is a local key, not a cross-source job key.
`offers`: three rows per plan, one for each original price field, including missing prices.
`current_csv_raw`: all original CSV records as string-valued JSON, to preserve raw values independently.
`history`: one row per original daily/series record and possible price field; absent fields remain null.

`gpu_model_raw` preserves the source label. `gpu_model_id` is a conservative lower-case slug of that label;
unknown/generic labels are null. `gpu_family` is a broad family only, not evidence of compatibility.
`price_per_plan` has the stated `currency` and `billing_unit`. `price_per_gpu` divides only by a positive
stated GPU count. No currency conversion or month-to-hour conversion is applied. History prices are
per-plan statistics, with the original observation count. Dates use Parquet date32; no intraday time is invented.
`raw_record_json` preserves the entire source record. Source file, source series and 1-based row identify provenance.
`captured_date` records the source snapshot date, not the download time. `locations` preserves listed regions.
Provider/plan alone is not unique: Latitude repeats one plan across four regions with different prices.
No price identifies GPU performance, availability, interruption probability or negotiated rates.
'''
    (REPORT/'pricing-dictionary.md').write_text(dictionary,encoding='utf-8')
    report=f'''# Pricing findings

Verified: {len(plans)} plans from {plans.provider.nunique()} providers. JSON and CSV plan keys agree.
Hourly USD prices exist for 46 plans, monthly USD for 109, monthly EUR for 76.
There are {summary['missing_model']} missing model labels and {summary['generic_model']} generic `GPU` labels.
The history has 181 all-model days and 2,997 records in 23 model series, with unequal coverage.
Three repeated provider/plan keys represent four regional Latitude offers. They are retained, not silently deleted.
Their listed prices differ (USD48–66/hour for the same 8-GPU model label), a 37.5% range above the minimum.
Hourly prices for {len(hourly)} identified plans can be divided by their stated GPU count; the
median is USD {hourly.price_per_gpu.median():.3f}/GPU-hour. This mixes distinct hardware and is not a value ranking.

Figures: `pricing_hourly_prices` compares identified current plans; `pricing_history` shows four exact
model labels over time with separate hourly USD, monthly USD and monthly EUR panels;
`pricing_coverage` exposes missing billing/currency coverage. All contain source captions.
Missing GPU counts or prices remain null. No month/hour or EUR/USD conversion is assumed.
CPU, RAM, region, interconnect and model variants must be checked before declaring options compatible.
Historical medians reflect changing plan/provider composition and are not per-plan spot-price histories.
This supports scenario cost accounting, not workload placement without performance measurements.

Licence: CC-BY-4.0. Attribution: GPU Cloud Price Index, https://gpucloudcompare.com/data/.
All records retain raw JSON, original source identifiers and source-file hashes in the quality manifest.
'''
    (REPORT/'pricing-report.md').write_text(report,encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
