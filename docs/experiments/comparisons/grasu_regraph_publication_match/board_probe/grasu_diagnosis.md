# GraSU Startup And Repeated Cache Cost

## Finding

The latest G path has two concrete sources of overhead: first-use input
residency costs in the nominal kernel-event envelope, and complete cache
preload/writeback repeated for every destination shard. Neither is evidence
that PMA updates inherently require a 67-fold slowdown. Neither establishes
that the remaining difference to the GraSU paper has been eliminated.

No HLS, simulator coefficient, paper, or figure was changed. These are new
FPGA diagnostics using the existing routed weighted-SSSP G+R bitstream in
`--update-only` mode. R does not execute.

## Controlled Startup Probe

Same AU input as the initial probe: 515,281 declared vertices, 390,847 initial
edges, 131,072 unique absent-edge insertions, original external IDs, eight
destination shards. The two modes use the same hash-pinned host and xclbin,
150 MHz, U55C BDF `0000:c1:00.1`, and CPU affinity 124,125.

Each mode uses one new host process with four executions, restoring all PMA
copies outside the timer before each execution. Only the final execution in
each process receives the touched-PMA readback gate: both pass, with 716,992
checked words and zero mismatches. Earlier repetitions are diagnostics, not
independently verified performance samples or a confidence interval.

| Mode | First execution (ms) | Next three executions (ms) | Median of next three (ms) | Median rate (Mupdates/s) |
| --- | ---: | --- | ---: | ---: |
| Existing initial transfer sequence | 46.398211 | 24.886051, 24.743867, 24.498890 | 24.743867 | 5.297 |
| Explicitly migrate inputs before update | 24.038835 | 24.502419, 24.485139, 24.533150 | 24.502419 | 5.349 |

Explicit premigration covers 80 buffers / 169,368,496 bytes and takes
19.8713 ms by DMA-event timing (19.8918 ms wall). This is consistent with
first-use input residency explaining much of the approximately 22 ms
cold-versus-warm difference. It is not a separate measurement proving every
one of those milliseconds is PCIe DMA. Crucially, this cost has moved before
the update window; it has not disappeared from a setup-inclusive boundary.

The update timer is the first-start to last-end envelope of nine concurrent
update CUs across eight serial shards. Explicit initial DMA, PMA restoration,
and final readback are excluded. Implicit first-use migration may still enter
the baseline envelope. Calling that cold envelope pure resident G throughput
would be misleading. The earlier independent cold-process measurements are
preserved, not replaced.

## Source And Synthesis Evidence

The actual routed source is `grasu-regraph-sim-aligned`, not the older
integration worktree. `kernels/grasu_complete/cache_pipeline.hpp:32` allocates
16 URAM banks per cache half, preloads the entire half, processes updates, and
writes the entire half back. `cache_bank.hpp` sets 8,192 words per bank and
512 bits per word. Two cache CUs run concurrently.

| Quantity | Derivation | Value |
| --- | --- | ---: |
| One cache half | 16 banks x 8,192 words x 64 bytes | 8 MiB |
| Two halves, load plus writeback per shard | 2 x 8 MiB x 2 | 32 MiB |
| Eight serial shards per batch | 8 x 32 MiB | 256 MiB |
| Synthesized preload / writeback latency, each | XML best-case cycles | 131,075 cycles |
| Achieved loop initiation interval / trip count | XML loop schedule | 16 / 8,192 |
| Nominal fixed schedule across eight shards | 8 x (131,075 + 131,075) / 150 MHz | 13.981 ms |

This last number is a **source/synthesis-derived no-stall floor**, not a
counter-isolated board measurement. Do not sum both cache CU times: the CUs
overlap. The preload and writeback within each CU are sequential. Runtime AXI
stalls, update processing and backpressure can add latency.

The final premigrated execution is 24.533150 ms. Its inter-shard gaps total
2.109055 ms; median within-shard CU start spread is 0.109924 ms. Shards with
only 976 and 1,410 updates still take approximately 2.093 and 2.092 ms. The
fixed schedule and these observations explain why small shards do not finish
in proportion to their update count. They do not independently attribute all
remaining time among search, editing, AXI stalls and stream waits.

The preserved original-source U55C port also has full-cache load/store loops
with `II=16`. That behavior is not newly invented by the latest port. Our
destination-sharded integration amplifies it through eight serial invocations.
There is no controlled same-input original-G versus current-G experiment here
that quantifies exactly how much of the publication gap this amplification
accounts for.

