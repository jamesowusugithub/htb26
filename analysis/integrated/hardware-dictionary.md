# Hardware relationship dictionary

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
