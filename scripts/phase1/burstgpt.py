"""Harmonise and explore BurstGPT without inventing GPU or calendar fields.

Run from any directory: python scripts/phase1/burstgpt.py
Dependencies: pandas, numpy, pyarrow and matplotlib (also loaded from ROOT/.deps).
"""
from __future__ import annotations

import collections
import hashlib
import heapq
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.deps'))
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

RAW = ROOT / 'data' / 'burstgpt'
OUT = ROOT / 'harmonized' / 'burstgpt'
REPORT = ROOT / 'analysis' / 'phase1'
FIGS = ROOT / 'analysis' / 'figures'
CHUNK = 200_000
SOURCE = 'https://github.com/HPMLL/BurstGPT/releases/tag/v2.0'
RAW_FIELDS = ['Timestamp', 'Session ID', 'Elapsed time', 'Model', 'Request tokens',
              'Response tokens', 'Total tokens', 'Log Type']
RAW_NAMES = ['raw_timestamp', 'raw_session_id', 'raw_elapsed_time', 'raw_model',
             'raw_request_tokens', 'raw_response_tokens', 'raw_total_tokens', 'raw_log_type']
SCHEMA = pa.schema([
    ('source_dataset', pa.string()), ('source_file', pa.string()),
    ('source_row_id', pa.int64()), ('trace_id', pa.string()),
    ('relative_timestamp_s', pa.float64()), ('trace_local_timestamp_s', pa.float64()),
    ('calendar_timestamp_utc', pa.timestamp('us', tz='UTC')),
    ('input_tokens', pa.int64()), ('output_tokens', pa.int64()), ('total_tokens', pa.int64()),
    ('elapsed_time_s', pa.float64()), ('llm_model', pa.string()),
    ('log_type', pa.string()), ('session_id', pa.string()), ('gpu_model', pa.string()),
    ('zero_response_tokens', pa.bool_()),
] + [(name, pa.string()) for name in RAW_NAMES], metadata={
    b'source': SOURCE.encode(), b'release': b'v2.0',
    b'time_origin': b'Original relative seconds; calendar date/time zone unavailable.',
    b'row_id': b'One-based physical data row, excluding CSV header.',
    b'licence': b'CC-BY-4.0; cite BurstGPT authors (CITATION.cff).',
})


def read_chunks(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=CHUNK)


def raw_frame(frame):
    return frame.reindex(columns=RAW_FIELDS)


def canonical_lines(frame):
    # JSON escaping permits exact row comparison even if a field contains a delimiter.
    return [json.dumps(list(row), ensure_ascii=True, separators=(',', ':')) + '\n'
            for row in raw_frame(frame).itertuples(index=False, name=None)]


def percentile(hist, probability):
    n = int(hist.sum())
    return int(np.searchsorted(np.cumsum(hist), max(0, math.ceil(probability * n) - 1), side='right')) if n else None


def histogram_stats(hist):
    n = int(hist.sum())
    occupied = np.flatnonzero(hist)
    return {'n': n, 'min': int(occupied[0]) if n else None,
            'max': int(occupied[-1]) if n else None,
            'mean': float(np.dot(np.arange(len(hist)), hist) / n) if n else None,
            **{f'p{int(p * 100)}': percentile(hist, p) for p in [.5, .9, .95, .99]}}


def pad_hist(hist, values):
    more = np.bincount(values)
    if len(more) > len(hist):
        hist = np.pad(hist, (0, len(more) - len(hist)))
    hist[:len(more)] += more
    return hist


def count_duplicates(sorted_paths):
    handles = [p.open(encoding='utf-8', newline='') for p in sorted_paths]
    previous = None
    run = repeated_rows = repeated_groups = 0
    try:
        for line in heapq.merge(*handles):
            if line == previous:
                repeated_rows += 1
                if run == 1:
                    repeated_groups += 1
                run += 1
            else:
                previous, run = line, 1
    finally:
        for handle in handles:
            handle.close()
    return {'extra_identical_raw_rows': repeated_rows,
            'repeated_raw_tuple_groups': repeated_groups,
            'method': 'Exact external merge sort of canonical raw JSON tuples within each trace; all rows retained.'}


def check_filtered(index, full_digest, expected_count):
    path = RAW / f'BurstGPT_without_fails_{index}.csv'
    digest = hashlib.sha256()
    count = zero = 0
    for chunk in read_chunks(path):
        count += len(chunk)
        zero += int((pd.to_numeric(chunk['Response tokens']) == 0).sum())
        digest.update(''.join(canonical_lines(chunk)).encode())
    if count != expected_count or zero or digest.hexdigest() != full_digest:
        raise ValueError(f'Filtered variant mismatch: {path.name}')
    return {'source_file': path.name, 'rows': count, 'zero_response_rows': zero,
            'canonical_sha256': digest.hexdigest(), 'exact_ordered_success_subset': True,
            'harmonisation': 'Not emitted again: exact success-only subset of the canonical full trace.'}


