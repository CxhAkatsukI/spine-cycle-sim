# Current-FPGA zero-net claim boundary

## Decision

The current routed Spine hardware and the paper target do not implement the
same zero-net protocol.  A result from the current hardware-aligned profile
must not be labelled `zero_net_no_repair` unless batch reduction is moved ahead
of dirty-frontier publication in both HLS and the simulator.

This finding does not invalidate the AU/SU/WK/R19 insertion calibration rows.
Those rows contain effective mutations and exercise the current routed path.
It does prevent the old target-only zero-net representative from being mixed
into a figure described as entirely current-FPGA aligned.

## Paper target

The frozen algorithm contract says that a reciprocal batch is reduced by full
edge identity before publication.  A reduced zero-net batch publishes no new
analytic version and executes no repair.  The current paper text likewise says
that a zero-net batch performs neither switch nor repair.

Relevant local evidence:

- `docs/cc_residual_execution_contract_20260728.md`, lines 47-58;
- `/home/chuxiao/texpage-deltahls-latest/sections/02NN_programming_contract.tex`;
- `/home/chuxiao/texpage-deltahls-latest/sections/04NN_latest_view_hierarchy.tex`.

## Current HLS behavior

The HLS branch used by the routed owner-FIFO implementation is
`codex/paper-owner-fifos` in
`/home/chuxiao/spine-dynamic-graph-reduce-levels`.

1. `spine_sorter_kernel` sorts all input records and emits the original record
   count.  It does not coalesce signed differentials.
2. `partitioned_frontier_classify_reduce` groups records only by source and
   accumulates a destination-family mask.  Its `REDUCE` loop does not sum
   per-edge differentials.
3. `partitioned_mark_dirty_frontier_one_pass` publishes those source records
   before the L0 writer later coalesces full edge keys.

Consequently, a sorted `+e/-e` pair dirties its touched source even though the
L0 writer eventually cancels the edge group.  This is conservative and
correct, but it performs repair work forbidden by the target zero-net fast
path.

## Reproduction

The current-v9 plugin (`sha256
22a369e71e68b4e069371c11f6442274a05e21652499f98399e93fcc686666dd`)
was run with the owner-FIFO CC profile:

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

python3 scripts/run_sst_connected_components.py \
  --architecture spine \
  --profile configs/architectures/spine_owner_fifo_cc_hls_v1.json \
  --workload tests/data/connected_components_formal/cc_zero_net_base.slice \
  --update-workload \
    tests/data/connected_components_formal/cc_zero_net_delete_then_reinsert_u2.slice \
  --out-dir \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v9_rq3_20260812/targeted/zero_net_cc \
  --lib-dir cpp/sst/build/sst-current-fpga-v9 \
  --max-cycles 2000000000 \
  --max-rounds 256 \
  --no-build
```

The mathematical update has zero effective mutations and the final labels are
correct.  The current device path nevertheless dispatches and completes two
sources and processes two edges:

| Counter | Value |
| --- | ---: |
| physical update records | 4 |
| effective logical mutations | 0 |
| target initial active vertices | 0 |
| current-HLS source dispatches | 2 |
| current-HLS source completions | 2 |
| reader edges | 2 |
| compute edges | 2 |
| owner request/byte ledger | closed |
| FIFO ledger | closed |

The run is intentionally rejected by the current correctness gate because its
execution work does not equal the target no-repair architecture reference.

## Figure 10 policy

Until the mechanism is implemented, use one of these explicit treatments:

1. Omit the zero-net bar from a strictly current-FPGA figure and report the
   unsupported target mechanism in the limitations.
2. Show a current-HLS `zero_net_conservative_repair` bar, with the repair work
   included and without claiming the target no-op path.
3. Show the old `zero_net_no_repair` result only in a target-architecture panel
   whose provenance is visibly separate from current-FPGA calibration.

The preferred final treatment is to implement full-key batch reduction before
dirty publication in HLS and the simulator, synthesize the changed HLS, and
then regenerate the current-profile zero-net row.  Non-zero insertion
calibration parameters must not be refit from this corner case.
