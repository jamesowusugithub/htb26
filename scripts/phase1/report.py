"""Assemble the measured source reports and graph index after validation."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]

EXPLANATIONS={
 'alibaba_arrivals':'Hourly arrivals, including the origin concentration and a separate post-origin view.',
 'alibaba_priority_counts':'High-priority and spot submission volumes.',
 'alibaba_duration_distribution':'Full job-duration distributions by priority, with skew retained.',
 'alibaba_hardware_demand':'Two explicitly separate request-duration proxies by hardware, not measured GPU use.',
 'alibaba_resource_requests':'Recorded GPU requests and worker counts by priority.',
 'pricing_hourly_prices':'Identified current hourly offers, divided by recorded GPU count and labelled by provider and region.',
 'pricing_history':'Selected hardware price indices with billing units and currencies in separate panels.',
 'pricing_coverage':'Recorded and missing billing/currency coverage across providers.',
 'burstgpt_request_rates':'Traffic and spikes across observed trace spans, retaining quiet bins.',
 'burstgpt_token_distributions':'Input and output token distributions across canonical full traces.',
 'burstgpt_size_latency':'Input size versus recorded completion latency, including zero latency.',
 'burstgpt_latency_distribution':'Completion-latency distributions for trace 3.',
 'burstgpt_size_latency_by_model':'Size and latency within each recorded LLM model category.',
 'burstgpt_daily_profiles':'Relative 24-hour demand profiles; calendar clock and weekday are unknown.',
 'thermal_temperature_utilisation':'Joint GPU temperature and utilisation observations.',
 'thermal_temperature_power':'Joint GPU temperature and power observations.',
 'thermal_temperature_time':'Temperature over elapsed time in explicitly selected training sessions.',
 'thermal_temperature_distribution':'Sample-weighted temperature distributions by GPU model.',
 'thermal_temperature_workload':'Temperature distributions separated by recorded hardware and workload groups.',
}


def main():
    check=json.loads((ROOT/'analysis/phase1/validation.json').read_text())
    figures=sorted((ROOT/'analysis/figures').glob('*.png'))
    expected=set(EXPLANATIONS)
    actual={p.stem for p in figures}
    if actual != expected:
        raise ValueError(f'Figure set differs: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')
    missing_pdf=[p.stem for p in figures if not p.with_suffix('.pdf').is_file()]
    if missing_pdf:
        raise FileNotFoundError(f'Missing figure PDFs: {missing_pdf}')
    text=f'''# Phase 1: GPU data harmonisation and trend analysis

Completed on 8 November 2026. All four retained sources were processed. Kestrel is excluded.
No prediction model, reinforcement-learning environment, simulator or frontend was built.

## Outcome and analytical boundaries

Normalisation standardises schemas, units, hardware identifiers and provenance. It does not
apply min-max scaling or z-scores. Missing values are not imputed. The source tables stay
separate: there is no claim that they describe the same GPU, job or data centre.

## Source records retained

| Source | Raw scope | Harmonised scope | Counting rule |
| --- | ---: | ---: | --- |
| Alibaba jobs | 466,867 jobs | 466,867 jobs | One job per source row |
| Alibaba nodes | 4,278 nodes | 4,278 nodes | One node per source row |
| BurstGPT | 20,776,759 rows across six files | 10,632,194 requests | The other 10,144,565 rows are verified filtered variants of the full traces |
| GPUCloudCompare plans | 131 plans | 131 plans | Eight providers; the 2,997 historical records form a separate series |
| Thermal | 2,424,786 timestamp-bearing records in 95 CSV paths | 1,843,254 sensor observations in 72 unique sessions | These expand to 11,923,254 per-GPU telemetry rows; 23 baseline copies are byte-identical |

These counts describe different entities. Do not add them into one workload total.

## Main measured findings

Alibaba's 415,713 high-priority jobs have a 1,101 s median duration, while 51,154
Spot jobs have a 2,095.5 s median. The high-priority P99 is 5,972,708.9 s, compared
with 186,322.2 s for Spot. The trace records requests, not actual allocation or wait time.

BurstGPT's three full traces have complete-minute median rates of 2, 2 and 4
requests/min and observed peaks of 1,250, 1,104 and 1,048 requests/min. Trace 3
has a 0 s median completion latency; 59.43% of values are zero at its recorded
precision. Latency and token counts do not measure GPU service time.

Among 18 identified current cloud plans with a stated GPU count and hourly USD
price, the median listed price is USD 4.175 per GPU-hour. The plans differ in
hardware and region, so this is a coverage summary, not a value ranking.

Thermal measurements vary by recorded hardware and workload. For example, the
B200 median temperature is 37 degrees C under image generation and 50 degrees C under text
generation, with different power distributions. These are sample-weighted sensor
readings from experiments, not independent jobs or controlled scheduling trials.

## Time and unit boundaries

Alibaba submits are seconds from its first recorded job. BurstGPT timestamps
support relative minute and hour bins, but no trustworthy calendar weekday.
Thermal node sessions use elapsed seconds; workstation clocks have unknown
timezones and three partial-clock sessions. Pricing uses offer snapshots and
daily index dates. No source clock is aligned with another source clock.
GPU-request hours are demand proxies, USD/GPU-hour is a listed price unit, and
temperature/power/utilisation are sampled telemetry. None is a common measure
of job energy or cost.

Alibaba and BurstGPT have source-relative time. Thermal recordings have local clocks with
unknown timezones and explicit parse failures. Pricing has snapshot/index dates. No shared
calendar timeline is invented. Raw values remain available with source rows and file hashes.

Full decoding passed for {len(check['tables'])} Parquet files. PNG integrity and paired PDF
existence passed for {len(check['figures'])} figure pairs. These checks establish output
readability; source-specific reconciliation and semantic checks are documented separately.
Graph appearance was inspected separately. PDF rendering was not independently verified.

- [Data dictionary and relationships](data-dictionary.md)
- [Full validation catalogue](phase1/validation.json)
- [Reproduction instructions](../harmonized/README.md)
- [Exact dependency versions](../requirements-phase1.lock.txt)

## Scheduling decisions supported for investigation

| Evidence | Decision worth investigating | Limit |
| --- | --- | --- |
| Alibaba priority, requests, duration and arrivals | Priority-aware admission, placement and backfilling | Actual starts, allocation and interruptions are absent; request scope is ambiguous |
| BurstGPT arrival and token variability | Batching, queue admission and serving-capacity changes | GPU service times and hardware are unknown; elapsed time is coarse end-to-end latency |
| Current cloud offers and daily indices | Cost sensitivity for explicitly specified hardware/region/billing scenarios | Price does not establish performance, availability or interruption risk |
| Experimental temperature, power and load | Workload power-budget and temperature monitoring hypotheses | Experiments are not causal scheduler comparisons; workloads and sampling rates differ |

These are hypotheses for later evaluation. No scheduling improvement or future predictability
has been demonstrated. Quiet arrivals do not establish idle GPUs, observed output token counts
are not known at request admission, and temperature correlations do not establish throttling.
Exact hardware variants and source-local identifiers must remain distinct.

'''
    for source in ('alibaba','burstgpt','pricing','thermal'):
        report_path=ROOT/'analysis/phase1'/f'{source}-report.md'
        try:
            report=report_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            report=report_path.read_text(encoding='cp1252')
        text+='\n'+ '\n'.join('#'+line if line.startswith('#') else line for line in report.splitlines())+'\n'
    text+='\n## Graphs\n\nEach graph carries its source, units, observation counts and interpretation limits. PDF versions are linked for export.\n\n'
    for p in figures:
        description=EXPLANATIONS.get(p.stem,p.stem.replace('_',' '))
        text+=f'### {description}\n\n![{description}](figures/{p.name})\n\n[PDF](figures/{p.stem}.pdf)\n\n'
    text+='''## Findings that cannot be established

These data do not establish a feasible replay of a production cluster without further capacity,
placement and policy information. They do not provide causal evidence for scheduler speed-ups,
carbon savings or energy savings. There are no measured cross-hardware completion-time curves
for the same submitted jobs. There is no joint job-to-power-to-price record across the four sources.
Before any later modelling, define the decision time, available input fields, train/test time
boundaries, feasible actions and failure/overrun handling. Do not leak final duration or output
token count into an admission-time predictor.

## Licensing and redistribution

BurstGPT and GPUCloudCompare identify CC-BY-4.0 terms; preserve their attribution and citations.
The downloaded Alibaba README provides citation instructions but no explicit licence grant.
Figshare metadata says CC BY 4.0 while the thermal archive says CC BY-NC-ND 4.0. These are
unresolved source terms, not a new licence applied to all repository contents. The private
repository and preserved source notices do not resolve those discrepancies.
'''
    (ROOT/'analysis/data-exploration-report.md').write_text(text,encoding='utf-8')
    print('Assembled final report and graph index')


if __name__=='__main__':
    main()