def process_trace(index):
    path = RAW / f'BurstGPT_{index}.csv'
    trace_id = f'burstgpt_{index}'
    dest = OUT / trace_id
    dest.mkdir(parents=True, exist_ok=True)
    # Clear only the script-owned previous output shards for an idempotent rerun.
    for old in dest.glob('part-*.parquet'):
        old.unlink()
    result = {'trace_id': trace_id, 'source_file': path.name, 'source_url': SOURCE,
              'original_rows': 0, 'harmonised_rows': 0, 'raw_missing': {},
              'zero_response_rows': 0, 'negative_numeric_rows': 0,
              'token_total_mismatch_rows': 0, 'descending_timestamps': 0,
              'raw_zero_elapsed_rows': 0, 'elapsed_missing_rows': 0,
              'models': {}, 'log_types': {}, 'readback_equal_every_shard': True}
    hists = {field: np.zeros(1, dtype=np.int64) for field in ['input', 'output', 'total', 'elapsed']}
    minute_counts = collections.Counter()
    hourly_tokens = collections.Counter()
    model_counts, log_counts = collections.Counter(), collections.Counter()
    missing = collections.Counter()
    success_digest = hashlib.sha256()
    previous_time = None
    start = None
    input_edges = np.unique(np.r_[0, 1, np.geomspace(2, 150_000, 33).astype(int)])
    latency_by_size = np.zeros((len(input_edges) - 1, 1001), dtype=np.int64)
    latency_by_model = collections.defaultdict(lambda: np.zeros(1001, dtype=np.int64))
    size_latency_by_model = collections.defaultdict(lambda: np.zeros_like(latency_by_size))
    model_moments = collections.defaultdict(lambda: np.zeros(6, dtype=np.float64))
    moments = np.zeros(6, dtype=np.float64)  # n, x, y, xx, yy, xy
    tmp = Path(tempfile.mkdtemp(prefix=f'{trace_id}-', dir=OUT))
    sort_paths = []
    try:
        for part, chunk in enumerate(read_chunks(path)):
            if part == 0:
                result['original_schema'] = list(chunk.columns)
            n = len(chunk)
            raw = raw_frame(chunk)
            for name in RAW_FIELDS:
                missing[name] += int(raw[name].isna().sum() + (raw[name] == '').sum())
            timestamp = pd.to_numeric(chunk['Timestamp'], errors='raise').to_numpy(dtype=np.float64)
            inputs = pd.to_numeric(chunk['Request tokens'], errors='raise').to_numpy(dtype=np.int64)
            outputs = pd.to_numeric(chunk['Response tokens'], errors='raise').to_numpy(dtype=np.int64)
            totals = pd.to_numeric(chunk['Total tokens'], errors='raise').to_numpy(dtype=np.int64)
            if start is None:
                start = float(timestamp[0])
                result['relative_timestamp_min_s'] = float(timestamp.min())
            result['relative_timestamp_max_s'] = float(timestamp.max())
            result['descending_timestamps'] += int((np.diff(timestamp) < 0).sum())
            if previous_time is not None:
                result['descending_timestamps'] += int(timestamp[0] < previous_time)
            previous_time = timestamp[-1]
            result['zero_response_rows'] += int((outputs == 0).sum())
            result['token_total_mismatch_rows'] += int((inputs + outputs != totals).sum())
            result['negative_numeric_rows'] += int(((timestamp < 0) | (inputs < 0) | (outputs < 0) | (totals < 0)).sum())
            elapsed = pd.to_numeric(chunk['Elapsed time'], errors='raise').to_numpy(dtype=np.float64) if 'Elapsed time' in chunk else np.full(n, np.nan)
            result['elapsed_missing_rows'] += int(np.isnan(elapsed).sum())
            result['raw_zero_elapsed_rows'] += int((elapsed == 0).sum())
            if np.isfinite(elapsed).any():
                if np.any(elapsed[np.isfinite(elapsed)] != np.floor(elapsed[np.isfinite(elapsed)])):
                    raise ValueError('Elapsed values are no longer integer seconds; adjust histogram resolution explicitly.')
                if np.nanmax(elapsed) > 1000 or np.nanmin(elapsed) < 0:
                    raise ValueError('Unexpected elapsed range; widen exact histogram.')
                observed = np.isfinite(elapsed)
                hists['elapsed'] = pad_hist(hists['elapsed'], elapsed[observed].astype(int))
                bins = np.searchsorted(input_edges, inputs, side='right') - 1
                np.add.at(latency_by_size, (bins[observed], elapsed[observed].astype(int)), 1)
                for model in chunk['Model'].unique():
                    mask = observed & (chunk['Model'].to_numpy() == model)
                    latency_by_model[model] += np.bincount(elapsed[mask].astype(int), minlength=1001)
                    np.add.at(size_latency_by_model[model], (bins[mask], elapsed[mask].astype(int)), 1)
                    mx, my = inputs[mask].astype(float), elapsed[mask]
                    model_moments[model] += [len(mx), mx.sum(), my.sum(), np.dot(mx, mx), np.dot(my, my), np.dot(mx, my)]
                x, y = inputs[observed].astype(float), elapsed[observed]
                moments += [len(x), x.sum(), y.sum(), np.dot(x, x), np.dot(y, y), np.dot(x, y)]
            for name, values in [('input', inputs), ('output', outputs), ('total', totals)]:
                hists[name] = pad_hist(hists[name], values)
            values, counts = np.unique((timestamp // 60).astype(np.int64), return_counts=True)
            minute_counts.update(dict(zip(values.tolist(), counts.tolist())))
            values, inverse = np.unique((timestamp // 3600).astype(np.int64), return_inverse=True)
            hourly_tokens.update(dict(zip(values.tolist(), np.bincount(inverse, weights=totals).astype(np.int64).tolist())))
            model_counts.update(chunk['Model'].value_counts().to_dict())
            log_counts.update(chunk['Log Type'].value_counts().to_dict())
            lines = canonical_lines(chunk)
            success_digest.update(''.join(line for line, successful in zip(lines, outputs != 0) if successful).encode())
            sort_path = tmp / f'part-{part:04d}.jsonl'
            sort_path.write_text(''.join(sorted(lines)), encoding='utf-8', newline='')
            sort_paths.append(sort_path)
            normalised = {
                'source_dataset': ['burstgpt'] * n, 'source_file': [path.name] * n,
                'source_row_id': np.arange(result['original_rows'] + 1, result['original_rows'] + n + 1, dtype=np.int64),
                'trace_id': [trace_id] * n, 'relative_timestamp_s': timestamp,
                'trace_local_timestamp_s': timestamp - start, 'calendar_timestamp_utc': [None] * n,
                'input_tokens': inputs, 'output_tokens': outputs, 'total_tokens': totals,
                'elapsed_time_s': [None if np.isnan(v) else float(v) for v in elapsed],
                'llm_model': chunk['Model'], 'log_type': chunk['Log Type'],
                'session_id': [None if pd.isna(v) or v == '' else v for v in raw['Session ID']],
                'gpu_model': [None] * n, 'zero_response_tokens': outputs == 0,
            }
            for old, new in zip(RAW_FIELDS, RAW_NAMES):
                normalised[new] = [None if pd.isna(v) else v for v in raw[old]]
            table = pa.Table.from_pydict(normalised, schema=SCHEMA)
            target = dest / f'part-{part:04d}.parquet'
            pq.write_table(table, target, compression='zstd', row_group_size=100_000)
            restored = pq.ParquetFile(target).read()
            if not table.equals(restored, check_metadata=True):
                raise ValueError(f'Parquet read-back mismatch: {target}')
            result['original_rows'] += n
            result['harmonised_rows'] += restored.num_rows
            print(f'{trace_id}: {result["harmonised_rows"]:,} rows written and read-back verified', flush=True)
        result['duplicates'] = count_duplicates(sort_paths)
        print(f'{trace_id}: exact duplicate check complete', flush=True)
    finally:
        if not tmp.resolve().is_relative_to(OUT.resolve()):
            raise RuntimeError('Temporary cleanup path escaped the script-owned output folder')
        shutil.rmtree(tmp)
    result['raw_missing'] = dict(missing)
    result['models'], result['log_types'] = dict(model_counts), dict(log_counts)
    result['zero_response_percent'] = 100 * result['zero_response_rows'] / result['original_rows']
    result['stats'] = {key: histogram_stats(hist) for key, hist in hists.items()}
    result['timestamp_span_days'] = (result['relative_timestamp_max_s'] - start) / 86400
    lo, hi = min(minute_counts), max(minute_counts)
    dense_minutes = np.zeros(hi - lo + 1, dtype=np.int64)
    for minute, count in minute_counts.items():
        dense_minutes[minute - lo] = count
    # The first and last minute may be partial; all other minutes are observed windows.
    inner = dense_minutes[1:-1]
    median = float(np.median(inner))
    threshold = 5 * median
    result['minute_rates'] = {'minutes_including_partial_edges': len(dense_minutes),
                             'complete_minutes': len(inner), 'zero_request_complete_minutes': int((inner == 0).sum()),
                             'median_requests_per_complete_minute': median,
                             'p95_requests_per_complete_minute': float(np.quantile(inner, .95)),
                             'p99_requests_per_complete_minute': float(np.quantile(inner, .99)),
                             'peak_requests_per_minute': int(dense_minutes.max()),
                             'spike_definition': 'Complete minute with request count > 5 times median complete-minute count; descriptive threshold.',
                             'spike_threshold_requests_per_minute': threshold,
                             'spike_complete_minutes': int((inner > threshold).sum())}
    # Exclude partial first/last hours, including their partly observed edge minutes.
    hours = np.arange(lo // 60 + 1, hi // 60, dtype=np.int64)
    hourly_counts = np.array([dense_minutes[max(0, int(h * 60 - lo)):int((h + 1) * 60 - lo)].sum() for h in hours], dtype=np.int64)
    lag_correlations = {}
    for lag in [1, 24, 168]:
        lag_correlations[f'lag_{lag}_hours'] = float(np.corrcoef(hourly_counts[:-lag], hourly_counts[lag:])[0, 1]) if len(hourly_counts) > lag + 2 else None
    hour_profile = [{'source_relative_hour_mod_24': hour,
                     'n_complete_hour_bins': int((hours % 24 == hour).sum()),
                     'median_requests_per_hour': float(np.median(hourly_counts[hours % 24 == hour])),
                     'p10_requests_per_hour': float(np.quantile(hourly_counts[hours % 24 == hour], .1)),
                     'p90_requests_per_hour': float(np.quantile(hourly_counts[hours % 24 == hour], .9))}
                    for hour in range(24)]
    result['hourly_pattern'] = {'complete_hour_bins': len(hours), 'lag_pearson_correlations': lag_correlations,
                              'hour_mod_24_profile': hour_profile,
                              'interpretation': 'Descriptive autocorrelation, not forecast validation; trends and changing request mix can contribute. Relative hour is not a UTC or calendar weekday claim.'}
    result['size_latency_by_model'] = {}
    for model, hist in size_latency_by_model.items():
        n, sx, sy, sxx, syy, sxy = model_moments[model]
        result['size_latency_by_model'][model] = {
            'rows': int(n),
            'input_tokens_elapsed_pearson_r': float((n * sxy - sx * sy) / np.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))),
            'bins': [{'input_token_lower_inclusive': int(edges_low), 'input_token_upper_exclusive': int(edges_high),
                      **histogram_stats(row)} for edges_low, edges_high, row in zip(input_edges[:-1], input_edges[1:], hist)]}
    if moments[0]:
        n, sx, sy, sxx, syy, sxy = moments
        result['input_tokens_elapsed_pearson_r'] = float((n * sxy - sx * sy) / np.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy)))
    result['filtered_variant'] = check_filtered(index, success_digest.hexdigest(), result['original_rows'] - result['zero_response_rows'])
    result['parquet_shards'] = len(list(dest.glob('*.parquet')))
    if result['original_rows'] != result['harmonised_rows']:
        raise ValueError('Row reconciliation failed')
    (REPORT / f'burstgpt-trace-{index}-quality.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result, hists, lo, dense_minutes, hourly_tokens, input_edges, latency_by_size, dict(latency_by_model), dict(size_latency_by_model)


def save_figure(fig, stem, caption):
    fig.text(.07, .025, caption, ha='left', va='bottom', fontsize=8, wrap=True)
    fig.savefig(FIGS / f'{stem}.png', dpi=220, bbox_inches='tight', facecolor='white')
    fig.savefig(FIGS / f'{stem}.pdf', bbox_inches='tight', facecolor='white')
    plt.close(fig)


def plots(traces):
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.titleweight': 'bold', 'grid.alpha': .2,
                         'pdf.fonttype': 42, 'savefig.facecolor': 'white'})
    colours = ['#176B87', '#D55E00', '#6B4C9A']
    total = sum(t[0]['original_rows'] for t in traces)
    fig, axs = plt.subplots(3, 1, figsize=(10.5, 8.8), sharex=False)
    for ax, t, colour in zip(axs, traces, colours):
        q, _, lo, counts, *_ = t
        minute_times = (np.arange(len(counts)) + lo) / 1440
        # Show every observed minute and a complete 60-minute moving average.
        ax.plot(minute_times, counts, color=colour, lw=.4, alpha=.65, label='Observed minute count')
        if len(counts) >= 60:
            smooth = np.convolve(counts, np.ones(60) / 60, mode='valid')
            ax.plot(minute_times[59:], smooth, color='#202020', lw=1.1, label='60-minute moving average')
        ax.set(title=f'{q["trace_id"]}: n = {q["original_rows"]:,}', ylabel='Requests / minute', xlabel='Source-relative day (no calendar origin supplied)')
        ax.grid(axis='y')
    axs[0].legend(frameon=False, loc='upper right', fontsize=8)
    fig.suptitle('BurstGPT traffic varies sharply within each observed trace', y=.99, fontsize=15)
    fig.subplots_adjust(hspace=.55, bottom=.12, top=.93)
    save_figure(fig, 'burstgpt_request_rates', f'Source: HPMLL/BurstGPT v2.0; n = {total:,} full-trace requests. Every one-minute bin is shown.\nZero bins are retained inside each observed span; separate panels preserve the unobserved gap between traces 2 and 3.')

    fig, axs = plt.subplots(1, 3, figsize=(12, 4.6), sharey=True)
    for ax, t in zip(axs, traces):
        q, hists, *_ = t
        for key, label, colour in [('input', 'Input tokens', '#176B87'), ('output', 'Output tokens', '#D55E00')]:
            hist = hists[key]
            x = np.flatnonzero(hist)
            ax.step(x, np.cumsum(hist)[x] / hist.sum(), where='post', label=label, color=colour, lw=1.5)
        ax.set_xscale('symlog', linthresh=1)
        ax.set(title=f'{q["trace_id"]}\nn = {q["original_rows"]:,}', xlabel='Tokens per request (symlog scale)', ylim=(0, 1.02))
        ax.grid()
    axs[0].set_ylabel('Cumulative fraction of requests')
    axs[0].legend(frameon=False, fontsize=8)
    fig.suptitle('Input and output lengths have distinct, skewed distributions', fontsize=14)
    fig.subplots_adjust(bottom=.23, top=.79, wspace=.15)
    save_figure(fig, 'burstgpt_token_distributions', f'Source: HPMLL/BurstGPT v2.0; n = {total:,} full-trace requests. Exact empirical cumulative distributions.\nToken counts are unitless; zero-token observations are retained. The linear segment around zero avoids dropping zero values.')

    q, hists, _, _, _, edges, size_latency, model_latency, size_models = traces[2]
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 5.4), gridspec_kw={'width_ratios': [1.45, 1]})
    y_edges = np.r_[np.arange(0, 21), np.arange(25, 101, 5), np.arange(125, 751, 25)]
    coarse = np.zeros((len(edges) - 1, len(y_edges) - 1), dtype=np.int64)
    for j in range(len(y_edges) - 1):
        coarse[:, j] = size_latency[:, int(y_edges[j]):int(y_edges[j + 1])].sum(axis=1)
    mesh = axs[0].pcolormesh(edges, y_edges, np.ma.masked_equal(coarse.T, 0), cmap='viridis', norm=LogNorm(vmin=1, vmax=max(2, coarse.max())), rasterized=True)
    axs[0].set_xscale('symlog', linthresh=1)
    axs[0].set_yscale('symlog', linthresh=1)
    axs[0].set(xlabel='Input tokens per request (symlog)', ylabel='Complete response latency (s; symlog)', title='All-data binned counts')
    fig.colorbar(mesh, ax=axs[0], label='Requests per two-dimensional bin', pad=.02)
    centres = np.where(edges[:-1] == 0, 0, np.sqrt(np.maximum(edges[:-1], 1) * edges[1:]))
    bins_n = size_latency.sum(axis=1)
    eligible = bins_n >= 100
    for p, label, colour in [(.5, 'Median', '#176B87'), (.95, 'P95', '#D55E00'), (.99, 'P99', '#6B4C9A')]:
        ys = np.array([percentile(hist, p) if n else np.nan for hist, n in zip(size_latency, bins_n)], dtype=float)
        axs[1].plot(centres[eligible], ys[eligible], marker='o', ms=3, lw=1.3, label=label, color=colour)
    axs[1].set_xscale('symlog', linthresh=1)
    axs[1].set(xlabel='Input tokens per request (symlog scale)', ylabel='Complete response latency (s)', title='Exact quantiles within size bins')
    axs[1].grid()
    axs[1].legend(frameon=False)
    fig.suptitle('Request length alone does not determine observed completion latency', fontsize=14)
    fig.subplots_adjust(bottom=.27, top=.82, wspace=.36)
    save_figure(fig, 'burstgpt_size_latency', f'Source: HPMLL/BurstGPT v2.0, trace 3; n = {q["original_rows"]:,} requests, no sampling. Latency is end-to-end, not TTFT.\nCounts use geometric input bins and stated latency bins; quantile lines require at least 100 requests per input bin.\nZero latencies are retained ({q["raw_zero_elapsed_rows"]:,}); missing latency in traces 1 and 2 is excluded, never changed to zero.')

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    for (model, hist), colour in zip(sorted(model_latency.items()), colours):
        x = np.flatnonzero(hist)
        ax.step(x, np.cumsum(hist)[x] / hist.sum(), where='post', label=f'{model}: n = {hist.sum():,}', lw=1.7, color=colour)
    ax.set_xscale('symlog', linthresh=1)
    ax.set(xlabel='Complete response latency (s; symlog scale)', ylabel='Cumulative fraction of requests', ylim=(0, 1.02), title='BurstGPT trace 3: observed completion latency by model')
    ax.legend(frameon=False)
    ax.grid()
    fig.subplots_adjust(bottom=.24)
    save_figure(fig, 'burstgpt_latency_distribution', f'Source: HPMLL/BurstGPT v2.0, trace 3; n = {q["original_rows"]:,} requests. Exact empirical cumulative distributions.\nInteger-second elapsed times include zero. Model differences are descriptive and do not isolate hardware or request-mix effects.')

    fig, axs = plt.subplots(1, len(size_models), figsize=(11, 5.2), sharey=True, squeeze=False)
    for ax, (model, hist) in zip(axs[0], sorted(size_models.items())):
        bin_counts = hist.sum(axis=1)
        eligible = bin_counts >= 100
        for p, label, colour in [(.5, 'Median', '#176B87'), (.95, 'P95', '#D55E00'), (.99, 'P99', '#6B4C9A')]:
            ys = np.array([percentile(row, p) if n else np.nan for row, n in zip(hist, bin_counts)], dtype=float)
            ax.plot(centres[eligible], ys[eligible], 'o-', ms=3, lw=1.2, color=colour, label=label)
        ax.set_xscale('symlog', linthresh=1)
        ax.set(title=f'{model}: n = {hist.sum():,}', xlabel='Input tokens per request (symlog scale)')
        ax.grid()
    axs[0, 0].set_ylabel('Complete response latency (s)')
    axs[0, 0].legend(frameon=False)
    fig.suptitle('Size and latency relationship within each LLM model', fontsize=14)
    fig.subplots_adjust(bottom=.25, top=.82, wspace=.15)
    save_figure(fig, 'burstgpt_size_latency_by_model', f'Source: HPMLL/BurstGPT v2.0, trace 3; n = {q["original_rows"]:,} requests, no sampling. Exact within-bin quantiles.\nEach line includes bins with at least 100 requests for that model. Zero latencies remain; hardware and service conditions are unknown.\nStratification separates the model categories but does not remove other confounding factors.')

    fig, axs = plt.subplots(1, 3, figsize=(12, 4.8), sharex=True, sharey=False)
    for ax, t, colour in zip(axs, traces, colours):
        tq = t[0]
        profile = tq['hourly_pattern']['hour_mod_24_profile']
        hour = np.arange(24)
        ax.fill_between(hour, [r['p10_requests_per_hour'] for r in profile], [r['p90_requests_per_hour'] for r in profile], color=colour, alpha=.2, label='P10 to P90')
        ax.plot(hour, [r['median_requests_per_hour'] for r in profile], color=colour, lw=1.7, label='Median')
        ax.set(title=f'{tq["trace_id"]}: n = {tq["hourly_pattern"]["complete_hour_bins"]:,} hours', xlabel='Source-relative hour modulo 24', xticks=[0, 6, 12, 18, 23])
        ax.grid()
    axs[0].set_ylabel('Requests per complete hour')
    axs[0].legend(frameon=False, fontsize=8)
    fig.suptitle('Daily demand profiles vary across BurstGPT observation windows', fontsize=14)
    fig.subplots_adjust(bottom=.24, top=.81, wspace=.25)
    save_figure(fig, 'burstgpt_daily_profiles', f'Source: HPMLL/BurstGPT v2.0; n = {total:,} full-trace requests before partial-hour exclusion. All complete hours are used.\nMedian and P10/P90 bands group hours by original relative timestamp modulo 24; no UTC time or calendar weekday is inferred.')


