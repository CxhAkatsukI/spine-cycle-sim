# Independent Read/Write Channels

This is a separately selected **v2 model correction**, not a replacement for
the frozen [v1 checkpoint](../README.md), a hardware timing calibration, or
an original-A4 performance match. The original hardware runs, figure package,
production HLS and default v8 simulator remain unchanged.

## Why The Model Changed

The [completion diagnostic](../completion_diagnostic/README.md) reproduced
an unwanted dependency: holding a streamed read consumer prevented a write
on the same physical master from issuing/completing. The whole WK observation
also showed a writer waiting behind that read path.

The exact measured SSSP wrapper XO contains separate read and write modules.
Its top RTL instantiates `gmem1` and `gmem2` with
`NUM_READ_OUTSTANDING=16` and `NUM_WRITE_OUTSTANDING=16`; these override
the generic submodule defaults. Its SHA-256 is
`005f0b40523bd021034c90f179a7d2666001bc1bde1de6af5d6ef0638cc194c7`.
The XO and extracted top/master RTL identities are recorded with the raw
evidence. This is structural evidence, not a measured memory-latency value.

Version 2 gives source-state masters independent AR/AW credits and R/B
response capacity/backpressure. A fully issued read waiting for its consumer
cannot suppress an otherwise eligible write. Ordering remains intact within
each operation direction. The correction does **not** add physical masters,
HBM channels, aggregate address/data issue bandwidth, or a timing multiplier.
Apply and adapter masters retain their existing behavior; this is not a claim
that every generated AXI channel or HLS schedule is now reproduced exactly.

The 150-MHz clock, nine masters, DRAMSim3 INI, memory-channel budgets,
deterministic addresses, stage delays and buffer limits remain unchanged.
Only the explicit `grasu_regraph_routed_sssp_compute_v2` profile enables the
correction. V1 and all existing default selections retain their old behavior.

## Complete Matrix Finding

All six v2 executions pass full external result-byte equality with the FPGA,
the padded-state oracle, convergence, replicas and finite traffic conservation.
The same final plugin replays the five legacy cases and all six v1 matrix
rows exactly: every result field and complete external output bytes are
unchanged, with no ignored fields. The delivery is frozen separately below.

Times below use the predeclared first FPGA repetition (`r0`), not a selected
repeat or the setup-inclusive median. The model runs at 150 MHz.

| Graph | Adapter | v2 resident compute ms | FPGA compute span ms | Model / FPGA span |
| --- | --- | ---: | ---: | ---: |
| AU | Optimized | 103.212 | 200.395 | 0.515 |
| SU | Optimized | 169.209 | 395.824 | 0.427 |
| WK | Optimized | 58.303 | 92.622 | 0.629 |
| AU | Original | 1,137.972 | 2,053.708 | 0.554 |
| SU | Original | 1,867.021 | 3,382.743 | 0.552 |
| WK | Original | 3,008.764 | 5,670.419 | 0.531 |

Correcting channel independence changes completion order substantially but
barely changes total elapsed cycles on these inputs. The model still
underpredicts the nominal hardware span. This is an unresolved discrepancy,
not successful timing calibration.

For the original adapter, the median observed tail per trailing empty row is:

| Graph | v1 model ns/row | v2 model ns/row | FPGA ns/row |
| --- | ---: | ---: | ---: |
| AU | 519 | 461 | 988 |
| SU | 0 | 437 | 987 |
| WK | 0 | 486 | 988 |

The diagnostic is `max(adapter_end - lksg_end, 0) / trailing_empty_rows`.
`lksg_end` ends the complete Little invocation, including source/Scatter
completion and downstream backpressure. It is not an exclusive Gather or
AXI-read counter. A zero v1 value describes event ordering, not free reads.
The v2 result removes the zero-tail symptom on SU/WK, but its nonzero tail
still does not match the FPGA. A controlled empty-row sweep is the next
useful test; no latency constant has been fitted to these three graphs.

## Acceptance Gates

The final campaign passed these independently:

1. The new core test holds the R consumer, separately stalls R/B/W, varies
   credits and read sizes, reverses component registration, verifies complete
   payloads and traffic, and limits aggregate issue rate to one beat/cycle.
   The old mode must still reproduce the diagnosed blocking.
2. All 23 core test executables pass. All five legacy SST cases preserve
   **every** result field, including cycles, counters and memory statistics.
