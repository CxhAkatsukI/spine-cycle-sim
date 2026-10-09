# Rejected simulator runtime paths

## Scope

These experiments tested host-runtime changes only. They did not change the
modeled accelerator, clock, FIFO/AXI/HBM behavior, or simulated cycle count.
The workload was Candidate10 Spine `syn_spread_e512` with thresholded residual
PageRank. It executes 4,778,979 core cycles and 410,621 DRAM requests.

All four `result.json` files are byte-identical, with SHA-256:

```text
da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758
```

## Compiler optimization level

The production SST element Makefile uses `-O2 -g`. A temporary `-O3 -DNDEBUG`
build was compared on the same source and workload.

| SST element | Host wall seconds | Result |
| --- | ---: | --- |
| `-O2 -g` | 61.481 | baseline |
| `-O3 -DNDEBUG` | 61.657 | no benefit |

This was one interleaved run per build on a shared machine, so the sub-percent
difference is not a publishable regression. It is sufficient to reject the
claim that changing optimization level closes the large-graph runtime gap. The
Makefile change was reverted and never committed.

## SST thread scaling

SST 16.0.0 supports `--num-threads`. Four-thread runs were tested both with the
default partition and with the probe fixed to thread zero and memory
controllers assigned round-robin using `Component.setRank(0, thread)`.

| Configuration | Host wall seconds | Relative to single-thread `-O2` |
| --- | ---: | ---: |
| four threads, default partition | 175.745 | 2.86x slower |
| four threads, explicit controller partition | 174.916 | 2.85x slower |

The explicit run used all four host cores, but the probe-controller links have
1 ns latency. Conservative cross-thread synchronization at that granularity
costs more than parallel DRAMSim3 clocks save. Increasing link latency would
change modeled memory timing and was therefore not considered a valid runtime
optimization. All partitioning changes were reverted and never committed.

## DRAMSim3 build type

The live 50K-edge process maps:

```text
/data/feiyang/sst-build/DRAMsim3/libdramsim3.so
```

This is not an accidental debug backend. Its CMake cache records
`CMAKE_BUILD_TYPE=Release`, and
`build/CMakeFiles/dramsim3.dir/flags.make` records:

```text
CXX_FLAGS = -O3 -DNDEBUG -std=c++11 -fPIC -Wall
```

Rebuilding DRAMSim3 with ordinary release flags therefore cannot explain or
close the runtime gap. This audit changes no binary and no simulated event.

## DRAMSim3 epoch-output suppression

DRAMSim3 supports `output_level=0`, which retains the final aggregate JSON but
does not serialize a JSON record every `epoch_period`.  The real-comparison
runner now accepts `--dram-config`, passes it to both systems through
`CANDIDATE10_SST_DRAM_CONFIG`, hashes the config into the execution identity,
and records its output contract in the matrix manifest.  The checked-in
`configs/memory/HBM2_1ch_x128_summary_only.ini` differs from the frozen HBM
config only in `output_level`.

An AB run used Candidate10 Spine `syn_spread_e512` thresholded residual
PageRank, with 4,778,979 core cycles, 410,621 DRAM requests, and the same
release binaries as the frozen matrix:

| DRAMSim3 output | Host wall seconds | Result SHA-256 |
| --- | ---: | --- |
| epoch plus final summary | 61.022 | `da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758` |
| final summary only | 60.971 | `da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758` |

After removing only `sst_host_wall_seconds`, both complete summaries also have
the same SHA-256,
`4854d259d2b3eec89a8aba82e15aeb40ed6b015fc8cbc7164a7e3710ebf9b438`.
Cycles, requests, ACT/PRE/row-hit counts, final DRAM energy, queue activity,
and correctness are therefore unchanged.  The observed 0.08% host-time
reduction is noise-sized and cannot close the large-runtime gate.  The
summary-only config remains an explicit reproducibility option, not the
publication baseline and not an accepted performance optimization.

Raw AB evidence is retained outside Git at:

```text
/data/tmp/chuxiao/dramsim_summary_long_ab_20260727/
```

## Fail-closed post-hoc runtime acceptance

A long simulation can outlive the runner revision that launched it. Re-running
the same multi-hour simulation solely to add a newer acceptance field would
waste compute and would create a different execution fingerprint. The checked-in
post-hoc finalizer therefore evaluates the host-runtime gate from the completed
matrix without launching SST:

```bash
python3 scripts/finalize_large_real_runtime.py \
  --result-dir /data/tmp/chuxiao/candidate10_hls_v3_large_runtime_fixed_fallback_v5_20260727
```

The finalizer fails closed unless both system rows and the comparison pair are
present, all simulator and cross-system correctness checks pass, the input and
result-table hashes match the matrix manifest, and every raw result JSON still
matches its recorded SHA-256. Its `runtime_acceptance.json` records that no
cycle or performance result was modified. A failed 1,800-second host-runtime
gate remains a completed scientific observation; it is not converted into a
simulator PASS.

## Implication

The remaining large-run host cost is dominated by valid, already release-built
DRAMSim3 clock work on the 23 pseudo-channels bound by Candidate10, not by debug
compiler flags or idle FIFO polling. The accepted scheduler sleep changes
remain useful but small. A material speedup requires either a more efficient
exact DRAM backend integration or an event/wakeup scheme that preserves every
controller-visible ordering and refresh effect; coarse cycle skipping is not
authorized.

Raw outputs are retained outside Git:

```text
/data/tmp/chuxiao/scheduler_release_flags_o2_run1
/data/tmp/chuxiao/scheduler_release_flags_o3_run1
/data/tmp/chuxiao/sst_threads4_spread_residual_20260727
/data/tmp/chuxiao/sst_threads4_partitioned_spread_residual_20260727
/data/tmp/chuxiao/dramsim_summary_long_ab_20260727
```
