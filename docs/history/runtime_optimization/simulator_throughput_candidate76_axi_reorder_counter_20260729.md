# Simulator throughput milestone 23: constant-time AXI reorder occupancy

## Scope

The AXI master previously recomputed streamed-read reorder occupancy by
walking every pending parent request after each active evaluate and commit.
This work was performed even on non-streaming ports, including the dominant
GraSU+ReGraph degree port. Candidate 76 replaces that scan with one exact
counter, incremented when a streamed beat enters the reorder map and
decremented when that beat is published.

This is a host implementation optimization. It does not change request
generation, burst splitting, response order, FIFO capacity, AXI timing,
DRAMSim3 timing, traces, counters, modeled cycles, or architecture parameters.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. An alternating
three-run A/B test uses native LTO simulator builds and the same Candidate 73
PGO DRAMSim3 library.

| System | Previous median host s | Candidate 76 median host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| GraSU+ReGraph | 23.627 | 23.139 | 1.021x | 15,310,428 |

The individual previous-build times are 23.581, 23.627, and 23.765 seconds;
the Candidate 76 times are 22.965, 23.139, and 23.808 seconds. The effect is
small but directionally consistent in the medians. It is retained because it
also removes an avoidable O(pending AXI parents) operation from every active
AXI cycle. The cumulative publication-build result remains Candidate 73's
5.003x geometric-mean speedup until PGO is retrained on the changed source.

## Exactness gate

The complete Spine and normalized GraSU+ReGraph profile run passes the
fail-closed Candidate 24 comparator:

- both architecture result files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, requests, bytes, FIFO/AXI stalls, traces, activity, and energy
  counters are unchanged.

The Candidate 76 native plugin SHA-256 is
`82f41be668a894f08ca700974a02bf90673c18f259cb9f9c2e1881c48dd523a8`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate76_axi_reorder_counter_20260729`.

## Validation

- shared-core and GraSU C++ tests: 2/2 CTest targets pass;
- Python tests: 586 pass, five expected skips; and
- `git diff --check`: clean.

## Next step

The next target is scheduler polling that remains outside component timing.
Candidate 76 will be included in the next two-system native+PGO training run
after the scheduler change is accepted, avoiding repeated profile rebuilds for
each small source optimization.
