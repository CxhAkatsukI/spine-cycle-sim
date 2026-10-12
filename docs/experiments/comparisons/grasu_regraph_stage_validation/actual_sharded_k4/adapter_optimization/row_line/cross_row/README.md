# Cross-Row Production HLS Study

## Decision

The default-off cross-row candidate passes production HLS synthesis, exact
external ABI checks, three-format C++ packet equivalence and the complete
twelve-case production-RTL AXI matrix. The unchanged whole-line reference
replays all original request/response timestamps and outputs exactly.
**No route, FPGA speedup, numerical-simulator change or A4 match is admitted.**

This is a real HLS input-path change, not a timing correction factor. Within
each cached eight-source directory line, one memory process flattens source
and segment traversal, allowing PMA requests to overlap across short occupied
rows. A separate publisher consumes a finite depth-16 FIFO. The existing
single AXI master, directory/PMA layout, packet order, padding contract and
control/stream ABI are retained. Directory-line transitions still drain the
inner pipeline; this is not overlap across the complete graph.

## Review And Reproduce

| Item | Location |
| --- | --- |
| Complete matrix, ABI and synthesis results | [results.json](evidence/results.json) |
| 340 focused and 15 organization test results, resources and frozen tests | [regression.json](evidence/regression.json), [raw_regression.tar.gz](evidence/raw_regression.tar.gz) |
| Archive identities and per-file index | [verification.json](evidence/verification.json) |
| Both XOs, generated RTL, sources, binaries, transcripts and failed first attempt | [raw_cross_row.tar.gz](evidence/raw_cross_row.tar.gz) |
| Execution, validation, raw recheck and packaging | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/cross_row/` |
| Admission and mutation tests | `tests/test_sharded_k4_cross_row.py` |

Production source belongs to `grasu-regraph-integration`:
`kernels/pma_to_regraph_adapter/cross_row_pipeline.hpp`, with the default-off
`GRASU_REGRAPH_CROSS_ROW_PIPELINE=1` branch in the existing adapter. The archive
pins the exact executed versions, independent of later working-tree changes.
It includes synthesis helper reports, not only the top-level estimate.
The successful production-source checkpoint is integration commit `074ecb2`.
Documentation layout, generated catalogs and whitespace checks pass; the
regression archive is separate from the original synthesis/RTL run archive.

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.delivery \
  --destination docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/row_line/cross_row/evidence \
  --verify-only

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.study \
  --integration /home/chuxiao/grasu-regraph-integration \
  --reference /data/chuxiao/experiments/sharded_k4_row_line_20261011/attempt-v1/production/adapter.hw.xo \
  --output /data/chuxiao/experiments/fresh_cross_row \
  --vivado-bin /data/yxx/tools/xilinx/Vivado/2024.1/bin

python3 -m unittest discover -s tests -p 'test_sharded_k4_cross_row.py'
```

The second command requires the exact reference XO and the production source
snapshot from this archive, not arbitrary later HLS. The first command only
extracts into a fresh temporary directory and verifies raw evidence; it needs
neither the original run paths nor proprietary tools. C++ checks have a
3-GiB/240-second subprocess budget; synthesis has 8 GiB/1200 seconds; RTL
steps have 4 GiB/120 seconds. Each preserves a live 16-GiB reserve and runs
serially. Proprietary tools and compiled simulation images are not redistributed.

## Versions And Results

| Version | XO SHA-256 |
| --- | --- |
| Unchanged whole-line reference | `752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2` |
| Cross-row candidate, successful attempt-v2 | `053a2b27a8a5f84ef05e05c779d23c9add6b313d7c3f4c511cb1a5f547f27504` |

The table includes every case, including regressions. L is a synthetic ordered
AXI response-eligibility parameter, not a measured HBM latency. Cycles span
first `ap_start` high through `ap_done`, not host launch or convergence.

| Trial | Sources / occupied rows | Segments/row | L | Sink stall | Reference cycles | Candidate cycles |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 / none | 1 | 1 | 0 | 2 | 6 |
| 1 | 1 / all | 1 | 1 | 0 | 227 | 232 |
| 2 | 8 / all | 1 | 1 | 0 | 787 | 267 |
| 3 | 9 / all | 1 | 1 | 0 | 939 | 396 |
| 4 | 17 / all | 1 | 1 | 0 | 1651 | 560 |
| 5 | 17 / all | 1 | 64 | 0 | 1735 | 588 |
| 6 | 17 / all | 1 | 128 | 0 | 3079 | 1036 |
| 7 | 17 / all | 3 | 64 | 0 | 1803 | 730 |
| 8 | 17 / last only | 1 | 64 | 0 | 439 | 564 |
| 9 | 17 / first only | 1 | 64 | 0 | 239 | 244 |
| 10 | 17 / every seventh | 1 | 64 | 0 | 519 | 416 |
| 11 | 17 / all | 1 | 64 | 1000 | 2416 | 1080 |

Trial 5 improves 2.95x and trial 6 improves 2.97x; maximum outstanding rises
from 1 to 8. Three segments/row reach 16 outstanding. These are complete
adapter RTL lifetimes, not exclusive memory-stall measurements. Packet
data/keep/strb/last and PMA/directory traffic remain equal in all twelve cases;
output stability under downstream backpressure also passes. Each of three
C++ formats preserves 1,482 packets in 254 scenarios; all earlier adapter
functional matrices pass as well.

Trial 8 is **28.47% slower**, and empty/one-row calls pay a small startup cost.
The flattened reader still enters its deep pipeline for entirely empty
cached blocks. Bypassing such blocks is a testable follow-up, not a proven
explanation or an already recovered speedup. The complete v2 results remain
frozen regardless of that follow-up's outcome.

Synthesis requests U55C/150 MHz. The inner read loop and publisher half loop
both achieve II=1; the read-loop depth is 75. Estimates are 30,466 LUT,
12,850 FF, 15 BRAM_18K, no DSP/URAM and 4.867 ns. LUT use approximately doubles
from the reference's 15,249; the added overlap is not resource-free. These
are HLS estimates, not placed-and-routed timing or ASIC/board power evidence.

## Failed Attempt And Open Gates

The first three-process design passed software packet checks but failed
production synthesis: Vitis rejects separate directory and PMA readers on
the same `gmem0` AXI bundle (`HLS 200-1013`, `HLS 200-984`). Its frozen sources,
compiler logs and explicit `FAILED_RETAINED` record are in `development/`.
The admitted two-process design keeps both types of reads in one process.

Only weighted production RTL is tested; the other formats have C++ evidence.
The responder has no HBM banks, refresh or real interconnect; each invocation
resets the adapter, and the sink is not the actual ReGraph backend. Route
still requires 40 GiB plus a 16-GiB reserve; it is not started while available
memory is below 56 GiB. FPGA admission, a separately versioned synchronized
simulator and original-A4 performance comparison remain unfinished. The
default plugin, existing bitstreams, figure handoff and paper are unchanged.
