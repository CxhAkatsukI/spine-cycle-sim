# Current K4 Diagnostic Results

This is a checkpoint, not completion of the revised comparison goal.

## Unchanged Hardware

All 27 runs pass the CPU oracle, result-byte equality, identical round/state
semantics and before/after input/bitstream hash checks. Each algorithm uses
three repetitions of baseline, trace-disabled and trace-enabled hosts.

| Algorithm | Baseline ms | Trace disabled ms | Trace enabled ms | Compute span ms | Adapter-after-gather union ms | Peak RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SSSP | 2063.606 | 2063.742 | 2062.583 | 2053.787 | 1735.511 | 603.9 |
| CC | 1038.353 | 1039.114 | 1039.646 | 1034.403 | 891.807 | 643.1 |
| ResPR | 1189.597 | 1189.555 | 1189.434 | 1169.608 | 0.366 | 709.4 |

These are current G+R measurements, not speedups against original A4.
Times are medians; result bytes and convergence counts, not noisy elapsed
time, are required to match exactly. CPU affinity is fixed to 120,121.

## What Was Found

The original source loop traverses all source rows even after sending the
stream's last packet. In the first traced SSSP round, shard 0 gather ends
about 81 ms after round enqueue, while its adapter ends around 512 ms.
This is consistent with the visible trailing-row walk. Next-shard adapter
launches wait for the previous adapter on the same frontend, so such tails
can delay subsequent shards. Four adapter and gather events overlap, while
mux/apply/HBM each have peak concurrency one, matching the intended topology.

An adapter-after-gather interval is not an exclusive AXI-stall measurement
and cannot simply be subtracted from total time to promise a speedup.
Existing counters still cannot partition all internal memory/backpressure
causes. The source code plus schedule motivate two separate candidates:
stop when the known final packet is sent, and prefetch eight contiguous rows.

## Candidate Gates

The original path remains the default. Both candidate flags are off unless
explicitly enabled. The candidate uses the existing aligned, monotonic row
ABI; no sparse-source index or update maintenance is assumed free.
Weighted, destination-only and unit-weight source tests each check 243
cases and 1,464 packets against the baseline, including first/last-source
placement, empty rows, 8-row tails, capacity clipping and cold/stale banks.

| HLS variant | LUT | FF | BRAM_18K | Estimated clock ns |
| --- | ---: | ---: | ---: | ---: |
| combined | 17170 | 12183 | 15 | 4.867 |
| original | 16952 | 11294 | 15 | 4.867 |
| prefetch | 17019 | 12150 | 15 | 4.867 |
| stop_after_last | 17062 | 11327 | 15 | 4.867 |

These are 150-MHz U55C Vitis 2024.1 adapter compile results, not routed
frequency or board performance. Continuous row reads are inferred for
both the original and prefetch paths. Prefetch changes the local scheduling;
automatic widening is refused due to the 8-byte alignment
type information. Do not claim a single 512-bit directory transaction or
an eightfold traffic reduction from this candidate.

## Remaining Work

Route and validate the selected candidate against the frozen bitstream;
only then synchronize/admit the simulator model and collect matched A4/K4
results. FullPR arithmetic/state/round matching is still a prerequisite
for the original-ReGraph comparison. The production FullPR host has three
rounds, whereas the existing original-A4 control has one PR iteration.

The old finite PMA+A4 74--791x prediction remains a different control.
No optimized FPGA speedup or publication ~10% match has been established.

## Evidence

[Machine-readable results](results.json), [raw file/hash index](raw_index.json),
[raw logs, canonical results and HLS reports](raw_diagnostic.tar.gz).
The full local run tree and XOs are under
`/data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010`.
Bitstream binaries are indexed by immutable SHA-256, not copied into Git.
