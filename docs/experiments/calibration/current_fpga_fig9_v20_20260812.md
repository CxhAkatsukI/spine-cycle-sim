# Current-FPGA Figure 9 v20

## Result

The frozen current-model Figure 9 matrix completed all nine AU/SU/WK pairs.
Every architecture row passed its algorithm correctness oracle, memory ledger,
backend arbitration ledger, and DRAM request-count gate.

The plotted quantity is the ratio of normalized sharded-K4 GraSU+ReGraph to
Delta.hls. Values above one favor Delta.hls.

| Algorithm | Dataset | Accepted-byte ratio | HBM-energy ratio |
|---|---|---:|---:|
| Weighted SSSP | AU | 4,016.59x | 1,421.78x |
| Weighted SSSP | SU | 5,459.61x | 2,251.57x |
| Weighted SSSP | WK | 5,848.60x | 5,141.80x |
| Connected Components | AU | 1,276.72x | 709.61x |
| Connected Components | SU | 2,696.11x | 1,182.46x |
| Connected Components | WK | 7,057.96x | 6,311.30x |
| Thresholded Residual PageRank | AU | 4,680.19x | 3,684.47x |
| Thresholded Residual PageRank | SU | 6,517.00x | 6,371.14x |
| Thresholded Residual PageRank | WK | 11,534.73x | 15,273.92x |

Across all nine rows, the median accepted-byte ratio is 5,459.61x and the
range is 1,276.72--11,534.73x. The median HBM-energy ratio is 3,684.47x and
the range is 709.61--15,273.92x.

## Admission gates

For each of the 18 architecture executions, the exporter requires:

- algorithm correctness `PASS`;
- execution-driven memory ledger `PASS`;
- unique backend intents = grants = consumed grants = backend requests;
- no pending arbitration intents or grants at completion;
- DRAMSim3 reads + writes = backend requests.

The matrix and exporter both fail closed. The final manifest reports
`PASS_CURRENT_MODEL_DATA`, `rows=9`, `expected_rows=9`, and an empty missing
list.

## Evidence boundary

Accepted bytes are bytes actually accepted by the shared execution-driven
backend after finite FIFOs, arbitration, outstanding limits, and backpressure.
They are not an edge-count formula. HBM energy is the bound-channel DRAMSim3
activity and background energy accumulated by those executions.

This figure does not claim direct routed-FPGA HBM-byte agreement because the
current FPGA hosts do not expose equivalent per-run HBM traffic counters. It
also does not report total accelerator energy, FPGA board power, or ASIC core
energy. The result is therefore admissible as a conserved current-model memory
comparison, not as a direct hardware power measurement.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

python3 scripts/run_current_fpga_grasu_frozen_matrix.py \
  --simulation-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812 \
  --workload-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812/workloads \
  --lib-dir cpp/sst/build/sst-current-fpga-v19 \
  --jobs 2 \
  --memory-reserve-gib 72 \
  --memory-poll-seconds 10 \
  --dataset au --dataset su --dataset wk \
  --algorithm weighted_sssp \
  --algorithm connected_components \
  --algorithm thresholded_residual_pagerank

python3 scripts/export_current_fpga_fig9.py \
  --spine-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812 \
  --grasu-root /data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812 \
  --out-dir docs/evaluation_refresh_20260810/fig9_current_v20
```

The tracked manifest freezes the case and Figure 9 contracts, both SST plugin
hashes, all architecture-profile hashes, and the hashes of all 18 result and
summary files.
