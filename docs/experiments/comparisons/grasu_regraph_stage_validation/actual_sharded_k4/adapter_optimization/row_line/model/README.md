# Whole-Line Model Checkpoint

The subsequent [resident-graph matrix](real_graph/README.md) extends this
checkpoint to all three pinned AU/SU/WK inputs. It preserves full outputs
and reduces directory traffic approximately 8x, but predicted total cycles
only 1.42--3.31%. It is a separate archive and explicit execution scope;
the small-fixture results and legacy evidence below remain unchanged.

## Scope

This continues the [production HLS/RTL checkpoint](../README.md). It changes
the actual `ReGraphPmaAdapter`, not the independent original-A4 PMA reader.
`row_line_reads` defaults to false. The distinct
`grasu_regraph_row_line_sssp_compute_v1` profile compares the unrouted
skip-empty/prefetch reference with the unrouted whole-line candidate.
The runner's `original` arm means that skip-empty reference, **not** the
historical routed original bitstream and not original ReGraph A4.

One response now decodes up to eight valid rows. The final-row extent query
remains a separate request, even if its line is read again. Partial blocks
are bounded; empty input issues no directory request in whole-line mode.
The existing shared AXI path, response latency, finite queues, row-control
latency, segment issue interval, stream depths, source service and backend
are not retimed. No sparse-source index or free host preprocessing is added.
The skip-empty reference does not charge the historical 73-cycle empty-helper
exit. This profile is not a replacement for the frozen routed v4 profile.

The topology basis remains the pinned dedicated-source v3 implementation.
It is a model of a proposed adapter replacement on that topology, not a
claim that every current HLS-worktree variant is identical. Both XO hashes
are explicit; no measured xclbin identity is inherited by the candidate.
Historical FPGA replay rejects this unrouted profile before creating output.

## Review Order

| Responsibility | Owner |
| --- | --- |
| Default-off request/decode behavior | `cpp/include/spine_sim/regraph_pma_adapter.hpp`, `cpp/src/regraph_pma_adapter.cpp` |
| Strict version, immutable basis and separate arm selection | `row_line/model_contract.py`, explicit architecture JSON |
| SST component selection | `sst_candidate.py`, `cpp/sst/routed_regraph_probe.cpp` |
| Bounded execution and pre-run source/input/plugin freeze | `row_line/model_study.py` |
| Separate smoke/resident limits and fixed graph identities | `row_line/model_scope.py` |
| Independent fixture inventory and traffic equations | `row_line/model_validation.py` |
| Offline source, complete-result and regression recheck | `row_line/model_recheck.py` |
| Immutable raw archive and portable delivery verification | `row_line/model_delivery.py` |
| Packet/pressure and full-system tests | `cpp/tests/routed_regraph/adapter_tests.cpp`, `system_tests.cpp` |
| Profile rejection and validation mutations | `tests/test_sharded_k4_row_line_model*.py` |

All Python owners are inside the existing cohesive
`spine_cycle_sim/experiments/sharded_k4_stages/` collection. HLS stays in its
own integration repository. No paper or figure package is edited.

## Results

All 27 CTest executables pass. The adapter retains 288 legacy combinations
at both prior and 73-cycle exit settings, and adds 240 whole-line scenarios
plus pressure, delayed-memory, finite-credit and chained-invocation controls.
The whole-system extension executes nine narrow/wide/reversed variants,
including 65,569 and 262,273 vertices, complete padded state, both source
copies/buffers, convergence, and memory conservation. These are functional
finite-model checks, not hardware timing calibration.

The isolated SST smoke uses two preserved resident SSSP fixtures with 4,096
and 32,768 vertices. Each has one destination partition, 64 PMA slots, five
live edges and two convergence rounds. Both arms match every external result
byte and preserve work/round activity. An independent fixture parser checks
directory counts, PMA slots/packets, source lines, full-partition Gather/Apply,
publication writes and backend/arbitration drainage.

| Fixture | Directory requests, reference -> candidate | Directory bytes | Predicted cycles, reference -> candidate |
| --- | --- | --- | --- |
| 4,096 vertices | 18 -> 4 | 1,152 -> 256 | 131,507 -> 131,507 |
| 32,768 vertices | 18 -> 4 | 1,152 -> 256 | 131,507 -> 131,507 |

