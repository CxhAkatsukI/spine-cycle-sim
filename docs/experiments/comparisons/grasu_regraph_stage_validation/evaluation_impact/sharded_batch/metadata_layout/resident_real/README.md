# Resident Chronological Multi-Shard G Check

## Predeclared Question

Does the both-table replica candidate preserve original prepared-shard G
performance across consecutive larger, timestamp-ordered batches and more
than one destination shard? This is a simulator-prediction diagnostic, not
published GraSU reproduction, actual HLS resource fit or board measurement.
No production model, paper or frozen figure package is changed.

The preceding [resident lifecycle](../lifecycle/README.md) checks correctness
on small synthetic batches. The [one-shard metadata study](../README.md)
owns the preceding 72-row performance diagnostic. Neither is overwritten.

## Matrix Frozen Before Timing

All three AU/SU/WK chronological inputs are reused with identical compact
IDs and first-contact records. Existing provenance verification checks source
hashes, timestamp/file order, excluded repeated contacts/self loops and every
input artifact. No new source selection or resampling is performed.

- Initial graph: first 8,192 distinct, non-self directed contacts.
- Reservation: the complete next 65,536 insertions, once before execution.
- Consecutive batches: first 4,096 insertions, empty batch, remaining 61,440
  insertions. The last batch starts with the first batch's updated PMA.
- Destination partition width: 8,192, giving two AU/SU shards and three WK
  shards. This deliberately exercises shard boundaries on bounded inputs;
  it is not the routed large-graph partition configuration.
- Arms: independent `original-prepared-shards`, `candidate-runtime-23`, and
  `runtime-both-copies`; latency assumptions 64/128 cycles at 200 MHz.
- Complete matrix: 18 executions, 54 batch observations. The empty batch is
  an identity check, not a throughput/speedup sample.

Original and candidate consume the same logical state, reserved layout and
physical edits. The original control reinitializes its independent prepared
shard model from each previously checked state; runtime arms retain the same
backend, allocations and physical PMA across batches. Updated shards execute
sequentially. All arms pay complete cache preload and acknowledged writeback
per touched shard. Union reservation and appended isolated-tail padding keep
edited segments hot and metadata fixed; cold-region and changed-reservation
behavior remain separate gates.

The replica arm retains originals and adds four full copies of both metadata
tables on legal existing channels `[3, 9, 15, 20]`. Allocation, bank spans,
logical initial upload and complete physical equality are checked. No extra
simultaneous masters, credits, hidden cache or timing multiplier is allowed.
Initialization bytes do not constitute measured host or DMA latency.

## Acceptance And Boundaries

Every declared row must pass independent edge-set/segment oracles, row and
binary-search work, full physical PMA/copy/padding equality, acknowledged
writes, complete request drain and byte conservation. All arms must have the
same full canonical state after every batch. Missing, duplicated or failed
rows cannot be dropped to claim a complete matrix.

The prediction retention test is absolute cycle difference at most 10% from
the original on **every nonempty batch** and on each sequence's total.
Slow rows stay in the result. Even a passing prediction test does not admit
production G, original-paper timing, host-inclusive timing or real hardware.
Reservation/allocation/replication, DMA, host launch/wait and ReGraph are
excluded on all arms; physical initialization/upload costs are separately
reported, not represented as free end-to-end work.

## Ownership And Safety

Common C++ batch oracles, resident allocation/execution and result writing
belong to `metadata_layout/lifecycle/`. Only real-input fixture preparation
and the thin executable live in `metadata_layout/resident_real/`. Python
provenance/counts, analysis and run/package entry points have separate owners
under the corresponding `resident_real/` package.

