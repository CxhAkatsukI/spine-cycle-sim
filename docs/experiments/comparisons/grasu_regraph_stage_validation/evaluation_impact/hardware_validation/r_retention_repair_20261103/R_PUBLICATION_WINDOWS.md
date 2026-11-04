# R Ordered Publication Windows

The first section diagnoses the **repair-before FPGA run**. The board event
envelope was 70.254409 ms for
the integrated Amazon path and 10.365434 ms for public-source A4. At the
predeclared 1.15 gate the candidate must reach 11.920249 ms or less.

The pinned candidate host launches adapter and gather on worker
`shard % 4`, but the single mux must publish destination shards in order.
Each recorded mux window starts when that command runs and ends when it
finishes. It can include waiting for the first output or downstream
backpressure; it is not a counter for time spent actively transferring.

| Amazon shard(s) | Worker | Sum of nonoverlapping mux windows |
| --- | ---: | ---: |
| 0 | 0 | 34.515 ms |
| 4 | 0 | 21.990 ms |
| 8 | 0 | 8.465 ms |
| 9 | 1 | 2.616 ms |
| Other eight | 1--3 | 2.315 ms |

Shards 0, 4 and 8 account for **64.970 ms (92.48%)** of the whole candidate
envelope. Their adapters each finish only 0.221--0.243 ms before the
respective mux finishes. The other mux windows, except shard 9, each take
0.279--0.305 ms; the recorded gaps between mux commands are all at most
1.150 us. This makes gaps *between* mux commands an inadequate explanation.
It does not establish a particular HBM bank, worker, or source of backpressure
as the cause. The corresponding skewed-source windows are 0.830 ms and
0.283 ms, within the 1.361358 ms envelope.

The Amazon host packed 43,198,432 PMA slots for 5,158,388 logical edges
(8.37 slots per edge). The actual prefetch/compact adapter already drops
invalid lanes and combines live edges into packets within source windows.
It still reads PMA segments before compacting. The directory-span repair
preserves this work: 2,699,902 segments of 16 slots. An independent replay
of the frozen CSR and host allocation rules gives worker slot counts
13,568,368 / 12,280,400 / 9,970,224 / 7,379,440. Worker 0 owns **31.41%**
of the slots; its 92.48% of elapsed publication windows is not explained
by raw slot-count imbalance alone. At one segment per worker per cycle
and 150 MHz, the heaviest worker's 848,023 segments imply a floor of
**5.653 ms**, compared with the perfectly balanced floor of 4.500 ms.
These are ideal floors, not predictions, not measured clocks for the old
image, and not additive with gather or publication. Skipping or overlapping
output padding alone cannot explain away 58.334 ms of excess Amazon latency.

On each repaired image, compare the same two controls once per arm and
replay these windows before choosing the next change. If long windows
survive the directory repair, measure the worker's PMA segment counts
and first-packet/last-packet progress before attributing the gap to the
adapter, gather or shared property service.

## Tail Repair: Derated FPGA Diagnostic

The first ResPR tail-repair image passed correctness on both supported
controls. The reference and candidate ran once each on the same U55C, using
the same first-CU-start to last-CU-end boundary as above. Driver-reported
compute clocks were both 150 MHz, but HBM was 450 MHz on the public A4 and
440 MHz on the candidate (441.6 MHz in the link report). No clock scaling
was applied to these results.

| Control | Public A4 | Integrated tail repair | Integrated / A4 |
| --- | ---: | ---: | ---: |
| Full Amazon | 10.339166 ms | 10.215603 ms | 0.988x |
| Skewed sources | 0.432862 ms | 0.811403 ms | 1.875x |

The same Amazon mux windows for shards 0, 4 and 8 now sum to 7.445 ms,
down from 64.970 ms before the repair. This localizes where the reduction
appears in the event trace, not which hardware operation caused it.
On skewed sources, gather 0 finishes 212 us after adapter 0 and the whole
run finishes another 104 us later. These are timestamps of overlapping
kernels, not per-stage service counters.

**Admission remains open.** Amazon is numerically inside the 1.15 gate,
but this was not a same-clock comparison. Skewed sources also misses the
numeric gate by 0.314 ms. The duplicate-edge boundary ring remains
unsupported. No resident matrix row or figure is admitted by these results.

The [receipt and raw timestamp/clock records](derated-diagnostic.tar.gz)
include `diagnostic.json`, `board/results.json`, the per-arm logs, and both
public A4 `result.json` files. To replay the candidate event windows, extract
the archive and pass `--results "$raw/board/results.json" --raw-root "$raw"`
to the command below, for both `--case amazon` and `--case skewed_sources`.

## Hardware Control Coverage

The public-source four-Little control on hand is a PageRank build.
The locally archived weighted SSSP U55C image at
`/home/chuxiao/regraph/ReGraph_sssp_hw_scratch/xclbin_hw_sssp/graph_fpga.hw.xilinx_u55c_gen3x16_xdma_3_202210_1.xclbin`
is **not** a matched A4 control. Its embedded link metadata has
`LITTLE_KERNEL_NUM=1`, `BIG_KERNEL_NUM=1`, and weighted SSSP UDFs
(UUID `4a5e2a68-32e8-daa7-049a-d7908f08be4b`, SHA-256
`0f8e9f786b35c951b76b33f9ecac30b25ef888823a99de21be50a7e58f98b76d`).
The old PR control and this SSSP image do not establish four-Little
retention for weighted SSSP or for minimum-label CC.

The frozen public A4 source packet contains `bfs`, `cc`, and `pr`
UDFs, but no weighted-SSSP UDF. Its `acc_udfs/cc/l2.h` combines
messages and old state with bitwise OR; the integrated minimum-label CC
instead compares candidate labels. An algorithm-matched SSSP/CC control
would keep the public four-Little topology and dataflow, with a declared
algorithm-UDF adaptation and an independent exact-output oracle. Label
it as a same-resource adaptation, not as an unchanged upstream image.

## Replay

Set `evidence` to this document's directory and run from the simulator root:

```bash
raw="$(mktemp -d)"
tar -xzf "$evidence/before-once/evidence/raw_board.tar.gz" -C "$raw" \
    before-once/results.json before-once/r_amazon_current.stdout.txt \
    before-once/r_amazon_current.stderr.txt
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_windows \
    --results "$raw/before-once/results.json" --raw-root "$raw" --case amazon
```

The command verifies the archived stdout/stderr identities, correctness,
event ordinals, and the total timing envelope. Ordinal mapping is from
`cpp/tests/publication_sources/source_retention/device.hpp`, included
in the same checkpoint's reproduction archive. Add `--csr <directory>`
pointing to the frozen Amazon input identified in
[`before-once/data/artifacts.json`](before-once/data/artifacts.json)
to reproduce the slot counts. The layout replay requires the duplicate-free
unit-weight no-update control and verifies its totals against the board log.
