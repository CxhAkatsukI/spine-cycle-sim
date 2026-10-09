# K4-shared FullPR FPGA component-envelope calibration

## Scope

This evidence aligns the execution-driven GraSU + ReGraph Full PageRank
simulator with the conversion-free K4-shared U55C xclbin.  It does not replace
the simulator's FIFO, AXI, HBM, or backpressure execution.  The calibrated
quantity is the routed OpenCL event window used by the matched FPGA matrix.

The routed FullPR xclbin completes bitstream generation and passes all
correctness checks.  Its 150 MHz implementation target is slightly missed
(`WNS = -0.077 ns`), so this evidence is labelled board-runnable rather than
150 MHz timing-closed.

The old single multiplicative scale failed because the simulator's fixed
full-partition sweep hid the PMA stream growth visible in hardware.  The
replacement envelope uses realized work already checked by both executions:

```text
event_cycles = fixed + vertices * c_vertex + executed_pma_slots * c_slot
```

`executed_pma_slots` includes every FullPR round.  The loader rejects a row if
hardware and simulator disagree on vertices, rounds, partition count, PMA
slots, correctness, conversion-free handoff, or shared-ReGraph topology.

## Evidence split

Calibration uses two compact real-topology slices and two synthetic scale
anchors:

- Amazon-2008 insertion batch of eight;
- Web-Google insertion batch of eight;
- 64-vertex chain; and
- 4,096-vertex PMA-spread star with 1,024 insertions.

Neither holdout participates in the fit:

- Flickr insertion batch of eight, a real-topology holdout; and
- 16,384-vertex PMA-spread graph with 4,096 insertions, a scale holdout.

All real cases have three FPGA repeats.  Synthetic anchors have one routed
FPGA run each.  Every row passes the float32 architecture oracle and the
independent float64 mathematical oracle.

## Result

The fitted coefficients are:

| Component | Cycles |
| --- | ---: |
| fixed | 385,422.23 |
| per vertex | 416.0571 |
| per executed PMA slot | 1.959856 |

| Role | Cases | Raw median abs. error | Calibrated median abs. error | Calibrated max abs. error |
| --- | ---: | ---: | ---: | ---: |
| calibration | 4 | 46.02% | 4.91% | 9.79% |
| holdout | 2 | 71.84% | 2.33% | 2.59% |

The real Flickr holdout error is `2.06%`; the independent 16K scale holdout
error is `2.59%`.  This passes the declared 20% transfer gate.  The model is
specific to FullPR, K4-shared, the routed event window, and the measured scale
domain.  It is not evidence for another algorithm or partition topology.

## Reproduction

Generate the simulator manifests with the K4-shared FullPR profile, then run:

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 scripts/analyze_k4_fullpr_component_calibration.py \
  --summary /data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805_repeat2/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805_repeat3/summary.tsv \
  --case amazon_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_fullpr_20260806/amazon/manifest.json \
  --case web_google_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_fullpr_20260806/web_google/manifest.json \
  --case flickr_insert:holdout:/data/tmp/chuxiao/k4_hw_calibration_sim_fullpr_20260806/flickr/manifest.json \
  --microbench chain_v64:calibration:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_sim_20260806/small_chain_v64/manifest.json:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_20260806/runs/small_chain_v64 \
  --microbench star_v4096:calibration:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_sim_20260806/small_star_v4096/manifest.json:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_20260806/runs/small_star_v4096 \
  --microbench spread_v16384:holdout:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_sim_20260806/medium_spread_v16384/manifest.json:/data/tmp/chuxiao/k4_fullpr_fpga_microbench_20260806/runs/medium_spread_v16384 \
  --out-dir docs/evidence/k4_fpga_fullpr_component_calibration_20260806
```

The generated manifest pins SHA-256 hashes for every input summary and
simulation manifest.  `predictions.tsv` preserves raw and calibrated errors;
`group_summary.tsv` keeps calibration and holdout statistics separate.
