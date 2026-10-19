# Source-Bound Bank Streaming

This study selects the current production HLS source topology in SST without
changing legacy defaults or fitting a timing multiplier. It is a simulator
correctness and traffic checkpoint, not FPGA calibration, publication matching,
or final Fig7--11 admission. The paper and frozen figure handoff are untouched.

Read the preceding [pairwise source checkpoint](../source_pairs/README.md)
for physical source ownership. The new profile combines that ownership with
the existing bank-stream adapter implementation.

## Code Review

| Owner | Responsibility |
| --- | --- |
| `configs/architectures/grasu_regraph_bank_stream_sssp_compute_v1.json` | Explicit source identity, topology, schedule and timing limitations |
| `cpp/include/spine_sim/routed_regraph_profile.hpp` and `cpp/src/routed_regraph/profile.cpp` | Testable profile selection; unchanged old defaults and rejection of mixed modes |
| `cpp/sst/routed_regraph_probe.cpp` | Thin SST parameter selection and fixture/system wiring |
| `spine_cycle_sim/experiments/sharded_k4_stages/bank_stream/model_contract.py` | Strict profile, timing-basis and HLS-source checks |
| `spine_cycle_sim/experiments/sharded_k4_stages/bank_stream/model_validation.py` | Independent traffic inventory, topology, drain and complete output validation |
| `spine_cycle_sim/experiments/sharded_k4_stages/bank_stream/study.py` | Pinned AU/SU/WK resident replay and source/input provenance |

The factory also owns the existing v1--v4, row-line and cross-row selections.
The new selection is default-off and candidate-only. It does not reinterpret
old row-line, routed-XO or FPGA timing evidence as a bank-stream result.

## Scope And Assumptions

Four adapter masters, two pairwise source masters and one Apply/status master
give seven physical masters. Workers 0/2 share the source service on HBM23;
workers 1/3 share HBM24. Adapter directory caching uses 1,024 rows, with packet
streaming and a 256-line bank FIFO. These settings and ten HLS source hashes
are explicit in the new profile. The study additionally checks both exported
input headers, rather than accepting an arbitrary input ABI.

The nominal timing basis remains the existing v3 model. In particular,
71-cycle read-to-use and writeback, 100-cycle Apply service, directory control,
and beat-progressive bank returns are assumptions pending hardware checks.
Beat-progressive returns are not an HLS compile define or a measured AXI trace.
Old XO, RTL and hardware hashes are deliberately not inherited from that basis.

The boundary is resident weighted-SSSP compute, without host launch gaps.
GraSU updates, host preprocessing, DMA, programming and host orchestration are
outside this study. It does not admit CC or PageRank timing.

## Predeclared Matrix

| Case | Logical vertices | Destination partitions | Converged rounds |
| --- | ---: | ---: | ---: |
| AU | 515,281 | 8 | 2 |
| SU | 567,316 | 9 | 2 |
| WK | 1,140,149 | 18 | 1 |

These are exactly the fixtures, complete expected values, old-state inputs
and convergence boundaries pinned by `row_line/model_scope.py`. They are not
newly selected favorable workloads. Every output value is checked, along
with all source replicas, per-round active counts, directory/edge/source
traffic, Apply/writeback traffic, AXI parent/beat conservation and drained
arbitration. Burst parents are not incorrectly equated with individual beats.

## Status

The relocated execution now passes all five exact legacy regressions and all
three predeclared resident cases. The independent
[resident evidence record](resident_evidence.json) supplements the historical
[build checkpoint](evidence.json); it does not rewrite that earlier record.
No FPGA timing, original-A4 match or final figure is admitted by either record.

Campaign root:
`/data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/`.
The pre-edit baseline freezes clean revision
`3b906c7aae1d6cb77706728edc857b493c8b0ed8`; its source archive SHA-256 is
`d254cd1aeea7803684029cfae135c56ead89b64b560d58a757bcd9100a2fd269`.

