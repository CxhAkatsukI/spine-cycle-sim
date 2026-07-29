# Simulator throughput milestone 24: latched ReGraph scheduling

## Scope

The normalized GraSU+ReGraph compute path had already made FIFO and worker
completion transitions event-driven, but seven components still exposed
dynamic scheduler guards. The scheduler therefore polled three evaluate guards
and up to seven commit guards on every simulated cycle, including long idle or
blocked intervals.

Candidate 77 uses the existing component latch interface for PageRank source
preparation, source HBM reading, PMA reading, merge, apply, HBM writeback, and
the ReGraph controller. Start and done transitions latch or clear evaluate
readiness. Each evaluate latches commit readiness only when it produced staged
state. Active phases still execute at the original cycle granularity, including
source-cache waits and all architectural stall accounting.

No accelerator cycle, FIFO operation, AXI request, HBM transaction, trace, or
counter is skipped.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. Three native-LTO
runs use the same Candidate 73 PGO DRAMSim3 library.

| System | Candidate 76 median host s | Candidate 77 median host s | Incremental speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| GraSU+ReGraph | 23.139 | 22.422 | 1.032x | 15,310,428 |

Candidate 77's individual times are 22.328, 22.422, and 22.778 seconds. This is
a scheduler host-runtime optimization, not an architectural performance
change. The cumulative publication-build headline remains Candidate 73's
5.003x geometric-mean result until the changed simulator source is retrained
with two-system PGO.

## Exactness gate

The complete two-system run passes the fail-closed Candidate 24 comparator:

- both architecture result files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, requests, bytes, FIFO/AXI stalls, DRAM commands, traces, activity,
  and energy counters are unchanged.

The Candidate 77 native plugin SHA-256 is
`49abd1b8cc487199e3b66263eef78f2548deab1351d0a45aaa1f4bd5773892f5`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate77_regraph_latched_scheduling_20260729`.

## Validation

- shared-core and GraSU C++ tests: 2/2 CTest targets pass;
- Python tests: 586 pass, five expected skips; and
- `git diff --check`: clean.

## Next step

Retrain native PGO on both frozen systems with Candidate 76 and 77 present,
then measure three exact repetitions against Candidate 73. Subsequent work
targets active-cycle component cost rather than inactive readiness polling.
