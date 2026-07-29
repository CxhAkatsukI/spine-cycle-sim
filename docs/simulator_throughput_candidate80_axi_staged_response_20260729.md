# Simulator throughput milestone 25: staged AXI response resolution

## Scope

The AXI master validates each ready backend response during `evaluate()`, but
previously repeated the request-mapping lookup, active-burst search, and parent
lookup during `commit()`. Candidate 80 retains the already-resolved mapping and
stable burst/parent pointers in staged state. Commit still reads the response
payload from the backend's committed response view, so the strict
evaluate-then-commit boundary remains unchanged.

This is a host implementation optimization. It does not change response
eligibility, AXI timing, burst completion, response ordering, FIFO capacity,
DRAMSim3 timing, traces, counters, modeled cycles, or architecture parameters.

## Controlled result

The frozen workload is `syn_spread_e512__residual_pagerank` from
`shared_comparison_candidate10_k1_multipart_v4_20260728.json`. An alternating
three-run A/B test pins native LTO simulator builds to CPU 100 and uses the same
Candidate 73 PGO DRAMSim3 library.

| System | Candidate 77 median host s | Candidate 80 median host s | Speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| GraSU+ReGraph | 22.765 | 21.963 | 1.037x | 15,310,428 |

The Candidate 77 times are 22.765, 22.835, and 22.578 seconds; the Candidate
80 times are 21.963, 21.871, and 22.180 seconds. The 1.037x median speedup is
stable across the interleaved samples. The cumulative publication-build
headline remains Candidate 73's 5.003x geometric-mean speedup until the final
source is retrained with a representative two-system PGO workload.

## Exactness gate

The complete Spine and normalized GraSU+ReGraph profile run passes the
fail-closed Candidate 24 comparator:

- both architecture result files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- cycles, requests, bytes, FIFO/AXI stalls, DRAM commands, traces, activity,
  and energy counters are unchanged.

The Candidate 80 native plugin SHA-256 is
`143b1f9c955a1f512cd428a504758fa0c8fcb957bf8aa47bc6e5e4c2c174f05a`.
Compact evidence is under
`docs/evidence/simulator_throughput_candidate80_axi_staged_response_20260729`.

## Validation

- shared-core and GraSU C++ tests: 2/2 CTest targets pass;
- Python tests: 586 pass, five expected skips;
- exact comparator: two result files and 26 DRAM JSON files pass; and
- `git diff --check`: clean.

## Next step

Profile active AXI response retirement after this change and remove any
remaining work proportional to all active bursts when only a small set of
bursts changed. Retrain two-system PGO only after that source milestone is
accepted.
