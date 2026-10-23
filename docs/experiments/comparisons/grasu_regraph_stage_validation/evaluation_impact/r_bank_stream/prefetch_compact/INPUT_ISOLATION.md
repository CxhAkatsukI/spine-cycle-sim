# Current Finite Input Isolation

## Decision

Simulator only. This diagnostic isolates the **same finite input reader and
compactor** as the latest complete candidate, without source loading, Scatter,
Gather, Apply or writeback. It does not pass complete-R retention. The latest
[complete comparison](WRAPPER_SCHEDULE.md) remains **1.084725 / 1.243611** times
A4 at memory latencies 64 / 128. Only latency 64 meets the +/-10% gate.
No numerical core, HLS, FPGA artifact, paper or figure is changed here.

The latest reader has three physical input masters per frontend, two directory
tiles, two 512-line PMA rings, three finite pipeline slots and whole-parent
refill. Data still comes from actual AXI responses. Both metadata and PMA
traffic are counted; empty slots are read before compaction. The fast sink
accepts one packet/cycle. A second sink accepts one every five cycles and
tests finite downstream backpressure. Neither sink is a complete R backend.

## Fixed Comparison

The frozen Amazon real-ID slice has 258,046 vertices, 1,450,899 weighted edges
and four destination shards. Input is the resident post-update PMA used by
the complete warm-state SSSP reference: old converged state, three source-0
weight decreases, 46 synchronous rounds. This diagnostic scans the input
**once**, without executing those rounds or including G, host preparation,
DMA or launch. The complete references retain those R convergence semantics.

All controls use registered MockMemoryBackend arbitration, latencies 64 / 128,
32 outstanding **64-byte beats per channel**, and at most one accepted beat
per channel/cycle. Each AXI master has 16 finite parents of at most 16 beats.
The current input uses twelve masters; the complete candidate uses sixteen
versus A4's thirteen, and three state copies versus four. This is not strict
resource equivalence, FPGA timing calibration or publication reproduction.

The declared matrix contains both latencies, both component-registration
orders, two historical reader controls and the current fast/throttled sinks:
**16 executions**, eight exact historical replays and eight exact
registration-order pairs. All pass independent weighted-CSR edge comparison,
slot/dummy/packet conservation and request/beat closure. Fresh harnesses pass
144 synthetic finite-input checks. The unchanged numerical core is reused
from a checked 37/37-test build; those tests were **not rerun** for this
harness-only diagnostic.

## Results

| One-scan endpoint, cycles | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Historical single-master reader | 424,166 | 432,565 |
| Historical dual-master reader | 292,040 | 452,891 |
| Current reader, fast sink | **184,004** | **362,046** |
| Current reader, period-five sink | 530,366 | 536,201 |

Every scan reads **38,696,960 bytes / 604,640 accepted 64-byte beats**, retains
all 1,450,899 live edges and emits 181,464 packets. Current readers issue
37,796 parent requests with either sink. Slowing the sink changes time and
publisher stalls, not physical traffic or results. Fast-sink worker endpoints
are `[184004, 159517, 102821, 65671]` at latency 64 and
`[362046, 314543, 203706, 130246]` at latency 128.

| Fast-sink observation | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Backend capacity-blocked observations | 15,695 | 1,092,927 |
| Failed submit/wait observations | 620,335 | 1,697,567 |
| Worker-0 selector waits | 3,420 | 180,994 |
| Worker-0 peak reserved PMA ring lines | 512 | 259 |

These are overlapping counters, **not additive or exclusive stage times**.
Fast-sink publication has no output stalls; the slower sink exercises
backpressure. Larger buffers alone cannot remove a backend credit limit.

### Source-Based Occupancy Estimate

Worker 0 reads 179,508 PMA segments. Its parity extents are below the 131,072
hot/cold threshold, so they occupy two active hot PMA banks, `pma0` and `pma2`;
the two cold banks have no segment reads. Runtime mapping places the active
banks in disjoint channel ranges. At latency 128, a channel with 32 in-flight
beats has a steady-state occupancy envelope of roughly `32/128` beat/cycle.
Two active channels therefore suggest about half a segment/cycle:

