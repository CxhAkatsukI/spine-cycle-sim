# Original Mixed ReGraph Execution

This independent whole-graph control connects the artifact's 11-Little/3-Big
example from admitted original-host task buffers through all acknowledged PR
state writes. It reuses the independently tested original-R component family,
not the ported G+R kernel or production SST path. See the
[results and limits](../../experiments/comparisons/grasu_regraph_stage_validation/MIXED_GRAPH_EXECUTION.md).

## Ownership

| Boundary | Owner |
| --- | --- |
| Original mixed write arbitration | `cpp/include/spine_sim/original_regraph/mixed_indexer.hpp`, `cpp/src/original_regraph/mixed_indexer.cpp` |
| Binary descriptor and independent CSR arithmetic | `cpp/tests/original_regraph/whole_graph/mixed/input.hpp`, `oracle.hpp` |
| Named finite queues and shared memory | `resources.hpp` in the same directory |
| Little reader/Scatter/Gather/local merge | `little_path.hpp` |
| Big request/cache/Scatter/omega/banks/packer | `big_path.hpp` |
| Shared mergers, indexer, degree/Apply/writer and independent task progress | `wiring.hpp` |
| Complete pre-Apply observation, output replicas and conservation | `execution.cpp`, `verification.hpp` |
| Priority, unavailable-Little progress, finite backpressure and rejection | `indexer_tests.cpp` |
| Preparation/run/analysis/regression/instrumentation/package | `spine_cycle_sim/experiments/original_regraph_execution/mixed/` |
| CLI | `scripts/run_original_regraph_mixed.py` |

The existing Big merger gains a bounded multi-partition entry. Its original
entry delegates with count one; frozen Big source comparison and all previous
component/A4 results must remain exact. Other existing numerical bodies and
test fixtures are unchanged. No production SST Makefile entry is added,
because this family remains outside that plugin.

## Original Contracts

Original `merge_big_little_writes` in `acc_template/kernel_apply/acc_apply.h`
uses nonblocking Little-first arbitration, independent counters, and Big's
index starting after the dense extent. The new indexer preserves those rules:
Big can proceed while Little is unavailable, without a whole-dense barrier.
The 2-cycle index pipeline is a named assumption inherited from the existing
index stage, not an independently measured mixed-control HLS schedule.

Every path starts its next task only after its own prior task drains. There
is no group-wide writeback barrier or added host relaunch cost. Big merger
accepts the complete count of successive groups before execution; it does not
require an empty output and a host restart between groups. Finite streams
hold later group data until the continuous merger can consume it.

Little uses 11 private eight-lane destination arrays, each matching the
existing Little family. Big uses three separately routed eight-bank arrays.
Two global mergers feed the shared index/Apply path and 14 state replicas.
PR has `HAVE_VERTEX_PROP=false`; no extra Apply-private property write is
invented. Degree reads use original channel 30; path `k` uses edge channel
`2*k`, source and write channel `2*k+1`, for `k=0..13`.

## Publication Tail Safety

Original `partitionGraph` allocates `ceil(V/65536)*65536` property/degree words.
The mixed Apply publishes `dense*65536+sparse_groups*524288` words. The last
Big group is not clipped by the real graph size. Consequently two admitted
inputs require more state than the original host allocates. This is a source
geometry finding, not an observed board crash or a claim about unpublished
fixes in the authors' actual deployment.

The default binary interface rejects that case. The study explicitly sets
`ALLOW_PADDING=1`, allocating the maximum of the original and publication
extents, appending zeros only after the original buffers. Graph IDs, ordering,
all logical edges, tasks, arithmetic, and publication work remain unchanged.
All 14 output replicas and an allocation guard are checked, including every
padded word. No original source file or frozen capture is rewritten.

## Explicit Timing Assumptions

- Core clock: nominal 210 MHz; single original-host PR iteration, argument 0.
- Shared mock memory: 32 channels, 64-byte beats, baseline latency 64 cycles,
  one accepted beat/channel/cycle, registered round-robin arbitration.
- Every AXI master: 512 bits, 16-beat bursts, 16 outstanding bursts. Edge and
  Little source parents: two; Big source parents: 16; degree/writer parents:
  16 normally, one in the fixed pressure control.
- Little edge/request/response queues: 32; update, lane and local output: 8.
- Big queues retain frontend depths 32/16, omega layers 16/2, private route
  queues 2, bank pairs 4, packed output 8. Cache wrapper live slots: 32.
- Global merged, indexed and applied queues: 8. AXI interface queues: 32.
- Existing component pipeline latencies/credits remain named assumptions from
  their separately documented source and HLS controls.

This is not an exact HLS global-stall, AXI coalescing, memory-controller or
board model. Original graph-selected topology, throughput denominator,
publication event window and realistic memory service admission remain open.
Whole-state correctness and exact regressions cannot by themselves close
those timing gates.
