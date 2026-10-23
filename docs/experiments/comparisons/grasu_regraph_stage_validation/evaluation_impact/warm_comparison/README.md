# Exploratory Warm Spine Comparison

The user authorized this diagnostic before full baseline admission on 2026-10-23.
Its purpose is to ask whether the improved baseline changes the direction of
the Spine comparison. It is not a replacement evaluation or admission decision.
No FPGA, HLS, paper, or numerical-core change is part of this study.

The separate [warm-batch CPU preparation audit](HOST_PREPARATION.md) now
measures the common input's small-batch sorting/packing costs. These do not
change the diagnostic's direction, but omit active-state application, DMA,
launch/relaunch and readback; full host-inclusive timing remains unavailable.

## Fixed Scope

- Weighted SSSP only; a 96-vertex smoke followed by the existing Amazon
  real-topology slice (258,046 vertices, approximately 1.45 million edges).
- Both start from the independently verified, fully converged old graph.
  Three new root edges connect the farthest reachable, previously non-adjacent
  vertices; ties use ascending vertex ID and weights are 1, 2, 3.
  The selection rule is fixed before observing either system's performance.
- This is a new insertion batch, not the earlier R-only root-weight-decrease
  batch. Spine's endpoint coalescing does not establish identical semantics
  for weight replacement; this diagnostic uses their common supported subset.
- Both must reach the complete new-graph Dijkstra state, not one-hop completion.
  G+R additionally checks every round against its synchronous active oracle.
- G physically edits the PMA subsequently consumed by optimized R. No host
  PMA rematerialization is allowed at the handoff. This diagnostic uses finite
  parallel search and the native segment read/write path, not the full-cache
  candidate: the naturally sized shards do not meet that candidate's minimum
  16-MiB window. Padding to fit would artificially change downstream R's input.
  Each physical edited segment is charged; no metadata-copy/cache admission
  or original-G publication reproduction is inferred from this diagnostic.
  The routed reader's mandatory empty source-0 row is reserved in each shard
  before G starts; its scan traffic remains in R's measured work.
- R is the default-off `prefetch_gather_reuse` candidate; Spine follows the
  owner-FIFO SSSP profile, including reader control and fallback setup costs.
- Identical 150-MHz clocks and 32-channel MockMemoryBackend parameters,
  at fixed latency 64 and 128, acceptance interval 1, outstanding 32 and
  response capacity 32. This is a timing-sensitivity check, not DRAMSim3
  or new FPGA measurement. Port/storage differences remain explicit.
- Each latency has G+R normal/reverse registration and Spine fixed registration.
  The complete 12-execution matrix must close correctness and request ledgers.
- Old graph and old result preload are outside both device windows. G update,
  R propagation and Spine update-to-convergence are inside. Host CPU, launch,
  DMA and orchestration are excluded and cannot be inferred from simulator
  wall time. Spine receives the same three updates sorted by `(src,dst)`, as
  required by its resident ABI; that host sorting is outside this device window.
  Report the result as a device-cycle prediction only.

## Evidence And Safety

The runner validates the unchanged numerical core, compiler, libraries, frozen
input and all 37 passing core tests against the preceding Gather-reuse report.
It compiles only a new independent harness with Release flags and snapshots
all test sources. No new core regression is claimed when reusing those results.
Both the initial and final complete states, selected batch, cycles, traffic,
round records, physical handoff, logs, RSS and executable/source hashes are kept.

Use a fresh output directory for every attempt, retaining failures. The whole
job is contained at 6/5 GiB max/high, zero swap, with a 24-GiB live reserve,
atomic admission and an owned-process watchdog. A single worker is pinned to
one allowed CPU. Every child has a 4-GiB address-space cap and finite timeout.

```bash
systemd-run --user --wait --pipe --collect --unit=spine-warm-demo-rerun-v1 \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=8000 --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.study \
  --reference /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-v2/results.json \
  --output /data/chuxiao/experiments/warm_spine_comparison_rerun/attempt-v1 --cpu 124
```

No speedup is a passing threshold: correctness is mandatory, and either
performance direction is a valid finding. Report G, R and their combined
cycles separately; the earlier R/A4 near-match covered one different batch
and does not prove agreement across algorithms, workloads or all scenarios.

## Completed Results

### Same-Batch A4 Follow-Up (Predeclared)

The preceding R/A4 parity evidence used a different batch. The follow-up runs
original four-Little/zero-Big A4 on exactly the three inserted edges below,
using the same old converged vector, weights, vertex IDs and complete new
convergence. The matrix is smoke/Amazon x latency 64/128 x normal/reverse
registration (eight runs). The original author's `partitionGraph` and
`schedulePartitions` prepare the new compact input; DBG is deliberately not
repeated because the shared input IDs are already fixed. Captured task edge
multisets must exactly match the new logical graph before weighted encoding.
The original host's temporary PR properties validate only its layout and are
replaced by the common SSSP state before execution; no PR timing is measured.

No core, memory parameter, topology or timing multiplier changes are allowed.
R/A4 within 15% is an exploratory comparison, not a publication reproduction
or a gate permitting a mismatched warm state. All rows, including ratios
outside that interval, are retained. The candidate's 16-master/three-replica
layout and A4's 13-master/four-replica layout remain distinct. Host preparation
is outside both device windows, so this does not complete the host-time goal.
Run `warm_comparison.a4_study` with the original warm report, the Gather-reuse
core report, a verified clean upstream ReGraph source and a **fresh** output
under the same 6/5-GiB zero-swap, 24-GiB-reserve containment documented above.

