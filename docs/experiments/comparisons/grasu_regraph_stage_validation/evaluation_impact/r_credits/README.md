# R Credit And Apply-Window Sensitivity

## Question And Status

Does the preceding close A4/K4 prediction rely on different outstanding
request budgets? This study retains every legacy arm and tests explicit
resource controls. It is not a new admitted baseline or paper reproduction.
The [resource audit](../r_resources/README.md) is the motivation, not timing
evidence: A4 has 13 masters on 9 physical banks; K4 has 9 registered masters.

Current status: the pre-edit source, compiler/flags, input, binary and all
12 reference observations are frozen. The fresh serial Release build,
control-parser check and seven C++ regressions passed. The 58 focused Python
tests, documentation-layout check and catalog check also passed. The new
28-row campaign is waiting for safe memory: zero timing rows have executed.
Numerical extraction equivalence and sensitivity results remain pending.
No paper, frozen figure package, production core, SST or bitstream is changed.

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

## Code And Reproduction

The owner is `spine_cycle_sim/experiments/evaluation_impact/r_credits/`:
`freeze.py` pins the pre-edit baseline; `admission.py` owns memory admission;
`study.py` builds and executes; `analysis.py` validates the complete matrix.
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

The current persistent run is
`spine-regraph-credit-sensitivity-20261013-v1.service`, with output under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/r-credit-sensitivity-v1/attempt-v1/`.
Its `raw/build.stdout.txt`, `raw/control_test.stdout.txt` and
`raw/regression.stdout.txt` retain the completed build/check evidence.
`results.json` records live admission status and `r_rows`; an empty list is
not a performance result. The numerical sources and build are pinned while
the job waits; a changed pin stops it before timing, rather than mixing code
versions. The service has a 6-GiB cgroup bound, no swap and CPU affinity 127.

```bash
systemctl --user status spine-regraph-credit-sensitivity-20261013-v1.service
journalctl --user -u spine-regraph-credit-sensitivity-20261013-v1.service -n 30 --no-pager
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
Large FPGA work remains queued until its separate memory gate passes.
