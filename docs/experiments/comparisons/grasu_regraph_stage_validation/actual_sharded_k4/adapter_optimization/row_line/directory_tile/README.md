# Bounded Directory And Bank Streams

## Objective And Gates

Bring actual PMA-adapter + modified K4 model time to at most **1.10 times
original A4** on the fixed Amazon control, at both 64- and 128-cycle mock-memory
latency. Faster is acceptable; no timing constants, original-A4 configuration,
initial state, physical IDs or computational work may change to meet the gate.

This is one resident synchronous weighted-SSSP round, not convergence or a
published-performance reproduction. Cold and warm-update states remain
separately labeled. All three arms (A4, unchanged V3, tile candidate) must
run both component registration orders. The resource differences documented
in the [A4/V3 control](../cross_row/a4_control/README.md) remain explicit.

The investigation starts with a 128-row directory cache. The final candidate
uses a 1024-row (8 KiB) join cache, a 128-line directory FIFO, two 256-line
bank FIFOs (32 KiB together), a 16-segment loaded FIFO, and a separately
pipelined packet publisher. One existing AXI master owns all directory and
PMA reads. It reads bounded intervals of at most 256 lines from each bank,
splitting at the cached/external boundary. The join restores source/segment
order. The earlier 128-line bank version is retained, not overwritten.

The progressive-return model consumes actual AXI beats with finite buffering
and backpressure; the earlier aggregate-return model is retained separately.
The memory latency, 71-cycle reader floor, ports, outstanding credits and
backend are unchanged. All PMA padding and extra prefetched tail rows are
charged. No free sparse-source index, external port or materialized compact
edge copy is introduced. Legacy mode remains eight rows; neither candidate
is selected by the production plugin or an existing FPGA bitstream.

First check all three HLS edge formats, complete packets, boundary/tail cases,
production synthesis and full-top AXI RTL. Reject a requested II=1 schedule
if HLS does not implement it. Only then execute the corresponding simulator
organization. Preserve mismatches and failures, not just successful rows.

## Results

The final 256-line-bank HLS candidate passed three edge-format functional
suites (435 fixtures each), 23 full-top AXI RTL cases, and synthesis. Directory,
bank, join and publisher loops all achieved II=1. The estimated clock is
4.867 ns against 6.67 ns, with 76 BRAM18K, 16,854 FF and 39,326 LUT. These are
synthesis estimates for the adapter, not placed-and-routed system resources.

The fixed model matrix passes: 18 runs, including original A4, unchanged V3
and candidate, both registration orders, cold at latency 64 and warm-update
at latencies 64/128. Full output replicas and physical traffic are checked,
not only checksums or final timing. The warm-update result meets the
predeclared 10% gate at both latencies:

| Mock memory latency | Original A4 cycles | Unchanged V3 cycles | Final candidate cycles | Candidate / A4 | V3 / candidate |
| --- | ---: | ---: | ---: | ---: | ---: |
| 64 | 668,278 | 5,310,204 | 699,141 | 1.0462x | 7.5953x |
| 128 | 1,292,225 | 9,382,727 | 1,251,794 | 0.9687x | 7.4954x |

Thus the candidate is 4.62% slower / 3.13% faster than A4, respectively.
Cold and warm states differ, but their one-round work and latency-64 cycles
coincide. This is not evidence that their convergence costs coincide.

The retained intermediate results explain how the gap closed. Each value
below is candidate cycles divided by unchanged original-A4 cycles:

| Candidate | Memory latency 64 | Memory latency 128 |
| --- | ---: | ---: |
| Unchanged V3 | 7.946x | 7.261x |
| 128-row directory tile | 1.967x | 1.804x |
| 1024-row tile + packet pipeline | 1.623x | 1.541x |
| Bank streams, aggregate returns | 1.529x | 1.217x |
| Progressive AXI returns, 128-line banks | 1.119x | 1.010x |
| Progressive AXI returns, 256-line banks | 1.046x | 0.969x |

The 128-line progressive version still failed the 64-latency gate. Increasing
finite bank capacity lengthens continuous reads; it changes neither the
memory latency nor the number of ports or outstanding credits. Progressive
return corrects the earlier aggregate-response scheduling assumption: the
consumer can use actual returned beats before the complete parent response,
but still waits for the final acknowledgement. The original timing/control
arms are not retuned.

All versions read 7,609,792 PMA slots, including 6,158,893 dummy entries,
and emit 951,224 packets. The final version reads 129,024 directory lines
versus V3's 129,022; its extra 128 bytes are charged. Total reads are
43,939,840 bytes, and writes remain 3,145,732 bytes. Every one of the three
262,144-word source-state replicas matches the frozen oracle.

