# Whole-Line Row Directory Candidate

## Decision

The production HLS now has an explicit, default-off whole-line directory
reader. Its generated RTL issues one 64-byte read per visited eight-row block,
plus the separate final-row extent read. This removes the repeated line reads
identified in the [previous production AXI probe](../adapter_axi/README.md).
It does not introduce a free sparse-source index or change PMA edge storage.

All functional, production-XO ABI, full-top AXI RTL and four-algorithm host
preparation gates pass. **This is not a routed/board timing result, simulator
calibration, or completed original-A4 comparison.** At that HLS checkpoint the
numerical simulator was unchanged. The later, explicitly separate
[model checkpoint](model/README.md) adds default-off whole-line requests and
preserves the default plugin, previous measured bitstreams and paper.

## Review Package

| Item | Location |
| --- | --- |
| Complete twelve-case comparison and HLS report | [results.json](evidence/results.json) |
| Four-algorithm preparation equality | [host.json](evidence/host.json) |
| Per-file identities and archive hash | [verification.json](evidence/verification.json) |
| Complete XOs, executed RTL, sources, binaries and raw logs | [raw_row_line.tar.gz](evidence/raw_row_line.tar.gz) |
| 276 focused Python regressions, source identities and raw logs | [regression.json](evidence/regression.json), [raw_regression.tar.gz](evidence/raw_regression.tar.gz) |
| Runner, validation and packaging owner | `spine_cycle_sim/experiments/sharded_k4_stages/row_line/` |
| Focused tests | `tests/test_sharded_k4_row_line.py`, `tests/test_sharded_k4_row_line_evidence.py` |

Execution (`study.py`, `probe.py`, `host.py`), contracts (`validation.py`), raw
admission (`evidence.py`) and packaging (`delivery.py`) have separate owners.
Production HLS and native-host changes belong to `grasu-regraph-integration`,
not this simulator repository. The archive contains the versions actually
executed; later files in the same package are not retroactively run inputs.

## Exact Versions And Memory Contract

The reference is the compiled skip-empty XO, **not** the earlier routed
combined XO. The latter is separately pinned to its original route manifest.

| Version | Complete XO SHA-256 |
| --- | --- |
| Reference, skip-empty | `4bae8791463a71f8b02ccad870d0178b2268cea8cfa6173c480e8a596a24417a` |
| Candidate, whole-line reads | `752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2` |
| Historical routed combined reference | `93aa6b76e441eda51ffc0a9bb25c1411cfab2be2bf18326371558a0cefb1863a` |

Both tested production XOs enable weighted/sharded PMA, shared adapter AXI,
row prefetch, stop-after-last and skip-empty. Only the candidate defines
`GRASU_REGRAPH_ROW_LINE_READ=1`. Neither uses test-only interface depths.
The requested synthesis target is U55C, 150 MHz. Complete external kernel
XML interfaces match, including control offsets, master width and stream ABI.

The HLS C row pointer changes from 64 to 512 bits; the packed little-endian
64-bit entries do not change. A candidate host must use `--row-line-read`:
row buffers are 64-byte aligned and padded to whole eight-entry lines. The
original V+1 entries, including the sentinel, are preserved; padding is zero.
The update kernels still use the same 64-bit entries. Padding does not change
4-KiB-rounded region allocation or channel placement in the tested cases.
Do not pair this XO with an unpadded host merely because XML ABIs match.

## Results

Each arm passes twelve complete production-RTL invocations against the same
checked AXI memory/sink bench. All packet data/keep/strb/last values, PMA
requests/bytes and output stability under backpressure are preserved.
Three C++ edge formats each pass 254 scenarios and 1,482 exact packets for
each of prefetch, skip-empty and whole-line modes, plus six legacy builds.

Selected rows below are descriptive; all twelve are in the results file.
Cycles span first `ap_start` high to `ap_done`, not host launch.

| Sources / placement | Synthetic L | Sink stall | Row requests, reference -> candidate | Row bytes | RTL cycles |
| --- | --- | --- | --- | --- | --- |
| 0 / all | 1 | 0 | 0 -> 0 | 0 -> 0 | 2 -> 2 |
| 8 / all | 1 | 0 | 9 -> 2 | 576 -> 128 | 796 -> 787 |
| 9 / all | 1 | 0 | 10 -> 3 | 640 -> 192 | 950 -> 939 |
| 17 / all | 64 | 0 | 18 -> 4 | 1152 -> 256 | 1755 -> 1735 |
| 17 / last-only | 64 | 0 | 18 -> 4 | 1152 -> 256 | 459 -> 439 |
| 17 / first-only | 64 | 0 | 9 -> 2 | 576 -> 128 | 248 -> 239 |
| 17 / every seventh | 64 | 0 | 17 -> 3 | 1088 -> 192 | 537 -> 519 |
| 17 / all | 64 | 1000 | 18 -> 4 | 1152 -> 256 | 2427 -> 2416 |

