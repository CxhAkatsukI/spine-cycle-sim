# Evaluation Figure Refresh

This directory is a review packet, not an in-paper replacement. It addresses
the open questions about Figures 7--10 while keeping the TeX repository
unchanged until the revised evidence is accepted.

## Frozen decisions

- Figure 7 is hardware-only. Panels (a)--(c) use three correctness-admitted
  U55C repetitions on eight complete graphs under the setup-inclusive dynamic
  latency boundary. Panel (d) temporarily uses the existing three compact
  Full PageRank FPGA rows and is explicitly labeled as compact evidence.
- Projected values, timeout lower bounds, and missing bars are removed from
  Figure 7.
- Figures 8--10 are regenerated here from the currently archived simulator
  evidence. They are candidate formatting/data-boundary fixes, not the final
  post-calibration replacement.
- Figure 8 gives each panel a symbol-appropriate legend and uses
  setup-inclusive update-only throughput.
- Figure 9 removes vertical separators and groups AU, SU, and WK by algorithm,
  with dataset color encoded once in a shared legend.
- Figure 10 uses reader-facing workload labels and explicitly states that each
  stacked bar is normalized to 100% of its own device-cycle interval.

## Current contents

- `figures/fig7_fpga_speedup_candidate.{pdf,png}`: first hardware-only
  candidate.
- `data/fig7_fpga_speedup.csv`: frozen medians and observed min/max values.
- `provenance/fig7.json`: hashes of every input evidence table.
- `figures/fig8_update_throughput_candidate.{pdf,png}`: setup-inclusive
  update-only throughput speedup, split into cross-dataset and batch-size
  panels.
- `figures/fig9_memory_energy_candidate.{pdf,png}`: accepted-byte and HBM
  energy ratios. The two panels do not share a y-axis.
- `figures/fig10_rq3_breakdown_candidate.{pdf,png}`: normalized RQ3
  end-to-end cycle breakdown over representative realized-work cases.
- `provenance/fig8.json`, `provenance/fig9.json`, and `provenance/fig10.json`:
  hashes, timing scope, normalization, and current limitations.
- `alignment_audit.md` and `provenance/alignment_audit.json`: gate whether
  refreshed figures use FPGA-aligned campaign evidence or still fall back to
  archived simulator data.
- `hardware_and_calibration_status_20260810.md`: current evidence boundary,
  including the Fig. 7 convergence semantics and why Fig. 8--10 remain interim.

The calibration report and final handoff archive remain pending. A failed
calibration row will be retained under `diagnostics/` and will not be promoted
into a final figure.

## Figure 10 label key

- `ZN`: zero-net update.
- `SI`: shallow insertion.
- `A-S`, `L-S`, `S-S`: AskUbuntu, LiveJournal-2008, and Superuser shallow
  SSSP insertion rows.
- `L1`, `L3`, `L5`: synthetic traces that force carry through levels 1, 3,
  and 5.
- `PR-corr`: PageRank residual-correction rows.
- `FL`, `SU`, `WK`: Flickr, Superuser, and WikiTalk residual-correction rows.
- `Del`: SSSP deletion-fallback rows on AU, SU, and WK.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 -m venv /data/tmp/chuxiao/spine-cycle-sim-eval-venv
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/pip install -e '.[plots]'
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/render_evaluation_refresh.py
```

After the calibration-refresh campaign has produced complete pair rows, rerun
with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/finalize_evaluation_refresh.py
```

The finalizer runs campaign analysis with `--require-complete`, calls the
renderer with the resulting analysis directory, refreshes the FullPR route
evidence, and writes the alignment audit. For debugging only, pass
`--allow-partial`; otherwise incomplete pair rows are rejected before final
figures are regenerated.

When current-model Fig. 8 or Fig. 10 evidence has been regenerated, pass it
through the finalizer rather than editing the renderer constants:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/finalize_evaluation_refresh.py \
  --fig8-data-dir <DIR_WITH_PERSISTENT_UPDATE_SETUP_CSVS> \
  --fig10-data-dir <DIR_WITH_RQ3_CSVS_AND_SUMMARY>
```

The Fig. 8 directory must contain current-model setup-inclusive update-only
rows, not formal campaign simulator wall time. In particular,
`spine_host_wall_seconds` and `competitor_host_wall_seconds` in publication
`pair_rows.csv` are CPU time spent by the simulator process and must not be used
as modeled host preprocessing time. See
`hardware_and_calibration_status_20260810.md` for the current Fig. 8 blocker.
Generate the Fig. 8 CSVs from an admitted update-only evidence root with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/build_current_fig8_update_only_evidence.py \
  --formal-root <CURRENT_FORMAL_UPDATE_SCALING_ROOT> \
  --out-root <CURRENT_UPDATE_ONLY_EVIDENCE_ROOT> \
  --host-tool /data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-build/cpp/persistent_update_host_benchmark
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/export_persistent_update_setup_fig8.py \
  --evidence-root <CURRENT_UPDATE_ONLY_EVIDENCE_ROOT> \
  --out-dir <FIG8_DATA_DIR> \
  --status PASS_CURRENT_MODEL_DATA
```

The renderer refuses `--fig8-data-dir` unless that directory also contains
`persistent_update_setup_manifest.json` with
`status=PASS_CURRENT_MODEL_DATA`.

If a sidecar campaign is used to finish queued long-tail cases, merge it during
finalization with repeated `--extra-result-root <DIR>` arguments.

Campaign ETA can be inspected with:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/estimate_evaluation_campaign_eta.py
```
