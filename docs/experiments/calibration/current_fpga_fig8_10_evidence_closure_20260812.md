# Current-FPGA Figure 8--10 evidence closure

## Decision

The current Figure 8--10 review packet is complete under an explicit mixed
admission result:

- Figure 8: `PASS_CURRENT_MODEL_DATA` for setup-inclusive update-only
  throughput.
- Figure 9: `PASS_CURRENT_MODEL_DATA` for conserved accepted bytes and
  bound-channel DRAMSim3 energy.
- Figure 10: `PARTIAL_COMPONENT_CALIBRATION` for seven SSSP breakdown rows and
  selected realized-work correlations. The global cost model is rejected.

The combined manifest status is `PASS_WITH_DECLARED_PARTIAL_FIG10`. This is
intentional: the packet is complete as an audit deliverable, but it does not
turn an unsupported Figure 10 claim into a calibrated result.

## Frozen identities

The evidence is tied to immutable case, architecture, plugin, and calibration
hashes. In particular:

- Delta.hls SST plugin SHA-256:
  `f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70`;
- G+R SST plugin SHA-256:
  `13296920b5493610f706303395200306dea966475b2505779d586f1b9f87c6fc`;
- Spine v15 frozen mechanism model SHA-256:
  `483146050c32bf423a57d8d568dc6d4bff346ff5369dc72650375726f43e3642`;
- G+R v20 frozen persistent-update model SHA-256:
  `6433b04fdcb5dfb60e75dca283e6063d414faabcb16dab182340a6a928a6255d`.

Calibration and holdout are separate. The Spine v15 manifest explicitly says
`holdout_used_for_fit=false`; the G+R v20 holdout says `model_refit=false`.

Historical v4--v8 contracts referenced a CC architecture-profile file that
was later changed by the August 12 host-reordering implementation. The audit
tests now expose the old-to-current hash drift. Current v20 contracts freeze
the current profile and are unaffected.

## Figure 8: update-only throughput

Figure 8 includes measured host preprocessing, modeled PCIe transfer and
launch/synchronization, and frozen calibrated persistent device-update cycles.
Graph propagation is intentionally excluded.

At 512 updates, Delta.hls speedup over G+R is 11.24x on AU, 10.37x on SU,
18.48x on WK, 18.94x on SO, and 6.09x on PK. The AU batch sweep gives 11.47x,
11.24x, and 10.07x at 64, 512, and 4,096 updates.

The narrow component-calibration boundary matters. Spine SSSP maintenance has
9.25% median and 16.15% maximum absolute error on the independent holdout. G+R
v20 passes its untouched SO/PK persistent-update holdout without refitting:
median/maximum errors are 16.88%/32.24% for SSSP, 5.90%/8.28% for CC, and
4.47%/8.59% for Residual PageRank.

## Figure 9: memory traffic and HBM energy

All nine AU/SU/WK pairs pass correctness and strict request conservation. The
accepted-byte ratio G+R/Delta.hls ranges from 1,276.72x to 11,534.73x, with a
5,459.61x median. Bound-channel DRAMSim3 energy ratios range from 709.61x to
15,273.92x, with a 3,684.47x median.

Every architecture row closes this ledger:

```text
unique intents = grants = consumed grants = backend requests
DRAM reads + DRAM writes = backend requests
pending intents = pending grants = 0
```

These are simulator memory-system quantities, not direct FPGA HBM counters.
They support a conserved relative traffic/energy claim under the shared memory
model; they do not support a total-system power claim.

## Figure 10: realized-work evidence

Seven SSSP rows are admitted for the normalized breakdown: AU/SU/WK shallow
insertions, forced carries through L1/L3/L5, and one synthetic deletion
fallback. Zero-net is omitted because current HLS lacks the paper's no-repair
fast path. PageRank correction is omitted because routed hardware has no
nonzero iterative-round component sample.

The holdout correlations support:

| Mechanism | Holdout samples | R2 | Decision |
|---|---:|---:|---|
| Sort/front end | 7 | 0.971 | supported |
| Carry | 2 | 1.000 | limited two-point evidence |
| Physical resolve/apply | 7 | 0.962 | supported |
| Seed | 5 | 0.904 | supported |
| Directory | 7 | 0.427 | unsupported |
| Switch | 7 | 0.406 | unsupported |
| Drain | 7 | 0.021 | unsupported |

The global real-trace cost-model diagnostic has R2=0.979, but its median and
maximum absolute errors are 59.17% and 107.35%. The high R2 reflects ordering
over a large dynamic range; it does not make the absolute predictions usable.
The global model is therefore `DIAGNOSTIC_NOT_ADMITTED`.

## Whole-machine calibration boundary

The Spine v15 whole-machine holdout remains `FAIL`, even though its structural
and memory ledgers pass. The failures are:

- CC compute median absolute error: 37.39%, above the 20% gate;
- SSSP and CC workload rank on the two holdout datasets: -1.0, below the 0.9
  gate.

Consequently, this packet does not claim that current Spine whole-machine
cycles are calibrated across arbitrary datasets, and it does not use the
Figure 10 global cost model for publication-grade latency prediction.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

python3 scripts/export_current_fpga_fig9.py \
  --spine-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812 \
  --grasu-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig9_current_v20

/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/finalize_current_fpga_fig8_10.py \
  --fig8-dir docs/evaluation_refresh_20260810/fig8_current_v20 \
  --fig9-dir docs/evaluation_refresh_20260810/fig9_current_v20 \
  --fig10-dir docs/evaluation_refresh_20260810/fig10_current_v15_evidence \
  --out-dir docs/evaluation_refresh_20260810/current_fpga_fig8_10_v20

python3 -m unittest discover -s tests
git diff --check
```

The final review packet is under
`docs/evaluation_refresh_20260810/current_fpga_fig8_10_v20/`. Its manifest
hashes all three source manifests, the final Figure 9 rows, and every copied
Figure 10 artifact.
