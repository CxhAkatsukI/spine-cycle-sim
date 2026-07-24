# Architecture figures

- `fine_grained_cycle_sim_architecture.svg`: target architecture and evidence
  flow for `codex/fine-grained-cycle-sim`. Its editable Graphviz source is the
  adjacent `.dot` file.
- `spine_cycle_sim_architecture.svg`: legacy Python simulator architecture.
  The `.dot` file is its source and the `.png` is a raster export.
- `spine_architecture_annotated.svg`: detailed mapping between the split Spine
  HLS design and the calibrated legacy simulator. Its own header pins the old
  source/calibration snapshot; it is not the current fine-grained core design.
- `spine_exact_range_task_reader.svg`: current payload and control path for the
  latest HLS exact range-task reader. It shows DEVICE_DIRTY and HOST_ACTIVE
  payload decoding, the 16-credit source-value protocol, HBM level
  metadata/epoch gating, two-pass range replay, the ten-word terminal
  diagnostic transcript, HOST coverage validation, and the two-pass
  ACK_DIRTY ownership closeout. It now also shows DEVICE limit handoff and the
  payload-driven HOST discovery/replay fallback. Its editable source is the
  adjacent `.dot` file.
- `spine_axi_request_window.svg`: implemented loop-scoped bounded AXI issue,
  ordered response retirement, and replay backpressure. The separate coarse
  global-window implementation remains a labeled what-if. Its editable source
  is the adjacent `.dot` file.
- `spine_axi_interface_profile.svg`: source-shaped per-interface AXI beat
  widths and outstanding limits. It also marks platform width conversion as a
  remaining explicit component. Its editable source is the adjacent `.dot`
  file.
- `spine_streamed_maintenance_scans.svg`: request-scoped sorted-edge read
  beats, finite FIFO backpressure, ordered retirement, parent completion, and
  report-derived scan-loop timing. Its editable source is the adjacent `.dot`
  file.

Regenerate a Graphviz SVG from the repository root with:

```bash
dot -Tsvg docs/figures/fine_grained_cycle_sim_architecture.dot \
  -o docs/figures/fine_grained_cycle_sim_architecture.svg
```
