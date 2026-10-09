# GraSU+ReGraph Residual PageRank Execution-Frontier Validation

## Problem

The paper-scale, three-partition AskUbuntu runs converged and matched both the
float32 architecture oracle and the independent float64 PageRank oracle, but
the result was rejected because the accumulated active-edge count was required
to equal the sequential CPU reference exactly.  The observed differences were
4,160 / 44,532,094 edges for batch 8, 14,800 / 44,503,631 for batch 64, and
8,331 / 45,011,443 for batch 4,096.

That equality is not a valid correctness condition for thresholded floating
point execution.  ReGraph reduces edges in bank, bypass, partition, and AXI
response order.  The CPU oracle reduces each adjacency list sequentially.
Both use float32 states and the same strict residual threshold, but
non-associative addition can move a near-threshold vertex across the activation
boundary for one iteration.  The resulting execution trace may differ while
the final state and convergence remain correct.

## Validation Contract

The simulator now records the actual active-vertex count at every ReGraph
superstep barrier.  A residual run passes only when all of the following hold:

1. the execution frontier has one entry per executed superstep and ends at zero;
2. residual L1 is at most `1.01 * epsilon`;
3. float32 architecture-state and float64 mathematical-oracle checks pass;
4. every mapped active edge produces exactly one gather-bank update and cannot
   exceed the number of scanned live edges;
5. AXI issued/completed beats, backend accepted requests, phase traffic, update
   state, degree state, and HBM request/byte ledgers close exactly.

The CPU active-edge total remains in the result as a diagnostic:

- `active_edge_reference_exact`
- `active_edge_reference_relative_error`
- `reference_frontier_in_sizes`
- `reference_frontier_out_sizes`

It does not gate correctness.  `frontier_in_sizes` and `frontier_out_sizes` now
describe the execution-driven hardware trace rather than relabeling the CPU
reference trace.

## Reproduction

Build and run the focused component tests:

```bash
cmake --build build --target grasu_cycle_tests -j 4
./build/cpp/grasu_cycle_tests
python3 -m unittest \
  tests.test_hls_pagerank_real_comparison \
  tests.test_grasu_hls_residual_pagerank_runner
```

Build the SST plugin and run the thresholded residual smoke:

```bash
make -C cpp/sst -j 2
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install
python3 scripts/run_sst_grasu_regraph_hls_residual_pagerank.py \
  --no-build \
  --max-cycles 100000000 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --out-dir /data/tmp/chuxiao/residual_frontier_ledger_smoke_idle_v1_20260728
```

The formal AskUbuntu rerun uses the frozen Candidate10 K1 v4 residual profile,
540,000-edge base slice, and 8 / 64 / 4,096 insertion slices.  Those rows are
admitted to paper tables only after the same contract produces a PASS manifest.

## Concurrent Spine Plugin Provenance

The three long-running Spine jobs started from simulator commit `256d70b`.
Commit `2d931de` subsequently changed only the GraSU+ReGraph residual frontier
validation path and rebuilt the monolithic SST plugin.  Rather than silently
accepting the resulting plugin-hash difference or rerunning several hours of
unaffected Spine execution, reconstruct the launch plugin from the pinned
commit:

```bash
git worktree add --detach \
  /data/tmp/chuxiao/spine-cycle-sim-plugin-256d70b 256d70b
make -C /data/tmp/chuxiao/spine-cycle-sim-plugin-256d70b/cpp/sst \
  BUILD_DIR=/data/tmp/chuxiao/spine-cycle-sim-plugin-256d70b/build/sst -j 2
sha256sum \
  /data/tmp/chuxiao/spine-cycle-sim-plugin-256d70b/build/sst/libspine_cycle.so
```

The reconstructed hash is
`2880b2f1e325701b933dbb1766be35b4a34a2fc942feb6f0ac643db021502b8f`.
The comparison recovery command may adopt a Spine summary only when its
embedded plugin hash matches that file exactly:

```bash
--resume --adopt-validated-results \
--adopt-spine-plugin \
  /data/tmp/chuxiao/spine-cycle-sim-plugin-256d70b/build/sst/libspine_cycle.so \
--adopt-spine-plugin-source-revision 256d70b
```

GraSU+ReGraph adoption continues to require the current plugin hash. The final
matrix manifest records both current and adopted Spine plugin provenance.
