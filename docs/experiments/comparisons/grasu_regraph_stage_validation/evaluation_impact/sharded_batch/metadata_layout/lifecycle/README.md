# Resident Multi-Batch Metadata Check

## Decision And Scope

The three-shard, three-batch correctness diagnostic passes all 12 declared
executions and 36 batch observations. Shared and replicated metadata preserve
the same complete PMA state as the independent prepared-shard original.
Replicas remain coherent because the reservation metadata is fixed before
the first batch, not because metadata maintenance is free.

This closes a bounded resident-state consistency check, **not production G
admission or general performance retention**. Small batches pay large fixed
cache costs and cannot establish large-batch search performance. The
[preceding 72-row diagnostic](../README.md) owns the larger chronological
performance result. No production model, HLS host/kernel, SST plugin, paper
or frozen figure package is changed here.

| Deliverable | Purpose |
| --- | --- |
| [Matrix and decision](evidence/index.json) | All 12 executions, resources, complete states and timing boundaries |
| [72-row replay](replay/index.json) | Exact pre-extraction regression, including every old copy control |
| [Failed preflight](preflight/index.json) | Failed build and incomplete runtime attempt, never counted as accepted |
| [HLS connectivity audit](HLS_CONNECTIVITY.md) | Legal existing ports versus actual host changes and hardware gates still required |

## Fixed Inputs And Execution

Both synthetic inputs have 161 vertices, three destination shards of at most
64 vertices, and 2,304 initial directed weighted edges. Each shard has 32
updated source rows with 24 initial edges per row. All update rows span two
segments; every physical update makes one binary probe. All physical edits
are in the hot cache. These are not temporal datasets or cold-region tests.

| Input | Batch 0 | Batch 1 | Batch 2 |
| --- | --- | --- | --- |
| staggered | 128 physical edits in shards 0 and 1 | Empty | 192 physical edits across all three shards |
| all-active | 192 physical edits across all three shards | Empty | 192 physical edits across all three shards |

Each logical weight replacement is a delete followed by an insertion. Batch 0
changes weight 3 to 1; batch 2 changes the then-current weight to 5. The second
batch is an empty identity check, not a throughput point. In `staggered`, the
last batch also touches a previously untouched shard.

The union of future edits determines reservation once, before batch 0. As in
the prior complete-cache controls, each shard has an identical empty tail
reservation so both cache halves are complete. The same physical layout is
supplied to every arm. This deliberate padding is not a realistic memory
footprint claim.

Two memory-latency assumptions (64/128 cycles) cross three arms: independent
`original-prepared-shards`, `candidate-runtime-23`, and `runtime-both-copies`.
The two runtime arms retain **one backend and one initial PMA allocation**
through all batches. Only update-buffer contents change between batches;
PMA and metadata are not restored. Updated shards are processed sequentially,
paying the complete 16-MiB cache preload and acknowledged writeback each time.
The shared arm additionally matches a fresh call to the actual sharded update
wrapper on each batch, with exact cycles and traffic.

The original control retains its independent prepared-shard execution. Its
next input is the previous batch's fully checked state, but it does not have
the runtime candidate's persistent allocation. This is an explicit control
boundary, not equal host/resource cost.

## Results And Resource Accounting

For every batch, all arms agree on complete canonical state after physical
payload checks. Empty batch 1 equals batch 0, while batch 2 differs and equals
the final oracle. Checks cover full PMA, untouched shards, metadata, every
replica, non-owner buffers, padding, complete request drain and conserved
per-port traffic. Every nonempty batch's runtime cycle difference is below
0.022% from the original; shared and replicated times coincide on these small,
cache-dominated inputs. That result does **not** erase the original runtime's
22.7--35.5% slowdown on the separate 64K chronological cases.

| Runtime layout | Allocated bytes | Summed bank spans | Extra metadata | Initial logical metadata upload |
| --- | ---: | ---: | ---: | ---: |
| Shared | 56,709,120 | 56,709,120 | 0 | 6,295,344 B |
| Both tables copied | 81,924,096 | 113,360,896 | 25,214,976 B | 31,476,720 B |

All 23 existing graph banks are already used by this three-shard fixture.
Each table retains its original and adds four copies at fixed channels
`[3, 9, 15, 20]`. Copies use common 4-KiB-aligned bases; gaps count toward bank
spans. Every region is nonoverlapping and below 512 MiB per bank. No physical
master or credit budget is added. Additional allocation is about 24.05 MiB,
not the one-shard study's 8.30--8.61 MiB.

