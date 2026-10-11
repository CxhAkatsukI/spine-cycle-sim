# Routed SSSP SST Checkpoint

## Decision

**Complete SSSP results and traffic pass; hardware timing does not pass.**
This is an explicitly selected SST implementation of the measured sharded-K4
compute topology. It is not a replacement for the frozen v8 default, a
publication-speed match, or the final A4-versus-integrated-K4 comparison.

Read [sst.json](sst.json) for the complete six-row report and
[sst_raw_index.json](sst_raw_index.json) for the file hashes inside
[raw_sst.tar.gz](raw_sst.tar.gz). These three files are frozen. Earlier
[system](../system/README.md) and [board](../../adapter_optimization/BOARD_RESULTS.md)
evidence remains separate and unchanged.

## What Was Connected

The new `spine_cycle.RoutedReGraphProbe` selects `RoutedReGraphSystem`, with
four adapter/Scatter/Gather frontends, an ordered shared mux/merger/Apply,
two source-state replicas, finite stream buffers, shared AXI clients and
DRAMSim3. The measured SSSP wrapper has **four dedicated source-read masters**.
The later worktree's two pairwise source services are a different target;
see the [binary-source audit](../frontend/README.md).

The profile is
`configs/architectures/grasu_regraph_routed_sssp_compute_v1.json`.
Original and candidate arms select `(row_prefetch, stop_after_last)` of
`(0, 0)` and `(1, 1)`, respectively. Both use exactly the same resident fixture.
No timing multiplier or fitted correction was introduced.

The fixture exporter uses the owning HLS graph builder and checked PMA update
reference. It preserves row offsets, reserved slots, destination sharding,
vertex mapping and touched-segment updates; it does not rebuild a compact
post-update edge array. The old distances and update-source active set are
resident before compute starts. An independent synchronous oracle confirms
the exported old state within the hardware host's 256-round limit:

| Graph | Vertices | Shards | PMA slots | Final edges | Old-state cold rounds | New resident rounds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AU | 515,281 | 8 | 1,843,296 | 390,855 | 15 | 2 |
| SU | 567,316 | 9 | 2,625,456 | 616,126 | 15 | 2 |
| WK | 1,140,149 | 18 | 2,727,664 | 1,142,360 | 2 | 1 |

All six runs pass complete external result-byte equality against their
matching FPGA run, the final padded-state oracle, source-replica equality,
round-count and graph-geometry checks. Conservation checks cover PMA
segments/slots, live and dummy edges, packets, source lines/terminators,
Gather/mux rows, Apply and replica writes, status, AXI parents/beats and
backend completion. This is not a sampled-vertex correctness check.

## Timing Finding

Values below use the predeclared first board repetition (`r0`) for each arm,
not the three-repeat setup-inclusive medians in the earlier board report.
All times are milliseconds at 150 MHz.

| Graph | Arm | Predicted resident compute | FPGA compute span | Predicted / FPGA span |
| --- | --- | ---: | ---: | ---: |
| AU | Optimized | 103.212 | 200.395 | 0.515 |
| SU | Optimized | 169.208 | 395.824 | 0.427 |
| WK | Optimized | 58.303 | 92.622 | 0.629 |
| AU | Original adapter | 1,141.008 | 2,053.708 | 0.556 |
| SU | Original adapter | 1,867.019 | 3,382.743 | 0.552 |
| WK | Original adapter | 3,008.764 | 5,670.419 | 0.531 |

These are **nominal diagnostics, not identical-window calibration errors**:

- The candidate excludes GraSU maintenance, host preparation, DMA, dispatch,
  same-CU relaunch and inter-round host gaps. The board compute span runs
  from the first compute-kernel start to the last compute-kernel end and
  therefore contains scheduling gaps inside that span.
- Deterministic, disjoint source/state offsets are modeled; actual XRT BO
  physical addresses and their DRAM address mapping were not captured.
- The memory INI, arbitration and component schedules remain assumptions.
  Examples are adapter minimum read-to-use of 71 cycles, row control of 6,
  Scatter latency/II of 4/1, Apply latency/capacity of 100/100 and writeback
  latency/capacity of 71/71. AXI outstanding is 16 per modeled master.
- The model still underpredicts optimized spans by roughly 37--57% and
  original spans by 44--47%. Small inter-round gaps alone do not explain
  this discrepancy. It must not be corrected by an unexplained scale factor.

The old-adapter tail diagnostic provides another warning. It normalizes
`max(adapter_end - lksg_end, 0)` by known trailing empty rows. The report's
`gather` event labels the **whole `lksg` invocation**, including Scatter and
source completion; it is not an exclusive Gather-stage counter.

The model median is approximately 519 ns/row on AU and **zero** on SU/WK;
the board median is approximately 987--988 ns/row on all three. Zero here
means that the recorded model `lksg` end falls after adapter end for enough
shards, not that metadata reads were free. Several model invocation end
orders differ from hardware. These observations require checking source
completion, downstream backpressure and relaunch/mux timing alongside
physical memory behavior. They do not isolate an AXI read latency or prove
which waiting condition is wrong. Neither this tail nor overlapping kernel
lifetimes can serve as exclusive stage calibration.

A subsequent [bounded completion diagnostic](completion_diagnostic/README.md)
reproduces shared-port write blocking behind a held streamed read, with
isolated non-stall controls. It preserves this checkpoint, changes no model
parameters and does not claim to resolve the overall timing gap.

The subsequent [independent-channel correction](independent_channels/README.md)
selects a distinct v2 profile after checking the exact wrapper RTL. It retains
this v1 evidence and requires separate legacy, complete-state and timing gates.

