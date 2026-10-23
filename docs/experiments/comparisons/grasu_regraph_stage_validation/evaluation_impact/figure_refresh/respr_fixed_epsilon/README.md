# Residual PageRank: Historical Fixed Threshold

Status: **COMPLETE_FIXED_EPSILON_RES_PR_DIAGNOSTIC**. All three numerical
pairs, both correctness smokes, 39 core tests and offline verification pass. This
bounded follow-up changes only the residual threshold of the preceding
simulator comparison; it does not change the paper or FPGA results.

## Results

Speedup is G+R cycles divided by Spine cycles. These are **simulator-predicted
resident-device cycles**, not host-inclusive or measured FPGA times.

| Dataset | Spine cycles | G+R cycles | Spine speedup | Initial correction active vertices |
| --- | ---: | ---: | ---: | ---: |
| AU | 8,533 | 766,215 | 89.79x | 0 |
| SU | 8,035 | 990,248 | 123.24x | 0 |
| WK | 12,214 | 1,484,599 | 121.55x | 0 |

The advantage exists for these three batches under the restored threshold,
but **none exercises nonempty propagation**. They are real eight-insertion
batches, not zero-net updates: correction modifies the residual state, but
no residual crosses epsilon. Both arms finish with identical rank arrays,
which equal their old rank arrays. Spine completes maintenance and correction
without reading active edge sources; G+R still prepares state and scans a
full graph round. The recorded Spine round is an empty termination round,
not one hop of propagation. Do not claim 90--123x for general residual
propagation or all sparse updates from these cases.

| Dataset | Previous strict Spine / G+R cycles | Previous strict Spine / G+R rounds | Fixed-threshold maximum stored residual (Spine) | Rank L1 error versus new-graph double oracle |
| --- | ---: | ---: | ---: | ---: |
| AU | 183,160,033 / 34,974,705 | 57 / 58 | 1.791e-7 | 1.24933e-5 |
| SU | 164,806,227 / 39,893,391 | 48 / 49 | 1.861e-7 | 7.85769e-6 |
| WK | 307,094,993 / 65,040,895 | 55 / 56 | 6.242e-8 | 6.28042e-6 |

The older strict threshold required many rounds of below-1e-6 residual work.
At the restored threshold, this work is intentionally not required by the
algorithm contract. Both core libraries have identical SHA256 hashes before
and after the rerun: no architecture or timing-coefficient change explains
this particular reversal. This comparison does not establish that threshold
is the only cause of differences from the much older paper implementation.

The actual maximum rank errors are AU 1.19249e-6, SU 2.49713e-7 and WK
4.15919e-7. Epsilon bounds the **residual**, not direct rank error, so AU's
rank error exceeding 1e-6 is not a failed residual stopping check. The
conservative `V*epsilon/(1-damping)` L1 bounds are 3.43521, 3.78211 and
7.60099; these are loose bounds, not an assertion of tight global accuracy.
The actual L1 errors above are retained to make this distinction visible.

## Why Rerun

The historical primary contract is a **fixed per-vertex `epsilon=1e-6`**,
activation `abs(residual[v]) > epsilon`, and termination with no active
vertices and stored residual infinity norm at most epsilon. See the
[historical contract](../../../../deltahls_residual_k1_screening_20260728.md).
The preceding [nine-pair collection](../multialgorithm/README.md) instead
used `epsilon=1e-5/V`; that changes precision and is not a normalization of
the historical setting. Its three negative ResPR results remain preserved,
but do not establish performance at the historical threshold.

## Fixed Scope

- AU, SU and WK, the same complete materialized sink-free projections and
  eight insertion records as the preceding matrix, with physical vertex IDs.
- Both arms preload the same independently converged old rank, receive the
  same update batch, and use FP32 damping 0.85 and fixed FP32 epsilon 1e-6.
- Count resident batch maintenance, device correction/preparation and all
  propagation through termination; exclude initial preload and host time
  on both arms. This is not a new setup-inclusive Figure 8 measurement.
- Keep the same core architecture, resources, 150-MHz clock, DRAMSim3 model,
  and all-32-channel energy accounting. No timing coefficient or architecture
  optimization is introduced to obtain a preferred result.
- Require both small correctness smokes, independent final-rank checks,
  complete residual stopping checks, identical initial/oracle state hashes,
  and drained request/byte ledgers. Report actual rank error as well as the
  conservative epsilon-dependent bound; the bound is not fixed global L1
  accuracy and grows with vertex count.

The current old-rank oracle is a tight double-precision solve rounded to
FP32, unchanged from the preceding matrix. This restores the historical
activation/stop threshold, not every detail of the historical experiment.
Spine correction remains oracle-directed timed replay; original-G and
original warm-residual-R timing admission remain open. Results are simulator
predictions, not new FPGA calibration or publication-performance reproduction.

## Reproduce

The explicit `--residual-epsilon` option now defaults to fixed 1e-6. Use fresh
output and core directories; do not rebuild a frozen plugin:

```bash
cmake -S . -B CORE -DCMAKE_BUILD_TYPE=Release
systemd-run --user --wait --pipe --collect --unit=respr-fixed-epsilon \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p RuntimeMaxSec=10800 \
  --working-directory="$PWD" /usr/bin/python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.study \
  --output OUT --core CORE --cpu 7 --timeout 1800 \
  --algorithms ResPR --residual-epsilon 1e-6
```

Each child has a 4-GiB memory limit; the runner atomically reserves its full
6-GiB service budget, allows no swap, and monitors a 24-GiB system reserve.
Both arms run serially. All failures and timeouts must remain in the report.

## Delivery

| Entry | Contents |
| --- | --- |
| [Threshold comparison](data/threshold_comparison.csv) | Strict/fixed cycles, rounds, zero-active counts and actual oracle errors |
| [Figure 9 rows](data/fig9_memory_energy_rows.csv) | Three new ResPR traffic/energy ratios; not mixed into the frozen nine-pair table |
| [Per-arm data](data/fig9_arms.csv) | Absolute cycles, traffic and all-channel energy components |
| [Summary](data/summary.json) | Exact configurations, boundaries, state hashes and source identities |
| [Evidence index](evidence/index.json) | SHA256 membership for the portable raw-evidence archive |
| [Test report](TEST_REPORT.md) | Regression, memory safety, verification commands and remaining limits |

The archive contains complete output states, source snapshots, raw command
logs, DRAMSim3 channel reports and core-test evidence. Full graph/update
inputs, toolchains and linked binaries remain external hash-pinned
dependencies. The preceding strict report is included as an immutable
comparison reference; its complete raw evidence remains in its own frozen
delivery.

The code remains in the existing
`spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm`
package: `study` runs the matrix and `residual_followup` packages/verifies
this explicit three-pair scope. No duplicate plotting or experiment tree is
introduced. From the repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.residual_followup \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh/respr_fixed_epsilon \
  --verify
```
