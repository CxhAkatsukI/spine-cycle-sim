# Full-Burst Refill Experiment

## Reader Result

The sixteen-row reader matrix completed; all eight eager observations replay
the pre-edit checkpoint exactly. All 64 synthetic executions and 36 fresh
Release CTest targets passed. **The performance hypothesis did not pass:**
request grouping improves, but cycles do not materially improve. Do not
promote this policy to the integrated default or use it to redraw a Spine
comparison. The fresh SST plugin also exactly replays all five default
cases. The [evidence capsule](burst_refill.json) indexes the immutable raw
reports, source/build/input pins, observations and gate decisions.

| Memory latency | Masters per reader | Eager cycles | Full-burst cycles | Cycle reduction | Eager parents | Full-burst parents |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 1 | 424,166 | 424,225 | -0.014% | 44,268 | 37,796 |
| 128 | 1 | 432,565 | 432,818 | -0.058% | 42,050 | 37,796 |
| 64 | 2 | 292,040 | 290,775 | 0.433% | 224,669 | 37,796 |
| 128 | 2 | 452,891 | 463,778 | -2.404% | 100,040 | 37,796 |

Both registration orders agree exactly. Every execution still reads
38,696,960 physical bytes (604,640 beats), emits 1,450,899 weighted live
edges in 181,464 packets, and preserves each shard's physical slots and
dummy counts. The full-burst policy issues 29,728 PMA parents, only seven
of which are short physical-bank tails across all four readers. The other
8,068 parents fetch extent/directory information. Those reads were not
removed or treated as free.

| Memory latency | Masters per reader | Reader-only cycles for 46 scans | Unchanged complete A4 cycles | Reader floor / complete A4 |
| --- | ---: | ---: | ---: | ---: |
| 64 | 1 | 19,514,350 | 10,904,254 | 1.790 |
| 128 | 1 | 19,909,628 | 15,840,606 | 1.257 |
| 64 | 2 | 13,375,650 | 10,904,254 | 1.227 |
| 128 | 2 | 21,333,788 | 15,840,606 | 1.347 |

These are conditional reader-only floors, not measured complete-R runs.
All exceed the 1.10 target before computation. The last complete candidate
therefore remains the [source-loading study](SOURCE_LOADING.md), at
2.519 / 2.150 times strong A4 cycles. This checkpoint has no new complete-R
or G+R/Spine convergence result.

## Interpretation

Short-parent fragmentation is real but does not explain most remaining
time in this finite model. For the dual-port latency-128 case, fewer parents
do not reduce shared capacity-blocked cycles (997,938 eager versus 1,005,562
full-burst). Worker 0 still holds 848,130 of 1,450,899 live edges; its selector
wait count increases from 250,916 to 261,804. These are overlapping counters,
not exclusive causal stage times.

The next hypothesis is the depth-two reader/publisher pipeline: a slot that
retires this cycle is not available to new work until the next cycle. It
needs an isolated sustained-throughput and backpressure control before any
change. No memory latency, original-A4 configuration, padding requirement or
timing coefficient was changed in this experiment. A deeper buffer would be
an explicit architecture change, not a retroactive correction to old results.

## Preregistered Question

Simulator only. The previous [reader-port diagnostic](READER_PORTS.md)
improved the latency-64 reader but regressed at latency 128. It issued many
small parents when only a few ring entries were free. Does waiting until a
whole parent fits reduce fragmentation without changing the physical PMA,
weighted output, memory latency or finite storage? No FPGA build or paper
change is part of this experiment.

This is a reader diagnostic, **not complete-R performance retention**.
Even a passing reader-only floor does not establish the integrated result.

## Frozen Before State

The pre-edit checkpoint is commit `eb3eb1c52b133164505e3c59f84ce1e2d7e8d383`.
The local immutable freeze is
`/data/chuxiao/experiments/r_full_burst_20261022/before/freeze.json`;
its source archive SHA-256 is
`d3f4b87ee6755ca8727180ccf5dd07c687a49b980f41acaff08bf158194bf1de`.
It includes the previous reader and complete-convergence reference identities.

