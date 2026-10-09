# HLS-Aligned Real Compact Small Batches

Date: 2026-07-26

## Purpose

This milestone freezes byte-identical dynamic weighted-SSSP inputs for Spine
and the `ff13a67` GraSU/ReGraph profile. It extends the existing Amazon-2008,
web-Google, and soc-Flickr compact real-edge slices with deterministic small
insertion, deletion, and weight-change batches.

It is an input and correctness contract, not a performance result. The compact
slices preserve real topology samples but remain much smaller than the source
datasets.

## Frozen Batches

Each dataset has three independent eight-mutation batches:

| Scenario | User mutations | Differential records | Encoding |
| --- | ---: | ---: | --- |
| insertion | 8 | 8 | insert absent source-0 to sink edges |
| deletion | 8 | 8 | delete exact existing source-0 edges |
| weight change | 8 | 16 | exact delete immediately followed by insert of the new weight |

The weight-change encoding is intentionally architecture-neutral. It does not
ask one simulator to infer overwrite semantics that the other does not have.
Final reports must therefore distinguish eight user mutations from sixteen
physical differential records.

All records are monotonic in `(src,dst)`, as required by the Spine maintenance
input. A delete/insert replacement preserves delete-first order within the
same key. Insertions target compact IDs at or above 128, which are sink-only in
the frozen extraction policy. Deletions and weight changes use source 0's
direct edges.

## Correctness Boundary

The generator materializes every final weighted graph, runs an independent
Dijkstra oracle, and checks how many synchronous relaxation rounds are needed.
Amazon-2008 and web-Google cases need one data-propagation round. The Flickr
insertion and weight-change cases need four; no frozen run exceeds the four
host supersteps in the `ff13a67` HLS profile.

An Amazon weight-change vertical smoke already passes both systems with zero
architecture and mathematical mismatches:

| System | Timed result | Important interpretation |
| --- | ---: | --- |
| GraSU/ReGraph HLS-aligned | 204,396 total cycles | 269 update + 204,127 fixed-four-round compute |
| Spine routed-reference profile | 115,832 update-phase cycles | full rebuild after a separately measured 111,618-cycle cold baseline |

These values are a runner-interface smoke, not the final matrix. In particular,
Spine's top-level 227,450 cycles include both cold initialization and dynamic
execution, while GraSU's 204,396-cycle window starts at PMA update. The common
comparison must use Spine `update_cycles` against GraSU `update_cycles +
compute_cycles`, while reporting cold setup separately.

## Reproduction

Generate and verify the corpus:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_hls_weighted_real_batches.py
python3 scripts/prepare_hls_weighted_real_batches.py --verify-only
python3 -m unittest tests.test_real_small_batches
```

The authoritative manifest is
`configs/experiments/hls_weighted_real_small_batches_20260726.json`. It pins the
existing shared real-graph manifest and all nine generated update files.

Reproduce the two-system Amazon weight-change smoke:

```bash
python3 scripts/run_sst_grasu_regraph_hls_weighted.py \
  --no-build \
  --workload tests/data/shared_comparison/real_amazon_2008_compact.slice \
  --update-workload \
    tests/data/hls_weighted_real_batches/real_amazon_2008_weight_change_u8.slice \
  --source 0 \
  --out-dir results/grasu_hls_real_amazon_weight_u8_smoke_20260726

python3 scripts/run_sst_spine_vertical.py \
  --no-build \
  --scenario dynamic_sssp_delete \
  --validation-mode generic \
  --profile configs/architectures/spine_shared_engine_9c08763.json \
  --workload tests/data/shared_comparison/real_amazon_2008_compact.slice \
  --update-workload \
    tests/data/hls_weighted_real_batches/real_amazon_2008_weight_change_u8.slice \
  --source 0 \
  --max-rounds 4 \
  --max-cycles 100000000 \
  --out-dir results/spine_hls_real_amazon_weight_u8_smoke_20260726
```

The next milestone is a fail-closed parent runner for all nine pairs. It must
use the aligned dynamic timing window, retain both correctness oracles, and
report E2E, update, memory, stall, DRAM energy, and host runtime fields without
promoting these compact slices to full-dataset evidence.