## Why Public Code Is Not A Paper Performance Match

GraSU does have [public author code](https://github.com/qgwang-hust/GraSU).
However, the [FPGA 2021 paper](https://doi.org/10.1145/3431920.3439288), Sec. 3.2,
describes a Verilog implementation; Sec. 6.1 uses U250 at 200 MHz, 32 update
PEs, eight 4-byte entries per segment, and ten temporal batches. Sec. 6.4
explicitly says AU/SU fit entirely in URAM. The public HLS path and our port
instead operate on 512-bit segments and require their own implementation and
timer audit. Porting public HLS successfully does not establish equivalence
to the published RTL experiment.

Table 4 reports AU at 190.77 Mupdates/s. Relative to the new warm rate of
5.349 Mupdates/s the numerical ratio is still approximately 35.7. That is an
**unmatched-workload rate ratio**, not a controlled reproduction error. Our
weighted ID-preserving AU input differs from the paper's temporal dataset.
The 200/150 MHz difference alone cannot explain a difference of this size.
Nor can all remaining cost be assigned to sparse updates without testing.

## Implication

First separate residency setup from resident update throughput and continue
reporting setup-inclusive time when that is the system boundary. Then address
repeated full-capacity cache traffic in the actual G+R HLS, not just in the
simulator: investigate valid cache extents, shard organization, or persistent
cache operation with explicit coherence and ownership. R's need for local
destination shards does not by itself prove G must reload its entire cache
for each shard. A particular alternative still needs correctness validation,
synthesis/routing and measurement before claiming its speedup.

This investigation diagnoses real overhead, but does **not** deliver a
paper-identical GraSU reproduction, a 10% match, a new routed design, or a
revised G+R-versus-Spine matrix.

## Evidence And Reproduction

Packaged report: [grasu_launch_results.json](grasu_launch_results.json).
It pins source witnesses, synthesis XML, input identities, host/xclbin and all
raw output hashes. Raw directory:
`/data/chuxiao/checks/grasu-launch-20261025-v1/`.

Runner and packager live together in
`spine_cycle_sim/experiments/publication_board_probe/` as `grasu_launch.py`
and `grasu_launch_analysis.py`. From the simulator root:

```bash
systemd-run --user --scope --quiet \
  -p MemoryMax=8G -p MemoryHigh=7G -p MemorySwapMax=0 \
  python3 -m spine_cycle_sim.experiments.publication_board_probe.grasu_launch \
  --host /data/chuxiao/checks/sharded-k4-host-final-20261024/sssp/sharded_k4_sssp_native_host \
  --xclbin /data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/route-slr-v2/sssp/grasu_regraph_weighted_pma_native_sharded_k4.hw.xclbin \
  --graph /data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/workloads/sx_askubuntu/graphs/directed_weighted.slice \
  --updates /data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/workloads/sx_askubuntu/updates/directed/insert_u131072.slice \
  --device 1 --bdf 0000:c1:00.1 --output /data/chuxiao/checks/NEW-grasu-launch

python3 -m spine_cycle_sim.experiments.publication_board_probe.grasu_launch_analysis \
  --raw /data/chuxiao/checks/grasu-launch-20261025-v1 \
  --synthesis /data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/sssp/build/process_cache/process_cache/process_cache/process_cache/solution/syn/report \
  --hls-root /home/chuxiao/grasu-regraph-sim-aligned \
  --author-cache /data/chuxiao/experiments/baseline_hardware_validation_20261015/original-g-external-port-return-follow-v7/returned/packet/source/kernel_process_cache.cpp \
  --paper /data/feiyang/delta-hls-paper/related_papers/2021_FPGA_GraSU.pdf \
  --output docs/experiments/comparisons/grasu_regraph_publication_match/board_probe/grasu_launch_results.json
```

Use a new raw directory. The runner leases the board, resolves its render
node from its BDF, checks idle state and at least 24 GiB available memory,
runs serially, and imposes a 240-second deadline per mode. Do not run another
board user concurrently.

Verification: 36 focused tests passed across `test_grasu_launch_probe`,
`test_publication_board_probe`, `test_publication_match`, and
`test_repository_structure`. Document layout, generated catalogs and
whitespace checks passed. No full simulator suite or routing was run.
