# Candidate10 HLS-derived normalized v3 baseline

## Purpose

This baseline replaces normalized v2 as the latest structural comparison
configuration. It answers a narrow scientific question: what happens when the
two execution-driven simulators use one FPGA/HBM platform contract while each
side preserves the closest known implementable datapath?

Native alignment is still useful, but only as a mechanism-validation anchor.
Native cycles are not scaled into normalized results. The comparison path is:

1. validate reusable mechanisms against native/component HLS evidence;
2. run both architectures through the same FIFO, AXI, and SST/DRAMSim3
   substrate;
3. preserve architecture-specific dataflow, port mapping, contention, and
   required algorithm work; and
4. permit a headline claim only after symmetric matching-HLS and sensitivity
   gates pass.

## What changed from v2

Normalized v2 is retained as an immutable audit point. V3 is generated from the
three pinned GraSU/ReGraph HLS profiles and corrects every known v2-to-HLS
parameter mismatch:

| Mechanism | v2 | HLS-derived v3 |
|---|---:|---:|
| ReGraph Map/Reduce lanes | 4 | 8 |
| AXI outstanding requests per port | 32 | 16 |
| PMA edge comparison | simplified weighted word | full 32-bit packed word |
| Dynamic PageRank degree maintenance | untimed | timed read-modify-write |
| Comparison clock | 150 MHz | 150 MHz |

The first four fields are architecture-fidelity corrections. The 150 MHz clock
is the shared platform normalization; the closest GraSU/ReGraph HLS requested
200 MHz. No lane, queue, channel, or algorithm optimization is hidden in v3.

The generated artifacts are:

- `configs/architectures/grasu_regraph_candidate10_normalized_hls_*_v3.json`;
- `configs/contracts/grasu_regraph_candidate10_hls_capabilities_v3.json`;
- `configs/contracts/candidate10_normalized_hls_feasibility_v2.json`; and
- `configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json`.

Regenerate or verify them with:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_hls_derived_normalized_v3.py --write
python3 scripts/prepare_hls_derived_normalized_v3.py
```

The generator pins its v2 source manifest, Spine parent and normalized
profiles, GraSU/ReGraph HLS profiles, and HLS evidence summary by SHA-256.

## Algorithm contracts

All three algorithms use architecture-state validation plus an independent CPU
mathematical oracle.

- Weighted SSSP preserves ReGraph's host-controlled fixed-superstep mechanism.
  For each workload, the CPU oracle selects the minimum number of synchronous
  rounds that produces the correct result. Oracle execution time is excluded.
  This is deliberately favorable to GraSU/ReGraph and avoids charging arbitrary
  extra rounds, but it is not automatic hardware convergence.
- Full PageRank performs exactly three iterations and includes dynamic degree
  read-modify-write work.
- Thresholded residual PageRank uses damping `0.85`, epsilon `1e-6`, at most
  256 iterations, and includes the same dynamic degree work.

All graph and update files, algorithm parameters, and profile hashes are frozen
in the 73-run manifest. Static PageRank rows use an explicit empty update;
dynamic PageRank behavior is validated separately below.

## Executed smoke evidence

The three-algorithm static smoke ran on the same eight-vertex weighted-diamond
holdout fixture. All six architecture rows passed both correctness oracles,
profile identity checks, physical HBM binding checks, and request-ledger checks.

| Algorithm | Spine cycles | GraSU/ReGraph cycles | GraSU/Spine cycle ratio |
|---|---:|---:|---:|
| Weighted SSSP | 58,618 | 200,002 | 3.412x |
| Full PageRank | 32,069 | 132,892 | 4.144x |
| Thresholded residual PageRank | 689,247 | 2,727,372 | 3.957x |

These ratios are not performance conclusions. They are one tiny graph and are
admissible only as structural smoke evidence. In particular, GraSU/ReGraph has
zero of three exact matching whole-system HLS implementations at this point.

Reproduce the static smoke with:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_shared_comparison_matrix.py \
  --claim-scope structural_exploratory \
  --run-id syn_weighted_diamond_v8__weighted_sssp \
  --run-id syn_weighted_diamond_v8__full_pagerank \
  --run-id syn_weighted_diamond_v8__residual_pagerank \
  --out-dir docs/evidence/candidate10_hls_v3_profile_smoke_20260726 \
  --jobs 3 \
  --no-build
```

The dynamic smoke applies five logical updates. Full-word weight replacement
lowers these to eight physical delete/insert operations. Results were:

| Algorithm | Update cycles | Compute cycles | Total cycles | Key dynamic evidence |
|---|---:|---:|---:|---|
| Weighted SSSP | 116 | 99,294 | 99,410 | 2 oracle-minimum fixed rounds |
| Full PageRank | 186 | 132,834 | 133,020 | 8 degree reads and 8 degree writes |
| Residual PageRank | 186 | 2,829,751 | 2,829,937 | 8 degree reads and 8 degree writes |

The raw manifests, SST logs, result files, and DRAM channel statistics are under
`docs/evidence/candidate10_hls_v3_dynamic_smoke_20260726/`. A compact,
hash-pinned index is
`docs/evidence/candidate10_hls_v3_smoke_summary_20260726.json`.

## Claim gate

V3 is the current baseline for correctness, structural timing, traffic,
contention, stalls, and sensitivity studies. The runner permits
`structural_exploratory` and labels every row accordingly.

It rejects these claims before SST starts:

- `headline_normalized_performance`;
- `iso_resource_performance`; and
- `fpga_measured_performance`.

Promotion requires a timing-dispositioned weighted whole system and complete
Full/Residual PageRank HLS paths including adapter, queues, state storage,
degree RMW, convergence/host control, resources, and timing. The final matrix
must then use disjoint calibration and holdout datasets and demonstrate that
reasonable FIFO/AXI/HBM uncertainty does not reverse the reported ordering.

## Prepared HLS work

Run the long jobs sequentially. First retry the existing weighted whole-system
route:

```bash
cd /home/chuxiao/grasu-regraph-integration
/data/tmp/chuxiao/grasu_regraph_weighted_sssp_native_hw_relink_route_aggressive_a927186_20260726/link_command.sh \
  > /data/tmp/chuxiao/grasu_regraph_weighted_sssp_native_hw_relink_route_aggressive_a927186_20260726/link.stdout.log \
  2>&1
/data/tmp/chuxiao/grasu_regraph_weighted_sssp_native_hw_relink_route_aggressive_a927186_20260726/collect_result.sh
```

Then compile the isolated eight-lane algorithm policies:

```bash
cd /home/chuxiao/grasu-regraph-integration
/data/tmp/chuxiao/regraph_algorithm_policy_hw_20260726/compile_commands.sh \
  > /data/tmp/chuxiao/regraph_algorithm_policy_hw_20260726/compile.stdout.log \
  2>&1
```

The isolated policy XOs establish arithmetic feasibility only. They do not
promote Full or residual PageRank without their complete data paths.
