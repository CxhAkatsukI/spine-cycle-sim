# Validation And Retained Failures

This report distinguishes the fresh numerical gates from historical frozen
contracts. A passing core or figure gate does not make the full repository
test suite green. All paths below are members/prefixes of the portable
`evidence/evidence.tar.gz`, unless explicitly stated otherwise.

## Passing Gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Fresh Release numerical core | 39/39 CTest targets pass, including separate focused warm-PR test | `core-tests-v7/results.json`, commands, full logs and sources |
| Same-model final matrix | Six smoke arms and eighteen real-input arms; nine complete pairs, unchanged pins, no failures | `matrix-v5/results.json`, all configurations, states and raw logs |
| Spine owner bookkeeping | Ten saved arms: state, cycles, traffic and energy exact | `runtime-equivalence-v1/` |
| Explicit finite-read-credit replay | Twelve SSSP trajectories; answers/bytes/G/Spine exact, declared R-cycle correction, registration-order invariant | `sssp-replay-v5/` and `pre_extension/results.json` |
| Figure refresh and delivery tests | 27/27 pass, including source/energy/state corruption and snapshot-exclusion checks | `focused-python-v2/figures.stderr.txt` |
| Organization tests | 6/6 pass | `focused-python-v2/organization.stderr.txt` |
| Original-R offline model and board-host CPU controls | 5/5 plus 9/9 pass in isolation; no board run | `python-isolated-v1/` |
| Process cleanup and route watchdog tests | 5/5 plus 9/9 pass with the compatible finite-cgroup environment; no routing launched | `route-test-environment-v1/` |

The 39-target numerical gate includes independent CC/PR oracles, FP32
multipart/tail cases, residual and replica checks, shared-channel pressure,
finite reordered-read credits, held consumers and registration-order checks.
The AXI tests cover capacities 1/2/4/32 and issue widths 1/4; production storage
was not increased to avoid the deadlock.

The later multipart transport gate runs all **30 figure tests**, including
three new transport tests (lossless assembly, corruption/missing/reordered
parts, and rejected unindexed files). Its logs and resource records are in
`validation/`, outside the already sealed numerical archive. Publication
changes only transport and rechecks the complete original archive hash.

## Full Python Suite Is Not Green

`python-suite-v4` ran **2,906 tests: 40 failures, 9 errors, 8 skips**.
Its complete output and resource record remain archived. Failure groups:

| Group | Count | Disposition |
| --- | ---: | --- |
| Frozen numerical-source identity checks against preceding accepted profiles | 34 failures | Current core is a new model; do not rewrite old acceptance manifests to pass these checks |
| Frozen GraSU publication-source contract | 1 failure | Source hash differs; original publication admission is not recovered |
| Old FPGA overlap plugin/profile identity | 2 failures | Frozen/current identity mismatch; no new calibration claim |
| Older evaluation alignment expecting `READY` | 2 failures | Actual status remains `INCOMPLETE`, not silently admitted |
| Profile capability catalog coverage | 1 failure | Seven experimental profiles missing from the older capability list; remains open |
| Frozen v15/v19 plugin identity contracts | 3 errors | External binary/source identity mismatch; remains open |
| Architecture profile schema | 1 error | Existing profile/schema incompatibility; remains open |
| Original-R isolated CPU setup | 2 errors | The whole-suite finite environment is rejected by these controls; the 14 isolated tests pass as recorded above |
| Route cleanup/watchdog subprocess setup | 3 errors | Inherited 2-GiB hard `RLIMIT_AS` prevents tests installing a 64-GiB child address-space limit; the 14 isolated tests pass under an exact 2-GiB RAM cgroup with no inherited hard address-space ceiling |

The isolated route rerun still enforces **2 GiB RAM for the entire tree,
zero swap, a live reserve and finite timeouts**. It does not grant 64 GiB
physical memory or start FPGA tools. The original failed runs remain failed;
the independent reruns explain the environment issue rather than relabeling
their outcome. Forty failures and four non-environment errors remain open.
Some frozen source-contract failures are intentionally triggered by this
round's numerical correction; they cannot all be called pre-existing.

## Earlier Attempts Are Retained

- `sssp-replay-v4` rejects the intentional finite-credit R timing change;
  `sssp-replay-v5` names and checks that correction explicitly.
- `core-tests-v6` retains the 38/39 result from an incidental-contention A4
  test; v7 uses explicit finite shared-channel pressure and passes 39/39.
- Earlier PR, deadlock/probe, partial and superseded matrix attempts retain
  their original status. The selected data is the complete `matrix-v5`, not
  a mixture of favorable rows from different attempts.
- `python-suite-v2` was interrupted during memory reclaim; v3 retained tmpfs
  exhaustion/setup failures. V4 uses disk-backed temporary storage and is
  the complete-suite report above. None is discarded or called a pass.

Offline archive verification checks membership/hashes, source/core identity,
all output-state hashes, independent-oracle contracts, request/byte closure,
all-channel energy conservation, table arithmetic and the explicit SSSP
correction trajectory. It verifies reproducibility and the stated diagnostic
scope, not FPGA calibration or original-publication performance parity.