The later [routed stream-capacity correction](routed_streams/README.md) uses an
explicit v3 profile bound to both routed block designs. All 19 connections are
checked; nine edge-path FIFO depths change from 16 to 32. All six full results
and non-timing counters remain equal; cycle changes are below 0.101%. The
earlier nominal timing mismatch remains open.

The [empty-exit control](empty_exit_model/README.md) adds only a generated-RTL
73-cycle empty-row exit in explicit v4. It explains the old adapter's
fixed-payload empty-tail slope while preserving old results and full outputs.
The optimized path's residual timing discrepancy and real-graph validation
remain open; local slope agreement does not admit system calibration.

## Regression And Resources

The same final plugin and numerical-source snapshot produced all six rows
and the five legacy SST regression cases. Every legacy result field remains
identical, with no ignored fields:

| Legacy case | Cycles | Requests |
| --- | ---: | ---: |
| SSSP mixed cold | 99,885 | 33,848 |
| SSSP multipart warm | 5,997,674 | 1,775,700 |
| CC reciprocal | 133,841 | 50,741 |
| Residual PR warm | 1,487,890 | 997,048 |
| Residual PR update-only | 200 | 48 |

All 22 CTest executables pass, including the complete-system checks and
fixture truncation/shape/identity rejection tests. Python tests cover profile
selection, forbidden silent timing changes, mismatched geometry, independent
old-state/active validation and diagnostic units. Repository-level package
tests additionally verify the frozen archive hashes and status boundaries.

The final plugin SHA-256 is
`ff5476635141530cb5c7f0190ec3fd1e88766ba941dc1ca2e7fc544a964bd341`.
The campaign used at most two workers, 8 GiB per child, a 16 GiB reserve,
900-second row timeouts and a one-billion-cycle limit. SST wall times were
10--544 seconds; largest recorded process RSS was about 623 MiB. Recorded
`wait4` RSS is the maximum process RSS, not an aggregate process-tree peak.
Builds and regressions have separate bounded resource records.

## Owners And Reproduction

| Responsibility | Owner |
| --- | --- |
| Checked resident input ABI | `cpp/include/spine_sim/routed_regraph_fixture.hpp`, `cpp/src/routed_regraph/fixture.cpp` |
| Owning-HLS input export and independent oracle | `cpp/tools/routed_regraph/` |
| SST lifecycle and reporting | `cpp/sst/routed_regraph_probe.cpp`, `routed_regraph_report.*` |
| Version admission and bounded execution | `spine_cycle_sim/experiments/sharded_k4_stages/sst_candidate.py`, `sst_timing.py`, `sst_campaign.py` |
| Independent input audit and frozen delivery | `sst_input_audit.py`, `sst_delivery.py` in the same package |

Build into fresh directories. These are the original local tool roots;
the profile/header/library hashes must agree before comparing a replay.

```bash
g++ -std=c++20 -O2 -Wall -Wextra -Werror \
  -I/home/chuxiao/grasu-regraph-integration/include \
  cpp/tools/routed_regraph/export_hls_fixture.cpp \
  -o build/export_hls_fixture
make -C cpp/sst BUILD_DIR=/absolute/fresh/plugin \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 -j1
python3 scripts/run_routed_k4_timing_matrix.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --plugin-dir /absolute/fresh/plugin --exporter build/export_hls_fixture \
  --output /absolute/fresh/matrix --jobs 2
```

The contract `configs/experiments/sharded_k4_routed_sssp_timing_v1.json`
pins every graph, source and board-pair input. On another machine, relocate
paths explicitly while retaining those input hashes. The runner admits
every predeclared arm, records failures and never promotes timing to a pass.
For a direct replay of an archived resident fixture, set
`ROUTED_K4_RUN_CONFIG` to a relocated archived `run_config.json` and launch
`sst/routed_k4_compute.py` with the recorded forced plugin binding.

The roughly 57 MiB archive includes final numerical sources, owning HLS
input headers, graphs, one identical old/new fixture per graph, tested
plugin/exporter binaries, complete six-row SST outputs, matching board logs
and results, legacy before/after outputs, commands and resource records.
SST, DRAMSim3, XRT and xclbins remain hash-pinned external dependencies;
the archive is not a portable FPGA toolchain/container. Initial smoke and
intermediate attempt logs are retained, but the complete final source-body
binding is asserted for the final six-row matrix and legacy gate, not for
every earlier exploratory attempt. Supplementary input-audit/delivery
sources have their own archive hashes.

`scripts/package_routed_k4_sst.py --integration <HLS-root> --data <campaign-root>
--output <new-package>` revalidates a completed campaign. It requires the
full build, input-audit and legacy-gate layout recorded in this archive;
it is not a substitute for running those gates. Existing frozen packages
cannot be overwritten.

## Work Still Required

1. Isolate the observed completion-order and physical-memory timing gaps
   with narrower events/counters or controlled experiments. Preserve this
   checkpoint before changing the model.
2. Validate a newly versioned timing candidate on the full predeclared
   matrix with matched boundaries. A functional pass is insufficient.
3. Compare original four-Little A4 and the actual integrated K4 path using
   matching algorithm/state/rounds/resources and a common memory/evidence
   basis. Earlier mock-memory A4 times cannot be divided by these SST times.
4. Admit other algorithms against their own routed binary and arithmetic.

The persistent goal remains open. The paper, figure package, existing
calibration outputs and production HLS are not modified by this checkpoint.
