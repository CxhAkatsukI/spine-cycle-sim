# Fig. 7: roadNet-CA (RN)

This supplement belongs to the existing Fig. 7 handoff. It does not change
the paper, the selected eight-dataset CSV, or the November 6 archive.

## Result Status

[RN data and status](fig7_rn.csv) · [Frozen inputs](input_manifest.json) ·
[FPGA artifact bindings](hardware.json) · [CPU checks](cpu/) ·
[Board receipts](board/) · [Raw board logs](board/raw_attempts.tar.gz)

No valid RN FPGA pair is available. The weighted SSSP and ResPR attempts
both started the Spine arm but stopped during preparation when system-wide
memory PSI remained above the board safety limit for ten seconds. Neither
reached the paired resident timer. CC was not started while the same resource
condition persisted. No speedups are inferred from incomplete arm logs or
CPU results, and no RN bar is added to the preview.

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
  636 and 554 hops, respectively. The earlier G+R host's 256-superstep
  ceiling cannot prepare those reference states. The updated RN workload
  manifests use 1,024 as a stopping ceiling, not a fixed iteration count.
  The aborted first SSSP attempt used 256; its log is retained as an
  attempt, not admitted as performance evidence.
- Use the selected Fig. 7 images and hosts, one measured pair per algorithm
  and no extra warm-up pair. Old-state construction is outside the resident
  wall. CC uses the existing host-pack-to-final-readback variant. ResPR
  uses the existing matched derated image and fixed threshold.

## Reproduce

Run from the simulator repository root. `hardware.json` records the exact
board artifacts and local paths. The external comparator is pinned in the
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
  systemd-run --user --wait --pipe --quiet \
    -p MemoryMax=16G -p MemoryHigh=14G -p MemorySwapMax=0 -p OOMPolicy=kill \
    env PYTHONPATH="$PWD" python3 -m spine_cycle_sim.experiments.evaluation_impact.affected_fraction.board \
    --workloads "$scratch/rn-inputs/$algorithm/workloads.json" \
    --template "$PWD/$handoff/hardware.json" --comparator "$comparator" \
    --output "$scratch/board-$algorithm" --device 0 --bdf 0000:82:00.1 \
    --memory-gib 16 --memory-profile zfs-arc-clean-half-background5-v1 \
    --wait-seconds 300 --timeout-seconds 900 --warmup-pairs 0 --repetitions 1 || break
done
```
