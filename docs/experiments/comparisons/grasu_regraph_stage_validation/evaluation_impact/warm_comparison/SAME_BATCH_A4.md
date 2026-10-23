# Same-Batch Original A4 Check

This follow-up checks the R baseline **on the exact three-insertion batch**
used by the [common-warm Spine diagnostic](README.md), rather than importing
parity from the earlier 46-round weight-decrease batch. It changes no numerical
core, memory timing, topology or fitted multiplier. All values below are
simulator predictions, not FPGA measurements or original-paper reproduction.

## Result

All eight A4 executions pass full-vector state, guard, per-round oracle,
request/byte conservation and normal/reverse registration checks. Their old
state, inserted batch and complete final state match the twelve previously
captured G+R/Spine executions. Every execution converges in two rounds.

| Input | Memory latency | Original A4 cycles | Adapter + R cycles | R slower than A4 | G+R / Spine |
| --- | ---: | ---: | ---: | ---: | ---: |
| 96-vertex smoke | 64 | 67,218 | 99,467 | 47.98% | 1.2281 |
| 96-vertex smoke | 128 | 71,324 | 105,527 | 47.95% | 0.7224 |
| Amazon slice | 64 | 474,098 | 482,435 | **1.76%** | **5.3226** |
| Amazon slice | 128 | 688,722 | 826,100 | **19.95%** | **5.2749** |

The last column is the unchanged, actually simulated G+R/Spine comparison,
including G's 585 / 1,097 cycles. It is not recomputed from the A4 arm.
Only Amazon at latency 64 meets the user's exploratory 15% interval. It is
incorrect to describe this matrix as parity in every scenario. No failed
interval is dropped, and the pre-existing negative Spine smoke is retained.

As a **sensitivity calculation only**, substituting A4's faster compute cycles
for R while retaining the simulated G cycles gives
`(A4 + G) / Spine = 5.2307 / 4.3989` for Amazon. Thus this particular positive
Spine diagnostic is not explained solely by R being slower than A4. Those
substituted values are **not an executed G+A4 integration**, nor proof about
other algorithms, graph sizes, update batches, host time or hardware.

Original A4 reads 34,892,800 B and writes 8,388,608 B across the two Amazon
rounds. Current G+R reads 87,879,920 B and writes 6,291,656 B, including G's
240/192 B. Different input representations and four versus three output
replicas make the bytes different even when cycles are close. Neither a total
cycle near-match nor this diagnostic attributes every internal stall.

## Matched Conditions And Limits

- Same old Dijkstra-converged state, root, three weighted inserted edges,
  fixed vertex IDs and complete new-graph convergence. The shared Amazon
  slice has 258,046 vertices and 1,450,899 old edges. See the parent guide for
  the explicit batch and state semantics.
- Original author `partitionGraph` and `schedulePartitions` generate new A4
  tasks for the new graph. A second DBG permutation is intentionally omitted:
  it would change the already fixed common IDs. Task edge multisets are
  checked before packing the identical weights/local destination ABI.
- The original host's PR initialization is used only by the layout validator,
  not as SSSP input or timed PR computation. The execution uses the shared
  weighted-SSSP policy/state. This is an original-layout A4 **control**, not
  the paper's original 11-Little/3-Big publication throughput.
- Same 150-MHz model clock, 32-channel mock backend, latency 64/128 and finite
  credits as the preceding diagnostic. A4 has 13 masters/four state copies;
  candidate R has 16 masters/three copies. Strict equal-resource admission
  remains open. Both exclude host preparation, DMA, launch and orchestration.
- G in the previous diagnostic uses direct native segment RMW on naturally
  small shards, not the separate full-cache candidate. Full baseline/G timing
  admission and host-inclusive conclusions are still open. Figures and paper
  remain unchanged; no FPGA work is part of this follow-up.

## Evidence And Reproduction

[Portable evidence index](same_batch_a4/index.json) includes both matrices'
raw command/resource records and full output states, the new graph and author
compact layouts, captured harness sources, and the retained failed build.
The raw successful directory is
`/data/chuxiao/experiments/warm_a4_comparison_20261023/attempt-v2`.
Attempt v1 failed on a missing `<iostream>` include; v2 fixes only the harness.
Compiler, unchanged core libraries, upstream checkout and all used dependency
identities are hash-indexed. The pre-existing 37/37 core tests are reused by
hash, not rerun or described as fresh. No SST/FPGA test was run.
Fresh Python checks pass: nine same-batch analysis/delivery checks, nine
preceding warm-comparison checks, nine cached-core checks and fifteen
repository-organization checks (42 total). Document layout, catalogs and
whitespace checks pass. Both old and new portable capsules verify offline.

The job took about 34 seconds. Saved cgroup peak is 448,380,928 B (427.61 MiB),
swap zero, within 6/5-GiB max/high limits and a 24-GiB live reserve. One worker,
CPU 124, finite child timeouts and 4-GiB address-space caps were enforced.

Run from the repository root, using a fresh output/unit for every attempt:

```bash
systemd-run --user --wait --pipe --collect --unit=spine-warm-a4-rerun-v1 \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=8000 --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.a4_study \
  --reference /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-v2/results.json \
  --comparison /data/chuxiao/experiments/warm_spine_comparison_20261023/attempt-v6/results.json \
  --source /home/chuxiao/spine-cycle-sim/spine-cycle-sim-sharded-k4-v3/build/publication_sources/regraph \
  --xrt-include /opt/xilinx/xrt/include \
  --output /data/chuxiao/experiments/warm_a4_rerun/attempt-v1 --cpu 124

python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.a4_delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/same_batch_a4
python3 -m unittest discover -s tests -p 'test_warm_a4*.py' -v
```

Code owners in `warm_comparison/`: `fixed_id_layout.cpp` captures author
layout, `a4_input.hpp` checks and overlays common weighted state, `a4_main.cpp`
exports/executes, and the Python `a4_preparation`, `a4_study`, `a4_analysis`,
`a4_delivery` modules separate layout, bounded execution, gates and packaging.
To package a fresh run, use `a4_delivery` with a fresh `--output` plus
`--attempt` and `--comparison`; packaging refuses changed pinned artifacts.
