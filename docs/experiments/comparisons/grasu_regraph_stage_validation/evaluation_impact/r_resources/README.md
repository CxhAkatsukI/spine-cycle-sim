# R Resource Accounting

## Finding

Original A4 constructs **13 distinct AXI masters on 9 physical HBM banks**,
not 13 endpoints sharing 9 masters. Both K4 arms register 9 masters. The old
summary conflated physical banks with master instances; the preceding raw
cycle reports and model code have not been rewritten.

The [evidence capsule](evidence/index.json) comes from a fresh Release build
and constructor-only audit. No round is started and no request is issued.
It is an executable resource inventory, not another performance measurement.

| Resource | Original compact A4 | Cross-row / bank-stream K4 |
| --- | --- | --- |
| Distinct registered masters | 13 | 9 |
| Input organization | 4 edge + 4 source masters | 4 adapter + 4 source masters |
| Remaining masters | 1 apply-read + 4 write masters | 1 shared apply master; source writes also share source masters |
| Physical source-state banks | 1, 3, 5, 7 | 23, 24 |
| Graph placement | Edge banks 0, 2, 4, 6 | Runtime plan within 23 graph banks; adapter target varies per request |
| Parent credits per master | 2 | 16 declared |
| Burst credits per master | 16 | 16 declared |
| Apply request window | 2 | 16 declared |
| Clock | 150 MHz | 150 MHz |

The audit introspects actual A4 `AxiMaster::config()` objects and checks them
against backend registrations. For K4 it observes actual backend registrations
and runtime-plan regions, but reports private port configuration as **declared
input**, not independently introspected values. The constructor wiring is in
`cpp/src/routed_regraph/composition.cpp`. No production introspection API was
added solely for this study.

The K4 placement fixture has four destination shards, one edge per shard,
196,610 logical vertices and 262,144 padded vertices. It instantiates the same
port construction and candidate configuration as the earlier convergence
control, but is not that Amazon workload or a traffic-occupancy experiment.
Do not infer active bandwidth from allocated regions or registered masters.

## Consequence

The earlier Amazon warm-SSSP candidate/A4 ratios (1.0462 at latency 64 and
0.9687 at latency 128) remain the results of their recorded configurations.
They do **not** establish strict resource equivalence. The credit asymmetry,
different source banks, state replicas and adapter buffers require explicit
controls and hardware feasibility checks before baseline promotion. More
masters does not automatically imply greater effective bandwidth, just as
four frontends does not automatically mean equal resources.

Next R timing control: retain original A4 unchanged, add separately labeled
credit/window sensitivity arms, check complete convergence/state/traffic and
report the full matrix. Do not silently upgrade A4 or reduce K4 credits and
call the result the preceding control. Original mixed-topology publication
reproduction and the actual G-to-R handoff remain separate gates.

## Reproduction

From the simulator repository root:

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2G \
  -p MemorySwapMax=0 python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.r_resources.study \
  --output /path/to/fresh-r-resource-run

python3 -m spine_cycle_sim.experiments.evaluation_impact.r_resources.delivery \
  --run /path/to/fresh-r-resource-run --output /path/to/fresh-evidence

python3 -m unittest tests.test_regraph_resource_audit -v
```

Every compiler/audit child is capped at 2 GiB address space, requires an
additional 8 GiB available-memory reserve and has a timeout. Compilation is
serial. The audit process is pinned to CPU 127 in this run. Build peak process
RSS was 459,052 KiB and audit peak was 30,328 KiB; these are per-process peaks,
not a measured simultaneous tree maximum. The first shell invocation used
`python`, which is unavailable on this machine; no experiment started until
the corrected `python3` invocation.

The capsule contains `report.json`, frozen source, raw logs/resource records
and their hashes. The report additionally pins compiler commands, Release
cache, binary and static libraries in the indexed `/data` run. No production
core/SST numerical code, paper source, figure package or historical report
is changed. The finite-search HLS and hardware-route queues keep their
existing admission guards; this small audit does not lower those thresholds.

Verification: the fresh C++ audit and 45 focused Python tests pass, along
with document-layout, catalog and whitespace checks. The first capsule test
incorrectly matched every nested `CMakeLists.txt` by suffix; it now resolves
the exact archived path against the recorded repository root. No evidence
was changed to resolve that test. This checkpoint does not claim a new full
core/SST regression, stage calibration or HLS/RTL result.