This is deliberately not a real-graph performance matrix. The two fixtures
share a tiny live prefix and the same padded 65,536-vertex backend work.
Directory traffic falls by 4.5x, while total cycles are unchanged. Thus this
checkpoint verifies representation and conservation; it does not show that
directory optimization recovers the independent A4 control's old slowdown.
The hardware RTL checkpoint also found only a small total-cycle improvement
in its dense synthetic case. Neither observation justifies a general speedup.

All five legacy SST cases also pass with the newly built isolated plugin.
Their full result JSON files are byte-identical to the pre-edit baseline;
no result fields or manifest identities are ignored. This includes cold and
multi-partition warm SSSP, reciprocal CC, warm residual PR and update-only
residual PR. It verifies default-off compatibility, not candidate support
for every algorithm. The 16 focused Python checks pass, including rejection
of changed fixtures, complete outputs, plugin/source identities, execution
arms, traffic, watchdog limits and nominal-success flags.
The wider 292-test sharded-K4 Python suite passes as well; its
[resource report](evidence/regression.json) and
[raw logs](evidence/raw_regression.tar.gz) are separate from the frozen
numerical-run archive. These regression logs do not add hardware admission.

## Evidence Package

The [results](evidence/results.json), [file index](evidence/verification.json)
and [raw archive](evidence/raw_model.tar.gz) form one portable checkpoint.
The archive contains 1,131 indexed files (39,154,656 compressed bytes),
including the executed numerical source snapshot, explicit profiles,
inputs, full outputs, isolated plugin, core/build logs, both legacy runs
and resource records. The archive SHA-256 is
`bc15f762165f5072dffea60cea4c11ca34899762e71706fff1b605749cc810eb`.
SST, DRAMSim3 and toolchains are indexed dependencies, not redistributed.

Portable verification extracts into a fresh temporary directory and
recomputes geometry, traffic, full-output equality, source identities and
all-field legacy equality without reading the original experiment paths.
It does **not** rerun simulation, compilation or hardware. Later delivery
code/tests are reviewed code in this repository, not retroactively part
of the executed numerical source snapshot.

The pre-edit source archive omitted five thin CLI scripts. It is preserved
unchanged. Verification recovers their byte-identical copies from the
executed source archive and checks every copy against its pre-edit SHA-256.
This is explicit archive recovery, not a regenerated pre-edit baseline.

## Reproduction

Use a new core/plugin build directory. Do not replace `build/sst` or any
hash-pinned plugin. From the simulator root:

```bash
python3 -m unittest discover -s tests -p 'test_sharded_k4_row_line_model*.py'
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_delivery \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/model/evidence \
  --verify-only
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_study \
  --plugin /data/chuxiao/experiments/sharded_k4_row_line_model_20261011/plugin \
  --fixture /data/chuxiao/experiments/sharded_k4_empty_exit_model_20261011/sweep/corrected_v4/4096/candidate \
  --fixture /data/chuxiao/experiments/sharded_k4_empty_exit_model_20261011/sweep/corrected_v4/32768/candidate \
  --output /data/chuxiao/experiments/fresh_row_line_model
```

Each fixture directory supplies `resident.bin` and its previously checked
complete `result.json.values.txt`. Every arm is serial, with a 180-second
timeout, one-million-cycle cap, 3-GiB sampled process-tree RSS budget,
16-GiB live reserve and CPU affinity 112-113. Complete source, dirty numerical
diff, profiles, plugin and DRAMSim3 identity are frozen before execution;
raw outputs, resources and failures are retained. Source/plugin changes fail
the run rather than silently changing its identity.

## Open Gates

The model has not been calibrated to a newly routed whole-line bitstream.
Its timing parameters remain assumptions inherited from the pinned basis,
not an exact translation of every HLS pipeline. Even the empty invocation's
model completion is not asserted to equal the RTL's two clocks. There is no
per-stage FPGA counter admission, no publication-performance match, and no
completed matched original-A4 comparison here.

Route admission remains a 40-GiB process-tree budget plus a 16-GiB host
reserve. Available memory at this checkpoint is below that 56-GiB threshold;
the budget is not lowered to force a route. The next hardware gate requires
the exact candidate XO, padded host, immutable new route/connectivity and
alternating resident paired runs before a hardware latency claim.
