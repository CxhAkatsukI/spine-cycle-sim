# Simulator throughput milestone 2: shared core and memory bookkeeping

## Scope

This milestone optimizes host work in the shared scheduler, AXI model, and SST
memory bridge, plus quiescent ReGraph phases. It does not alter an architecture
profile, clock, FIFO depth, AXI limit, request, response, arbitration decision,
or DRAM command.

The changes are:

- dynamic readiness for the scheduler prepare phase;
- SST backend prepare/commit calls only when arrivals, submissions, response
  pops, or pending arbitration require work;
- ReGraph reader/gather/merger/apply/wrapper calls omitted only before start or
  after completion, with active stall cycles retained;
- O(1) AXI counts for issueable, streamed, and write-data bursts, avoiding a
  scan of already-issued bursts while waiting for HBM;
- a reusable active-slot issue array instead of a per-cycle hash table;
- registered HBM arbitration over channels with intents rather than all 32
  channels, with O(1) grant and intent ledgers;
- O(1) staged submission counts per HBM channel and initiator.

## Controlled A/B result

The cumulative candidate was compared against the frozen pre-optimization
baseline on the same residual PageRank probe and exact-idle SST/DRAMSim3 stack.

| System | Baseline host s | Candidate host s | Host speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 7.284 | 1.082x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 87.058 | 1.209x | 15,310,428 |

The two-system geometric-mean speedup is 1.144x. This is an intermediate
result, below the frozen 10x medium/large-suite target. The sampled evaluate
cost of the G+R degree AXI master fell from 2,840,544 ns in the baseline sample
to 1,663,875 ns in the issueable-burst candidate before the final arbiter
optimization. This identifies active AXI bookkeeping as a real host hotspot.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical;
- no observability field was added or removed.

Evidence is committed under
`docs/evidence/simulator_throughput_candidate5_shared_core_20260728`. Raw runs
remain outside Git:

- candidate: `/data/tmp/chuxiao/simulator_throughput_candidate5_active_arbiter_20260728`
- equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate5_active_arbiter_equivalence_20260728`

The candidate SST plugin SHA-256 was
`c70dcb591f571dc6187f483fa57c853b58b8e24864dc4124d0529e3095eb6722`.

Validation at this milestone: 585 Python tests passed with 5 expected skips;
both C++ test executables passed; `git diff --check` was clean.
