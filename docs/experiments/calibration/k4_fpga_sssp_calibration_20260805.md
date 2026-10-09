# K4-shared SSSP FPGA event-envelope calibration

## Scope

This evidence aligns the execution-driven GraSU + ReGraph SSSP simulator with
the final conversion-free K4-shared U55C xclbin.  The raw simulator cycles are
preserved.  A separate one-parameter event-envelope scale converts those raw
cycles to the routed OpenCL event window used by the matched FPGA comparison.

The evidence is intentionally narrow:

- algorithm: weighted SSSP;
- operation: insertion batch of eight user mutations;
- hardware: U55C, 150 MHz, K4-shared G+R xclbin;
- calibration: Amazon-2008 and Web-Google compact real-topology slices;
- untouched holdout: Flickr compact real-topology slice;
- three hardware repeats per case;
- all rows pass both architecture and independent mathematical oracles; and
- every simulator run uses the same number of supersteps as hardware,
  including the final empty convergence-confirmation round.

These compact slices each touch one destination partition.  The routed
two-partition boundary smoke proves K4-shared functional ordering, but this
fit is not evidence that the event scale transfers across partition counts.
CC, Full PageRank, and residual PageRank require separate calibration.

## Result

The raw simulator underestimates the FPGA event envelope by 63.0% to 75.6%.
The fitted multiplicative scale is `3.327118`.  It is the geometric mean of
the hardware/simulator ratios on calibration cases, which gives each graph
equal relative weight instead of allowing the largest cycle count to dominate.

| Role | Cases | Raw median abs. error | Calibrated median abs. error | Calibrated max abs. error |
| --- | ---: | ---: | ---: | ---: |
| calibration | 2 | 69.29% | 21.00% | 23.18% |
| holdout | 1 | 75.36% | 18.02% | 18.02% |

The holdout passes the declared 20% gate.  This is adequate as a bounded SSSP
event-envelope correction, but it is not a component calibration: it does not
identify whether the residual belongs to adapter scheduling, kernel launch
gaps, HBM behavior, or another stage.  Raw component counters remain the only
valid source for bottleneck attribution.

## Reproduction

The three aligned simulator manifests are generated with the normalized
150 MHz profile and explicit hardware superstep counts (`2`, `2`, and `5`).
Then run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/analyze_k4_fpga_calibration.py \
  --summary /data/tmp/chuxiao/matched_fpga_sssp_k4_real_20260805/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_sssp_k4_real_20260805_repeat2/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_sssp_k4_real_20260805_repeat3/summary.tsv \
  --case amazon_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_sssp_aligned_rounds_20260805/amazon/manifest.json \
  --case web_google_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_sssp_aligned_rounds_20260805/web_google/manifest.json \
  --case flickr_insert:holdout:/data/tmp/chuxiao/k4_hw_calibration_sim_sssp_aligned_rounds_20260805/flickr/manifest.json \
  --out-dir docs/evidence/k4_fpga_sssp_calibration_20260805
```

The generated `manifest.json` pins SHA-256 hashes for every hardware summary
and simulator manifest.  `predictions.tsv` retains raw and calibrated errors;
`group_summary.tsv` keeps calibration and holdout metrics separate.
