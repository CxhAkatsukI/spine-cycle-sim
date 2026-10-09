# K4-shared Residual PageRank FPGA component calibration

## Scope

This evidence aligns the execution-driven GraSU + ReGraph Residual PageRank
simulator with the routed conversion-free K4-shared U55C xclbin. The target is
the matched OpenCL event window, while the simulator's raw cycles and component
counters remain unchanged.

The frozen protocol is:

- direct per-vertex threshold `epsilon=1e-6`, damping factor `0.85`;
- one correction execution followed by propagation until the active set is
  empty;
- four GraSU PMA/update lanes and one serially shared ReGraph worker;
- insertion batches of eight on compact real-topology slices;
- Amazon-2008 and Web-Google are calibration cases;
- Flickr is an untouched holdout; and
- every graph has three correctness-admitted hardware repeats.

The loader checks exact agreement between hardware and simulator for vertex
count, destination partitions, pipeline executions, and total PMA work. Total
PMA work is `correction_pma_slots + compute_pma_slots` in the simulator and
`pma_slots_per_partition_pass * pipeline_executions` in hardware.

## Model and result

The routed event-envelope model is:

```text
predicted_cycles = 153.325494 * vertices
                 + 85.437119 * total_executed_pma_slots
```

It has no intercept. The two non-negative coefficients are identified only
from the two calibration topologies; the Flickr timing is not read by the fit.

| Role | Cases | Raw median abs. error | Calibrated median abs. error | Calibrated max abs. error |
| --- | ---: | ---: | ---: | ---: | ---: |
| calibration | 2 | 71.72% | 0.00% | 0.00% |
| holdout | 1 | 80.84% | 5.69% | 5.69% |

The independent Flickr holdout passes the declared 20% transfer gate. This is
an algorithm-, topology-, and event-window-specific envelope. It is not a
replacement for the execution-driven memory/FIFO model and must not be used to
claim transfer to multi-partition or non-insertion workloads without new
holdout evidence.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 scripts/analyze_k4_respr_component_calibration.py \
  --summary /data/tmp/chuxiao/matched_fpga_respr_k4_real_20260805/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_respr_k4_real_20260805_repeat2/summary.tsv \
  --summary /data/tmp/chuxiao/matched_fpga_respr_k4_real_20260805_repeat3/summary.tsv \
  --case amazon_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_respr_hardware_contract_20260806/amazon/manifest.json \
  --case web_google_insert:calibration:/data/tmp/chuxiao/k4_hw_calibration_sim_respr_hardware_contract_20260806/web_google/manifest.json \
  --case flickr_insert:holdout:/data/tmp/chuxiao/k4_hw_calibration_sim_respr_hardware_contract_20260806/flickr/manifest.json \
  --out-dir docs/evidence/k4_fpga_respr_component_calibration_20260806
```

The generated manifest records SHA-256 hashes for every hardware summary and
simulation manifest. `predictions.tsv` preserves both raw and calibrated
errors, and `group_summary.tsv` keeps calibration and holdout rows separate.
