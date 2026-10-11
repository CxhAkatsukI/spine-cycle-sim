# Production Model Synchronization

This is an **adapter component checkpoint**, not a completed candidate
production simulator, timing calibration, or original-A4 performance match.
The [paired FPGA results](../adapter_optimization/BOARD_RESULTS.md) remain
unchanged. No paper, figure inputs, v8 profile or frozen plugin is replaced.

The later [compute/port checkpoint](compute_ports/README.md) also extracts
Gather, merger, Apply and source-state writing and validates finite shared
AXI clients. It preserves the five legacy results separately; complete K4
composition and hardware timing admission remain open. The archive and
adapter-checkpoint claims on this page remain frozen.

The [frontend checkpoint and source-topology correction](frontend/README.md)
adds connected Scatter/source tests and binary-bound provenance checks.
**The measured SSSP XO has four independent source masters, not the two
pairwise masters in the later HLS worktree.** The compute checkpoint's
pairwise-wrapper description is not the SSSP calibration target. Its frozen
component evidence remains valid within its original scope.

The subsequent [complete SSSP candidate checkpoint](system/README.md) connects
four independently dispatched frontend chains and one whole-round backend.
Its full-state, finite-traffic and convergence tests are separate from the
still-open artifact-bound SST profile and matched hardware timing gates.

## Status And Reading Order

| Gate | Status and scope |
| --- | --- |
| Legacy reader extraction | Five predeclared SST cases preserve every result field |
| Shared-master adapter functionality | 288 primary finite-model cases; 12 HLS variants, 324 shared-fixture calls |
| Completion and pressure | Separate edge-stream/adapter completion; finite read/segment/FIFO capacity; chained invocations with an undrained output FIFO |
| Whole core | 16 CTest executables pass |
| Candidate system integration | Still open: Scatter, per-kernel dispatch, shared round backend, explicit profile and result gates |
| Hardware timing admission | Not established by these component tests |
| Original A4 vs actual K4 | Still open; use matched arithmetic, state, rounds and resources |

Use [the machine-readable checkpoint](model_adapter.json),
[raw archive index](model_raw_index.json), and
[raw results and source snapshots](raw_model_adapter.tar.gz) together.
The archive includes both extraction-only and final legacy regressions,
build/CTest logs, HLS probe commands, and retained failed attempts.
Executable and plugin hashes are included; large compiled binaries are not.

## Reviewable Owners

| Code | Responsibility |
| --- | --- |
| `cpp/src/grasu_regraph_legacy_reader.cpp` | Existing combined reader, extracted without numerical changes |
| `cpp/src/detail/grasu_regraph_payload.hpp` | Existing payload helpers and constants |
| `cpp/src/detail/grasu_regraph_streams.hpp` | Existing packets/context plus a small partition-reader interface |
| `cpp/include/spine_sim/regraph_pma_adapter.hpp` | New raw AXIS packet, geometry, schedule and counter contracts |
| `cpp/src/regraph_pma_adapter.cpp` | Shared AXI adapter only; no source-property, Scatter or algorithm policy work |
| `cpp/tests/routed_regraph/` | Shared exact packet fixtures, finite-pressure tests, optional production-HLS probe |
| `spine_cycle_sim/experiments/sharded_k4_stages/model_adapter.py` | Bounded, source-pinned HLS/model checks |
| `spine_cycle_sim/experiments/sharded_k4_stages/model_delivery.py` | Recheck raw gates and freeze this checkpoint |

See the [C++ map](../../../../../../cpp/README.md) and
[experiment package map](../../../../../../spine_cycle_sim/experiments/sharded_k4_stages/README.md).
Both CMake and the SST Makefile compile the new units. The new adapter is
**not selected by any production topology yet**. Existing paths still use
the legacy reader factory. Compiling a component into a plugin is not wiring
it into the simulated system.

## What Is Modeled

The adapter reads a destination-sharded, contiguous, segment-aligned PMA.
The following behavior is explicit rather than hidden in a timing multiplier:

- One 512-bit AXI master handles row metadata and all four PMA bank addresses.
- A final-row extent request is charged, including the guarded row-zero
  speculative read for a zero-node invocation.
- The row cache holds at most eight entries and bounds a partial final block.
- **Prefetch is not cache-line coalescing.** The current production-generated
  RTL loads a full 512-bit line for each 64-bit row, then selects its lane.
  The model therefore charges one 64-byte request per prefetched row, not
  one request per group of eight rows. The HLS burst report's missed widening
  and the generated row-prefetch AXI/address logic support this distinction.
- PMA hot/cold bank selection, weighted/destination-only/unit-weight encodings,
  dummy slots, global destination rebasing and `last` agree with production
  HLS on the same fixtures. HLS `keep` and `strb` are checked as all ones;
  these constant sidebands are implicit in the model packet type.
- Pending reads, returned segment storage and output FIFO are bounded.
  Accepted/completed requests, responses, segments, packets and bus bytes
  must conserve. There is no free host-built sparse-source directory.
  Fixture row allocations are padded to complete 64-byte lines; the candidate
  SST buffer map must admit that physical access range explicitly.
