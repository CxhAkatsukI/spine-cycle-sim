# Current-FPGA Figure 10 v15 admission

This note records the current evidence boundary for the Figure 10 realized-work
breakdown. It does not promote a diagnostic plot to a fully FPGA-calibrated
result.

## Reproduction

The immutable execution package contains 21 correctness-gated rows from the
current v12 Spine SST plugin. The five forced-carry wrappers now include the
known synthetic vertex count, so their maintenance envelope can be projected
without inventing graph metadata.

```bash
python3 scripts/build_current_fpga_rq3_v12.py \
  --simulation-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812 \
  --carry-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/carry \
  --delete-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/delete_fallback \
  --residual-correction-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/residual_correction \
  --residual-correction-sweep-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/residual_correction_sweep \
  --out-dir /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/package_with_vertices

python3 scripts/calibrate_current_fpga_rq3_v15.py \
  --rq3-package /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/package_with_vertices \
  --frozen-model docs/evaluation_refresh_20260810/calibration_v15_frozen/frozen_spine_mechanism_component_models.json \
  --holdout-analysis docs/evaluation_refresh_20260810/calibration_v15_holdout/analysis_manifest.json \
  --out-dir docs/evaluation_refresh_20260810/fig10_current_v15_with_vertices \
  --allow-partial-holdout
```

## Result

- 21 correctness-gated execution rows are present.
- 14 rows receive a frozen v15 aggregate component-envelope projection.
- 7 Residual PageRank rows remain `STRUCTURE_ONLY`: the routed FPGA evidence
  has no nonzero iterative-round sample for this algorithm.
- The independent v15 holdout remains `FAIL`; its known failures are the CC
  compute envelope and workload-rank transfer for CC and SSSP.
- FPGA counters do not expose the ten individual stages. Within-envelope stage
  fractions therefore remain execution-model attribution.

The generated manifest consequently reports `PARTIAL_COMPONENT_CALIBRATION`.
It is valid diagnostic evidence for which realized-work mechanisms appear, but
it is not admissible as a fully FPGA-calibrated Figure 10 performance claim.
