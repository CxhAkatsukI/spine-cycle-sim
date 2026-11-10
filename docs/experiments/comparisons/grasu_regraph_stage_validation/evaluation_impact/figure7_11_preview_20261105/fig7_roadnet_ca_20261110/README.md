# Fig. 7: roadNet-CA (RN)

This supplement belongs to the existing Fig. 7 handoff. It does not change
the paper, the selected eight-dataset CSV, or the November 6 archive.

## Fig. 7 Results

[RN data and status](fig7_rn.csv) · [Frozen inputs](input_manifest.json) ·
[FPGA artifact bindings](hardware.json) · [CPU checks](cpu/) ·
[Board receipts](board/) · [Initial attempts](board/raw_attempts.tar.gz) ·
[RN follow-up scope](followups.md)

[Nine-dataset CSV](followup/fig7_nine_datasets.csv) ·
[Preview PNG](followup/fig7_nine_datasets.png) ·
[PDF](followup/fig7_nine_datasets.pdf). The preview combines the frozen
24 observations and three RN measurements, including the RN SSSP loss.
Bars extend from the 1x parity line; below it G+R is faster.
The `source_csv` values are relative to the nine-dataset CSV.

| Algorithm | Spine | G+R | Faster | Spine / G+R propagation rounds |
| --- | ---: | ---: | --- | ---: |
| [Weighted SSSP](board/sssp_measured.json) | 429.405 s | 12.890 s | G+R, 33.31x | 460 / 460 |
| [CC](board/cc_measured.json) | 4.390 ms | 30.185 ms | Spine, 6.88x | 0 / 1 |
| [ResPR](board/respr_measured.json) | 31.467 ms | 41.960 ms | Spine, 1.33x | 0 / 0 |

All three pairs passed the final CPU-reference checks. G+R's CC round
is the full convergence-check scan even though the batch changes no
labels. Neither ResPR arm had a nonempty propagation round at the fixed
epsilon of 1e-6. In SSSP, Spine's logged kernel span is 423.689 s of its
429.405 s wall; the RN loss is not explained by excluding host relaunch.
This is a single paired measurement per algorithm, not a repeatability
estimate. The raw logs are in [board/](board/).

## Workload And Measurement

- [SNAP roadNet-CA](https://snap.stanford.edu/data/roadNet-CA.html) has
  1,965,206 real vertices and 2,766,607 undirected roads. The file stores
  5,533,214 directed records. We retain the original ID space of 1,971,281
  entries; the ResPR projection adds 6,075 self-loops on missing IDs to
  satisfy the sink-free host contract.
- The existing deterministic publication generator produces eight logical
  insertions. CC writes both directions (16 records). SSSP uses the
  median-degree representative, source 0. The batch is not selected by
  effect size or performance.
- CPU checks found 916,808 changed SSSP distances, no CC label changes,
  and no ResPR propagation at the fixed per-vertex threshold of 1e-6.
  This RN SSSP batch is not a sparse-propagation example despite having
  only eight insertions.
- Exact shortest paths and minimum-ID labels on the old graph need up to
  636 and 554 hops, respectively, beyond the original 256-round setting.
  The RN workload manifests give G+R a 1,024-round runtime ceiling. The
  [RN SSSP host patch](sssp_rn_host.patch) raises Spine's compiled host
  ceiling from 256 to 1,024. These are stopping limits, not fixed
  iteration counts, and neither FPGA image changed. The CPU replay needs
  460 nonempty SSSP rounds after the batch. The aborted first attempts
  are retained separately.
- Use the selected Fig. 7 images and hosts, one measured pair per algorithm
  and no extra warm-up pair. Old-state construction is outside the resident
  wall. The frozen CC host's old-graph device bootstrap timed out before
  the measured update. The [RN CC host patch](cc_rn_host.patch) preloads
  exact CPU old-graph labels, then runs the device quiescence check and
  full-label audit before the existing host-pack-to-final-readback window.
  It does not change the FPGA image, measured update or final audit.
  G+R's CC receipt includes pack/upload and host seeding but places
  physical update mapping before the timer. ResPR uses the existing
  matched derated image and fixed threshold.

## Reproduce

Run from the simulator repository root. `hardware.json` records the exact
board artifacts and local paths; `hardware_sssp_rn.json` and
`hardware_cc_rn.json` bind the two RN-specific hosts. The external comparator is pinned in the
board campaign receipt. Keep the same binary bindings and use an unused
output directory for each attempt.

```sh
handoff=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/fig7_roadnet_ca_20261110
scratch=/path/to/experiment-scratch
PYTHONPATH="$PWD" python3 "$handoff/prepare.py" "$scratch/roadNet-CA.txt.gz" "$scratch/rn-inputs"
g++ -std=c++17 -O2 "$handoff/check_old_state.cpp" -o "$scratch/check_old_state"
"$scratch/check_old_state" sssp "$scratch/rn-inputs/weighted_sssp/insert-u8.graph" 0
"$scratch/check_old_state" cc "$scratch/rn-inputs/connected_components/insert-u8.graph" 0
g++ -std=c++17 -O2 -ffp-contract=off \
  spine_cycle_sim/experiments/evaluation_impact/affected_fraction/pagerank_reference.cpp \
  -o "$scratch/pagerank_reference"
"$scratch/pagerank_reference" "$scratch/rn-inputs/residual_pagerank/insert-u8.graph" 0.000001
```

On the board host, after memory pressure stabilizes, run serially:

```sh
comparator=/home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py
for algorithm in weighted_sssp connected_components residual_pagerank; do
  template="$PWD/$handoff/hardware.json"
  output=board-respr-memavailable
  if [ "$algorithm" = weighted_sssp ]; then
    template="$PWD/$handoff/hardware_sssp_rn.json"
    output=board-weighted_sssp-cap1024
  elif [ "$algorithm" = connected_components ]; then
    template="$PWD/$handoff/hardware_cc_rn.json"
    output=board-cc-preloaded
  fi
  systemd-run --user --wait --pipe --quiet \
    -p MemoryMax=16G -p MemoryHigh=14G -p MemorySwapMax=0 -p OOMPolicy=kill \
    env PYTHONPATH="$PWD" LD_LIBRARY_PATH=/opt/xilinx/xrt/lib \
    python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.board \
    --workloads "$scratch/rn-inputs/$algorithm/workloads.json" \
    --template "$template" --comparator "$comparator" \
    --output "$scratch/$output" --device 0 --bdf 0000:82:00.1 \
    --memory-gib 16 --memory-profile memavailable-v1 \
    --wait-seconds 300 --timeout-seconds 1200 --warmup-pairs 0 --repetitions 1
done
```