The upload ledger counts logical initialization bytes; it is **not measured
DMA or CPU time** and excludes allocator padding. Inter-batch metadata upload
is zero only because row bounds and reserved search heads remain immutable
under this predeclared edit sequence. Any new reservation, rebalancing or
changed search heads requires refreshing all affected copies before launch.
No general dynamic-coherence protocol is implemented or timed here.

Device timing starts with prepared resident inputs and ends after all writes
drain. Reservation, allocation, replication/upload, DMA, host launch/wait,
relaunch, degree/seed preparation and ReGraph are excluded on every arm.
All production, hardware, original-publication and host-inclusive admission
flags remain false. The [connectivity audit](HLS_CONNECTIVITY.md) confirms
existing legal port ranges, not a compiled or measured replicated design.

## Review And Reproduction

The C++ owner is
`cpp/tests/evaluation_impact/common_g/sharded/metadata_layout/lifecycle/`:
`fixture.hpp` prepares inputs and an independent edit oracle; `residency.hpp`
owns persistent allocation, copies and full physical checks; `execution.hpp`
owns bounded batch execution and traffic checks; `main.cpp` is the thin CLI.
The shared `metadata_layout/replicas.hpp` owns replica allocation only.
Python declaration, resource validation, analysis and execution/packaging are
separate modules under the corresponding `lifecycle/` package.

Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-metadata-lifecycle-v1`.
`attempt-v3` is complete. Before edits, source at `2857860` was frozen in
`g-metadata-layout-v1/pre-lifecycle-2857860.tar.gz`, SHA-256
`d7909f0940e78a4e3df1a73955cb61d06e2df7055170af7a3af28a64ac15f182`.
The matrix pins actual source, compiler/flags, libraries, binary and affinity.
The portable raw capsule contains the contract and all stdout/stderr/resource
records. Large canonical state files remain hash-indexed outside Git.

`attempt-v1` failed strict compilation before numerical execution; explicit
integer types and copying a temporary region value fixed the warnings.
`attempt-v2` passed four independent-original rows but failed all eight runtime
rows when re-registering a source ID on batch 2. The harness now assigns
distinct IDs to recreated ports and still requires zero outstanding requests
and removed old components at each boundary. Simultaneous port count is
unchanged. Both failed attempts remain in the separate preflight capsule.

The successful lifecycle steps took 242.2 seconds total, with maximum recorded
process RSS 1,100,512 KiB (1.05 GiB). Execution is serial and CPU-affined, with
a 2-GiB address-space limit, 8-GiB reserve and 600-second per-step timeout.
Minimum available memory at admission was 23.12 GiB. Larger queued HLS/R jobs
retain their own stricter gates; none is counted as completed here.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.study run \
  --output /path/to/fresh-resident-check \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.study package \
  --matrix /path/to/fresh-resident-check/results.json --output /path/to/fresh-evidence

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.study run \
  --output /path/to/fresh-layout-replay --prepared /path/to/chronological-inputs \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.study package \
  --matrix /path/to/fresh-layout-replay/results.json --output /path/to/fresh-replay-evidence

python3 -m unittest tests.test_grasu_metadata_lifecycle tests.test_grasu_metadata_lifecycle_delivery -v
```

The delivery test compares all 72 replayed observations and full-state hashes
exactly with the preceding capsule. It does not compare elapsed host wall time
or paths, which necessarily differ. The replay's successful bounded steps took
392.6 seconds with maximum process RSS 393,316 KiB (0.375 GiB).
The 69 focused Python/delivery/organization tests pass, including refusal to
package a changed intermediate batch state. These are focused harness and
regression checks, not a new full core/SST run or new hardware validation.

## Remaining Work

1. Larger multi-shard chronological batches, mixed hot/cold occupancy and
   changed-reservation coherence; this fixture verifies only fixed metadata.
2. Actual host replica allocation/binding/upload and measured preparation cost.
3. Finite-search/cache schedules, whole-G clock/resource fit and board evidence.
4. R resource/publication controls, measured host/seed windows and physical
   integration, then an honestly admitted warm-state Spine comparison.

No new Spine demo or replacement Figure 7--11 follows from this lifecycle check.
