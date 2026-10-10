# Original G DDR Shared-Memory RTL Control

## Accepted Finding

`grasu_ddr_rtl_final_v3` passes all twelve predeclared cases under the declared
finite memory model. Each case has two complete RTL runs, two normal source
runs and one UBSan source run. Every 2,048-byte cold-region state agrees with
the independent oracle. Source runs also check all 131,072 untouched prefix
lines and an end guard. RTL requests outside the admitted region are rejected.
All input packets, sentinel, requests, services and responses are conserved.

This validates one original G component's behavior and supplies timing/order
constraints. It is **not** a complete G cycle model, FPGA measurement, DDR
controller calibration, published-throughput match or current routed-port match.
The source is unchanged GraSU revision
`e95da256be9e7f2361449323b6fe0abf98c1b152`, with sixteen 32-bit slots per segment.
The publication's eight-slot geometry remains a separate control.

## Configuration And Boundaries

The [contract](../../../../configs/experiments/original_grasu_ddr_rtl_v1.json)
declares fresh Vitis HLS/XSim 2024.1 execution, a U250 `xcu250-figd2104-2L-e`
synthesis target at 5 ns, and an isolated `process_ddr` kernel. This is not an
achieved routed clock. Inputs are valid **post-search** update packets, not a
complete G graph/host/search workload.

All four original host pointers alias the same physical PMA allocation.
The test retains absolute cold-region addresses but stores only 32 lines.
Two read and two write AXI ports share one beat-service arbiter; each has
sixteen request slots and one held response. Each transaction is one 64-byte
beat. Read data is sampled at service. A write becomes visible only after
its independently accepted AW/W pair reaches service. Minimum request-to-service
latency is 16, 64 or 128 cycles as declared, not a fitted DDR parameter.

`kernel_cycles` below is observed `ap_done - ap_start`. Raw `cycles` additionally
includes three explicitly declared bench-settling cycles before state capture.
Neither includes host launch, search/BIPA, hot-cache preload/writeback or merge.

| Case | Updates | Minimum Memory Latency | Input Gap | Kernel Cycles |
| --- | ---: | ---: | ---: | ---: |
| Empty | 0 | 64 | 0 | 326 |
| Single | 1 | 64 | 0 | 503 |
| Unique even lanes | 16 | 64 | 0 | 521 |
| Unique both subpaths | 32 | 64 | 0 | 522 |
| Repeat even segment | 3 | 64 | 0 | 857 |
| Repeat odd segment | 3 | 64 | 0 | 857 |
| Repeat both segments | 6 | 64 | 0 | 858 |
| Paced repeat | 3 | 64 | 800 | 2,161 |
| Repeat, latency 16 | 3 | 16 | 0 | 815 |
| Repeat, latency 128 | 3 | 128 | 0 | 1,241 |
| Unique both, latency 128 | 32 | 128 | 0 | 650 |
| Alternating insert/delete | 4 | 64 | 0 | 1,034 |

The input driver inserts two handshake cycles between immediately offered
updates; `Input Gap` is the additional configured delay. Actual input and
memory timestamps are retained rather than replaced by an ideal arrival rate.

## What This Resolves

The inner sixteen-stream loop has HLS `II=1`, depth 146. Its enclosing RTL
controller waits for inner-loop completion before another sweep; inspect
`formal/rtl/process_ddr_process_r.v` and both inner-loop XML reports in the
archive. An `II=1` label alone therefore cannot justify one arbitrary update
per cycle or sixteen-cycle same-segment reuse.

For repeated even updates at latency 64, AR acceptance occurs at cycles
205, 382 and 559; writes become visible at 351, 528 and 705. Each next read
follows the prior write. All twelve cases have zero same-line reads before
the previous write, and the complete final state is correct. This resolves
the specific alias-ordering concern for these controls; it is not a proof for
all possible traces, clocks, compiler releases or real DDR timing.

The independent bus selftest passes delayed AW/W pairing, alias visibility,
stable IDs/data/responses under backpressure, a saturated sixteen-entry read
queue and one-service-per-cycle conservation. Unaligned reads, multi-beat
reads and partial writes are rejected for their declared reasons. Unsupported
port directions never supply request credit.

## Evidence And Reproduction

- [Complete results](grasu_ddr_rtl_results.json): all cases, source/header/tool/
  executable identities, fresh synthesis, event traces, states and resource logs.
- [Archive manifest](grasu_ddr_rtl_verification.json) and
  [raw archive](raw_grasu_ddr_rtl.tar.gz): 3,402 members, 8,038,547 bytes,
  SHA-256 `f44b3ad59cfb4120d998d147c43db7df8df4a78650b9471405c0a63e2aa374f5`.
- [Preservation and negative gates](grasu_ddr_rtl_preservation.json): all
  152 previously frozen code files, 2,437 protected evidence files, production
  plugin, accepted finite A4/B result and user patch remain unchanged. Nine
  mutated deliveries are rejected, including fabricated timing and omitted rows.
- [Implementation review guide](../../../implementation/grasu_regraph/original_grasu_ddr_rtl.md)
  and [package ownership](../../../../spine_cycle_sim/experiments/grasu_ddr_rtl/README.md).

The archive preserves three preflights and prior formal attempts v1/v2.
Preflight v2 incorrectly expected an unsupported port to accept and reject
a request; the corrected test checks withheld credit and uses an illegal
burst on a supported port. Formal v1 printed the expected rejection but XSim
then crashed during exit; it was not admitted. Formal v2 passed every gate.
Formal v3 moves version-query tool feedback into ignored experiment output;
all twelve cases' complete source/RTL observations remain exactly equal to v2.
The root directory no longer receives XSim `.pb` feedback files. The new
baseline-capture helper also passes preservation for 164 files, including all
152 original files, shared execution helpers and build lists.
Historical attempts were not silently repaired or substituted for accepted rows.

Run from the repository root, choosing unused baseline/output paths:

```bash
python3 scripts/run_original_grasu_ddr_rtl.py \
  --hls-tool /data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls \
  --simulator-bin /data/yxx/tools/xilinx/Vivado/2024.1/bin \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --capture-baseline \
  --baseline results/upstream_stage_controls/reproduce_ddr_baseline \
  --out results/upstream_stage_controls/reproduce_ddr
python3 -m unittest tests.test_original_grasu_ddr_rtl
```

Clean pinned upstream checkouts are prepared as described in the
[study guide](README.md). Add `--deliver-to` only for a new destination;
delivery refuses to overwrite accepted artifacts. It rechecks all raw rows,
tool/source/binary identities and complete state before packaging. Exit zero
alone is not admission: a completed state mismatch has an explicit rejected status.

The formal run has 74 bounded sequential steps, each limited to 4 GiB with a
16-GiB reserve. Peak per-process RSS is 580,596 KiB (about 567 MiB); minimum
available memory before a formal step is 119.04 GiB. The existing 14 C++ tests
and 172 focused Python tests pass. The full SST/FPGA matrices were not rerun:
their model bodies and frozen plugin were not changed in this control.

## Next G-Stage Gates

Build finite original search/BIPA/dispatch/cache/DDR composition using these
RTL ordering constraints, complete hot-cache load/store traffic and the existing
source/host oracles. Then admit a temporal workload, paper8/source16 distinction,
DDR/clock/event window and successful-update denominator before comparing an
original published G rate. Original R publication admission and measured host/C
composition remain separate tasks. Neither earlier A4/B agreement nor this DDR
control is evidence that all those stages are already validated.
