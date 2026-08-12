# Hardware and Calibration Status

Date: 2026-08-12

This note records the current evidence boundary for the evaluation-refresh
packet. It is intentionally separate from the paper text.

## Figure 7 Timing Semantics

Panels (a)--(c) use routed U55C hardware for the full-graph sharded-K4
experiments. The timing window is:

1. The old graph is already converged and resident.
2. One update batch is applied.
3. The accelerator runs until the updated state converges.
4. The reported latency is setup-inclusive dynamic latency.

This is not a one-hop truncation.

Representative raw protocol checks:

- SSSP AU G+R: `executed_supersteps=2`, `hardware_converged=1`,
  `oracle_supersteps=2`.
- SSSP AU Delta.hls: `iterations=2`, `coverage=converged`.
- CC AU G+R: `executed_supersteps=1`, `hardware_converged=1`,
  `oracle_supersteps=1`.
- CC AU Delta.hls: `iterations=1`, `coverage=converged`.
- ResPR AU G+R: `pipeline_executions=1`, `propagation_rounds=0`,
  `hardware_converged=1`, `oracle_propagation_rounds=0`.
- ResPR AU Delta.hls: `iterations=0`, `coverage=converged`.

Panel (d) is different: it temporarily uses compact Full PageRank routed
hardware. The current compact FullPR protocol is fixed-round
(`rounds=3` / `coverage=three_iterations`), not convergence-to-epsilon. The
sharded-K4 FullPR route has now produced an xclbin and routed reports, but it
misses the 150 MHz target slightly (`WNS=-0.069 ns`, `TNS=-2.591 ns`, 84 setup
failing endpoints). It is therefore recorded as `PASS_TIMING_MISS` evidence and
should not replace panel (d) until its correctness/performance matrix is run
and its timing status is accepted for the intended claim.

## Superseded Calibration Coverage

The repository contains older G+R K4 FPGA calibration evidence:

| Algorithm | Evidence directory | Holdout max abs error |
|---|---|---:|
| Weighted SSSP | `docs/evidence/k4_fpga_sssp_calibration_20260805` | 18.02% |
| CC | `docs/evidence/k4_fpga_cc_calibration_20260806` | 1.10% |
| Residual PR | `docs/evidence/k4_fpga_respr_component_calibration_20260806` | 5.69% |
| Full PR | `docs/evidence/k4_fpga_fullpr_component_calibration_20260806` | 2.59% |

These remain historical sanity checks. Current admission decisions use Spine
v15 and G+R persistent-update v20; the older rows are not reused as holdout.

## Figure 8--10 Status

The current evidence boundary is:

- Figure 8: `PASS_CURRENT_MODEL_DATA`. All seven unique update-only runs pass
  correctness, structural-work, memory-ledger, and frozen-identity gates.
- Figure 9: pending only the final WikiTalk G+R rows. Completed rows pass
  correctness and strict request/byte conservation.
- Figure 10: `PARTIAL_COMPONENT_CALIBRATION`. Seven SSSP rows are admitted for
  breakdown; the whole-machine cost model is diagnostic and rejected.

The Spine v15 whole-machine holdout is `FAIL`: structural and memory ledgers
pass, but CC compute has 37.39% median absolute error and workload ordering is
reversed on the two-row SSSP and CC holdouts. This failure is retained. It does
not invalidate Figure 8's narrower maintenance-only window, whose SSSP
maintenance holdout is 9.25% median and 16.15% maximum absolute error.

The frozen G+R v20 persistent-update model passes the untouched SO/PK holdout
without refitting. Median/maximum absolute errors are 16.88%/32.24% for SSSP,
5.90%/8.28% for CC, and 4.47%/8.59% for Residual PageRank.

Important Figure 8 boundary: Figure 8 uses setup-inclusive update-only
throughput, not simulator wall time and not full convergence time. The restored
path models persistent resident graph updates, host preprocessing, H2D
transfer, launch/sync cost, and device update cycles while explicitly disabling
graph computation. The current branch now contains the pieces needed for that
boundary:

- `spine_cycle_sim/experiments/persistent_update_only.py`
- `scripts/derive_update_only_manifest.py`
- `scripts/run_current_fig8_update_only_case.py`
- `scripts/export_persistent_update_setup_fig8.py`
- `cpp/tools/persistent_update_host_benchmark.cpp`

