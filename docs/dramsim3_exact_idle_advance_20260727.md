# Exact DRAMSim3 idle advance

Date: 2026-07-27

## Purpose and claim boundary

The Candidate10 architecture can spend millions of simulated core cycles in
compute while most instantiated HBM pseudo-channels have no request or pending
DRAM command. SST 16.0.0's stock DRAMSim3 backend nevertheless calls
`ClockTick()` on every channel every nanosecond. The implementation described
here removes that host-runtime cost without removing a simulated cycle or HBM
channel.

The only supported claim is **host-runtime optimization with exact observable
equivalence**. FIFO depth, AXI ordering, outstanding capacity, HBM timing,
refresh, energy, simulated cycles, and architecture parameters are unchanged.
The stock always-clocked backend remains the publication baseline until the
remaining acceptance matrix passes.

## Implementation

The DRAMSim3 patch adds `IsIdle()` and `AdvanceIdle(cycles)` to the public and
internal memory-system interfaces. A JEDEC controller is safe to advance only
when it has no read/unified request, pending read, response, command, refresh,
or self-refresh state that can make progress on an ordinary tick.

DRAMSim3's split read/write policy deliberately holds at most eight writes
until a drain threshold is crossed. Such a buffer is stable while no new
request arrives, so the optimization preserves the buffered writes and permits
idle advance only when `write_draining == 0` and the write buffer and pending
write map agree. A later request sees exactly the same dependency and threshold
state as the stock backend.

Idle intervals are never crossed blindly. They are divided at:

1. the next DRAM refresh insertion cycle;
2. the next DRAMSim3 epoch-statistics boundary;
3. the SST wake or simulation-finish cycle.

At a refresh boundary the implementation executes the normal `ClockTick()`;
between boundaries it bulk-advances controller, command-queue, refresh, rank
idle/active, and total-cycle counters. HMC does not use the optimization and
retains a conservative per-cycle fallback.

The SST patch lets a backend report that its clock may stop. Clock-off requires
both an empty SST convertor request queue and a DRAMSim3 state that satisfies
the rule above. The wake hook receives SST's current cycle and advances the
exact omitted interval before a newly arrived request can issue. The finish
hook performs the same synchronization so final background/refresh energy is
not lost.

## Reproduction

Build in a new isolated directory. The script never modifies the shared SST or
DRAMSim3 source trees:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate10-idle-repro \
  --install-prefix /data/tmp/chuxiao/candidate10-idle-repro-install \
  --jobs 8
```

The build pins DRAMSim3 revision
`29817593b3389f1337235d63cac515024ab8fd6e` and SST elements 16.0.0. It
applies both tracked patches, builds an isolated plugin, runs the standalone
A/B test, compares final and epoch JSON byte-for-byte, and writes
`build_evidence.json`.

Use the isolated backend with existing runners by passing the tracked wrapper
as `--sst`:

```bash
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-repro/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-repro-install

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json \
  --out-dir /data/tmp/chuxiao/candidate10-idle-residual-check \
  --system spine \
  --run-id syn_spread_e512__residual_pagerank \
  --no-build \
  --sst scripts/run_sst_exact_idle_dramsim3.sh
```

## Current evidence

Machine-readable evidence is in
`docs/evidence/dramsim3_exact_idle_advance_ab_20260727.json`.

| Layer | Result | Exact comparison |
| --- | ---: | --- |
| Standalone DRAMSim3 | 21 completions, 1,010,000 cycles | completion cycles plus final/epoch JSON |
| SST AXI smoke | 256 requests, 520 core cycles | result and DRAM JSON |
| Spine residual PageRank | 4,778,979 cycles | result and 8 channel DRAM JSON |
| Residual host wall | 68.02s -> 7.82s | 8.70x sample speedup |
| 50K real Full PageRank | 268,232,904 Spine cycles | runtime gate PASS in 389.09s |

The residual run has zero architecture-oracle and mathematical-oracle
mismatches. It preserves 410,621 backend requests and the exact ACT, PRE,
read/write, arbitration, and HBM energy ledgers.

## Remaining gates

1. Run both Candidate10 architectures across all three algorithms, including
   update-heavy, refresh-boundary, and holdout cases.
2. Re-run the frozen HBM sensitivity subset and confirm no strict architecture
   ranking inversion.
3. Only after those checks, make the exact-idle backend the default experiment
   launcher. Existing publication performance numbers do not change because
   simulated cycles do not change.
