# Cross-source hardware relationships

Verified: 26 named GPU identifiers, 22 origin-to-price rows and 104 model-to-thermal-session links.
Alibaba's A100-SXM4-80GB has generic A100 family price candidates only, not a confirmed exact variant match. Other Alibaba models have no supported cloud price match in these sources. Do not use candidate prices as measured job costs.
Thermal H100 and B200 have exact model-label pricing records; RTX3060 has no price match. H100 memory/interconnect variants remain distinct. No link establishes physical-device identity or full functional compatibility.

All 11,923,254 thermal GPU readings were used. They produce 45 workload/model/load-band profiles with observed P50/P90/P95/P99 temperature and power, valid counts and distinct session counts. These are experimental load associations, not measured effects of a scheduling policy.
Figures: `hardware_link_coverage` makes missing links visible; `hardware_thermal_load_profiles` compares recorded temperature and power across utilisation bands while preserving hardware and workload strata. Sources and counts are stated on each figure.
Raw timestamps are not aligned across datasets. Static Alibaba catalogue capacity does not describe maintenance, reservations or available GPUs over time. Additional performance and resource-compatibility evidence is needed before hardware substitution decisions.
