# Evaluation Figure Refresh

This directory is a review packet, not an in-paper replacement. It addresses
the open questions about Figures 7--10 while keeping the TeX repository
unchanged until the revised evidence is accepted.

**Current handoff (corrected September 17): [Figures 7--11](figure7_10_handoff_v1/README.md).**
Figure 10 now uses the same frozen v12 Spine plugin as Figures 8/9/11.
Its previous `7563b028...` candidate is superseded. The current handoff includes
raw evidence, the new SSSP zero-net fallback result, and the six-question audit.

## Frozen decisions

- Figure 7 is hardware-only. Its grouped three-algorithm panel uses three correctness-admitted
  U55C repetitions on eight complete graphs under the setup-inclusive dynamic
  latency boundary. Panel (b) uses the existing three compact
  Full PageRank FPGA rows and is explicitly labeled as compact evidence.
- Projected values, timeout lower bounds, and missing bars are removed from
  Figure 7.
- Figure 8 is regenerated from current setup-inclusive update-only evidence
  produced by the frozen v15 Spine and v20 sharded-K4 G+R models.
- Figure 9 is admitted only when all nine AU/SU/WK algorithm pairs pass
  correctness, memory-ledger, arbitration, and DRAM-request conservation.
- The complete Figure 10 candidate is explicitly simulator-predicted and uses
  correctness-admitted, cycle-conserving execution rows for all five workload
  classes. The older component-calibrated diagnostic packet is retained as a
  separate artifact and is not promoted to a whole-machine FPGA cost model.
- Figure 8 gives each panel a symbol-appropriate legend and uses
  setup-inclusive update-only throughput.
- Figure 9 removes vertical separators and groups AU, SU, and WK by algorithm,
  with dataset color encoded once in a shared legend.
- Figure 10 uses reader-facing workload labels and explicitly states that each
  stacked bar is normalized to 100% of its own device-cycle interval.

## Current contents

- `figure7_10_handoff_v1/`: self-contained final handoff for Figures 7--11,
  including one standalone Python renderer, frozen input CSVs, provenance,
  GraphyFlow reference archive, PDF/PNG outputs, a combined preview, and one
  overall explanation document. Use this directory when sharing the complete
  plotting package.
- `figures/fig7_fpga_speedup_candidate.{pdf,png}`: first hardware-only
  candidate.
- `data/fig7_fpga_speedup.csv`: frozen medians and observed min/max values.
- `provenance/fig7.json`: hashes of every input evidence table.
- `fig8_current_v20/`: admitted setup-inclusive update-only data and immutable
  provenance for five datasets plus the AU batch-size sweep.
- `fig9_current_v20/`: final nine-row accepted-byte and bound-channel DRAMSim3
  energy evidence with complete correctness and conservation gates.
- `fig10_current_v15_evidence/`: seven admitted SSSP breakdown rows, mechanism
  correlations, and explicit rejection of the global cost model.
- `simulator_predicted_fig10_v1/`: superseded historical breakdown using the
  earlier plugin. Use the corrected handoff's Figure 10 instead.
- `provenance/fig8.json`, `provenance/fig9.json`, and `provenance/fig10.json`:
  hashes, timing scope, normalization, and current limitations.
- `alignment_audit.md` and `provenance/alignment_audit.json`: gate whether
  refreshed figures use FPGA-aligned campaign evidence or still fall back to
  archived simulator data.
- `hardware_and_calibration_status_20260810.md`: current evidence boundary,
  including the Fig. 7 convergence semantics and Fig. 8--10 admission limits.

`current_fpga_fig8_10_v20/` is an earlier evidence packet. Its finalizer
refuses incomplete Figure 9 data and records Figure 10's partial calibration
status in the top-level manifest. Failed calibration evidence remains tracked
but is not silently promoted.

## Figure 10 admitted scope

- `SI`: shallow insertion.
- `AU`, `SU`, `WK`: AskUbuntu, Superuser, and WikiTalk current-model rows.
- `L1`, `L3`, `L5`: synthetic traces that force carry through levels 1, 3,
  and 5.
- `Del`: synthetic SSSP deletion-fallback row.

Zero-net is omitted because the current HLS does not implement the paper's
no-repair fast path. PageRank correction is omitted because no routed nonzero
iteration sample exists for component calibration.

That omission applies only to `fig10_current_v15_evidence/`. The corrected
`figure7_10_handoff_v1/` includes all five simulator-predicted classes using
the frozen v12 plugin. Zero-net is an SSSP rebuild fallback; SU/WK PR-corr
uses verified zero propagation rounds. Plugin identity is checked across
Figures 8--11, in addition to correctness and cycle-conservation checks.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 -m venv /data/tmp/chuxiao/spine-cycle-sim-eval-venv
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/pip install -e '.[plots]'
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/render_evaluation_refresh.py

/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/package_simulator_predicted_fig10.py
```

After the current Figure 9 matrix has produced all nine rows, export and
assemble the admitted packet with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/export_current_fpga_fig9.py \
  --spine-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812 \
  --grasu-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig9_current_v20

/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/finalize_current_fpga_fig8_10.py \
  --fig8-dir docs/evaluation_refresh_20260810/fig8_current_v20 \
  --fig9-dir docs/evaluation_refresh_20260810/fig9_current_v20 \
  --fig10-dir docs/evaluation_refresh_20260810/fig10_current_v15_evidence \
  --out-dir docs/evaluation_refresh_20260810/current_fpga_fig8_10_v20
```

The finalizer requires `PASS_CURRENT_MODEL_DATA` for Figures 8 and 9 and
`PARTIAL_COMPONENT_CALIBRATION` for Figure 10. There is no partial-data option
for the final packet.

The Fig. 8 directory must contain current-model setup-inclusive update-only
rows, not formal campaign simulator wall time. In particular,
`spine_host_wall_seconds` and `competitor_host_wall_seconds` in publication
`pair_rows.csv` are CPU time spent by the simulator process and must not be used
as modeled host preprocessing time. Generate current Fig. 8 CSVs from the
dedicated update-only runner with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/run_current_fig8_update_only_case.py \
  --materialization-manifest <DERIVED_OR_BASE_MATERIALIZATION_MANIFEST> \
  --dataset-id <DATASET_ID> \
  --dataset-key <SHORT_KEY> \
  --updates <UPDATE_COUNT> \
  --out-dir <CURRENT_UPDATE_ONLY_EVIDENCE_ROOT>/cross_dataset/<SHORT_KEY> \
  --host-tool /data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-build/cpp/persistent_update_host_benchmark
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/export_persistent_update_setup_fig8.py \
  --evidence-root <CURRENT_UPDATE_ONLY_EVIDENCE_ROOT> \
  --out-dir <FIG8_DATA_DIR> \
  --status PASS_CURRENT_MODEL_DATA
```

The finalizer refuses the Fig. 8 directory unless it contains
`persistent_update_setup_manifest.json` with
`status=PASS_CURRENT_MODEL_DATA`.