3. The same final plugin replays all six v1 AU/SU/WK old/new runs with every
   result field and complete external result bytes unchanged.
4. The same final plugin executes all six v2 runs from identical HLS-prepared
   resident PMAs and old converged state. Full FPGA result bytes, padded-state
   oracle, replicas, convergence and finite traffic must pass.
5. Timing differences are reported for every row. A functional pass does not
   promote the nominal model/FPGA comparison to an identical-window check.

The original graph and fixture identities are inherited from v1, not replaced
with a different graph or fewer rounds. The board comparator is the declared
`r0` repetition, not a selected favorable run or the setup-inclusive median.

## Review And Reproduction

The [machine-readable report](channels.json) and [raw index](channels_raw_index.json)
retain both successful and failed attempts. The 131-MiB compressed archive is
stored losslessly in three ordered volumes to stay below Git's file-size
limit. From this directory, reconstruct it with:

```bash
cat raw_channels.tar.gz.part00 raw_channels.tar.gz.part01 raw_channels.tar.gz.part02 > raw_channels.tar.gz
sha256sum raw_channels.tar.gz
```

The digest must equal `archive.sha256` in `channels_raw_index.json`. The
portable `tests/test_sharded_k4_channel_package.py` test reconstructs the
volumes in temporary storage and checks every member, full output-byte
equality, common plugin/source identity and the frozen parent dependency.
No large archive reconstruction needs to be committed.

The final fresh Release build passed 23/23 CTest executables. The five legacy
SST cases and six v1 rows were replayed with the same final plugin used for
the six v2 rows. Runtime-only optimizations also preserve three complete v2
optimized-adapter runs and two capped original-adapter observations; the
capped runs are explicitly not workload-correctness passes.
All 100 focused Python study tests, including volume reconstruction and
every-member integrity checks, pass. The 15 organization tests, documentation
layout/catalog checks and whitespace check also pass.

| Owner | Responsibility |
| --- | --- |
| `cpp/src/axi_independent_channels.cpp` | Independent request, data and response selection |
| `cpp/src/detail/backend_response_selection.hpp` | Validated stable retirement of selected backend responses |
| `cpp/src/memory_backend.cpp`, `cpp/sst/sst_memory_backend.cpp` | Mock/SST per-direction response capacity and staged retirement |
| `cpp/tests/axi/independent_channels_tests.cpp` | Finite pressure, payload, ordering and default-mode controls |
| `configs/architectures/grasu_regraph_routed_sssp_compute_v2.json` | Explicit fixed assumptions and measured RTL identity |
| `spine_cycle_sim/experiments/sharded_k4_stages/channel_delivery.py` | Exact cross-version checks and a separate immutable delivery |

Use a fresh plugin/build/output directory. Do not overwrite a hash-pinned
plugin or alter source while the matrix or legacy regression is running.

```bash
cmake -S . -B build/k4-channel-review -DCMAKE_BUILD_TYPE=Release
cmake --build build/k4-channel-review -j2
ctest --test-dir build/k4-channel-review --output-on-failure --timeout 120
make -C cpp/sst BUILD_DIR=/absolute/fresh/plugin \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 -j1
python3 scripts/run_routed_k4_timing_matrix.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --plugin-dir /absolute/fresh/plugin --exporter /absolute/export_hls_fixture \
  --contract configs/experiments/sharded_k4_routed_sssp_timing_v2.json \
  --output /absolute/fresh/v2-matrix --jobs 2
```

Repeat with the v1 contract and a different output directory for the exact
v1 replay. The owning-HLS exporter and parent graphs are supplied by
`../raw_sst.tar.gz`; all recorded hashes must agree before replay.
The existing five-case legacy regression uses the same final plugin and the
parent archive's legacy baseline. `package_channel_checkpoint(root, data,
parent_data, output)` revalidates those gates before freezing this delivery.

## Remaining Boundary

The model measures resident compute without host dispatch/relaunch gaps.
The FPGA first-start-to-last-end span contains such gaps and overlapping
backpressure. Actual XRT BO physical addresses are not captured by the model.
Kernel lifetimes are not exclusive stage counters. Resolving one demonstrated
AXI coupling does not establish the cause of the total-time discrepancy.
Matched-window hardware timing and the original-A4 comparison remain separate
open requirements.
