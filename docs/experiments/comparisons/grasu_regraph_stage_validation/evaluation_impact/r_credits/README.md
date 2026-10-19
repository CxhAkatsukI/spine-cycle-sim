# R Credit And Apply-Window Sensitivity

## Question And Status

Does the preceding close A4/K4 prediction rely on different outstanding
request budgets? This study retains every legacy arm and tests explicit
resource controls. It is not a new admitted baseline or paper reproduction.
The [resource audit](../r_resources/README.md) is the motivation, not timing
evidence: A4 has 13 masters on 9 physical banks; K4 has 9 registered masters.

Current status: all 28 declared executions completed. The fresh serial
Release build, control-parser check and seven C++ regressions passed. Every
one of the twelve legacy observations replayed exactly, including trajectories,
cycles, complete state/replica hashes and physical read/write bytes. Every new
arm passed the synchronous oracle, shortest-path closure and registration-order
invariance. The [portable evidence](evidence/index.json) retains the complete
matrix, not just passing examples.
No paper, frozen figure package, production core, SST or bitstream is changed.

## Complete Results

The two registration orders give identical results. Lower cycle counts are
better; all values below are simulator predictions for the same 46-round
warm compute problem, not FPGA measurements.

| Arm | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| `a4` | 30,740,788 | 59,442,350 |
| `cross_row` | 244,269,384 | 431,605,442 |
| `candidate` | 32,160,486 | 57,582,524 |
| `a4_io16` | 10,904,254 | 15,840,606 |
| `candidate_apply2` | 53,168,456 | 96,684,180 |
| `candidate_parents2` | 77,654,808 | 145,284,836 |
| `candidate_both2` | 77,655,544 | 145,285,204 |

The candidate/legacy-A4 ratios are 1.046 and 0.969, but candidate/`a4_io16`
ratios are **2.949 and 3.635**. Increasing A4's edge/state parent budget from
2 to 16 exposes a substantial remaining gap. Therefore the preceding close
prediction is not sufficient evidence that the actual integrated baseline
retains original ReGraph performance. Equal parent counts still do not make
the different master/bank/replica organizations strictly resource matched.

All A4 arms read 802,534,400 B and write 192,937,984 B. Candidate arms read
2,021,232,640 B and write 144,703,672 B. Both registration orders and memory
assumptions preserve those traffic counts. Every full output replica has
SHA-256 `ff001ca203b3b7e0b4ae60b630cee6755acd2f2401fb08e1069e081562dd2c00`.
This is a defensible sensitivity finding, not publication reproduction,
hardware timing admission, or a replacement Spine speedup result.

## Predeclared Controls

| Arm | A4 edge / state parents | A4 source parents | K4 parents | K4 Apply window |
| --- | --- | --- | --- | --- |
| `a4` | 2 / 2 | 2 | -- | -- |
| `cross_row` | -- | -- | 16 | 16 |
| `candidate` | -- | -- | 16 | 16 |
| `a4_io16` | 16 / 16 | 2 | -- | -- |
| `candidate_apply2` | -- | -- | 16 | 2 |
| `candidate_parents2` | -- | -- | 2 | 16 |
| `candidate_both2` | -- | -- | 2 | 2 |

The first three are unchanged reference configurations. The last four are
sensitivity controls, not replacements selected for favorable speed. A4's
state setting covers its Apply read master and four property writers; it
does not change its four source readers. K4's parent setting also bounds
source-service buffering, so its effect is not an AXI-only experiment.
Bank placement, replica count, shared capacity, merge widths and source
service still differ. Equal parent counts alone do not make resources equal.

Every arm uses the same fixed Amazon real-ID SSSP slice (258,046 vertices,
1,450,899 edges), old converged state and three source-0 weight decreases.
The post-update graph and seed are preloaded. Propagation runs to convergence
at 150 MHz. The window excludes G, host preparation, DMA and orchestration
on all arms. Both 64/128-cycle memory assumptions and both registration
orders are required: 7 arms x 2 latencies x 2 orders = 28 executions.

## Validation And Interpretation

- Replay all twelve old rows exactly: each round's cycles and active count,
  full final-state hashes, replica extents and physical read/write bytes.
- Check every new round against the independent synchronous oracle and
  final shortest-path closure. All arms must have the same active trajectory.
- Check every final state word and replica; no missing or additional replica
  is accepted. Match forward/reverse registration results exactly.
- Conserve logical edges, physical packets, requests, completions and beats;
  verify Apply/source/status writes and total physical byte ledgers.
- Report all controls relative to both legacy A4 and `a4_io16`. Do not pick
  the closest row as a new baseline or fit a slowdown/speedup multiplier.

