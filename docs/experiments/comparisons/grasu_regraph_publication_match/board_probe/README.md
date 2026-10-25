# Publication Board Diagnostics

## Result

**G follow-up:** [startup and cache diagnosis](grasu_diagnosis.md) measures
46.398 ms on first use versus 24.744 ms warmed, and 24.039 ms on first use
after explicit premigration. Both final repetitions pass the PMA gate. The
source/synthesis audit identifies repeated full-cache preload/writeback
across eight shards (13.981 ms nominal fixed schedule at 150 MHz). Setup
cost is moved, not removed; no publication match is established.

**All-Little follow-up:** [four Little, zero Big](launch_diagnosis.md#all-little-follow-up-four-little-zero-big)
processes the complete Amazon graph and reaches 0.941 GTEPS warm baseline
(0.958 GTEPS with author enqueue order); all ten executions pass correctness.
This is A4, not the paper's fourteen-Little configuration. It does not
establish a publication match or isolate the effect of removing Big.

**Latest parameter control:** [numD=1 versus numD=3](dense_partitions.md)
uses the same 11L3B bitstream and identical logical input. Warm median throughput
increases from 1.110 to 1.518 GTEPS; all 20 executions pass the guarded oracle.
The author's camera-ready Amazon example passes `3`. The earlier `numD=1`
measurements below remain valid for that configuration, not that example.

Fresh U55C measurements on October 25, 2026 **do not establish a match to the
original GraSU or ReGraph publication**. All 15 measured runs passed their
correctness checks. No HLS, simulator timing coefficients, paper, or figure
was modified. This is a bounded diagnostic, not a complete reproduction.

**Follow-up:** [launch diagnosis](launch_diagnosis.md) and
[launch_results.json](launch_results.json) contain ten additional passing
executions with the same original-R bitstream and graph. Warm median throughput
is 1.099 GTEPS versus 0.572 GTEPS on that process's first execution. The table
below preserves the initial cold-process probe, not the latest steady-state
estimate. Its approximately 4 GTEPS reference was a chart approximation; the
camera-ready Table IV gives 3.744 GTEPS (System) and 4.224 GTEPS (Best) for AM PR.

| Measured path | Input | Median measured throughput | Published reference | Numerical rate ratio |
| --- | --- | --- | --- | --- |
| Latest routed G, update only | AU, 131,072 absent-edge insertions | 2.841 Mupdates/s | AU: 190.77 Mupdates/s, Table 4 | Reference / measured: 67.16 |
| Original-source R port, 11 Little + 3 Big | Amazon, one static PR superstep; author-initial binding | 0.557 GTEPS | Amazon selected configuration: approximately 4 GTEPS, Fig. 10 | Approximately 7.18 |
| Same R port | Same graph; CSR-degree binding | 0.537 GTEPS | Same approximate chart reference | Approximately 7.44 |
| Original-source R port, 4 Little + 0 Big | Same graph, both bindings | 0.502--0.505 GTEPS | Four-pipeline chart configuration is not necessarily all-Little | No matched error assigned |

These ratios compare **unmatched configurations**. They are not controlled
reproduction errors, and not multipliers to apply to Fig. 7 speedups.
The original-R port is **not the latest sharded K4 adapter+R implementation**.
The latter's publication-speed gap remains unmeasured by this delivery.

## What Was Measured

G uses the latest weighted-SSSP G+R bitstream with `--update-only`: ReGraph
computation is skipped. AU has 515,281 declared vertices, 390,847 initial
edges, and 131,072 unique, absent, positive insertions; external vertex IDs
are preserved. Three independent host processes produce 44.613, 46.143 and
47.346 ms. Each checks 716,992 touched PMA words with zero mismatches.
The numerator is successful insertions, not PMA words or padded slots.

The G timer is the envelope from the first of nine update CUs starting to the
last finishing, over all eight destination shards. It includes kernel start
staggering, backpressure and inter-shard gaps. Initial preparation, explicit
initial DMA and final correctness readback are outside it. Each process uses
one update repetition; this is not a warmed steady-state throughput claim.

R uses hash-pinned original-source U55C port artifacts and an independent
fixed-point PR oracle. The complete matrix is two topologies, two input-state
bindings, and three repetitions: 12 passes, including replica, padding and
guard checks. Amazon has 735,324 vertices and 5,158,388 logical directed edges.
It executes **one superstep, not convergence**, with logical edges divided by
the overlap-aware device-event envelope. For 11L3B the median envelopes are
9.265 and 9.599 ms; enqueue-to-finish wall medians are 22.306 and 22.843 ms.
Initial graph preparation/DMA and output readback are excluded from both.
Neither overlapping CU durations nor concurrent pipelines are summed.

Both probes use 150 MHz, XRT 2.18.179, U55C PCI `0000:c1:00.1`, CPU affinity
124,125. Board leases and BDF-derived render nodes prevent relying on DRM
minor numbers that changed after reboot. Runs are serial, with MemoryMax 8 GiB,
MemoryHigh 7 GiB, no swap, a 24 GiB available-memory launch reserve and bounded
process/service deadlines. No new synthesis or routing was required.

## Why A Gap Is Not Yet A Causal Explanation

The G log directly shows eight serial shard invocations, each launching nine
CUs. In the median repetition a shard with only 976 insertions still takes
4.686 ms. This demonstrates a substantial fixed-cost floor. Per-CU start
timestamps are staggered by several milliseconds. They cannot, by themselves,
separate driver scheduling, stream waiting, cache preload/writeback and useful
update work into non-overlapping contributions.

**The latest G does use a complete URAM cache**, unlike the old direct-cache
profile discussed in the parent checkpoint. The pinned build manifest includes
`kernels/grasu_complete/process_cache.cpp` and `cache_pipeline.hpp`; that path
rejects the direct-cache macro and binds the cache to URAM. Do not explain this
new measurement using the old profile's absence of URAM.

GraSU's paper uses U250 at 200 MHz, 32 update PEs, 32-byte segments, its own
temporal preprocessing and ten-batch workload. Our weighted destination-sharded
AU input and launch sequence are different. The source paper reports update
throughput excluding CPU--FPGA transfers. Exact temporal input and timer
equivalence are still required before calling 67.16 a reproduction error.

ReGraph's paper uses U280, graph-dependent Big/Little combinations and vertex
grouping/preprocessing. The camera-ready explicitly normalizes Fig. 10 to
210 MHz. Fig. 11 separately gives 217 MHz for the 11L3B implementation. The
Table IV AM PR System/Best scores are **not exact published scores for our
fixed 11L3B, one-dense-partition layout**. Our two initial-state bindings are
diagnostics, not proof of the paper's exact input layout. Clock ratios are not
an automatic performance normalization or evidence that they explain the gap.

Source correction: the local `2022_MICRO_ReGraph.pdf` is a 13-page arXiv
preprint, not the 17-page camera-ready linked here. The initial denial of
Fig. 10 frequency normalization was wrong. In the camera-ready, Table IV is
performance and Table V is preprocessing. Earlier frozen JSON/source hashes
are preserved; this note supersedes the erroneous paper interpretation.

Sources: [GraSU, Table 4 and Sec. 6](https://doi.org/10.1145/3431920.3439288),
[ReGraph, Figs. 10--12 and Table IV](https://soldierchen.github.io/assets/pdf/regraph.pdf).
Local PDF hashes and raw report/log hashes are in [results.json](results.json).

## Evidence And Reproduction

Start with [results.json](results.json). It contains all three G repetitions,
all four R summary groups, timing conservation checks, artifact identities and
absolute raw paths. Large inputs, board dumps and xclbins stay outside Git.
The raw R report also pins all expected/device output replicas and guards.

Raw root: `/data/chuxiao/checks/publication-board-probe-20261025-v3/`.
Preserved failed preflights are in the sibling `v1` and `v2` roots: one rejected
an uncalibrated board before launch; the other failed without an XRT environment.
Neither generated an accepted performance sample.

R depends explicitly on the frozen original-R validation worktree
`/home/chuxiao/spine-cycle-sim/spine-cycle-sim-regraph-a4-board` (commit
`535f8e8`); its oracle/runtime gate is not replaced with a weaker local check.
The module sources are in
[publication_board_probe](../../../../../spine_cycle_sim/experiments/publication_board_probe/).
Use a new output directory for every run, never overwrite frozen evidence.

From the simulator root, under the same bounded systemd resource policy:

```bash
root=/data/chuxiao/experiments/baseline_hardware_validation_20261015
export XILINX_XRT=/opt/xilinx/xrt
PYTHONPATH=/home/chuxiao/spine-cycle-sim/spine-cycle-sim-regraph-a4-board \
  python3 spine_cycle_sim/experiments/publication_board_probe/regraph.py \
  --manifest "$root/original-r-board-supervisor-v4/manifest.json" \
  --manifest "$root/a4-board-supervisor-v3/manifest.json" \
  --device 1 --bdf 0000:c1:00.1 --output /data/chuxiao/checks/NEW-r-probe

python3 -m spine_cycle_sim.experiments.publication_board_probe.grasu \
  --host /data/chuxiao/checks/sharded-k4-host-final-20261024/sssp/sharded_k4_sssp_native_host \
  --xclbin /data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/route-slr-v2/sssp/grasu_regraph_weighted_pma_native_sharded_k4.hw.xclbin \
  --graph /data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/workloads/sx_askubuntu/graphs/directed_weighted.slice \
  --updates /data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/workloads/sx_askubuntu/updates/directed/insert_u131072.slice \
  --device 1 --bdf 0000:c1:00.1 --output /data/chuxiao/checks/NEW-g-probe

python3 -m spine_cycle_sim.experiments.publication_board_probe.analysis \
  --grasu /data/chuxiao/checks/publication-board-probe-20261025-v3/grasu/results.json \
  --regraph /data/chuxiao/checks/publication-board-probe-20261025-v3/regraph/results.json \
  --output docs/experiments/comparisons/grasu_regraph_publication_match/board_probe/results.json
```

Do not start another board user concurrently. Confirm the BDF, idle device,
available CPUs and memory before repeating these commands.

## Conclusion

The requested first measurements are complete. **A 10% publication match is
not established.** Current G and the original-R port both show large apparent
gaps, but neither comparison yet isolates the cause under paper-identical
conditions. The latest K4 adapter+R publication comparison is still missing.
Matching a simulator to our hardware and reproducing published performance
remain separate claims.

Verification for the initial probe: 30 focused Python tests passed (`test_publication_board_probe`,
`test_publication_match`, `test_repository_structure`), as did document-layout,
catalog and whitespace checks. G's service peaked at 737.2 MiB; R's at 429.6 MiB.
Both completed. No full Python suite, simulator campaign or new routing was run.
