# Cross-Row V3 Route Checkpoint

## Decision

**All six environment checks passed; insufficient memory prevented route
from starting.** No new xclbin, routed timing, FPGA speedup or hardware
calibration is delivered here. The overall performance-validation goal is
still open.

The independent V3 entry point rechecks production synthesis/RTL and the
padded SSSP host, then replaces exactly one XO in the immutable whole-line
route command. The other ten kernels, stream/HBM connectivity, U55C platform,
150-MHz clock, concurrency and safety budgets remain unchanged. Historical
attempts are not edited or relabeled.

| Check | Recorded result |
| --- | --- |
| V3 adapter XO | `7d1785677ca7b54861688d7670d813ca2a4cfdc1e2c83cbc53151cd03ad02b6b` |
| Whole-line route basis manifest | `61ea41c7401e8a084eb14970bd3142aed3920c1c23772478ddd8d09ee6da27b0` |
| Padded host | Same checked binary; `ROW_LINE_READ=1`, weighted SSSP, sharded K4 |
| Toolchain preflight | Vitis, Vivado, GCC, G++, thread compilation and execution: six passed |
| Available memory at admission | 46,924,345,344 bytes, approximately 43.70 GiB |
| Required memory | 40-GiB process-tree budget plus 16-GiB reserve = 56 GiB |
| Execution | `ADMISSION_REJECTED_NOT_STARTED`, exit code 2, no route process |

The refusal is a safety result, not a synthesis failure or measured
performance regression. The threshold was not reduced. Preflight used a
4-GiB tree budget and 90-second timeout per command, preserving a live
16-GiB reserve. A permitted route uses two synthesis/implementation jobs
and a 14,400-second timeout. Sampled process-tree RSS and pidfd cleanup are
not cgroup containment.

## Ownership And Evidence

`row_line/cross_row/route_preparation.py` owns exact V3, ABI, source, host
and historical-input admission. Its thin `route.py` delegates to
`row_line/route.py::run_prepared`, which retains the existing environment,
preflight, admission and link supervisors. The extraction changes no
numerical model or execution policy.

[verification.json](evidence/verification.json) records the full command,
identities, admission, environment and six preflight records.
[raw_environment_admission.tar.gz](evidence/raw_environment_admission.tar.gz)
contains 87 indexed files: original logs/configuration and selected small
source snapshots. Its SHA-256 is
`e43bfc29b0452c803f0352801486002695bdae48770c343514786f0b60aab0f3`.

XOs, host binary and proprietary tools are identity-indexed, not duplicated
in this non-start archive. Candidate sources/RTL belong to the
[V3 HLS package](../README.md). Live semantic recheck requires the recorded
external paths; archive member-hash verification alone is portable. Neither
is a portable FPGA rebuild or a board measurement.

[Regression evidence](evidence/regression.json) and its
[raw archive](evidence/raw_regression.tar.gz) retain bounded test transcripts,
test sources and the pre-edit route snapshot. Focused checks cover exact
single-XO replacement, unchanged connectivity/limits, changed source/kernel/
host/tool rejection, failed prerequisites and fresh-path refusal. Shared
runner tests cover memory refusal and preflight/link failures.
All 384 sharded-K4 tests and fifteen repository-structure tests pass. Docs
layout, generated catalogs and whitespace checks pass. Numerical C++/SST
code was not changed or rebuilt in this route-only checkpoint; the earlier
functional/traffic evidence is not reclassified as hardware calibration.

## Reproduce

Run from the simulator repository root, with the pinned external inputs
available and a fresh output directory:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.route \
  --build /data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806 \
  --basis /data/chuxiao/experiments/sharded_k4_row_line_route_20261011/attempt-v1 \
  --study /data/chuxiao/experiments/sharded_k4_cross_row_20261011/attempt-v3 \
  --host /data/chuxiao/experiments/sharded_k4_row_line_20261011/host-v2 \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output /data/chuxiao/experiments/fresh_cross_row_route \
  --execute

python3 -m unittest discover -s tests -p 'test_sharded_k4_cross_row_route.py'
python3 -m unittest discover -s tests -p 'test_sharded_k4_row_line_route.py'
```

The recorded attempt is
`/data/chuxiao/experiments/sharded_k4_cross_row_route_20261012/attempt-v1`.
Keep it unchanged. A later attempt must recheck all inputs and use a new
directory. Even successful linking still requires routed timing/connectivity
admission and matched resident board runs. The
[18-run A4/model control](../a4_control/README.md) remains a separate
prediction experiment with resource differences, not a substitute for
these hardware gates. Paper, figure handoff and default plugin are unchanged.