Independent extraction and raw recomputation pass. Verification also includes
27 core tests, exact complete-result replay of five legacy SST cases, and
595 distinct Python tests (427 sharded-K4, 120 original ReGraph, 33 refactor,
15 repository-organization). Mutation tests reject changed physical traffic,
state replicas, original-control cycles, HLS sources, executed RTL and sealed
conclusions. The 17 focused tests are included in, not added to, the 427.

## Scope And Remaining Work

The input is a fixed Amazon physical-ID selection: 258,046 vertices and
1,450,899 directed edges, four destination shards. The warm arm starts from
old converged distances after the same three source-0 weight decreases.
The window is first component tick through required state-write
acknowledgements for **one synchronous round**, not update-to-convergence.
GraSU update, host preparation, DMA, launch and orchestration are excluded
on both sides. This is not a complete G+R or Spine speedup comparison.

The unchanged mock memory has 32 channels, one issue/channel/cycle and
32 backend credits; the AXI interfaces retain 16 outstanding burst credits.
Latencies 64/128 are sensitivity assumptions, not measured HBM calibration.
The existing A4/K4 source-bank, parent-credit and publication differences
remain documented in the linked resource audit. Four frontends does not
make this a strict same-resource comparison or an exact routed 23-channel
replica.

**The narrow prediction target is met.** FPGA timing validation, promotion
to production, additional graphs/algorithms, complete convergence and
comparison with original-publication measurements remain unverified.
HLS/RTL proves realizability and behavior of the adapter under the tested
synthetic conditions; it does not validate whole-system cycle prediction.

## Review And Reproduce

The experiment package separates `contract.py` (fixed scope), `hls.py` (tool
execution), `validation.py` (realized schedules and RTL/packet gates),
`analysis.py` (full-state and physical-ledger admission), `model.py`
(frozen three-arm execution), `selection.py` (portable evidence membership),
`recheck.py` (independent raw recomputation), and `delivery.py` (sealing).
C++ bank issue, progressive return, join and packet publication have separate
private modules under
`cpp/src/regraph_pma_cross_row/`.

The [results](evidence/results.json), [verification index](evidence/verification.json)
and its four lossless archive parts (at most 64 MiB each) contain the
final matrix, HLS resources/RTL, frozen source/input/build identities,
complete output buffers and legacy regression. Intermediate and failed
checkpoints are retained separately inside that same archive. Later Python
regression logs and tests have their own [index](python_regression.json) and
[archive](python_regression.tar.gz) so that frozen numerical evidence is not
rewritten. The first oversized single-file delivery is preserved locally and
indexed in the archive; partitioning only changes transport, not the sealed
evidence bytes.

Verify the delivered package without original runtime paths or vendor tools:

```bash
D=docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/directory_tile
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.delivery \
  --destination "$D/evidence" --verify-only
python3 -m unittest discover -s tests -p 'test_sharded_k4_directory_tile*.py'
```

For a new run, extract the basis package linked above and use fresh paths.
Rebuilding HLS requires the separate integration repository and vendor tools:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hls \
  --integration /path/to/grasu-regraph-integration \
  --reference /path/to/frozen-cross-row-adapter.xo \
  --vivado-bin /path/to/Vivado/2024.1/bin \
  --output /path/to/fresh-hls --bank-stream --bank-lines 256

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.model \
  --basis /path/to/frozen-cross-row-a4 \
  --hls /path/to/admitted-bank-hls/results.json \
  --output /path/to/fresh-run --bank-read-beats
```

The basis result SHA is fixed by `contract.py`. A4 and V3 must replay exactly,
both registration orders must agree, all state replicas must match the frozen
oracle, and directory tail bytes are independently recounted from the CSR.
Runs reserve 16 GiB of system memory and have bounded time/memory budgets.

Local raw run root: `/data/chuxiao/experiments/sharded_k4_directory_tile_20261012`.
Accepted children are `hls-bank-wide-v1`, `model-bank-wide-v1` and
`verification-v5`. The latter reuses the completed core build, 27 passing
core tests and fresh SST plugin from `verification-v4`, with hashes and
unchanged numerical-source checks recorded in `build_reuse.json`. It reruns
all five legacy SST cases after freezing the delivery code. The earlier
replay was rejected because packaging files changed during execution, and
is preserved as failed evidence. The production plugin is not overwritten.
The numerical archive, not the current checkout, identifies precisely
which source bytes were executed.

Keep the failed multiple-AXI-owner HLS experiment, the failed beat-mode compile
and interface check, and the source-change-rejected SST campaign. They are
negative evidence, not accepted verification.

Code owner: `spine_cycle_sim/experiments/sharded_k4_stages/row_line/directory_tile/`.
HLS candidate: integration repository,
`kernels/pma_to_regraph_adapter/{directory_tile,bank_stream,packet_pipeline}.hpp`.
Its source commit is `6f5ebf2` on `codex/sharded-k4-fullgraph-hls`.
Sources and default-plugin identity were frozen before editing. The paper,
existing figure handoff and unrelated calibration changes are out of scope.