Source before extraction is frozen at `6f846b0` in
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-metadata-lifecycle-v1/pre-real-6f846b0.tar.gz`,
SHA-256 `862edaf12183487c18710f4c1f6b470e72633214ad32c4ed246a3649188bd0ee`.
The full preceding 12-row/36-batch lifecycle matrix must replay exactly after
shared-code extraction. Frozen libraries and every new source/input/binary
are hash-pinned by the runner.

Runs are serial, CPU-affined, with a 2-GiB address-space limit, 8-GiB reserve
and 600-second per-step timeout. Insufficient available memory means waiting
or a retained failure, never bypassing the gate. Larger queued HLS/R studies
retain their stricter gates.

## Results And Decision

All 18 declared executions and 54 batch observations pass correctness,
physical-state, independent work-count, resource and traffic checks. The
both-table copy candidate passes the 10% prediction test on every nonempty
batch and every sequence total. Maximum absolute nonempty-batch difference
is **0.7432%** (rounded upward). No timing coefficient, memory latency or
original-control implementation was adjusted to obtain this result.

| Case | Latency | Original last-batch cycles | Shared difference | Both-copy difference | Both-copy sequence difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 64 | 1,183,817 | +12.7955% | +0.7004% | +0.2453% |
| SU | 64 | 1,191,038 | +11.9062% | +0.3943% | +0.0500% |
| WK | 64 | 1,739,647 | +10.4652% | +0.6499% | +0.3587% |
| AU | 128 | 2,348,349 | +11.5617% | -0.3144% | -0.3983% |
| SU | 128 | 2,360,264 | +11.2965% | -0.6886% | -0.6385% |
| WK | 128 | 3,444,106 | +10.2033% | +0.2350% | +0.0959% |

Difference is `candidate cycles / original cycles - 1`; negative means
faster. The last batch is 61,440 insertions, not a separately reset 64K run.
First-batch both-copy differences are -0.7432% to -0.3466%. Empty batches
cost zero cycles and preserve complete state; they are never speedup samples.
Shared sequence totals alone are within 10%, but **all six shared last-batch
comparisons fail**. Averaging away these failures would reverse the declared
decision. The [full matrix](evidence/matrix.json) includes every batch and arm;
the [decision index](evidence/index.json) is independently recomputed in tests.

This extends the passing copy prediction to bounded chronological multi-shard
resident sequences. It does not establish production-baseline, publication,
host-inclusive or hardware timing agreement. All those admission flags remain
false, and no new Spine comparison or Figure 7--11 replacement is claimed.

## Storage And Execution Costs

| Case | Shards | Allocated bytes | Summed bank spans | Extra metadata bytes | Initial logical metadata upload |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 2 | 56,320,000 | 87,732,224 | 17,793,024 | 22,240,880 B |
| SU | 2 | 55,828,480 | 87,269,376 | 17,399,808 | 21,742,080 B |
| WK | 3 | 84,733,952 | 115,945,472 | 27,082,752 | 33,849,480 B |

These are copy-arm allocations, not only live graph payload. Added metadata
costs approximately 16.59--25.83 MiB, with 18/19/23 used graph banks for
AU/SU/WK. All regions are nonoverlapping and below the existing per-bank
limit; fixed-base alignment gaps count toward bank spans. Logical upload
excludes allocator padding and is a byte ledger, not measured transfer time.
Inter-batch metadata upload is zero **only for these fixed reservations**.
All nonempty touched shards pay complete cache preload and writeback, even
when their update counts differ substantially.

The successful matrix's 22 bounded steps took 559.2 seconds in total. Maximum
recorded process RSS was 1,121,156 KiB (1.07 GiB); minimum admission-time
available memory was 23.87 GiB. This is simulator/compilation wall time, not
accelerator latency. Every step retained the 2-GiB address-space limit,
8-GiB reserve, affinity and timeout. Larger queued jobs were not launched
by weakening their memory gates.

## Retained Failure And Exact Regression

The [failed first attempt](preflight/index.json) retains 16 valid observations
and both SU shared-arm failures; it admits zero complete-matrix rows. Its
assertion incorrectly required identical cycle counts across **different
physical allocations**: the resident sequence reserves maximum per-shard
update capacity once, whereas a fresh production wrapper allocates the
current batch's capacity. SU's first batch therefore places some metadata
on different banks. This was a validator error, not evidence of identical
hardware layouts or a reason to discard the slow shared arm.

The corrected check independently compares the wrapper with manual execution
under the same per-batch allocation, and resident execution with fresh replay
under the same fixed resident allocation. Each pair must match the complete
observation. Wrapper and resident must also match when their layouts coincide.
All 18 shared-arm batch checks, changed regions and paired cycles are retained
in stderr. Timed matrix rows still use fixed resident allocations; they were
not replaced with whichever allocation runs faster. The row-table geometry
validator also includes the ABI's final sentinel, `(vertices + 1) * 8` bytes.
Neither correction changes the timing model.

Source before the wrapper-check correction is archived at
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-resident-chronological-v1/pre-wrapper-attempt-v1.tar.gz`,
SHA-256 `c746350a243773ae30a2993609cd9bf0b52f08dadf9fbdc255d4773aef95d65d`.
The [first extraction replay](replay/index.json) and
[final shared-helper replay](replay_final/index.json) each preserve all 12
preceding lifecycle observations, cycles, counters, final state hashes and
all 36 intermediate batch hashes **exactly**. Paths and wall time are not
numerical-regression targets. Large canonical state files stay hash-indexed
outside Git; compact input slices and raw logs are portable in each capsule.

## Review And Reproduction

C++ `lifecycle/batches.hpp` owns physical-edit oracles, `residency.hpp` owns
fixed allocation/copy equality, `execution.hpp` owns finite execution, and
`run.hpp` owns sequence orchestration and serialization. Real-input owners
are `resident_real/fixture.hpp` and `wrapper.hpp`; `main.cpp` is a thin CLI.
Python `preparation.py`, `analysis.py`, `study.py` and `retained.py` separately
own provenance/work, acceptance, execution/packaging and failed evidence.
No production core, HLS implementation or SST plugin was changed.

Raw root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-resident-chronological-v1`.
`attempt-v2` is complete and `attempt-v1` is retained separately. Each matrix
pins source, libraries, compiler flags, executable, affinity and input hashes.
Packaging refuses modified pins; delivery tests verify archived hashes and
reconstruct independent counts without machine-local source datasets.
The 87 focused Python/runner/delivery tests pass, including exact old replay,
raw archive verification and refusal to hide a slow batch in sequence totals.
These checks do not constitute a new full production core/SST regression or
new FPGA verification; those numerical owners were not changed here.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.study run \
  --output /path/to/fresh-resident-real \
  --prepared /path/to/chronological-inputs \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.study package \
  --matrix /path/to/fresh-resident-real/results.json --output /path/to/fresh-evidence

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.study run \
  --output /path/to/fresh-lifecycle-replay \
  --core-build /path/to/cached-handoff/banked/compatibility/build/cpp

python3 -m unittest tests.test_grasu_resident_real tests.test_grasu_resident_real_delivery -v
```

## Remaining Admission Gates

1. Mixed hot/cold edits, broader occupancy and realistic routed 64K partition
   geometry; these inputs deliberately exercise 8K shard boundaries.
2. Changed reservations/rebalancing, explicit replica refresh and measured
   host allocation/preparation/upload costs; future-union knowledge is not
   available for an arbitrary stream of online updates.
3. Actual HLS binding, search/cache schedule, whole-G resource fit and board
   measurements. Legal channel allocation is not timing closure.
4. Original GraSU temporal workload conversion and source16 versus paper8;
   prepared source-model agreement is not publication reproduction.
5. R resource/publication controls, actual composed windows and host/seed
   timing, followed by an admitted common-state Spine comparison.
