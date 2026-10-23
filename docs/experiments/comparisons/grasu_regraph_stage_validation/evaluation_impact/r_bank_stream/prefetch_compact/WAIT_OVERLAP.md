# Passive First-Round Wait Overlap

## Question And Boundary

Simulator only. The [complete capacity experiment](PREFETCH_CAPACITY.md)
retains correctness but fails the overall performance gate: candidate/A4
cycles are 1.08514 / 1.24316 at memory latencies 64 / 128. Increasing finite
PMA buffering reduces complete cycles by less than 0.34%. This diagnostic
asks which existing waits occur together before selecting another explicit
architecture change. It changes neither memory service nor timing parameters.

Replay the first round of the same frozen resident post-update Amazon input:
258,046 real-ID vertices, 1,450,899 weighted edges, old converged SSSP state
and three source-0 weight decreases. Both the 256-line and 512-line candidates
run at both latencies, both component registration orders, and with sampling
disabled/enabled: sixteen executions. The independent CSR oracle checks the
complete first-round state and active count. **This is one round, not a new
measurement of all 46 rounds or a new Spine comparison.**

## Observation Contract

After each scheduler step and completion update, record the changes in six
existing backend counters and the union across four frontends of two Scatter
counters. A bit is set only when that counter increases on that cycle. Require
each selected component counter to be monotonic and increase by at most one.

| Bit | Observation |
| --- | --- |
| 0 | Apply output blocked |
| 1 | Apply read window full with available input, from the existing clocked observer |
| 2 | Apply pipeline capacity blocked |
| 3 | Apply write window blocked |
| 4 | Replica writeback pipeline capacity blocked |
| 5 | Replica writeback write window/request queue blocked |
| 6 | At least one Scatter frontend output blocked |
| 7 | At least one Scatter frontend waiting for an input edge packet |

The 256 possible masks are mutually exclusive. Their counts must sum to the
executed cycles. Marginal backend counts must exactly equal the existing
post-run CSV export. Frontend bits are unions, not sums of four workers.
Mask zero means none of these selected counters increased, not that the
whole machine was idle. A counter can also be silent while its component is
not evaluated; this diagnostic does not replace it with an inferred predicate.

Gather and Merger are deliberately absent: their implementations can backfill
suspended waits in bulk when a guarded component wakes. Their per-step
counter deltas therefore cannot locate those waits in time. The existing
Apply read-window field is suitable because it already comes from a separate
per-cycle observer rather than that component's lazy accumulated counter.

Joint counts describe simultaneous observations, **not exclusive stage times,
causal attribution, or cycles recoverable by an optimization**. They cannot
justify removing pipeline latency or memory requests. Any subsequent scheduling
change must have its own explicit resources, correctness and complete-R gates.

## Replay Gates

- Sampling off/on must produce identical cycles, active count, physical traffic,
  complete primary and replica state files, and every existing progress CSV.
- All sixteen executions must exactly match their frozen complete-run first
  round's active count, cycle count and completion endpoints.
- Forward/reverse registration must produce identical outputs and histograms.
- Packet, live/dummy lane, physical-byte, parent/completion, beat and state-copy
  ledgers must close, with no outstanding backend request.
- Pin all source, compiler, linked library, input, reference and output identities
  before/after execution. Use a freshly compiled diagnostic linked to the
  unchanged, previously tested core; no production timing source is changed.

## Code Owners

| Owner | Responsibility |
| --- | --- |
| `cpp/tests/evaluation_impact/wait_overlap/round_probe.cpp` | Thin one-round runner, independent oracle and physical conservation |
| `cpp/tests/evaluation_impact/wait_overlap/histogram.hpp` | Passive bounded mask accumulator; no execution writes |
| `spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/wait_overlap.py` | Pinned, memory-contained sixteen-execution replay |
| `spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/wait_overlap_analysis.py` | Histogram closure, marginals and joint observations |
| `tests/test_regraph_wait_overlap.py` | Rejection and non-additive interpretation tests |

## Execution Status

**Passive replay passes; complete-R performance admission still fails.** All
sixteen executions finish correctly. Eight observation-off/on pairs have
identical cycles, traffic, state and existing progress files. Every execution
matches its frozen complete-run first round; registration order also leaves
the histogram unchanged. Source, library, compiler, input and output pins
remain unchanged. See the [compact evidence index](wait_overlap.json).

For the 512-line candidate, the first-round observations are:

| Observation | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Complete first round, cycles | 257,232 | 428,095 |
| At least one of the six backend wait counters increases | 0 | 141,292 |
| Apply read-window wait | 0 | 113,606 |
| Replica write-window/request-queue wait | 0 | 96,885 |
| Apply output wait | 0 | 30,625 |
| Apply output and replica write-window wait on the same cycle | 0 | 27,822 |
| At least one frontend waits for an edge packet | 166,214 | 339,939 |

At latency 128, the observed Apply read wait covers 26.54% of first-round
cycles and the replica write wait covers 22.63%. Of the Apply output-wait
observations, 90.85% coincide with replica write-window waits. These observations
support investigating backend issue/retirement and replica backpressure in
addition to input refill. They do **not** prove how many cycles either change
would save: waits overlap with one another and with frontend waits. Frontend
edge-wait counters alone cannot identify a memory or metadata bottleneck.

At latency 64 none of the six sampled backend counters increases, so removing
those observed waits cannot explain that configuration's remaining difference.
This does not prove the backend is free or every frontend wait is causal.
The new diagnostic narrows the next control; it is not an optimization and
changes no production model. The complete 46-round comparison remains
1.08514 / 1.24316 times A4 cycles. No new Spine comparison is admitted.

Raw attempts live under
`/data/chuxiao/experiments/r_prefetch_capacity_20261022/`:

- `wait-overlap-v1/` retains a diagnostic compilation failure before numerical
  execution. A test helper accepted `const char*`, while the diagnostic passed
  a constructed string; an explicit exception fixes the harness only.
- `wait-overlap-v2/` is the passing diagnostic, with a frozen source archive,
  compiler invocation, raw outputs and admission record. Its owned CPU-only
  service reserves 6 GiB hard / 5 GiB
  high, zero swap, one worker on CPU 124, a 24-GiB live reserve and an 8-GiB
  background budget. Admission requires at least 38 GiB plus bounded peers.
  It initially waited for admission, then completed the fresh probe build and
  all sixteen rows. Service lifetime was 11 minutes 15.496 seconds including
  admission waiting; CPU time was 89.271 seconds and peak owned memory was
  approximately 327.8 MiB. The software runtime is not simulated device time.

The diagnostic links the unchanged libraries from the previously passing
37-target core campaign. It does not claim a fresh whole-core/SST rebuild or
any FPGA calibration. The complete ReGraph Python test discovery passes
136 tests, including the new histogram closure/rejection checks.

## Reproduction

Use a new output directory and service name from the repository root:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-wait-overlap-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=20min -p CPUAffinity=124 \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.wait_overlap \
  --output /data/chuxiao/experiments/r_prefetch_capacity_20261022/wait-overlap-NEW \
  --reference /data/chuxiao/experiments/r_prefetch_capacity_20261022/convergence-v2/results.json \
  --cpu 124 --admission-wait-seconds 600

python3 -m unittest tests.test_regraph_wait_overlap -q
```
