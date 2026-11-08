# Pricing data dictionary

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