- Sending the last packet completes the edge stream. A non-optimized adapter
  can continue reading empty source rows afterward. The next adapter
  invocation can start while previous packets remain in the FIFO, without
  waiting for gather to complete. FIFO order preserves partition boundaries.

The default model schedule uses a 71-cycle minimum request-to-use delay,
six source-control cycles, and a two-cycle segment issue interval. These
are **explicit schedule-informed assumptions**, not measured HBM latencies
or calibrated FPGA component delays. Memory service can exceed that minimum.
The relevant combined-adapter reports have row-prefetch II=1 and segment
II=2; report/RTL stages do not alone prove end-to-end timing equivalence.
The default pending-read and returned-segment capacities are each 16;
whole-system AXI buffering/transport still needs a separately admitted check.

## Exact Legacy Regression

The baseline is detached revision `3e66f4c`, built before extraction, with
the existing `grasu_component_refactor_v1` contract. The extraction-only
plugin and final plugin are checked separately against it, using the same
profiles, inputs, compiler flags and DRAMSim3 library. No fields are ignored.

| Case | Cycles | Backend requests |
| --- | ---: | ---: |
| `sssp_mixed_cold` | 99,885 | 33,848 |
| `sssp_multipart_warm` | 5,997,674 | 1,775,700 |
| `cc_reciprocal` | 133,841 | 50,741 |
| `residual_warm` | 1,487,890 | 997,048 |
| `residual_update_only` | 200 | 48 |

This matrix establishes behavior-preserving extraction and default-path
preservation, not an eight-large-graph performance result. It also does not
test a new full-system adapter topology, because that topology is not wired.

The first optional HLS probe failed at link time because Vitis 2024.1 headers
defined the same specialization in two translation units. The probe now
includes the unchanged production source in one translation unit. That failed
attempt is retained; no linker multiple-definition override or relaxed packet
comparison was used. Later final probes include the chained-invocation test.
An additional empty-stream notification test then exposed a missing early
callback while legacy trailing-row scanning continued. It first failed,
then passed after issuing that callback at the final-extent response. Both
the failing log and the post-fix tests are retained. The final production
plugin is rebuilt and rechecked separately from the pre-fix plugin; neither
plugin activates the new component on the legacy path.

## Reproduce

Run from the simulator root with fresh output directories. Core tests do not
need Vitis. The optional HLS probe additionally needs Vitis headers and GMP.

```bash
cmake -S . -B build/k4-adapter-review -DCMAKE_BUILD_TYPE=Release
cmake --build build/k4-adapter-review -j2
ctest --test-dir build/k4-adapter-review --output-on-failure --timeout 120

python3 scripts/validate_sharded_k4_adapter_model.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --vitis-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --core-build build/k4-adapter-review \
  --output results/k4-adapter-review/shared_fixture_final

make -C cpp/sst BUILD_DIR="$PWD/build/k4-adapter-plugin-review" \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 -j1
python3 scripts/run_grasu_refactor_regression.py \
  --lib-dir build/k4-adapter-plugin-review \
  --out-dir results/k4-adapter-review/candidate \
  --baseline-dir results/k4-adapter-review/before \
  --jobs 2 --case-timeout-seconds 600
```

The `before` directory can be extracted from this archive into a fresh result
root. Alternatively, build `3e66f4c` in a detached worktree and run the same
regression command without `--baseline-dir`. Recorded source/build identities
remain authoritative; a different compiler/backend requires a new paired
baseline. Use a new plugin directory, not `build/sst`.

The local campaign root is
`/data/chuxiao/experiments/sharded_k4_model_sync_20261010/`.
Each HLS compile is bounded to 300 seconds, each probe to 120 seconds, with
8-GiB address-space limits and a 16-GiB free-memory admission reserve. The
SST comparison runs at most two cases simultaneously with 600-second case
timeouts. Saved commands record CPU affinity. No wall time here is a
hardware-performance measurement.

## Next Acceptance Gates

1. Connect the raw adapter to independently scheduled Scatter/source service;
   consume the declared packet count without waiting for adapter tail work.
2. Model separate per-worker adapter and gather chains, the globally ordered
   mux, and the one-round shared Apply/HBM lifetime. The current legacy worker
   waits for a bundle of stages; shortening its row delay is insufficient.
   The production host resets gather for every shard invocation, whereas the
   legacy controller currently chooses reset on the first algorithm round.
   Preserve this distinction in the candidate rather than silently changing v8.
   The later worktree's `regraph_k4_shared_hbm_wrapper` services frontend pairs
   (0, 2) and (1, 3) through two shared AXI bundles, switching after a complete
   source block or terminator. Its writes share those bundles. Four independent
   source-reader ports are not an equivalent arbitration model merely because
   their requests eventually reach the same physical HBM channels. That
   pairwise source is not the measured SSSP XO, as the subsequent frontend
   provenance check establishes above; the complete SSSP candidate targets
   the measured four-reader variant instead.
3. Admit a distinct candidate profile and full-state/traffic/convergence gates.
   Check matched bounded FPGA timing cases, retaining all mismatches and
   separating device service from host launch/wait gaps.
4. Compare original A4 against actual optimized K4 with matched arithmetic and
   rounds. Original fixed-point PR versus three-round production FP32 FullPR
   is not an admitted speed comparison. Published-topology matching remains
   a separate requirement.
