# Scatter, Source Service And Artifact Identity

This is a **frontend component checkpoint**, not a completed candidate K4,
FPGA timing calibration, or original-A4 performance comparison. The accepted
[old/new SSSP board measurements](../../adapter_optimization/BOARD_RESULTS.md)
are unchanged. Neither the paper nor the figure package is modified.

## Important Source-Topology Correction

The measured SSSP bitstream and the current HLS worktree do **not** contain
the same source-service topology. The earlier
[compute/port checkpoint](../compute_ports/README.md) described the worktree's
pairwise scheduler as the actual wrapper without verifying the linked XO.
That description must not be used as the SSSP calibration target.

| Evidence | Source services | Physical AXI masters | HBM mapping |
| --- | --- | --- | --- |
| Measured old and adapter-optimized SSSP xclbins | Four independent `littleKernelReadMemory` services | `gmem1` through `gmem4` | Readers 0/2 use HBM23, readers 1/3 use HBM24; writes share masters 1/2 |
| Current HLS worktree | Pairwise services (0,2) and (1,3), whole-block arbitration | `gmem1` and `gmem2` | Same source channel pair, fewer masters |

Sharing an HBM channel is not the same as sharing an AXI master. The optimized
board experiment replaced only the PMA adapter XO, so its source services
remain the four-master version. Both board arms use that same wrapper.

The current worktree's pairwise implementation was introduced by integration
commit `690c933` on August 7. The measured SSSP wrapper XO embeds the earlier
four-master source. Its embedded source hash is
`70ac3a10f6affe107740ae0124294c28a23e1b6f9fbb906db76415da71732624`;
the current worktree source hash is
`04041f066fd1bf99802cc668b4d583da9104b25bdf1b4125dda00ca2963ffd0d`.
This is a provenance correction, not evidence of a new board regression.

The validation runner now checks the measured route's XO hash, parses its
embedded kernel XML, extracts its embedded C++ source, and checks the
ReGraph header hashes against the original compile-input table. It runs
separate C-simulation probes for the embedded and worktree variants.
The worktree probe cannot substitute for the embedded-source probe.

## What Was Added

- `RoutedScatter` consumes raw adapter packets with a declared physical slot
  count. It models ping-pong source windows, lookahead requests, finite output
  storage, source waits and the final response drain. Gather-input completion
  is distinct from complete Scatter termination and from adapter completion.
- `RoutedSourceService` has one or two explicitly supplied workers. One
  worker models the measured dedicated service; two model the later pairwise
  implementation. Each requested block is 4096 vertices / 256 512-bit lines.
  Pairwise selection changes only between complete blocks or end markers.
- Parent-response completion and streamed-data completion are tracked
  separately. A late parent callback does not delay already-completed data
  delivery to the next worker; the service still waits for every parent
  before declaring the round complete. Capacity remains finite.
- Source services use an `AxiEndpoint`, not an extra physical master. The
  eventual composition must connect four masters for measured SSSP, with
  writeback sharing only the appropriate two. Channel contention remains
  with the common memory backend.
- SSSP/CC source activation and weighted/local destination fields are
  preserved. PageRank inputs are explicitly already-prepared FP32 words;
  this component does not compute degree correction or initial PR seeds.
- A source block outside the declared allocation is rejected instead of
  reading free zero padding. Dedicated HLS invocation counts are 8-bit and
  values above 255 are rejected.

The production v8 topology still uses its existing reader and scheduling.
Compiling these components into the SST library does not select them.

## Gates And Failures

| Gate | Scope |
| --- | --- |
| Connected adapter/Scatter/dedicated source | 80 cases: four algorithms, five algorithm/encoding combinations, short and skipped source windows, old/new adapter completion, FIFO pressure and reversed component registration |
| Pairwise source with shared writeback | 16 cases, two rounds each, bounded master routing, payload/request/byte conservation and registration-order equality |
| Completion and bounds | Early/late AXI parent response, independent source-end drain, invalid allocation, nonempty dummy input and zero-packet rejection |
| Production HLS source probe | Nine invocation-count cases from the measured XO's embedded dedicated implementation |
| Worktree HLS source probe | Nine cases for the separate, later pairwise implementation |
| Legacy SST | Same five-case contract, all result fields and bytes unchanged |
| Whole core | 20 CTest executables |

