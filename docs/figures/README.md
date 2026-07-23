# Architecture figures

- `fine_grained_cycle_sim_architecture.svg`: target architecture and evidence
  flow for `codex/fine-grained-cycle-sim`. Its editable Graphviz source is the
  adjacent `.dot` file.
- `spine_cycle_sim_architecture.svg`: legacy Python simulator architecture.
  The `.dot` file is its source and the `.png` is a raster export.
- `spine_architecture_annotated.svg`: detailed mapping between the split Spine
  HLS design and the calibrated legacy simulator. Its own header pins the old
  source/calibration snapshot; it is not the current fine-grained core design.

Regenerate a Graphviz SVG from the repository root with:

```bash
dot -Tsvg docs/figures/fine_grained_cycle_sim_architecture.dot \
  -o docs/figures/fine_grained_cycle_sim_architecture.svg
```