def write_reports(traces):
    qualities = [t[0] for t in traces]
    total = sum(q['original_rows'] for q in qualities)
    variants = sum(q['filtered_variant']['rows'] for q in qualities)
    summary = {'source': SOURCE, 'release': 'v2.0', 'canonical_rows': total,
               'source_rows_including_derived_filtered_variants': total + variants,
               'filtered_variant_rows_not_repeated_in_parquet': variants,
               'harmonised_rows': sum(q['harmonised_rows'] for q in qualities),
               'traces': qualities, 'schema': str(SCHEMA),
               'calendar_time_available': False, 'cross_dataset_record_join': False,
               'licence': 'CC-BY-4.0',
               'origin_and_gaps': 'relative_timestamp_s preserves original Timestamp. trace_local_timestamp_s subtracts first request of its own trace only. Calendar dates/time zone are unknown. Trace 3 is not shifted to immediately follow trace 2.'}
    (REPORT / 'burstgpt-quality.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    schema_records = [{'name': field.name, 'arrow_type': str(field.type), 'nullable': field.nullable} for field in SCHEMA]
    (REPORT / 'burstgpt-schema.json').write_text(json.dumps(schema_records, indent=2) + '\n', encoding='utf-8')
    dictionary = '''# BurstGPT harmonised data dictionary

Canonical tables: `harmonized/burstgpt/burstgpt_1/`, `burstgpt_2/`, `burstgpt_3/`. Each contains bounded-size Parquet shards with one request per row. No request is discarded or imputed.

| Field | Type / unit | Meaning |
| --- | --- | --- |
| source_dataset | string | `burstgpt`. |
| source_file | string | Original full-trace CSV filename. |
| source_row_id | int64 | One-based data-row position, excluding header. Unique with source_file. |
| trace_id | string | File-local trace identifier. |
| relative_timestamp_s | float64, seconds | Original Timestamp parsed numerically. Relative source origin is unknown as a calendar date. |
| trace_local_timestamp_s | float64, seconds | Original timestamp minus the first request timestamp of that trace. Never used to join traces. |
| calendar_timestamp_utc | timestamp UTC, nullable | Always null because the release does not establish a reliable absolute origin. |
| input_tokens / output_tokens / total_tokens | int64, token count | Parsed original request / response / total tokens. Zero is preserved. |
| elapsed_time_s | float64, seconds, nullable | Submission to complete final response. Null for traces 1 and 2; not TTFT. Zero is retained for trace 3. |
| llm_model | string | Original model category, ChatGPT or GPT-4. Not a GPU model. |
| log_type | string | Original API log or Conversation log. |
| session_id | string, nullable | Original nonempty session ID, available only for conversation rows in trace 3. |
| gpu_model | string, nullable | Always null: physical GPU is unobserved. |
| zero_response_tokens | bool | Response token count equals zero. Publisher calls these failures; cause is unavailable. |
| raw_timestamp / raw_session_id / raw_elapsed_time / raw_model / raw_request_tokens / raw_response_tokens / raw_total_tokens / raw_log_type | string, nullable | Exact parsed CSV field strings before numeric conversion. Absent columns are null; present empty fields remain empty strings. |

Missing and absent fields remain null in normalised columns; raw fields distinguish absent columns from present empty values. Token totals are checked; no correction is applied. No GPU identifier, price, utilisation, power, deadline or TTFT is invented. No calendar, weekday or cross-source identity join is possible from these fields.

The success-only release files are derived views, not additional independent requests. All six files are read. Exact ordered canonical hashes verify each success-only file against its full trace with zero-response rows removed. Their counts and source filenames are in quality reports. Filter them from canonical Parquet with `zero_response_tokens == false`.

Exact identical raw tuples are counted within each trace with external merge sort. They are retained because identical timestamp/token/model records can still represent separate real requests. Source row IDs preserve distinct observations. Cross-trace duplicate identity is not established.

Licence: CC-BY-4.0. Preserve source attribution, `data/burstgpt/LICENSE`, `CITATION.cff` and the BurstGPT paper citation. Source: https://github.com/HPMLL/BurstGPT ; release: https://github.com/HPMLL/BurstGPT/releases/tag/v2.0 .
'''
    (REPORT / 'burstgpt-dictionary.md').write_text(dictionary, encoding='utf-8')
    lines = ['# BurstGPT Phase 1 findings', '',
             f'**Verified:** all six release CSVs were read ({total + variants:,} stored rows). Canonical full traces yield {total:,} Parquet rows. The {variants:,} filtered-variant rows match ordered success-only subsets exactly and are not emitted a second time.', '',
             '| Trace | Full rows | Zero response rows (%) | Span (days) | Input P50 / P95 / P99 (tokens) | Output P50 / P95 / P99 (tokens) | Extra identical raw rows |',
             '| --- | ---: | ---: | ---: | --- | --- | ---: |']
    for q in qualities:
        a, b = q['stats']['input'], q['stats']['output']
        lines.append(f'| {q["trace_id"]} | {q["original_rows"]:,} | {q["zero_response_rows"]:,} ({q["zero_response_percent"]:.4f}%) | {q["timestamp_span_days"]:.3f} | {a["p50"]:,} / {a["p95"]:,} / {a["p99"]:,} | {b["p50"]:,} / {b["p95"]:,} / {b["p99"]:,} | {q["duplicates"]["extra_identical_raw_rows"]:,} |')
    lines += ['', '## Arrival variation', '']
    for q in qualities:
        m = q['minute_rates']
        lines.append(f'- **Measured, {q["trace_id"]}:** complete-minute median {m["median_requests_per_complete_minute"]:g}, P95 {m["p95_requests_per_complete_minute"]:g}, P99 {m["p99_requests_per_complete_minute"]:g} requests/min; peak {m["peak_requests_per_minute"]:,}. Of {m["complete_minutes"]:,} complete minutes, {m["zero_request_complete_minutes"]:,} have zero requests. {m["spike_complete_minutes"]:,} exceed the descriptive threshold of five times the median ({m["spike_threshold_requests_per_minute"]:g} requests/min).')
        lag = q['hourly_pattern']['lag_pearson_correlations']
        lines.append(f'  Hourly lag correlations: 1 hour {lag["lag_1_hours"]:.3f}; 24 hours {lag["lag_24_hours"]:.3f}; 168 hours {lag["lag_168_hours"]:.3f}. These are descriptive serial associations; trends and changing request mix can contribute. They do not establish out-of-sample predictability.')
    q = qualities[2]
    e = q['stats']['elapsed']
    lines += ['', 'A zero minute means no record within that observed trace window, not proof of idle GPU capacity. First and last minute bins can be partial; quiet/spike counts exclude them. The gap between trace 2 and trace 3 is unobserved and is not filled with zero-demand records. Relative days do not identify calendar weekdays. Arrival spikes alone do not establish predictability or a successful scheduling policy.', '',
              '## Completion latency and size', '',
              f'**Measured:** traces 1 and 2 have no elapsed-time column. Trace 3 has {e["n"]:,} values: median {e["p50"]} s, P90 {e["p90"]} s, P95 {e["p95"]} s, P99 {e["p99"]} s; maximum {e["max"]} s. {q["raw_zero_elapsed_rows"]:,} values ({100*q["raw_zero_elapsed_rows"]/q["original_rows"]:.2f}%) are zero. Pearson correlation between input tokens and recorded elapsed time is {q["input_tokens_elapsed_pearson_r"]:.4f}, using all trace-3 rows, including zero latencies and zero-response rows. The relationship is descriptive and can reflect request mix, service conditions or measurement resolution; it is not causal.', '',
              'The size-versus-latency figures use all rows and show exact P50/P95/P99 within geometric input-size bins, both pooled and stratified by LLM model. Bins with fewer than 100 requests are excluded from quantile lines but retained in pooled count plots. Model-stratified counts, bin quantiles and correlations are in the quality report. Stratification does not control unknown hardware or service conditions. Latency is request-to-complete-response time, not time to first token. Integer-second values and frequent zeros prevent precise subsecond calibration.', '',
              '## Quality, provenance and interpretation', '',
              'Every Parquet shard was read back and compared with the in-memory Arrow table, including schema metadata. Row counts reconcile. All six files have nondecreasing timestamps; all token totals equal input plus output tokens. Missing raw values and absent fields are counted by trace in `burstgpt-quality.json`. Exact repeated raw tuples are retained with separate source row IDs, because they cannot reliably be classified as ingestion duplicates. The success-only variants are verified derived subsets and must not be concatenated into the canonical request table.', '',
              '**Inference for scheduling:** the changing arrival rates and skewed token demand support replay experiments for queues, admission, batching and autoscaling. The model and log categories permit workload-specific descriptions. Such experiments require explicit hardware throughput, cost and SLO assumptions from other evidence. Observed final output lengths are unavailable at admission and must not serve as an oracle scheduling input.', '',
              '**Unanswerable from this source:** GPU placement, thermal behaviour, energy, cloud cost, hardware service rates, pre-emption effects, failure causes and policy improvements. No physical GPU identifier, explicit deadline or target SLO exists. No unrelated Alibaba, thermal or cloud-price record is treated as the same request or device.', '',
              'Licence: CC-BY-4.0. Keep source attribution and the supplied licence/citation. Source and field definitions: [BurstGPT](https://github.com/HPMLL/BurstGPT), [v2.0 release](https://github.com/HPMLL/BurstGPT/releases/tag/v2.0).', '',
              'Reproduce: `python scripts/phase1/burstgpt.py`. Dependencies load from `.deps` when present. Outputs: per-trace Parquet shards, quality/schema JSON, this report, dictionary and six PNG/PDF figures. No model or simulator is created.', '']
    (REPORT / 'burstgpt-report.md').write_text('\n'.join(lines), encoding='utf-8')


def load_plot_aggregates():
    """Rebuild figure aggregates from canonical Parquet without rewriting tables."""
    traces = []
    for index in range(1, 4):
        quality = json.loads((REPORT / f'burstgpt-trace-{index}-quality.json').read_text(encoding='utf-8'))
        hists = {key: np.zeros(1, dtype=np.int64) for key in ['input', 'output', 'total', 'elapsed']}
        minutes, hours = collections.Counter(), collections.Counter()
        edges = np.unique(np.r_[0, 1, np.geomspace(2, 150_000, 33).astype(int)])
        size_latency = np.zeros((len(edges) - 1, 1001), dtype=np.int64)
        model_latency = collections.defaultdict(lambda: np.zeros(1001, dtype=np.int64))
        size_models = collections.defaultdict(lambda: np.zeros_like(size_latency))
        for path in sorted((OUT / f'burstgpt_{index}').glob('part-*.parquet')):
            frame = pq.ParquetFile(path).read(columns=['relative_timestamp_s', 'input_tokens', 'output_tokens', 'total_tokens', 'elapsed_time_s', 'llm_model']).to_pandas()
            timestamp = frame['relative_timestamp_s'].to_numpy()
            values, counts = np.unique((timestamp // 60).astype(np.int64), return_counts=True)
            minutes.update(dict(zip(values.tolist(), counts.tolist())))
            for key, column in [('input', 'input_tokens'), ('output', 'output_tokens'), ('total', 'total_tokens')]:
                hists[key] = pad_hist(hists[key], frame[column].to_numpy(dtype=np.int64))
            if index == 3:
                elapsed = frame['elapsed_time_s'].to_numpy(dtype=np.int64)
                hists['elapsed'] = pad_hist(hists['elapsed'], elapsed)
                bins = np.searchsorted(edges, frame['input_tokens'].to_numpy(), side='right') - 1
                np.add.at(size_latency, (bins, elapsed), 1)
                for model in frame['llm_model'].unique():
                    mask = frame['llm_model'].to_numpy() == model
                    model_latency[model] += np.bincount(elapsed[mask], minlength=1001)
                    np.add.at(size_models[model], (bins[mask], elapsed[mask]), 1)
        lo, hi = min(minutes), max(minutes)
        dense = np.zeros(hi - lo + 1, dtype=np.int64)
        for minute, count in minutes.items():
            dense[minute - lo] = count
        traces.append((quality, hists, lo, dense, hours, edges, size_latency, dict(model_latency), dict(size_models)))
    return traces


def main():
    for path in [OUT, REPORT, FIGS]:
        path.mkdir(parents=True, exist_ok=True)
    if '--plots-only' in sys.argv:
        plots(load_plot_aggregates())
        print('BurstGPT figures regenerated from all canonical Parquet rows.', flush=True)
        return
    traces = []
    for index in range(1, 4):
        traces.append(process_trace(index))
    plots(traces)
    write_reports(traces)
    print('BurstGPT Phase 1 complete: Parquet, six PNG/PDF figures and validation reports.', flush=True)


if __name__ == '__main__':
    main()
