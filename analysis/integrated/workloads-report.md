# Unified workload layer

Verified: all466,867 Alibaba jobs and10,632,194 canonical BurstGPT requests are represented once in an identical common schema, for11,099,061 records. Original source strings are retained in separate nullable structs, alongside source table/row references. Different clocks, workload types, job duration and completion latency remain explicitly distinct.

The source-scoped arrival graph shows bursts and changing traffic volumes without assuming simultaneous operation. The time-quantity graph deliberately separates Alibaba job duration from BurstGPT completion latency. Missing GPU identity and resource demand for inference remain null, so the common interface does not invent GPU-hours per token or a placement target. Hardware/cost scenarios require separately declared assumptions rather than a record-level join.

No original harmonised tables changed. All output files were read back and compared with their constructed Arrow tables; counts and hourly aggregates reconcile. No ML/RL model, scheduler, simulator or frontend was built.
