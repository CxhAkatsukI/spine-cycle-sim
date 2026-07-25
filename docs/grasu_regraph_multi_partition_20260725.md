# GraSU + ReGraph multi-partition compute milestone

Date: 2026-07-25  
Branch: `codex/fine-grained-cycle-sim`  
Parent commit: `1bca4c3e2e9c41118a928c5add237ae338956281`

## Scope and claim tier

This milestone removes the one-destination-partition functional restriction
from PMA-native ReGraph compute. It is a **simulation-only normalized
architecture proposal**. It has not yet been synthesized or calibrated against
an xclbin, and it does not claim the throughput of ReGraph's original parallel
multi-CU host schedule.

One physical reader/gather/merger/apply/HBM-wrapper pipeline is reused serially
for every destination partition. `supersteps` counts algorithm iterations;
`partition_passes` counts physical partition invocations. These counters must
not be interchanged in performance reports.

## HLS mapping

The implementation follows these behaviors in `/home/chuxiao/ReGraph`:

- `host/preprocess/graph_preprocess.cpp` partitions each edge by global
  destination and encodes a local destination.
- `host/host.cpp` supplies `part_dst_offset` to each gather/scatter kernel.
- `acc_template/kernel_big_gs/kernel_scatter_gather.cpp` consumes local
  destinations and forwards `part_dst_offset` with the result stream.
- `acc_template/kernel_big_gs/acc_gather.h` uses a fixed-size local URAM window,
  emits the whole window, and clears it during writeout.

The simulator therefore preserves the 19-bit `local_dst + weight12` PMA word.
It does not widen every stored edge to carry a global destination.

Reference SHA-256 values:

| File | SHA-256 |
|---|---|
| `graph_preprocess.cpp` | `992a0227b4893eafb11eae95adcd51d8f033840112aea15c8eb7642a1aedb9cb` |
| `host.cpp` | `bbd503916824da7b7f294276be26511ec3c98b803082055ff75aada53a499ecf` |
| `acc_gather.h` | `866d582ebabdb312d32661d929311e018903f64997cebd0caa6f3a9c3742f79e` |
| `kernel_scatter_gather.cpp` | `70939aa4c8d61da3b6349639b07d4d58ef49acf439ba17b203c26e2fef639a8e` |

## Execution semantics

`GraSuPartitionedPmaLayout` keeps one PMA per destination partition. Every PMA
retains all global source rows, while each encoded destination is relative to
that partition's base. A 4 GiB configurable address stride separates row and
PMA payload windows; partition zero retains the historical addresses.

For one superstep:

1. The controller fixes the old ping-pong source-state epoch.
2. Each destination partition scans its own global source rows and PMA.
3. Gather and merger sweep one fixed `partition_vertices` window.
4. Apply reads/writes `vertex_state[part_dst_offset + local_dst]`.
5. The HBM wrapper writes the same global window into the next source-state
   epoch on both modeled channels.
6. Active counts and iteration error are accumulated across all partitions.
7. Only the final partition may end the algorithm or advance the superstep.

For PageRank, partition zero scans every source and computes dangling mass once.
Later partitions reuse that iteration context and read source degree/state only
for non-empty source rows. This prevents dangling mass from being multiplied by
the number of destination partitions.

## Directed validation

The tests use 33 vertices, `partition_vertices=16`, and therefore three
destination windows including a one-vertex partial final partition.

| Algorithm | Result | Key evidence |
|---|---:|---|
| Weighted SSSP | pass | 10,576 cycles; 5 supersteps; 15 partition passes; 495 row reads |
| Full PageRank | pass | 8,095 cycles; 3 partitions; 108 degree reads; rank sum 1.0 |
| Thresholded residual PageRank | pass | 155,326 cycles; 57 iterations; 171 partition passes; 285 active edges |

SSSP follows a path whose destination sequence crosses partitions
`1 -> 0 -> 2 -> 1`. PageRank has 29 dangling vertices, so repeated dangling
accounting would fail visibly. Residual PageRank checks the union of active
vertices across all partitions against an independent float32 oracle.

The previous 15 single-partition tests remain exact. In particular:

- Full PageRank: 1,243 cycles.
- Residual PageRank: 32,944 cycles.
- Native fixed-partition scan: 99,257 cycles.
- Finite-stream contention: 15,037 cycles.

## Reproduce

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2 --target grasu_cycle_tests
./build/cycle-core/cpp/grasu_cycle_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
```

Machine-readable evidence is in
`docs/evidence/grasu_regraph_multi_partition_20260725.json`. The architecture
diagram is `docs/figures/grasu_regraph_multi_partition.svg`.

## Remaining boundary

- GraSU update routing is not yet execution-driven across these partitions.
- Insert/delete degree read-modify-write traffic is not yet timed.
- The multi-partition tests currently use `MockMemoryBackend`; SST-HBM closure
  and DRAM activity evidence are the next integration gate.
- This profile serializes partition passes. Original ReGraph can schedule
  multiple kernels/CUs; any parallel profile must model those resources and
  shared-memory contention explicitly.
- No real dataset, hw/hw_emu calibration, energy, area, or timing claim is made
  by this milestone.