## Proposed Change And Gates

Default-off `RefillPolicy::kFullBurst` waits for space for sixteen 64-byte
beats, except a physical bank tail. The existing two 256-line rings per
frontend, directory tile, parent limits, modeled issue-to-use delay,
registered arbitration, backend latency and sink remain unchanged. The
default eager refill and optional second physical master remain separate
controls; extra masters are not described as a free scheduling change.

The frozen Amazon real-ID slice has 258,046 vertices, 1,450,899 weighted
edges and four destination shards. Its post-update PMA is resident. The
window is one scan through drained weighted-packet sinks, excluding G,
ReGraph computation, host preparation, DMA and orchestration.

1. Fresh Release build and all core CTest cases.
2. Sixty-four synthetic executions: sixteen old, sixteen dual-port and
   thirty-two full-burst; latency 64/128, both registration orders,
   fast/throttled sink and live/all-dummy data. Exercise bank boundaries,
   ring wrap, directory tiles and source-cache windows.
3. Sixteen real executions: both latencies, orders, one/two physical
   masters per frontend and eager/full-burst refill. All eight eager rows
   must exactly reproduce the frozen reader checkpoint.
4. Every weighted edge must match independent CSR; TLAST, packets, physical
   bytes, per-shard slots and dummy counts must close. No cache or padding
   reads can disappear. Full-burst PMA short parents are limited to four
   physical bank tails per frontend.
5. Inspect parents, beat counts, shared transport waits and cycles. Expect
   fewer parent requests; speedup is a hypothesis, not an admission gate.
   A 46-scan reader floor above 1.10 times unchanged strong A4 rejects the
   proposed complete-R performance target. A floor below it is necessary
   but not sufficient. Original A4 is not weakened or refitted.
6. Fresh SST software plugin and all five default exact replay cases.
   This is software compatibility, not FPGA timing calibration.
7. Before any integration admission, replay all sixteen prior complete-R
   executions and test the new integrated candidate to convergence. This
   diagnostic alone does not satisfy that gate or authorize a Spine claim.

## Runtime And Reproduction

Unique output directory, one pinned CPU, 6-GiB hard/5-GiB high memory limit,
zero swap, live watchdog, 24-GiB reserve and bounded per-step timeouts.
All source, compiler, inputs, reference and executable identities are pinned.
The final watchdog samples record peaks of 909,529,088 bytes for the core
campaign and 1,046,294,528 bytes for SST, with zero swap. Service runtimes
were 775.931 and 509.513 seconds. Independent post-run verification checked
2,384 core pins, 2,745 SST pins and fifteen frozen artifact/external records
without a mismatch.

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-full-burst-v1 \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=60min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.reader_ports \
  --output /data/chuxiao/experiments/r_full_burst_20261022/diagnostic-v1 \
  --before /data/chuxiao/experiments/r_bank_stream_comparison_20261022/prefetch-compact-v2/results.json \
  --a4-reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --full-burst-reference /data/chuxiao/experiments/r_dual_reader_20261022/diagnostic-v2/results.json \
  --cpu 124
```

The separate default-compatibility command builds software, not FPGA logic:

```sh
systemd-run --user --wait --pipe --collect --unit=spine-r-full-burst-sst-v1 \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=45min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.software_compatibility \
  --output /data/chuxiao/experiments/r_full_burst_20261022/sst-v1 \
  --core-result /data/chuxiao/experiments/r_full_burst_20261022/diagnostic-v1/results.json \
  --baseline /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1/legacy_final
```

All five default SST cases match correctness, cycles, counters and result
identities. The sixteen previous complete-R executions were **not rerun at
this checkpoint**; that integration gate stays open. Core, reader and default
SST passes are not a substitute for it. No production default, paper or
figure handoff was changed.

Status at preregistration was not yet run. The completed reader result above
does not overwrite the older checkpoint or satisfy the complete-R gate.
