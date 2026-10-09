# GraSU + ReGraph PMA-Native Contract

Date: 2026-07-25

## Purpose

This freezes the implementation boundary for the GraSU comparator before its
cycle model is added. It distinguishes four systems that must never be mixed
in one performance label:

| Label | Meaning | Conversion treatment |
| --- | --- | --- |
| `native` | Existing routed U55C GraSU + ReGraph integration | Measures the one-shot PMA-to-edge-array compactor |
| `hls_sw_emu` | Conversion-free weighted-PMA HLS at revision `ff13a67` | Direct 8-lane AXIS handoff; correctness only, no performance claim |
| `normalized` | Same fine-grained memory/FIFO/AXI core and resource budget used for the Spine comparison | ReGraph reads PMA directly; no conversion exists |
| `projected` | Explicitly optimized PMA-native design-space point | Direct PMA reader plus change-aware activation |

The native profile validates the old compactor path and available hardware
trends. The HLS-emulated profile proves that a weighted conversion-free whole
system can compile and execute, but not its hardware speed. The normalized
profile is the primary fair simulator comparison. The projected profile is an
optimization experiment, not a hardware result.

## Source Identities

- GraSU: `/home/chuxiao/GraSU`, revision `b79ccb0`, branch
  `codex/explore-grasu-u55c`.
- Existing integration: `/home/chuxiao/grasu-regraph-integration`, revision
  `a9aef06`, branch `codex/pure-hw-pipeline`.
- Weighted PMA-native HLS: `/home/chuxiao/grasu-regraph-integration`, revision
  `ff13a67`, branch `codex/weighted-pma-native-hls`.
- ReGraph source: `/home/chuxiao/ReGraph` (the root is not a Git repository, so
  every mapped file must be hashed in later implementation evidence).

The audit did not modify any of these reference repositories.

## GraSU Update Topology

1. Four `bin_search` CUs each read one update stream from HBM. The current U55C
   build defines `GRASU_COMPACT_HBM_PORTS`, so each CU runs
   `bin_search_direct`: one ordered update at a time reads source row bounds
   and then binary-searches 64-bit segment-head records. The 64-worker BIPA
   implementation remains in the original source but is not in this xclbin.
2. The four result streams enter one `dispatch` CU in fixed round-robin order.
3. `segment_head_slot[31:5] < MAX_CACHE_SEGMENT` selects cache versus DDR;
   slot bit 4 selects one of the two CUs in that class.
4. Each DDR CU divides work between two PMA halves; each half routes by address
   to 16 lanes. A lane reads one 512-bit segment, inserts or deletes one 32-bit
   destination in sorted order, and writes the complete segment.
5. The original cache path uses 16 single-port URAM banks. The current
   integration defines `GRASU_PURE_PIPELINE_DIRECT_CACHE`, so each cache CU
   instead processes its ordered input serially with one HBM segment RMW at a
   time. Native and normalized profiles preserve that behavior. The 64-worker
   search and 16-lane URAM cache are explicit projected features only.

All AXIS links are finite registered FIFOs in the simulator. Every PMA access
uses `FixedAxiPort` and the same `MemoryBackend` selected for Spine. No stage is
allowed to mutate a Python/C++ logical PMA mirror before the AXI write response
commits.

## PMA Capacity Semantics

GraSU does not allocate PMA capacity online. Host preprocessing merges initial
edges with all future insertions, rounds every source row to a multiple of 16,
and initializes non-live reserved slots with bit 31 set. Binary-search heads
are derived from that reserved image.

The simulator therefore needs both `initial_edges` and `reserved_updates` when
constructing a PMA image. An insertion without a reserved slot is an explicit
capacity failure. Silently extending the row would model a stronger system
than the HLS design.

## ReGraph Boundary

The old routed hardware path is:

```text
GraSU PMA -> capacity-wide PMA compactor -> edge array -> ReGraph little-GS
```

It is valid native hardware evidence, but the compactor dominates larger sparse
cases because it scans reserved slots. Removing its time while retaining its
materialized edge array is forbidden.

The `ff13a67` HLS-emulated path is:

```text
GraSU weighted PMA -> completion barrier -> 8-lane AXIS PMA adapter
                   -> ReGraph little-GS -> merger -> apply/HBM wrapper
```

It has no compact edge array. Weight changes lower to deletion of the old
encoded word followed by insertion of the new encoded word. PMA reservations,
binary heads, and ordering use the complete encoded destination-and-weight
word. The host reorders vertices using physical update density and executes a
fixed number of synchronous SSSP rounds.

The normalized and projected simulator path is instead:

```text
GraSU PMA -> PMA-native row/segment reader -> shared Map/Reduce policy
          -> ReGraph gather/apply state
```

The PMA reader emits only after real row-metadata and 512-bit segment reads.
Empty lanes are decoded, but no compact graph copy is created. Update and
compute may overlap only if dependency and memory-contention evidence permits
it; the initial implementation uses a completion barrier.

## Acceptance Gates

The first executable vertical slice is accepted only when it provides:

1. exact PMA payload equality against an independent set/multiset oracle after
   insert and delete batches;
2. cache/DDR and both-half routing coverage, including segment indices around
   `2 * MAX_CACHE_SEGMENT`;
3. an explicit capacity-failure test;
4. finite FIFO backpressure and shared-HBM contention counters;
5. identical final algorithm values from PMA-native compute and a graph oracle;
6. byte ledgers for updates, row metadata, binary heads, PMA RMW, vertex state,
   and any native-only conversion;
7. separate result manifests for native, HLS-emulated, normalized, and projected profiles.

Until those gates pass, the remaining GraSU/ReGraph comparison gap is
structural, not a calibrated performance result.

## Reproduction

Validate profile schema, source-frozen topology, and current hardware hashes:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 -m unittest tests.test_architecture_profiles -v
```

Regenerate the architecture figure:

```bash
dot -Tsvg docs/figures/grasu_regraph_pma_native_contract.dot \
  -o docs/figures/grasu_regraph_pma_native_contract.svg
```