The source-request FIFO is depth **16** in the routed connectivity. A negative
test reduces it to one and jumps over a source window: Scatter can block
trying to enqueue the next request while the old response block cannot
drain. This failure is retained and checked in both registration orders.
It is not a claim that the measured depth-16 hardware deadlocks.

The host reserves a dummy 16-slot segment even for a logically empty shard.
The Scatter kernel itself expects nonzero packet counts. Therefore the
model accepts all-dummy input but rejects a true zero-packet invocation;
it does not silently turn a hardware deadlock into zero-cost completion.

Other retained attempts include a fixture that incorrectly required write
responses with distinct AXI IDs to return in issue order, a build attempted
before regenerating CMake's new target, and a report parser that initially
rejected Vitis's informational stream-depth line. Final gates keep ID/data
conservation and require the complete declared report; only that specific
vendor informational line is allowed.

The HLS probes are functional C simulation with software streams. Their
reported maximum stream depth is not a hardware FIFO capacity or timing
measurement. Compiler warnings from vendor headers are retained in the logs.

## Timing Boundary

The source model selects a block, issues a 16-KiB streamed AXI parent and
forwards at most one returned line per cycle. The physical AXI model splits
the parent into bounded bursts. Selection, queues, backpressure and parent
credits are explicit; their exact Vitis arbitration timing is not calibrated.
The Scatter output pipeline exposes latency, initiation interval and
capacity (defaults 4, 1 and 5). Tests vary these settings but do not fit them
to FPGA time. Source-cache writes account for eight lane replicas even though
the functional payload storage is shared in the C++ implementation.

Still required before matched hardware timing: the lksg input-forwarding FIFO
and schedule, Gather lifetime, four independent per-worker kernel chains,
globally ordered frontend mux, one-round Apply/writeback/status completion,
and source-buffer lookahead capacity admission. Those are not replaced by
the component tests above. No hardware speedup prediction is made here.

## Review And Reproduce

The [C++ map](../../../../../../../cpp/README.md) lists the owners. Start with
`cpp/src/detail/routed_regraph_{source,scatter}.hpp`, then the two implementations
under `cpp/src/routed_regraph/`. Tests live together in
`cpp/tests/routed_regraph/`. The numerical legacy files are not modified.

`model_frontend.py` owns bounded execution and binary-source checks;
`frontend_delivery.py` rechecks the gates and packages the evidence. CLI files
only parse arguments and delegate. This directory contains `frontend.json`,
`frontend_raw_index.json`, and `raw_frontend.tar.gz`, including failed logs,
final source/input snapshots, the source XO, compiler commands and both
legacy result sets. Compiled simulator binaries are indexed, not bundled.

The local campaign is
`/data/chuxiao/experiments/sharded_k4_frontend_sync_20261011`.
Reproduction uses fresh build/output directories, at most two C++/SST jobs,
bounded process time and memory, and a 16-GiB available-memory reserve:

```bash
cmake -S . -B build/k4-frontend-review -DCMAKE_BUILD_TYPE=Release
cmake --build build/k4-frontend-review -j2
ctest --test-dir build/k4-frontend-review --output-on-failure --timeout 120
python3 scripts/validate_sharded_k4_frontend_model.py --help
python3 -m unittest discover -s tests -p 'test_sharded_k4_frontend*.py'
```

The validation command requires `--routed-hbm-xo`, `--route-manifest` and
`--compile-inputs` as well as explicit integration, ReGraph, Vitis, build and
output paths. The complete executed commands are in the archive. For the
five legacy cases, build SST in a new directory and run
`run_grasu_refactor_regression.py` against the archive's `before/` results
with the pinned compiler/backend, or rebuild that baseline as a paired run.

## Next Acceptance Gate

Compose the measured four-source-master SSSP topology, not the later pairwise
worktree variant. Then check complete state, convergence, traffic and measured
event windows before comparing predicted cycles with the old/new FPGA cases.
Only after those checks should original A4 be compared with the optimized
actual adapter + K4 path. The full goal remains open.