If these pass, the result answers resource sensitivity for this one compute
case. It does not establish strict resource matching, FPGA timing, original
11-Little/3-Big publication performance, complete G+R, or a Spine speedup.
Those admission flags remain false in the analysis output.

The subsequent [current bank-stream study](../r_bank_stream/README.md) adds the
two-pair source topology explicitly and requires all 28 rows here to replay
unchanged. This historical `candidate` is not silently relabeled as that newer
topology.

## Code And Reproduction

The owner is `spine_cycle_sim/experiments/evaluation_impact/r_credits/`:
`freeze.py` pins the pre-edit baseline; `admission.py` owns memory admission;
`study.py` builds and executes; `analysis.py` validates the complete matrix;
`delivery.py` owns portable evidence packaging and offline verification.
The C++ harness separates `control.hpp`, `a4.hpp`, `k4.hpp` and a thin CLI.
The production model and SST build lists are untouched.

The actual pre-edit freeze is under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/r-credit-sensitivity-v1/pre_edit/`.
Its `sources.tar.gz` was captured before numerical harness extraction.
Do not run the freeze command after edits and call that a pre-edit baseline.

```bash
python3 -m unittest tests.test_regraph_credit_controls tests.test_evaluation_impact tests.test_regraph_resource_audit -q
python3 -m spine_cycle_sim.experiments.evaluation_impact.r_credits.study \
  --before /data/chuxiao/experiments/baseline_evaluation_impact_20261012/r-credit-sensitivity-v1/pre_edit \
  --output /data/chuxiao/experiments/baseline_evaluation_impact_20261012/r-credit-sensitivity-v1/attempt-NEW
```

The output path must not exist. `results.json` retains each command, raw log
path, failure, complete observations and source/input/build hashes. A fresh
serial Release build checks the seven declared regression targets and the
control parser before attempting the matrix. Compilation alone does not
establish extraction equivalence; that needs the twelve exact replays.

The initial persistent run was
`spine-regraph-credit-sensitivity-20261013-v1.service`, with output under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/r-credit-sensitivity-v1/attempt-v1/`.
Its `raw/build.stdout.txt`, `raw/control_test.stdout.txt` and
`raw/regression.stdout.txt` retain the completed build/check evidence.
`results.json` records live admission status and `r_rows`; an empty list is
not a performance result. This earlier attempt is retained separately from
the current campaign. The numerical sources and build are pinned; a changed
pin stops execution rather than mixing code versions. The service has a
6-GiB cgroup bound, no swap and CPU affinity 127.

The current invocation is `spine-regraph-credits-20261015-v2.service`, with
output at
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/r-credit-v2/`.
Its predecessor `r-credit-v1` failed admission before producing any timing
rows because a collected transient cache unit was misclassified. The corrected
attempt has a fresh output directory and retains that failure; the seven
arms, two memory assumptions, two registration orders and twelve-row replay
requirement are unchanged. Read `r_rows`, `failures` and final `analysis` in
this attempt's `results.json`, not the old queue snapshot.

The committed capsule contains pre-edit and executed sources, all 33 command
records/logs, compiler/flags, fixed binary inputs and all 92 final replicas.
Identical binary files are stored once by SHA-256 with a logical-path index.
Executables and libraries remain hash-indexed, not redistributed. Packaging
rechecks all 503 source/input/build pins and pre-edit artifacts; offline
verification replays the raw-output analysis and verifies every included blob.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.r_credits.delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/r_credits/evidence
python3 -m unittest tests.test_regraph_credit_delivery -q
```

```bash
systemctl --user status spine-regraph-credits-20261015-v2.service
journalctl --user -u spine-regraph-credits-20261015-v2.service -n 30 --no-pager
```

## Memory Safety

Small compilation/regression commands have a 2-GiB address-space bound and
8-GiB available-memory reserve. Numerical cases retain the original 4-GiB
bound plus 24-GiB reserve, one case at a time. Pending route/cache/search
jobs add conservative reservations of 40/6/8 GiB while their supervisors
are active. With all three pending, admission requires 82 GiB available;
without them it still requires 28 GiB. Unknown or unbounded job states fail
closed. This does not change their own stricter admission rules.

The total admission-wait allowance is twelve hours across the campaign, not
twelve hours per row. Every case has an 1800-second wall bound and a
1.5-billion-cycle cap. Pins are rechecked after waiting and before each
case. A queued job is neither a completed experiment nor a passing result.
FPGA work has its own full-budget admission gate and may run concurrently;
the presence of another bounded tool alone is not a reason to wait.
