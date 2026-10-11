# Production XO And Route Admission

## Decision

The empty-segment candidate now has a **production XO with the frozen K4
adapter ABI**, compiled without the C/RTL test-only interface depths. It is
not routed, has no new board measurements, and does not establish original
A4 performance matching. The simulator and frozen SST plugin are unchanged.

Read the [paired RTL study](../README.md) for the optimization and packet
equivalence, then [current-v2/results.json](current-v2/results.json) for the
production compile. Local RTL speedup is not whole-system FPGA speedup.

| Gate | Result |
| --- | --- |
| Source-bound prerequisites | Twelve C++ configurations and paired thirteen-call C/RTL controls rechecked |
| Production compile | Vitis 2024.1, U55C, requested 150 MHz; passed in 52.69 seconds |
| ABI | Same ports, arguments, widths and control protocol as the frozen routed adapter XO |
| Effective flags | Weighted, sharded, shared-memory, row-prefetch, stop-after-last and skip-empty-segment; all enabled |
| Test-only depth define | Absent |
| HLS resources | 15 BRAM_18K, 12,314 FF, 17,473 LUT; DSP and URAM zero |
| HLS clock estimate | 4.867 ns; not routed timing |
| Compile sampled tree peak | 1,726,168 KiB; minimum available host memory 50.44 GiB |
| Route preparation | Eleven original XOs, only the adapter replaced; same connectivity and requested clock |
| Route execution | Not started: memory admission refused |
| Board/model/A4 timing admission | Pending |

The candidate XO SHA-256 is
`4bae8791463a71f8b02ccad870d0178b2268cea8cfa6173c480e8a596a24417a`.
Its HLS source remains default-off in the integration repository; the
production compile explicitly enables the candidate.

## Evidence Layout

| Directory | What it preserves |
| --- | --- |
| [prior-v1](prior-v1/verification.json) | First successful production compilation; its dependency closure was incomplete |
| [current-v2](current-v2/verification.json) | Recompiled candidate with the prerequisite raw inputs and validation dependencies pinned before execution |
| [route-preparation](route-preparation/verification.json) | Exact prepared command/configuration, original XO identities and recorded memory non-start |
| [checks](checks/verification.json) | 327-test Python regression, sampled execution resources and reviewed owner snapshots |
| [environment-admission](environment-admission/README.md) | Subsequent explicit environment/compatibility preflight; fresh route-v2 remains memory-refused, not routed |

The v1 record is not silently replaced. Its ABI and compile checks passed,
but some validation code and prerequisite raw inputs were not included in
its pre-execution dependency closure. V2 closes that provenance gap and is
the candidate selected for future route. It does not imply that v1 computed
wrong packets. Different compiled XO hashes alone are not packet inequality.

Both compile archives contain source snapshots, the candidate XO, generated
Verilog, synthesis/burst reports, compiler logs, functional-gate package and
inner/outer watchdog records. The vendor compiler and platform are hash
indexed rather than bundled. Original non-adapter route XOs are likewise
indexed in the preparation archive, not duplicated here.

The production checks bind the current HLS source to the frozen functional
and paired-RTL gates, reject changed interfaces and ambiguous/unknown GRASU
defines, and recheck all pinned inputs after compilation. Historical archive
verification uses each run's snapshots. Fresh route preparation additionally
requires the production run's pinned current inputs to remain unchanged.

## Why Route Did Not Start

The retained preparation observed **51.56 GiB available**. Its predeclared
budget is a **40-GiB sampled process-tree limit plus a 16-GiB host reserve**,
requiring at least 56 GiB before starting. Thus its status is
`ADMISSION_REJECTED_NOT_STARTED`, not a Vivado failure or a routed candidate.
There is no xclbin or route-timing result from this attempt.

Do not reduce the reserve to turn this non-start into a pass, or overwrite
its admission record. Use a fresh preparation when resources permit. Keep
Vivado synthesis and implementation jobs at two each. The live watchdog
also stops on reserve pressure, tree-budget excess or the four-hour timeout.
Sampled pidfd accounting/cleanup is not cgroup containment.

## Reproduction

From the simulator root, use fresh output paths and the prerequisite raw
runs. The recorded local root is
`/data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/`.

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production \
  --integration /home/chuxiao/grasu-regraph-integration \
  --paired /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/paired-v2 \
  --functional /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/functional-v4 \
  --reference /data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806/build/pma_to_regraph_adapter.hw.xo \
  --output results/empty-segment-production-fresh

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production_delivery \
  --run results/empty-segment-production-fresh \
  --destination results/empty-segment-production-package-fresh
```

The compile owner uses an eight-GiB inner tree budget and 1,200-second
timeout, a ten-GiB outer budget and 1,350-second timeout, and the same
sixteen-GiB live reserve. Source changes require fresh gates/builds; do not
edit a frozen manifest to make a new checkout satisfy it.

The earlier `empty_segment.route_execution` fixes execution exit statuses
but still inherits an unchecked caller environment. For future attempts use
`empty_segment.route_environment`; its [subsequent checkpoint](environment-admission/README.md)
passes explicit vendor-settings and GCC compatibility smoke checks while
retaining the same refused memory budget. The older entry points and
production-v2 owner snapshots remain unchanged for historical evidence.
Neither preflight nor preparation admits routed timing.

## Verification Scope

All 327 selected Python tests passed, covering original ReGraph controls,
sharded K4, the portable archives, route failure handling, artifact transport
and repository structure. The bounded regression took 64.74 seconds, peaked
at 2,054,816 KiB sampled tree RSS and retained at least 49.58 GiB available.
Its raw logs, watchdog records and owner snapshots are in `checks/`.

The numerical C++ sources and default SST plugin were not changed. The
earlier 28-test C++ gate is retained, not reported as rerun at this Python-only
checkpoint. Neither these tests nor a successful XO compilation admits new
FPGA timing or A4 performance matching.

## Remaining Acceptance

1. Route the single-XO replacement and check final clock, resources and
   connectivity, without changing the frozen candidate or other ten XOs.
2. Run alternating old/new resident board tests, admitting complete outputs,
   rounds and event dependencies before interpreting timing.
3. Represent the new helper behavior in an explicitly separate model
   candidate, retaining exact legacy outputs and conserved traffic. A
   sensitivity prediction is not new FPGA timing calibration.
4. Compare original A4 with the actual optimized adapter plus modified K4
   under documented arithmetic, state, round/convergence, resource and
   timing conditions. Do not attribute every difference solely to adapter
   cost or claim original-paper matching from this compile checkpoint.
