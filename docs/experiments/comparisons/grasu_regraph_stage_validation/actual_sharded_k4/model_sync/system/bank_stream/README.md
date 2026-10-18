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

The AU/SU/WK study is still awaiting atomic memory admission in
`resident-supervisor-v2`. Its 1-GiB cap plus the active CC build's full 40-GiB
reservation and 16-GiB reserve require 57 GiB available. The observed available
memory is below that threshold; the study is queued, not failed or completed.
The prior supervisor was superseded before replay because it did not handle
collection of the completed transient gate unit. No model or input was changed
for that supervisor correction. No new resident cycles or hardware timing are
admitted by this build checkpoint.

The first broad Python command encountered two sibling-import errors. Rerunning
the same intended matrix with `PYTHONPATH=.:tests` passed all 88 tests. The raw
archive retains that passing command and logs; the first command's errors were
observed in the terminal transcript, not saved as a separate raw log.

The build uses a 1-GiB physical cgroup, 960-MiB high watermark, zero swap,
atomic full-budget admission and a 16-GiB live reserve. Resident replay is
sequential with the same physical cap and reserve, CPU affinity 112--113,
a 600-second wall timeout per case and a 100-million simulated-cycle cap.
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