The [build checkpoint](evidence.json) records 35/35 fresh CTest executables,
88/88 focused Python tests and all five exact legacy SST regressions passing.
No result fields or manifest identities were ignored. The freshly built
plugin SHA-256 is
`070581686f7e32406069beff547379a4f8811155119da81f33a41221fbf4e712`.
The source remained unchanged during all build/regression gates.

| Preserved legacy case | Cycles | Backend requests | Result |
| --- | ---: | ---: | --- |
| Cold mixed SSSP | 99,885 | 33,848 | Every field identical |
| Warm multipart SSSP | 5,997,674 | 1,775,700 | Every field identical |
| Reciprocal CC | 133,841 | 50,741 | Every field identical |
| Warm residual PR | 1,487,890 | 997,048 | Every field identical |
| Residual PR update-only | 200 | 48 | Every field identical |

`delivery-v1/build_and_legacy_raw.tar.gz` contains the pre-edit source baseline,
candidate source snapshot/archive, fresh plugin, build settings/logs, complete
legacy outputs and Python-test logs. The separately hashed raw index lists
every archive member. Archive member hashes and the unchanged raw files are
rechecked after sealing. This archive deliberately excludes pending resident
replay and hardware results.

The local AU/SU/WK supervisor `resident-supervisor-v2` was stopped before replay
to relocate execution to the authorized high-memory host. Its 1-GiB cap plus
the active CC build's full 40-GiB reservation and 16-GiB reserve required
57 GiB available, above the observed local memory. Its exact invocation and
supersession reason are retained; no resident output had been created.
The prior supervisor was superseded before replay because it did not handle
collection of the completed transient gate unit. No model or input was changed
for that supervisor correction. The build checkpoint itself admits no resident
cycles; the separate completed execution below supplies them.

## Completed Resident Replay

Execution revision `0c3323cfd9d7334d1c159145acb722eb3e4a9a41` ran on
`seele` under invocation `4711217116ba463e960dfff8a3ff3430`, using the same
plugin as the build checkpoint. All five cross-host legacy comparisons preserve
every result field and semantic manifest identity, with no ignored fields.

| Case | Rounds | Bank-stream predicted cycles | Preserved row-line predicted cycles | New / previous | AXI beats | AXI parents |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AU | 2 | 1,090,874 | 15,063,595 | 0.07242 | 738,334 | 266,602 |
| SU | 2 | 1,493,965 | 24,516,942 | 0.06094 | 996,362 | 301,770 |
| WK | 1 | 908,191 | 8,621,421 | 0.10534 | 545,026 | 296,591 |

Each row passes complete external-state equality, source-replica equality,
per-round activity, convergence, independent traffic accounting and final
drain checks. The preserved row-line outputs use the identical fixtures and
convergence boundaries. These ratios compare two simulator predictions with
different declared input schedules; they are not measured hardware speedups,
an original-A4 comparison or a new Spine comparison.

`delivery-v2/resident_and_compatibility_raw.tar.gz` seals 894 members:
complete remote outputs, failed relocation, local supersession, recipes,
source snapshots, plugin, fixtures, expected states, HLS inputs and check logs.
Its size is 32,223,698 bytes and SHA-256 is
`47789aae2c57e3df9a9b63362deab3f89a7c3fc8b74050993646695720f82335`.
The external raw index SHA-256 is
`4e5434e153e5e472dcb5bea33fd61a1ea46ca3d95eb2ffd7a489c652661d97ce`.
All archive members and unchanged raw files were rehashed after sealing.
Independent replay admission rechecks all 1,182 relocation input hashes,
legacy comparisons and resident inventories rather than trusting summary flags.
Large runtime dependencies are hash-indexed, not redistributed in the archive.

The remote execution took 4.17, 5.22 and 4.18 seconds for AU, SU and WK.
Their sampled process-tree RSS peaks were 187,996, 224,504 and 623,340 KiB.
These are execution observations, not FPGA time or continuous RSS maxima.

The remaining acceptance gates are matching hardware timing, current complete
G and host composition, CC/PageRank variants, original-A4 comparison and the
new paired Spine matrices. The frozen Fig. 7--11 handoff is not replaced.

