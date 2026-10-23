# Sparse Residual Apply Verification

## Completed Gates

- A separate fresh GCC 15.2.0 Release build passes the dedicated
  `routed_pagerank_tests` run and **40/40 CTests**, including the new bounded
  bitmap tests. All four configure/build/regression steps return zero.
- Fresh dense and sparse SST plugins each pass two ResPR smoke arms and six
  real-input arms. Source identities stay fixed and agree with the fresh
  core build. All three declared inputs are retained, including Flickr's loss.
- The dense default exactly reproduces the frozen preceding cycles, traffic,
  HBM energy, full numerical state and frontier counts. G+R remains exactly
  unchanged in both controls. The fixed FP32 activation threshold stays
  `1e-6`; it is not divided by the vertex count.
- Dense and sparse final rank words and complete per-round active vertex
  sets agree on all three inputs. AU residuals and frontier order also agree
  bitwise. Flickr has 186 differing residual words (maximum absolute
  difference `1.1368683772161603e-13`) and sixteen reordered frontier lists.
  The README records the initial strict equality failure and the subsequent
  post-hoc diagnostic tolerance. This is not full bitwise state equivalence.
- **54 focused Python tests** pass across figure refresh, threshold,
  propagation, sparse Apply and repository organization. The complete Python
  suite was not rerun and is not claimed green.
- Portable verification recomputes the comparison from archived reports,
  full numerical arrays, active vertex IDs and raw outputs. Archive SHA256:
  `b60cf68e8e42c628a9a0b91de810909fc2cea1ea14362c69d8f9a0bc82f78a2f`.
- The preceding frozen capsule verifies unchanged, with SHA256
  `18e1f442473c6ec6f4031902bc8621341d60e05117c211cd9c1952d1a0939630`.
  Initial dense/sparse runs are retained separately inside the new capsule.

## Resource Safety And Deadline

Each owned build/matrix service has a 6-GiB maximum, 5-GiB high watermark,
zero swap, group OOM containment and a 2,400-second service deadline. Children
have a 4-GiB address-space bound, finite per-step timeouts, atomic full-budget
admission and a live 24-GiB system reserve. Compilation uses two jobs. No
foreign process or FPGA job was changed.

The confirmation core steps take 708.5 seconds in total; full CTest takes
374.3 seconds. Observed core cgroup peak was 991,424,512 bytes. Largest
single-process RSS in the matrix reports is 956,560 KiB, from plugin
compilation, not the simulation. These host costs are separate from predicted
device cycles. All confirmation jobs finished before 02:00 Beijing time on
October 24, ahead of the 05:30 stop deadline and 06:00 reboot.

## Verification Commands

Run from the repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.sparse_apply_followup \
  --verify \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh/respr_sparse_apply

PYTHONPATH=.:tests python3 -m unittest \
  tests.test_figure_refresh tests.test_figure_refresh_multialgorithm \
  tests.test_residual_threshold_followup tests.test_residual_propagation_followup \
  tests.test_residual_sparse_apply_followup tests.test_repository_structure

python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
git diff --check
```

## Fresh Run Commands

Use new external output directories, an allowed CPU, the recorded toolchain
and linked dependencies. The source/core/input pins and exact child commands
are embedded in `evidence/evidence.tar.gz`. The following service envelope
retains the required memory admission/watchdog and containment. Do not run
these numerical jobs without their bounded service environment.

```bash
ROOT="$PWD"
RUN=/data/chuxiao/experiments/respr_sparse_apply_reproduction

systemd-run --user --wait --collect \
  --property=WorkingDirectory="$ROOT" \
  --property=MemoryMax=6G --property=MemoryHigh=5G \
  --property=MemorySwapMax=0 --property=MemoryOOMGroup=yes \
  --property=OOMPolicy=kill --property=RuntimeMaxSec=2400 \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.core_gates \
  --output "$RUN/core-gates"

systemd-run --user --wait --collect \
  --property=WorkingDirectory="$ROOT" \
  --property=MemoryMax=6G --property=MemoryHigh=5G \
  --property=MemorySwapMax=0 --property=MemoryOOMGroup=yes \
  --property=OOMPolicy=kill --property=RuntimeMaxSec=2400 \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.study \
  --output "$RUN/sparse/matrix" --core "$RUN/core-gates/build" \
  --cpu 4 --algorithms ResPR --case-set historical-residual-u8 \
  --residual-epsilon 1e-6 --spine-residual-apply dirty-bitmap
```

For the dense control use a separate `dense/matrix` output and
`--spine-residual-apply dense`; keep every other setting fixed. Existing raw
paths are never reused. These checks establish a bounded simulator candidate,
not hardware timing calibration, a routed implementation, original-publication
G/R performance admission, or a replacement for all evaluation figures.
