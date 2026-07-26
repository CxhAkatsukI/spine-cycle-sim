# Architecture figures

- `fine_grained_cycle_sim_architecture.svg`: target architecture and evidence
  flow for `codex/fine-grained-cycle-sim`. Its editable Graphviz source is the
  adjacent `.dot` file.
- `normalized_sparse_hbm_binding.svg`: fail-closed sparse SST controller
  binding for normalized Spine and GraSU/ReGraph runs. It distinguishes the
  32-channel physical namespace, workload-reachable controller set, exact
  timing-equivalence claim, and sparse DRAM energy boundary. Its editable
  source is the adjacent `.dot` file.
- `grasu_regraph_pma_native_contract.svg`: frozen GraSU update topology and the
  explicit split between the currently measured capacity-wide compactor path
  and the target PMA-native ReGraph path. Its editable source is the adjacent
  `.dot` file.
- `grasu_regraph_profile_ladder.svg`: claim-preserving progression from the old
  routed compactor baseline through the weighted-PMA `sw_emu` implementation,
  normalized three-algorithm simulator, and projected design points. Its
  editable source is the adjacent `.dot` file.
- `grasu_native_update_vertical.svg`: implemented execution-driven GraSU U55C
  update path, including payload-backed PMA RMW, finite queues, shared-HBM
  contention, and the correctness/statistics sinks. Its editable source is the
  adjacent `.dot` file.
- `grasu_regraph_pma_native_sssp.svg`: implemented normalized GraSU update to
  PMA-native ReGraph weighted SSSP path for one 19-bit destination partition.
  It shows source-cache refill,
  capacity-wide PMA scanning, finite four/eight-lane batches, gather sweeps,
  the 64-to-512-bit free-running merger, three finite inter-kernel streams,
  partition-wide HBM apply/state mirroring, and the modeled six-stage RAW
  bypass. Its editable source is the adjacent `.dot` file.
- `spine_cycle_sim_architecture.svg`: legacy Python simulator architecture.
  The `.dot` file is its source and the `.png` is a raster export.
- `spine_candidate10_grouped_publication_schedule.svg`: frozen Candidate-10
  grouped-publication RTL control lower bound and its composition with the
  execution-driven AXI/SST-HBM window. Its editable source is the adjacent
  `.dot` file.
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
- `spine_dirty_rmw_pipeline.svg`: source-ordered persistent dirty bitmap/list
  read-modify-write, duplicate suppression, metadata lifecycle, and the shared
  finite AXI/HBM path. Its editable source is the adjacent `.dot` file.
- `spine_carry_refill_pipeline.svg`: request-driven carry streams, lower-level
  head/lookahead buffers, winner-triggered HBM refill, and the remaining target
  writer boundary. Its editable source is the adjacent `.dot` file.
- `spine_page_list_metadata.svg`: packed page-list IDs/counts, target commit,
  lower-level retirement, and the future payload-driven cursor consumer. Its
  editable source is the adjacent `.dot` file.
- `spine_payload_driven_carry_cursor.svg`: HBM-authoritative carry metadata,
  page, bitmap, row-offset, and old-edge chain with cursor refill timing and
  rejection paths. Its editable source is the adjacent `.dot` file.
- `spine_online_carry_writer.svg`: online differential group emission, packed
  row/mask/page/bitmap/page-list state, finite AXI writer backpressure, and the
  logical output mirror. Its editable source is the adjacent `.dot` file.

Regenerate a Graphviz SVG from the repository root with:

```bash
dot -Tsvg docs/figures/fine_grained_cycle_sim_architecture.dot \
  -o docs/figures/fine_grained_cycle_sim_architecture.svg
```