The 17-source dense case cuts directory traffic by 4.5x but RTL cycles by
only 1.14%. This is an important limit, not a failed conservation check.
Eliminating redundant requests does not guarantee a proportional latency
gain: the occupied-segment path and downstream waits remain. These small
tests do not establish which component dominates a real graph. In particular,
the old independent PMA+A4 model's 791x slowdown must not be assigned to this
actual K4 path or treated as a performance gain recovered by this change.

HLS estimates are 15,249 LUTs, 11,485 FFs, 15 BRAM_18K and no DSP/URAM,
with estimated clock period 4.867 ns. These are synthesis estimates, not
routed timing or area/energy evidence for the paper.

The separate host study builds SSSP, CC, FullPR and ResPR both with and
without padding. All four six-partition prepare/oracle outputs match
byte-for-byte. Eleven sizes exercise 8-entry tails and the 4-KiB boundary,
including rejection of a truncating runtime plan. A failed development
test caught the wrong expected exception type; its logs and sources remain
under `development/host-v1/` in the archive. No hardware bug is inferred
from that test-harness mistake.

## Reproduction

From the simulator root, use fresh output directories:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.study \
  --integration /home/chuxiao/grasu-regraph-integration \
  --reference /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/production-v2/adapter.hw.xo \
  --routed /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/ablations_safe_index/combined/adapter.hw.xo \
  --route-manifest /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/route_combined_sssp/manifest.json \
  --output /data/chuxiao/experiments/fresh_row_line \
  --vivado-bin /data/yxx/tools/xilinx/Vivado/2024.1/bin

python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.host \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output /data/chuxiao/experiments/fresh_row_line_host

python3 -m unittest discover -s tests -p 'test_sharded_k4_row_line*.py'
```

Each subprocess is memory/time bounded and executions are serial. Synthesis
has an 8-GiB tree RSS budget and 1200-second timeout; RTL steps have 4 GiB
and 120 seconds; host checks have 4 GiB and 300 seconds. All preserve a live
16-GiB reserve. There is no claim of a separately monitored aggregate parent
runner. Proprietary tools are identity-indexed rather than redistributed.

The archive has been extracted into a fresh temporary directory and both
`delivery.recheck(extracted / "study")` and
`delivery.recheck_host(extracted / "host")` pass without reading the original
run's source, XO, RTL or binary paths.

All 276 sharded-K4 Python tests and 15 repository-structure tests pass.
Documentation layout, generated catalogs and whitespace checks also pass.
These are regression/organization gates, not numerical timing calibration.

## Remaining Gates

The memory responder accepts AR immediately and supplies ordered responses;
it has no HBM bank, refresh or interconnect model. L controls response
eligibility, and the first accepted response is later than AR+L. A 10-ns
bench clock counts RTL clocks only. Every trial resets the adapter; repeated
invocation without reset and the actual ReGraph downstream are not tested.
Only weighted production RTL was probed; the other edge formats have C++
packet evidence. Host tests use CPU oracles, not FPGA execution.

Route/link still requires the unchanged 40-GiB tree budget plus 16-GiB reserve.
The [route checkpoint](route/README.md) binds this exact XO and padded host
to the unchanged historical connectivity. All six environment preflights
pass, but the 53.74-GiB available-memory observation fails 56-GiB admission;
no route was started. Once resources permit, retry in a fresh directory,
check routed timing/connectivity, and measure paired resident executions.
The [model checkpoint](model/README.md) separately checks new input traffic
and completion while preserving exact legacy outputs. It does not discharge
the route/board gate. The [original-A4 model control](a4_control/README.md)
adds 24 complete-state/traffic runs with exact legacy replay: whole-line
reads save only 1.44--2.36% total cycles beyond skip-empty, and the candidate
remains 23.83--25.93x slower than A4 in the declared model. This is not FPGA
timing or isolated adapter overhead. The final resource-matched original-A4
versus actual adapter+K4 comparison remains a separate unfinished gate.
The [passive occupied-row probe](occupied_rows/README.md) now reproduces all
original handshakes exactly and observes repeated serial helper lifetimes.
It motivates testing cross-row pipelining in actual HLS; it does not change
the simulator or establish a board-level bottleneck attribution.
The [cross-row production HLS study](cross_row/README.md) now passes complete
RTL/ABI/packet gates: dense synthetic cases improve approximately 2.5--3x.
The retained v2 last-only case regresses 28.47%; v3's empty-block bypass reduces
it from 564 to 402 clocks, with the other eleven rows unchanged. Estimated LUT
use approximately doubles. Both versions are retained; neither is routed or
a numerical-model correction.
