# Simulator throughput milestone 26: no-response AXI commit fast path

## Scope

`AxiMaster::commit_backend_responses()` previously walked every active burst
whenever the AXI component committed any staged state, even when the backend
returned no response in that cycle. Because only a backend response can
increase `beats_completed`, no burst can newly become complete in such a
cycle. Candidate 81 returns immediately when the evaluated response set is
empty.

This removes host bookkeeping only. Every component cycle still executes, and
request generation, burst timing, response ordering, FIFO capacity, AXI/HBM
backpressure, traces, counters, and architecture parameters are unchanged.

## Controlled result

The frozen `syn_spread_e512__residual_pagerank` workload was run in alternating
three-sample A/B order on CPU 100. Both native LTO plugins use the Candidate 73
PGO DRAMSim3 library.

| System | Candidate 80 median host s | Candidate 81 median host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 2.383 | 2.371 | 1.005x | 4,778,979 |
| GraSU+ReGraph | 22.335 | 21.798 | 1.025x | 15,310,428 |
| Geometric mean | - | - | 1.015x | - |

All three Candidate 81 G+R samples are faster than all three Candidate 80
samples. Spine is effectively neutral but has no measured regression. The
cumulative publication-build headline remains Candidate 73's 5.003x result
until final two-system PGO retraining.

## Exactness gate

The complete Spine and normalized GraSU+ReGraph run passes the fail-closed
Candidate 24 comparator:

- both architecture result files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, requests, bytes, FIFO/AXI stalls, DRAM commands, traces, activity,
  and energy counters are unchanged.

The Candidate 81 native plugin SHA-256 is
`d7e4972403deb744a4811d80f06d7cc5b216181e928c650d9ebbd98c461f491a`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate81_axi_response_fastpath_20260729`.

## Validation

- shared-core and GraSU C++ tests: 2/2 CTest targets pass;
- Python tests: 586 pass, five expected skips;
- exact comparator: two result files and 26 DRAM JSON files pass; and
- `git diff --check`: clean.

## Next step

Re-profile Candidate 81 to select an active-cycle hotspot. Further AXI work
will target only bursts changed by responses instead of scanning all active
bursts after each response-bearing cycle, if profiling shows that scan remains
material.
