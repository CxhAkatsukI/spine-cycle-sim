# Native simulator scheduler runtime optimization

Date: 2026-07-25

## Claim boundary

This milestone changes simulator host execution cost only. It does not skip an
architecture cycle, collapse a ReGraph superstep, approximate an HBM request,
or change a FIFO/AXI/DRAM counter. Its claim class is
`simulator_host_runtime_only`.

The native serial pipeline constructs update, compactor, and compute systems in
sequence. Before this change, every component from a completed stage remained
registered with the C++ scheduler and received `prepare`, `evaluate`, and
`commit` calls during all later stages. Those calls could not change hardware
state after the stage and shared backend had drained, but consumed host CPU.

The implementation now:

1. provides an exact `Scheduler::remove_component()` operation;
2. unregisters every FIFO, AXI master, and stage component only after the
   system reports `done` and all ports are idle;
3. freezes the stage's `end_cycle` when it is unregistered;
4. retains the shared SST memory backend;
5. uses an allocation-free one-clock scheduler path while preserving the
   global `prepare -> evaluate -> commit` ordering.

No cycle fast-forward is implemented here.

## Equivalence and runtime evidence

Both cases ran against the same SST/DRAMSim3 HBM configuration on an AMD EPYC
7C13 host. Each before/after pair produced byte-identical `result.json` files.

| Case | Supersteps | Before | After | Speedup | Result SHA equal |
| --- | ---: | ---: | ---: | ---: | --- |
| `tiny_chain_v16` | 16 | 24.963 s | 21.723 s | 1.149x | yes |
| `small_chain_v64` | 64 | 93.846 s | 84.655 s | 1.109x | yes |

The exact result identities are:

```text
tiny_chain_v16  6982b5bc138838bc6928284eb28112d71194786da6c76a09734dd2cd130fbabd
small_chain_v64 7265d22fdb3edcc05ca8c55c0c66feac19d3db02e0f4c7929d709a7ec2ec56f0
```

These are single-run engineering measurements. They are not accelerator
performance numbers and must not enter a Spine-versus-GraSU plot.

## Remaining runtime gap

The 64-superstep chain executes 2,186,371 simulated cycles, including 262,144
apply reads, 262,144 apply writes, and 524,288 mirrored source-state writes.
The native HLS contract scans and rewrites the fixed 65,536-vertex partition on
every superstep, even though only one chain edge becomes useful each round.

Linear extrapolation from the optimized 64-round run places the 4096-round
stress case at about 90.3 minutes. That estimate is deliberately not reported
as a completed run. The tens-of-minutes runtime gate remains open, and the next
optimization must reduce SST/DRAM simulation overhead without deleting those
real memory transactions or their contention.

## Reproduction

Build and test:

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j2
python3 -m unittest discover -s tests
```

Run the longer equivalence case:

```bash
python3 scripts/run_grasu_native_hw_matrix.py \
  --no-build \
  --roles holdout \
  --case small_chain_v64 \
  --out-dir results/grasu_native_scheduler_small_chain

cmp \
  docs/evidence/grasu_native_hw_matrix/simulation/small_chain_v64.result.json \
  results/grasu_native_scheduler_small_chain/small_chain_v64/sst/result.json
```

Machine-readable evidence is
`docs/evidence/grasu_native_scheduler_runtime_20260725.json`.
