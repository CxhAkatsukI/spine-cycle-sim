# Simulator throughput milestone 4: active DRAM command queues

## Scope

This milestone removes redundant host scans from the patched DRAMSim3 backend.
It does not change a DRAM timing parameter, transaction, bank mapping,
round-robin start, ready-command test, issued command, completion cycle, power
counter, or output statistic.

The upstream DRAMSim3 command queue had two costly operations:

- `QueueEmpty()` copied every per-bank `std::vector<Command>` before checking
  whether it was empty; and
- `GetCommandToIssue()` visited all 16 HBM banks on every active DRAM cycle,
  including empty queues.

`patches/dramsim3_active_queue_hotpath.patch` maintains one 64-bit non-empty
queue mask. Arbitration still examines non-empty queues in the original cyclic
numeric order, restores the original round-robin cursor when no command is
issued, and runs the unchanged ready and dependency checks. The isolated
DRAMSim3 build script applies this patch after the exact-idle patch and records
both hashes.

## Controlled A/B result

The cumulative candidate was compared with the frozen pre-optimization
baseline on the Candidate10 residual PageRank probe.

| System | Baseline host s | Candidate host s | Host speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 5.576 | 1.414x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 68.942 | 1.526x | 15,310,428 |

The cumulative two-system geometric-mean speedup is 1.469x. Relative to the
preceding AXI hot-path commit, this DRAM patch improves Spine by 1.113x and
GraSU+ReGraph by 1.102x on the controlled run. The result remains below the
frozen 10x medium/large-suite target.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- no observability field was added or removed.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate11_dramsim3_active_queue_20260728`.
Raw runs remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate11_dramsim3_active_queue_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate11_dramsim3_active_queue_equivalence_20260728`
- isolated DRAMSim3 source/build: `/data/tmp/chuxiao/candidate11-dramsim3-active-queue-build-20260728`

The candidate `libdramsim3.so` SHA-256 is
`017af220199af9a633ddce21227d3cfe2ad5f8981b6c8c10dd3a9fedfb8d8333`.

## Reproduction

Build a new isolated SST/DRAMSim3 stack with both exact patches:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate11-reproduction \
  --install-prefix /data/tmp/chuxiao/candidate11-reproduction-install \
  --jobs 8
```

Then run the frozen comparison:

```bash
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate11-reproduction/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate11-reproduction-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/candidate11-reproduction-run \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build
```

Validation at this milestone: the full 585-test Python suite passed at the
preceding code commit; this backend candidate passed complete result and DRAM
byte-equivalence. DRAMSim3 does not register CTest targets in its upstream
CMake build.
