# Shared normalized comparison runner

## Claim boundary

This milestone implements the fail-closed runner for the frozen 73-case shared
workload corpus. It compares source-following Spine against the normalized,
conversion-free GraSU plus PMA-native ReGraph proposal. Both run at 150 MHz and
use the same 32-channel SST/DRAMSim3 backend.

This is **normalized structural execution-driven simulation**. It is not a
native FPGA measurement, a calibrated absolute-cycle claim, or evidence that a
matching conversion-free GraSU/ReGraph HLS design has been synthesized. The
existing native GraSU/ReGraph path retains its conversion stage and separate
hardware-alignment evidence.

The complete matrix has not yet run. One filtered Full PageRank smoke pair is
recorded below to prove the orchestration and validation path. It is not a
headline speedup result.

![Shared normalized comparison runner](figures/shared_comparison_runner.svg)

## Execution and correctness contract

`scripts/run_shared_comparison_matrix.py` validates the hash-pinned source
manifest before launching any child. Every child receives the same graph or
graph/update bytes and algorithm parameters. The parent independently reloads
the child result and rejects it unless all of the following hold:

- architecture and mathematical mismatch counts are both zero;
- the named oracles match the algorithm contract;
- vertex, edge, and update counts match the frozen manifest;
- both systems report 150 MHz for normalized pairing;
- DRAM reports exactly 32 channels;
- DRAM reads plus writes equal the component backend-request ledger.

| Algorithm | Architecture oracle | Mathematical oracle |
|---|---|---|
| Weighted static/dynamic SSSP | synchronous frontier, saturating `uint32` | independent `uint64` Dijkstra |
| Full PageRank | iterative float32 Map-Reduce policy | independent iterative float64 |
| Thresholded residual PageRank | residual-push float32 policy | float64 Full PageRank, 200 iterations |

The runner writes `results.csv` for individual architecture runs and
`pairs.csv` only when both systems pass for the same run ID. A paired speedup is
therefore cycle-based at an identical clock and is labeled
`normalized_structural_execution_driven`.

Child processes start in separate process groups. A timeout first terminates
and then kills the complete process group so that SST or DRAMSim3 children are
not orphaned. `--resume` reuses a passing result only when both the complete
command, serialized run contract hash, and implementation fingerprint still
match. The fingerprint covers the compiled component library, SST executable,
memory config, architecture profiles, SST topology scripts, and child runners.
The matrix manifest reports executed and reused row counts separately; cached
rows retain the original simulation wall time and are marked in `results.csv`.

## Current smoke evidence

The filtered `syn_weighted_diamond_v8__full_pagerank` pair passed both oracles
and all parent gates:

| System | Cycles | Simulated time | Backend requests | Runner wall time |
|---|---:|---:|---:|---:|
| Spine | 20,072 | 0.133813 ms | 2,393 | 1.15 s |
| GraSU/PMA-native ReGraph | 133,053 | 0.887020 ms | 50,757 | 7.41 s |

For this one tiny case, the cycle ratio is 6.6288x in Spine's favor. It cannot
be generalized across algorithms, graph shapes, dynamic updates, or full
datasets. The output manifest correctly labels this run as a filtered subset
and sets `complete_matrix` to false.

Separate direct smoke runs also pass weighted SSSP, Full PageRank, thresholded
residual PageRank, and mixed dynamic SSSP on both normalized systems. These are
component bring-up checks, not a substitute for the complete frozen matrix.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/prepare_shared_comparison_workloads.py --verify-only

python3 scripts/run_shared_comparison_matrix.py \
  --run-id syn_weighted_diamond_v8__full_pagerank \
  --out-dir results/shared_driver_smoke \
  --jobs 2 \
  --no-build

python3 scripts/run_shared_comparison_matrix.py \
  --out-dir results/shared_comparison_full_20260725 \
  --jobs 4 \
  --resume \
  --no-build
```

The complete command schedules 146 system runs: 73 run IDs times two systems.
It is complete only when `comparison_manifest.json` says
`complete_matrix: true`, all 146 rows exist, and all 73 paired rows exist.

## Remaining evidence

- Execute and summarize the complete frozen matrix.
- Add full real-dataset performance runs; committed compact slices validate
  shapes and correctness only.
- Add dynamic PageRank batches rather than static PageRank alone.
- Add dense-batch, multi-partition scalability, and ablation matrices.
- Attach native and projected paths without relabeling normalized results.
- Extend selected-array activity evidence to every architecture/run class.