For the device portion, Spine uses the current SST maintenance-only path and
G+R uses the new `--update-only` weighted-PMA path, which stops after PMA update
maintenance and does not launch ReGraph compute. G+R update-only also uses a
lightweight host oracle that avoids SSSP Dijkstra because no graph-compute
correctness is claimed for this figure. Host preprocessing is measured by
`persistent_update_host_benchmark`.

The admitted current Fig. 8 evidence root is:

- `/data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig8_20260812`

The tracked renderer input is:

- `docs/evaluation_refresh_20260810/fig8_current_v20`

The generated CSVs are marked `PASS_CURRENT_MODEL_DATA` and cover:

- cross dataset, 512 updates: AU, SU, WK, SO, PK;
- AU batch sweep: 64, 512, and 4096 updates.

The setup-inclusive speedups are:

- cross dataset: AU `11.24x`, SU `10.37x`, WK `18.48x`, SO `18.94x`, PK `6.09x`;
- AU batch sweep: 64 updates `11.47x`, 512 updates `11.24x`, 4096 updates
  `10.07x`.

Reproduction sketch:

```bash
python3 scripts/export_persistent_update_setup_fig8.py \
  --evidence-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig8_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig8_current_v20 \
  --status PASS_CURRENT_MODEL_DATA \
  --cross-dataset au:AU \
  --cross-dataset su:SU \
  --cross-dataset wk:WK \
  --cross-dataset so:SO \
  --cross-dataset pk:PK \
  --batch-count 64 \
  --batch-count 512 \
  --batch-count 4096
```

Figure 10's immutable execution package contains 21 correctness-gated rows.
Seven SSSP rows are admitted to the plotted breakdown after v15 aggregate
component calibration: three shallow insertions, three forced-carry cases, and
one deletion fallback. The remaining limitations are explicit:

- Zero-net is omitted because current HLS lacks the paper no-repair fast path.
- PageRank correction is omitted because routed hardware has no nonzero
  iterative-round component sample.
- Sort, physical resolve/apply, and seed have holdout R2 values of 0.971,
  0.962, and 0.904. Carry is only a two-point holdout. Directory, switch, and
  drain correlations are unsupported.
- The global cost model has 59.17% median and 107.35% maximum absolute error
  on seven real-trace holdout rows and is not admitted.

## Active Figure 9 Completion Run

A frozen nine-row memory campaign is running under:

```bash
/data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812
```

It covers AU/SU/WK and all three differential algorithms. Spine data comes
from the immutable v12 execution package; G+R uses the unified v19 plugin with
v20-frozen evidence identities. Figure 9 records accepted backend bytes and
bound-channel DRAMSim3 energy, not simulator wall time.

```bash
/home/chuxiao/spine-cycle-sim-sharded-k4-v3/cpp/sst/build/sst-current-fpga-v19
```

Every admitted row must satisfy:

- architecture correctness `PASS`;
- memory ledger `PASS`;
- backend intents = grants = consumed grants = backend requests;
- no pending arbitration work at completion;
- DRAMSim3 reads + writes = backend requests.

Monitor it with:

```bash
watch -n 5 'for f in \
  /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812/\
runs_current_v1/wk/grasu_regraph/*/progress.json; do jq -c . "$f"; done'
```

Export only after all nine rows complete:

```bash
python3 scripts/export_current_fpga_fig9.py \
  --spine-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812 \
  --grasu-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig9_current_v20
```

Historical calibration contracts v4--v8 referenced a mutable CC architecture
profile later changed by the August 12 host-reordering work. Tests now expose
that hash drift instead of pretending the historical contract is current. The
v20 Figure 9 contract freezes the new profile hash and is unaffected.

## Immediate Replacement Rule

- Figure 7(a)--(c): can be discussed as real FPGA evidence now.
- Figure 7(d): use as compact FullPR placeholder only.
- Figure 8: admitted for its narrow update-only claim.
- Figure 9: admitted only after the nine-row exporter returns
  `PASS_CURRENT_MODEL_DATA`.
- Figure 10: use only the admitted SSSP breakdown and supported mechanism
  correlations; do not claim a calibrated whole-machine cost model.
