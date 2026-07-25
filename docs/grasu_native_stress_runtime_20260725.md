# Native GraSU/ReGraph 4096-round stress runtime

Date: 2026-07-25

## Claim boundary

This is a measured simulator-host runtime and structural/correctness stress
gate for the existing-HLS native path. It is not an accelerator speedup. The
native execution remains serial:

```text
GraSU update -> barrier -> PMA compactor/conversion -> ReGraph SSSP
```

The conversion is included. The architecture retains 32 physical U55C HBM
pseudo-channels while SST instantiates only the reachable physical channels
`0`, `1`, `2`, `3`, and `30`. No architecture cycle, memory request, response,
FIFO stall, or superstep is fast-forwarded.

## Workload and runtime

The frozen `large_chain_v4096` case contains 4096 vertices, 4095 initial chain
edges, no updates, and 4096 ReGraph supersteps. The native host reorder maps
external source 0 to internal source 2721.

The complete matrix invocation took 1149.385 seconds, or 19.156 minutes. The
prior projection from `small_chain_v64` was 1163.840 seconds, so the measured
runtime was 1.242% lower. This passes the intended tens-of-minutes runtime gate
for this stress shape on the recorded AMD EPYC 7C13 host.

## Exact gates

The simulator completed in 141,070,050 core cycles:

| Component | Cycles |
| --- | ---: |
| GraSU update | 1 |
| PMA compactor/conversion | 462,648 |
| ReGraph compute | 140,607,401 |
| Controller gap | 0 |

All hardware-alignment structure checks pass: vertex, initial/final edge, PMA
slot, compact slot, source mapping, superstep, and update counts match the
frozen FPGA log. SSSP reports zero mismatches, and the native HLS capacity
contract is safe.

The run also exercises finite memory pressure rather than merely counting
bytes:

| Counter | Value |
| --- | ---: |
| SST-HBM requests | 71,311,872 |
| Maximum outstanding requests | 64 |
| Backend submit stalls | 665,423 |
| Backend response-queue stalls | 5,325,289 |
| Edge-array output stalls | 3,247,262 |

The five final DRAMSim3 channel reports account for exactly 20,979,712
completed reads and 50,332,160 completed writes, equal to the backend request
total. They report 2,315,475 ACT commands, 2,315,475 PRE commands, and 904,295
refresh commands. Their aggregate `total_energy` is 331,247,755,860 pJ, or
0.331248 J. That number covers DRAMSim3 HBM energy only; it excludes accelerator
logic, on-chip SRAM, host, and board energy.

Only final cumulative DRAMSim3 JSON/TXT reports are archived. Per-epoch files
are intentionally omitted because they are redundant and add about 6.4 MiB.

## Timing limitation

The execution-driven raw timing remains an unfitted, trend-only estimate. At a
200 MHz core clock, the simulator predicts 705.350 ms versus the 1432.893 ms
FPGA event window, an absolute E2E error of 50.77%. Conversion and compute-span
errors are 37.02% and 40.22%, respectively. This stress run therefore proves
runtime feasibility, structural fidelity, correctness, and modeled contention;
it does not prove absolute cycle accuracy. The separately fitted native event
envelope must be used for hardware-calibrated timing claims.

## Reproduction

Build the existing SST plugin, then run the frozen stress role:

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
make -C cpp/sst -j2

time python3 scripts/run_grasu_native_hw_matrix.py \
  --no-build \
  --roles stress \
  --case large_chain_v4096 \
  --out-dir results/grasu_native_sparse_large_20260725
```

Expected terminal gates include:

```text
PASS grasu_regraph_native_sst
PASS native hardware alignment
PASS native hardware matrix
```

Machine-readable summary and raw artifacts are in
`docs/evidence/grasu_native_stress_runtime_20260725.json` and
`docs/evidence/grasu_native_stress_4096_20260725/`.