`179508 * 128 / (2 * 32) = 359016 cycles`, versus the observed 362,046.

At latency 64 the same estimate is 179,508 cycles, versus 184,004 observed.
This is a **steady-state estimate**, not a strict finite-scan lower bound,
measured channel trace, exclusive attribution or hardware result. Startup,
directory reads, registered handshakes and drain still exist. It supports
investigating physical PMA placement/service rather than merely enlarging
rings; it does not explain all complete-R overhead.

### Relation To Complete R

| Reference or conditional projection | Latency 64 | Latency 128 |
| --- | ---: | ---: |
| Complete latest R, executed | 11,828,118 | 19,699,546 |
| Complete A4, executed | 10,904,254 | 15,840,606 |
| 46 unchanged fast-input scans, **projection only** | 8,464,184 | 16,654,116 |
| Projected input / complete A4 | 0.776228 | 1.051356 |

The last two rows do not execute R and cannot replace its complete time.
They suggest that input restrictions matter at high latency, but the current
input estimate alone is below the 1.10 gate. Coupling, output tails and other
complete-path work must also be checked. No stage may be made free or hidden
behind another stage's improvement to admit the baseline.

## Next Gate

Any changed layout must be produced by G and consumed by R consistently,
pay for extra metadata, relocation, update and host costs, and retain finite
storage. A candidate-only credit increase or uncounted PMA remapping is not a
fix. A structural numerical change requires a new pre-edit freeze, fresh
core/SST regression, exact old-control replay and complete warm-state
convergence at both latencies and registration orders. The larger G,
integration/host and common-state Spine gates remain open. No such new
structural optimization is claimed by this diagnostic.

## Evidence And Safety

The [portable index](input_isolation.json) pins raw reports and source archives.
Independent verification rehashed 2,586 artifact pins, checked all 2,399 run
archive members and 2,397 pre-edit archive members, reparsed all sixteen raw
outputs and reproduced the analysis. All nineteen bounded steps exited zero.

The first attempt is retained as `FAILED_RETAINED`: admission failed with
zero build/run steps and zero observations. A fresh second attempt explicitly
uses the existing `cpu-only-cached-core-4g-v1` profile: 4-GiB hard / 3-GiB high,
zero swap, 8-GiB live reserve and 4-GiB background margin. Atomic admission
also reserves the full 16-GiB peer limit. Required memory was 34,359,738,368
bytes against 43,431,915,520 available. No peer limits were changed.

One worker on CPU 124 completed in 81.546 seconds; cgroup lifetime peak was
374,661,120 bytes, with zero swap. A live-memory watchdog and 600-second
per-step timeouts remained active. No FPGA tools were started.

## Reproduction

Use a fresh output path and unit name, outside any retained attempt. The
checked-core runner rejects changed numerical sources, compiler, libraries
or inputs. A new numerical change needs fresh core validation, not this cache.

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-current-input-isolation-new \
  -p MemoryMax=4G -p MemoryHigh=3G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=25min -p CPUAffinity=124 \
  -p WorkingDirectory=/home/chuxiao/spine-cycle-sim/spine-cycle-sim-fullgraph-evidence \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.input_isolation \
  --output /data/chuxiao/experiments/r_current_input_isolation_new/run \
  --before /data/chuxiao/experiments/r_current_input_isolation_20261022/before/freeze.json \
  --core-reference /data/chuxiao/experiments/r_prefetch_capacity_20261022/convergence-v2/results.json \
  --cpu 124 --memory-profile cpu-only-cached-core-4g-v1

python3 -m unittest tests.test_regraph_input_isolation \
  tests.test_regraph_prefetch_compact tests.test_regraph_reader_ports \
  tests.test_regraph_burst_refill -q
```
