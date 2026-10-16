# Resident Metadata Refresh

## Decision

At the 2026-10-16 09:30 UTC checkpoint, the host preflight is queued under
finite memory admission. Thirteen focused
Python tests pass, including strict transcript/resource replay and malformed
generation, DMA, timing and state rejection. **C++ compilation, the actual
host-model executions and device refresh have not yet passed.** Queueing or
parser tests are not FPGA measurements, integrated RTL or baseline admission.

The distinct package reuses the existing XRT session, G kernel bindings,
physical-state helpers and native five-shard fixture without changing them.
It does not alter any pinned route, earlier attempt, paper or figure.

## Test Contract

- 262148 vertices, five 65536-vertex destination shards; shards 0 and 4 have
  edges and shards 1--3 are empty. Both cache halves retain 131072 segments.
- Each generation runs an empty batch, twelve deletions and twelve exact
  reinsertions. Initial and restored logical edge counts are 524296; after
  deletion the count is 524284. Every nonempty batch covers all hot/cold ports,
  with aggregate port counts 4/2/4/2.
- Before generation one, verify the entire PMA has returned to its initial
  words through updates, not a host PMA reset. Swap directory rows for source
  pairs 0--3 and 262144--262147 and rewrite their binary metadata. Identical
  initial adjacency makes this remap preserve the logical graph.
- The six updated sources deliberately do not form complete swapped pairs.
  Retaining the old directory must therefore change physical output; the
  CPU negative must stop at generation one, batch one with a complete-PMA
  mismatch. A different exception or failed transaction is not accepted.
- The unexecuted device path writes row/binary data into the same OpenCL BOs
  and checks those handles across all six batches. It checks complete PMA,
  padding and metadata after every batch against an independent external-ID
  edge-set oracle. It does not claim to query raw physical HBM addresses.

This is a synthetic directory-lifecycle test. Its fixed reservation supplies
capacity; reinsertion restores weight 7 rather than replaying the earlier
weight-3 future trace. It is not real-trace capacity growth, production rebin
policy, ReGraph computation, convergence or an original-G speed comparison.
The negative uses the CPU physical-update reference, not measured FPGA stale
cache behavior.

Each populated source has one segment in this fixture. Its production search
can choose that segment directly from row bounds, without a binary-head
lookup. A later board pass would validate changed row-directory consumption
and binary-buffer DMA/readback, **not multi-segment binary-search refresh**.
That additional test and integrated finite-stream RTL remain separate gates.

## Timing And Safety

Metadata preparation and metadata DMA have separate windows. Per-batch G
ready time includes packing, update DMA and launch/wait to the publication
barrier. Setup, independent oracle, verification readback and report formatting
are diagnostic costs, not silently mixed into kernel time. A future device
transcript must contain all ten metadata writes, 300 kernel/barrier events
and 32 update-DMA events; host-only output must contain no device event times.

The preflight has a 2-GiB hard cap, at most 1536-MiB high watermark, zero swap,
group OOM kill and 300-second child deadlines. Admission requires its complete
2-GiB budget, every peer compiler's full finite cap and a 24-GiB reserve.
Unknown/unbounded peers reject admission. Other FPGA tools need not exit if
these budgets fit. Atomic leases and live guards remain active during execution.

Current raw attempt:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-metadata-refresh-host-v1`.
Service: `spine-g-metadata-refresh-host-20261016-v1.service`; invocation
`0810335b222341daacedce97c4be33c2`. The service has a finite 25-hour lifetime,
including at most 24 hours waiting for memory. Raw inputs, compiler/dependency
hashes, outputs and resources remain in that attempt; it is not yet a portable
evidence capsule.

```bash
python3 -m unittest discover -s tests -p 'test_g_metadata_refresh*.py'
systemctl --user show spine-g-metadata-refresh-host-20261016-v1.service \
  -p ActiveState -p SubState -p MemoryCurrent -p MemoryMax -p InvocationID
jq '{status,errors,admission,steps}' \
  /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-metadata-refresh-host-v1/results.json
```

The bounded runner is
`python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_refresh.study`.
Supply a new `--output`, production `--integration`, installed `--xrt` and a
finite `--wait-seconds`. Do not invoke it outside the required cgroup. Only
after raw host evidence passes may its compiled board path be considered for
an exclusively leased, identity-checked device and the correct reviewed route.
The [production route](../production_routing/README.md) and the
[older diagnostic route](../hardware/README.md) remain different artifacts.
