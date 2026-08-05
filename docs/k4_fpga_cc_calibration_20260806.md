# K4-shared CC FPGA event-envelope calibration

## Scope

This evidence aligns the execution-driven GraSU + ReGraph connected-components
simulator with the routed conversion-free K4-shared U55C xclbin. The calibrated
target is the OpenCL event window used in the matched FPGA comparison; raw
simulator cycles and component counters remain unchanged.

The frozen protocol is:

- algorithm: connected components on reciprocal graphs;
- operation: insertion batch of eight user mutations;
- hardware: U55C, 150 MHz, four GraSU PMA lanes and one shared ReGraph worker;
- calibration: Amazon-2008 and Web-Google compact real-topology slices;
- untouched holdout: Flickr compact real-topology slice; and
- three hardware repeats per graph.

Every row passes the architecture oracle, independent mathematical oracle,
conversion-free handoff gate, partition-topology gate, and exact executed-
superstep agreement between hardware and simulator.

## Result

The geometric-mean event-envelope scale fitted only on calibration rows is
`3.033904`.

| Role | Cases | Raw median abs. error | Calibrated median abs. error | Calibrated max abs. error |
| --- | ---: | ---: | ---: | ---: |
| calibration | 2 | 67.04% | 0.14% | 0.14% |
| holdout | 1 | 66.68% | 1.10% | 1.10% |

The independent Flickr holdout passes the declared 20% transfer gate. This is
an algorithm- and topology-specific routed event-envelope calibration, not a
per-component fit. Bottleneck attribution must continue to use the raw
execution-driven counters rather than the multiplicative scale.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 scripts/analyze_k4_fpga_calibration.py \
  --summary /data/tmp/chuxiao/matched_fpga_cc_k4_real_20260805/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_cc_k4_real_20260805_repeat2/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_cc_k4_real_20260805_repeat3/summary.tsv \
  --case amazon_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_cc_hardware_protocol_20260806/amazon/run_manifest.json \
  --case web_google_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_cc_hardware_protocol_20260806/web_google/run_manifest.json \
  --case flickr_insert:holdout:/data/tmp/chuxiao/k4_hw_calibration_sim_cc_hardware_protocol_20260806/flickr/run_manifest.json \
  --out-dir docs/evidence/k4_fpga_cc_calibration_20260806
```

The generated manifest pins SHA-256 hashes for all hardware summaries and
simulation manifests. `predictions.tsv` preserves raw and calibrated errors;
`group_summary.tsv` keeps calibration and holdout results separate.
