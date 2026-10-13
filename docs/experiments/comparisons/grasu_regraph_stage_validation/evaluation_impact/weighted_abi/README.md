# Weighted Source Compatibility

## Decision

The current weighted, destination-sharded host layout is functionally compatible
with the pristine GraSU binary-search unit and hot-cache edit operation on the
declared matrix below. Both the existing adapter and bank-stream candidate
emit the independently expected post-update logical graph.

This closes a **source-functional subset** of the weighted ABI question. It
does not admit complete G timing, a production cache implementation, a complete
G-to-ReGraph execution, or a published-performance match. The previous
[large-batch G performance failures](../hot_lanes/README.md) remain failures.
Neither production HLS nor core/SST numerical code changes in this checkpoint.

## Reading Order And Code

1. [Evidence index](evidence/index.json): all four attempts, source identities,
   compact archives, failures and claim flags.
2. [Fixtures and independent oracles](../../../../../../cpp/tests/evaluation_impact/common_g/weighted_abi/fixture.hpp):
   logical input and per-segment edit expectations.
3. [Search/dispatch checks](../../../../../../cpp/tests/evaluation_impact/common_g/weighted_abi/search.hpp)
   and [composition](../../../../../../cpp/tests/evaluation_impact/common_g/weighted_abi/control.cpp).
4. [Runner package](../../../../../../spine_cycle_sim/experiments/evaluation_impact/common_g/weighted_abi/):
   preparation, bounded execution, analysis and delivery have separate owners.

## What Is Executed

Each arm starts from the actual integration host's
`build_weighted_partitioned_pma_graph` output. Every physical operation goes
through pristine `binary_search`, current `dispatch`, and either pristine
`process_1` or the candidate `lane_update` helper. Complete PMA state is checked
after **every** edit, including padding and untouched segments. Actual adapter
source then reads that edited PMA; packet counts, masks, dummy flags, terminal
position, vertex translation, edge uniqueness and logical final state are
checked independently. Host-generated final-state expectations are not used
as the logical oracle.

The weighted encoding is a full 32-bit sortable word: 19 local-destination
bits, 12 weight bits, and an invalid-slot bit. Reserved segment heads and PMA
words are sorted by the **complete encoded word**, not just destination ID.
A weight replacement deletes the old encoded edge and inserts the new one.
Thus the original full-word comparison is compatible in principle; the test
checks its actual routing and edit behavior, including movement between
reserved segments.

| Case | Vertices / partition span | Physical edits per arm | Shards | Segments | Final edges |
| --- | --- | ---: | ---: | ---: | ---: |
| Empty | 8 / 4 | 0 | 2 | 2 | 0 |
| Segment/weight changes | 128 / 64 | 36 | 2 | 9 | 120 |
| Repeated replacements | 96 / 32 | 40 | 3 | 9 | 8 |
| Destination/weight limit | 524,288 / 524,288 | 5 | 1 | 1 | 1 |

Four cases x two cache-edit arms x two adapter modes = **16 passing rows**,
324 physical edits checked in total. The boundary case includes local
destination 524,287, weight 4,095 and encoded valid word `0x7fffffff`.
An additional dispatch-only check covers both parities on both sides of the
hot/cold threshold; it does **not** test cold DDR edits.

## Results And Retained Failures

| Attempt | Outcome |
| --- | --- |
| `g-weighted-source-abi-v1` | Retained compile failure: missing vendor `include/etc` search path |
| `g-weighted-source-abi-v2` | Retained compile failure: pristine config lacks integration-only debug macro |
| `g-weighted-source-abi-v3` | All source state/packet markers pass, but the strict diagnostics gate rejects vendor width warnings; retained as failed |
| `g-weighted-source-abi-v4` | Fresh run passes the complete matrix and explicitly classified diagnostics |

The pristine insertion expression `res_data |= update_edge` combines 512-bit
and 32-bit vendor integers. Vendor headers emit exactly two warning lines for
each of the original arm's 40 insertions, in each adapter mode. The analyzer
requires the exact **40 warning pairs** and full intermediate-state checks;
unknown warnings, missing/extra pairs and leftover-stream diagnostics fail.
No pristine expression was rewritten to silence this warning. The current
dispatch's debug-print macro is defined as a no-op; algorithm logic is intact.

GCC 15.2.0, `-O1 -D_GLIBCXX_ASSERTIONS`, CPU 127, Vitis HLS 2024.1 headers.
Each compile/run has a 180-second timeout, 1-GiB cgroup and address-space cap,
no swap, and an 8-GiB host reserve. The two adapter modes run sequentially.
Peak observed process RSS: compilation 481,176 KiB, execution 26,036 KiB.
These are process peaks, not simultaneous process-tree totals; the cgroup
provides the aggregate hard cap. C execution took 0.15 / 0.21 seconds; **these
wall times are not device latency measurements**.

## Limits And Next Gates

- C streams are unbounded and calls are sequential; no finite-FIFO deadlock,
  AXI backpressure, HLS schedule or cycle-accuracy claim follows.
- Cache load/writeback is reconstructed by the fixture. Whole-cache load,
  16-lane concurrency and registered-pipeline RTL timing require the separate
  [cache probes](../cache_probe/README.md).
- The candidate helper extraction has not yet passed a fresh HLS/RTL run;
  this source test cannot transfer the earlier frozen helper's timing proof.
- The original search **unit** is tested, not the full parallel-search
  controller or its clock closure. Its previous timing gate remains open.
- All edited data lies in the hot region. Cold update/writeback, cache-capacity
  overflow, full G resource fit and production integration remain untested here.
- Adapter packet correctness is not downstream ReGraph convergence or a
  measured host-orchestration window. Those remain explicit later gates.
- Public source16 and paper8 geometry are still separate identities. This
  weighted source check does not reproduce the published GraSU throughput.

## Reproduce

From the repository root, with a fresh output path and sufficient memory:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.study \
  --output /path/to/fresh-weighted-source-control \
  --upstream /path/to/pinned-pristine/GraSU/GraSU_kernels/src \
  --integration /path/to/grasu-regraph-integration \
  --hls-include /path/to/Vitis_HLS/2024.1/include

python3 -m unittest tests.test_grasu_weighted_source_abi \
  tests.test_grasu_weighted_source_abi_delivery -v
```

The committed archives retain frozen source, report, compiler dependency
identities, stdout/stderr and resource logs. Generated binary SHA-256 identities
are recorded; executables and proprietary vendor headers are not bundled.
Raw attempts remain under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/`.
Offline archive verification does not need these machine-local paths.
