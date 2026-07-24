# GraSU/ReGraph Finite Stream Overlap

Date: 2026-07-25

## Scope

This milestone removes the phase barrier between ReGraph gather output and
partition Apply. It preserves the normalized GraSU/ReGraph memory topology and
executes each inter-kernel transfer through a registered, finite FIFO.

The HLS-to-simulator mapping is:

| HLS behavior | Simulator component |
| --- | --- |
| `accGather` output/clear, one 64-bit URAM row per cycle | `ReGraphGather` |
| `kernelLittleGSMerger`, pack eight 64-bit rows | `ReGraphMerger` |
| `Apply`, 512-bit property read and result stream | `ReGraphApply` |
| local `write_out`, HBM[30] | Apply-local `FixedAxiPort` |
| wrapper `write_out`, HBM[1] and HBM[3] | `ReGraphHbmWrapper` |

The three external AXIS links use the depth-16 values in the ReGraph
connectivity and normalized architecture profile. FIFO pushes become visible
on the next cycle, and a full downstream FIFO stalls its producer.

Apply retires bursts in increasing `write_idx` order even when SST-HBM returns
AXI requests out of order. This matches the ordered HLS loop and prevents a
later response from overtaking an earlier result on the output stream.

## Normalized SST Result

The same real `.slice` input/update pair and profile used by the previous
phase-barrier model gives:

```text
correctness mismatches:             0
phase-barrier cycles:          115012
finite-stream cycles:           98970
cycle reduction:                13.95%
backend requests:               32816 (unchanged)
compute read/write bytes: 525056 / 1572864 (unchanged)
backend max outstanding:            9 (previously 32)
backend submit stalls:             130 (previously 233932)
```

Across two supersteps, gather emits 65536 64-bit rows, the merger emits 8192
512-bit bursts, and Apply and the wrapper each consume exactly 8192 bursts.
All three finite FIFOs reach a maximum occupancy of one and do not stall on
this sparse workload. Apply and HBM writes keep pace with one merged burst
every eight gather-output cycles.

## Backpressure Evidence

`pma_compute_contention` reduces all three stream depths to one, limits Apply
to one request, limits the wrapper pipeline to one entry, and uses a one-entry
shared-HBM backend. It remains oracle-correct and records:

```text
gather output stalls:       1482
merger output stalls:       1366
apply output stalls:         416
wrapper pipeline stalls:    1904
aggregate AXIS push stalls: 2864
```

This verifies that contention propagates upstream through every modeled
boundary rather than being applied as a post-hoc latency term.

## Claim Boundary

The cycle result is structural execution-driven evidence, not measured FPGA
performance. The wrapper's 71-cycle pipeline value comes from the existing HLS
synthesis report, while memory completion timing comes from SST/DRAMSim3.

The exact six-stage gather RAW bypass and the source-cache request controller
remain simplified. GraSU PMA payloads also remain unit-weight only, and the
normalized PMA-native reader has not yet been synthesized.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
./build/cycle-core/cpp/grasu_cycle_tests
python3 scripts/run_sst_grasu_regraph.py \
  --out-dir results/grasu_regraph_sst_stream_overlap
```

The SST runner validates the row/burst ledgers, all FIFO occupancy bounds, the
three-copy state-write ledger, and the independent SSSP oracle before writing a
PASS manifest.