Attempt v6 completes all twelve executions with identical common old/final
state hashes, independent full-vector Dijkstra agreement, drained request/beat
ledgers and exact G+R reverse-registration replay. Every case takes two rounds
to convergence. Speedup is G+R cycles divided by Spine cycles.

| Input | Memory latency | G cycles | R cycles | G+R cycles | Spine cycles | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 96 vertices / 95 old edges | 64 | 585 | 99,467 | 100,052 | 81,469 | 1.2281 |
| 96 vertices / 95 old edges | 128 | 1,097 | 105,527 | 106,624 | 147,606 | **0.7224** |
| Amazon, 258,046 vertices / 1,450,899 old edges | 64 | 585 | 482,435 | 483,020 | 90,749 | **5.3226** |
| Amazon, 258,046 vertices / 1,450,899 old edges | 128 | 1,097 | 826,100 | 827,197 | 156,817 | **5.2749** |

The Amazon root is 169,560. The three inserted `(src,dst,weight)` records are
`(169560,246188,1)`, `(169560,254443,2)` and `(169560,255983,3)`.
G+R accepts 87,879,920 read bytes and 6,291,656 write bytes; Spine accepts
10,240 read bytes and 3,716 write bytes. G's contribution is 240 read bytes
and 192 write bytes, already included in G+R. Counts are identical across the
two latency settings. The G/R event windows meet with zero handoff-cycle gap;
Spine reports zero host handoffs and three owner-control cycles.

**Finding:** Spine retains approximately 5.3-times predicted device-cycle
advantage on this real-topology, three-insertion case after the R improvements.
The small smoke at latency 128 instead favors G+R: Spine takes 1.3844 times
as many cycles. Both directions are retained. No performance threshold or
parameter was chosen after observing which system won.

This does **not** establish a final evaluation:

- Only weighted SSSP and one real graph slice are covered. The selected
  shortcut destinations produce a short, two-round propagation; there is no
  coverage of broad/deep propagation, CC, ResPR, FullPR or mixed/deletion work.
- Earlier R/A4 ratios, 0.953364 and 1.157245, describe a different 46-round
  root-weight-decrease batch. The subsequent
  [same-batch A4 check](SAME_BATCH_A4.md) gives R/A4 ratios 1.017585 / 1.199468
  on Amazon and approximately 1.480 on the smoke. Thus across-scenario
  agreement within 15% is **not** established; the 5.3-times Spine diagnostic
  must not be presented as if all its baseline parity gates had passed.
- The earlier A4 uses 13 masters/four state replicas versus the candidate's
  16 masters/three replicas. Strict resource equality remains unestablished.
- This naturally small-shard diagnostic uses direct segment RMW for G,
  rather than the separate full-cache G candidate. It verifies real physical
  integration but does not admit G's general timing or publication matching.
- Host time is excluded from both sides. No host-inclusive advantage or new
  hardware timing/calibration claim follows. Figures 7--11 remain unchanged.

The successful job's saved live-memory peak is 696,090,624 bytes (663.84 MiB),
zero swap, within its 6-GiB cgroup and 24-GiB reserve. The unchanged core's
preceding 37/37 tests are reused by hash; this job rebuilt only the harness.
Fresh Python checks pass: nine comparison/delivery checks, nine cached-core
checks and fifteen repository-organization checks. Document layout, generated
catalogs and whitespace checks also pass. No new SST or FPGA gate was run.

## Evidence And Review

- [Portable evidence index](evidence/index.json): all twelve command records,
  full output states (deduplicated by content), source snapshot, round/wait
  CSVs, safety records, and reports/logs from all five failed attempts.
- Raw successful directory:
  `/data/chuxiao/experiments/warm_spine_comparison_20261023/attempt-v6`.
  Original input, compiler and core libraries are hash-indexed there; these
  external artifacts are not redistributed in the compact capsule.
- Attempt v1 retained a harness compilation failure; v2 rejected undersized
  full-cache geometry. Attempts v3/v4 exposed the missing Spine batch sort;
  v5 rejected a missing pre-reserved source-0 row in Amazon's resident PMA.
  The fixes are harness/input preparation only; no numerical core or timing
  parameter was changed to obtain the v6 results.
- Input preparation/oracles: `cpp/tests/evaluation_impact/warm_comparison/input.hpp`.
  Execution owners: `integrated.hpp` and `spine.hpp` in that directory.
  Runner, analysis and portable packaging:
  `spine_cycle_sim/experiments/evaluation_impact/warm_comparison/`.

Verify the committed capsule without the original machine-local directories:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.warm_comparison.delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/evidence
python3 -m unittest discover -s tests -p 'test_warm_spine*.py' -v
```

For a new run use a fresh attempt path and unit name in the command above.
Package it into a **fresh** directory with the same delivery command plus
`--attempt /path/to/new-attempt`; the packager refuses changed pinned files.

The original capsule above remains unchanged. Read
[the same-batch A4 follow-up](SAME_BATCH_A4.md) for its separate reproduction,
eight-run comparison, resource limits and portable evidence package.
