# GraSU + ReGraph K-pipeline Phase 2B

Date: 2026-07-28

## Result

The normalized GraSU + ReGraph simulator now times the initial HLS
`regraph_pagerank_source_prepare` operation instead of materializing its result
for free in the C++ constructor. This removes the last known functional timing
shortcut before PageRank partition workers start.

For every 16-vertex burst the execution-driven component:

1. issues a state read and an out-degree read through finite AXI ports;
2. waits for both payload-bearing responses;
3. performs the configured source-map latency;
4. writes the 32-bit prepared source payload to both mirrored HBM arrays; and
5. completes the HLS-shaped 16-lane by 8-bank, 128-cycle reduction tail.

The controller does not dispatch a destination partition until this global
phase drains. Later rounds do not repeat source preparation because each apply
worker emits the next prepared source payload. Worker-local active count,
error, and dangling mass are reduced only at the superstep barrier.

## Dynamic degree correctness

Initial source payload is now derived from the degree payload read from HBM.
The dynamic PageRank test poisons the host-side degree vector after a timed
GraSU insert/delete batch; PageRank still matches both oracles. This proves that
the compute path consumes the updated HBM degree state rather than a stale host
shortcut.

## Physical request ledger

The evidence distinguishes logical AXI operations from physical backend beats.
This matters because the apply degree port is 32 bits wide: one logical 64-byte
degree read becomes 16 SST-HBM requests. Every compute AXI master now contributes
`beats_issued` and `beats_completed` to the system ledger. Acceptance requires:

```text
compute_axi_beats_issued == compute_axi_beats_completed
update_backend_requests + compute_axi_beats_issued == backend_requests
traffic request and byte classifications close exactly
```

The three SST smokes close this ledger with 1,621, 42,744, and 3,446 total HBM
requests for Full PageRank, residual PageRank, and three-partition dynamic Full
PageRank respectively. All architecture and mathematical oracle mismatch counts
are zero.

## Reproducible plugin binding

The PageRank runners previously used SST `--add-lib-path`. On this host that
could select the older `/home/chuxiao/spine-cycle-sim` plugin before the current
repository's plugin. All three runners now use `forced_sst_library_binding`,
pass an exact `--lib-path`, and record the plugin path and SHA-256 in each
manifest. The validated plugin SHA-256 is:

```text
9ae4b003a49aa37ed6b241fe3d2af87a65b274d2822deec535f42dc31ba57724
```

## Evidence summary

| Run | Result |
|---|---:|
| Weighted SSSP, 3 partitions, K=1 mock HBM | 10,576 cycles |
| Weighted SSSP, 3 partitions, K=2 mock HBM | 6,891 cycles |
| Full PageRank, 3 partitions, K=2 mock HBM | 4,334 cycles |
| Residual PageRank, 3 partitions, K=2 mock HBM | 80,648 cycles |
| Full PageRank SST smoke | 4,056 cycles; 1,621 requests |
| Residual PageRank SST smoke | 102,494 cycles; 42,744 requests |
| Dynamic Full PageRank, 3 partitions, SST | 8,082 cycles; 3,446 requests |

Machine-readable evidence is in
`docs/evidence/grasu_regraph_pagerank_k_pipeline_phase2b_20260728.json`.

## Claim boundary

This is normalized, execution-driven component evidence. The functional source
prepare order and payload match the current HLS prototype. Residual PageRank is
stored as one packed 8-byte state in the normalized simulator, while the current
HLS prototype exposes separate rank and residual arrays. The 128-byte state
traffic is represented, but exact native per-port contention remains a later
feasibility/native-profile concern. No FPGA cycle calibration is claimed here.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2 BUILD_DIR=../../build/sst

python3 scripts/run_sst_grasu_regraph_pagerank.py \
  --out-dir /data/tmp/chuxiao/phase2b_full --smoke --no-build
python3 scripts/run_sst_grasu_regraph_residual_pagerank.py \
  --out-dir /data/tmp/chuxiao/phase2b_residual --smoke --no-build
python3 scripts/run_sst_grasu_regraph_partitioned_dynamic_pagerank.py \
  --out-dir /data/tmp/chuxiao/phase2b_dynamic --smoke --no-build
```