## Execution Relocation

`bank_stream/runtime.py` validates explicit SST, CPU and DRAMSim3 paths.
Relocation rejects a DRAMSim3 library whose hash differs from the original
plugin-build snapshot. The manifest distinguishes that original build source
from the current execution source, and records host, CPU selection, SST and
memHierarchy binary hashes and relevant environment variables. The plugin,
HLS-source checks, fixtures, expected values, timing parameters and convergence
requirements are unchanged. Relocation is not numerical calibration.

The study accepts `--sst`, `--cpus` and `--dramsim3-root`; omitted options retain
the original local defaults. The three focused runtime tests reject unavailable
or duplicate CPUs and a changed DRAMSim3 dependency. The resulting 91-test
Python matrix, document/catalog checks and single-threaded `git diff --check`
pass; logs are in `runtime-relocation-v1/checks`. The initial bounded diff check
could not create Git's default preload threads; its error is retained separately
from the passing single-threaded check. Those checks alone did not admit remote
results; the completed replay and independent seal above supply that gate.

The copied SST launcher has a compiled-in installation prefix. The successful
remote execution uses the pinned `sst/bin/sst_python310` wrapper to start the
unchanged `libexec/sstsim.x` with its relocated Python 3.10 standard library,
plus the explicit `--no-env-config` study option. Only the SST child receives
`PYTHONHOME`; the supervisor remains on the host Python with pidfd support.
The wrapper SHA-256 is
`497b77bcdfdda3f699baefdd2a67cf4f616d0b9e3b16fdb142db3325ab8907d3`.
The earlier copied-Python supervisor failed its required pidfd check before
simulation; `execution-v1/failure.json` is retained. These are execution
relocation failures, not model results. Disabling environment discovery does
not change the explicit plugin search path or DRAMSim3 hash requirement.
The follow-up 92-test Python matrix passes; logs are retained separately in
`runtime-relocation-v2/checks`. This includes a test that the opt-in engine
mode is recorded and does not duplicate the executable pin.

The first broad Python command encountered two sibling-import errors. Rerunning
the same intended matrix with `PYTHONPATH=.:tests` passed all 88 tests. The raw
archive retains that passing command and logs; the first command's errors were
observed in the terminal transcript, not saved as a separate raw log.

The local build and independent packaging use 1-GiB physical cgroups,
960-MiB high watermarks, zero swap, atomic full-budget admission and a 16-GiB
live reserve. The remote replay instead uses the documented
`seele-reserve-128g-v1` policy: a 40-GiB physical cgroup, 36-GiB high watermark,
zero swap, group OOM termination, full finite peer budgets and a 128-GiB live
reserve plus 8-GiB background allowance. Its complete cgroup peak was
1,513,680,896 bytes. The sequential per-case 1-GiB process-tree RSS watchdog
is sampled, not a separate physical 1-GiB cgroup. Each case retains CPU
affinity 112--113, a 600-second wall timeout and a 100-million simulated-cycle
cap. Independent packaging completed with a 316,764,160-byte cgroup peak.
Set `TMPDIR=/data/chuxiao/tmp` on the current host because `/tmp` is full.

## Reproduce

Build in a fresh directory, run the complete CTest suite and the fixed
five-case `scripts/run_component_refactor_regression.py` contract first.
The study requires the recorded passing gate summary and exact plugin hash:

```bash
TMPDIR=/data/chuxiao/tmp python3 -m \
  spine_cycle_sim.experiments.sharded_k4_stages.bank_stream.study \
  --gates /path/to/passing/gates \
  --integration /path/to/frozen/production/integration \
  --fixtures /path/to/pinned/resident/study \
  --output /path/to/fresh/bank-stream-study
```

Use the documented bounded cgroup and atomic memory admission when executing
this command. A successful run produces `manifest.json`, per-case raw SST
outputs and admission records, a source archive and `results.json`. A failure
retains raw output and `failure.json`; it must not be dropped from a report.
