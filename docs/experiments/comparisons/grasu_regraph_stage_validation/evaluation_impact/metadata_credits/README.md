# G Metadata Buffer Controls

## Question And Scope

Can explicitly increasing metadata buffering reduce the remaining search
gap, without increasing physical bank capacity or changing timing assumptions?
This study follows the [read-only diagnostic checkpoint](../search_diagnostics/README.md)
and the [overall admission plan](../PLAN.md). It is not a routed implementation
or a reproduction of published GraSU performance.

All 190 executions pass state, work, traffic and resource checks. All 114
preceding observations, including their read-only diagnostics, replay exactly.
Both new arms pass the complete nonempty-input 10% prediction gates in both
directions. Production, publication and hardware timing admission remain open.

The [evidence index](evidence/index.json) contains the complete matrix,
preceding diagnostic report and indexed raw logs/diagnostic snapshots. These
are model predictions under the declared assumptions, not measured FPGA time.

## Predeclared Controls

All nineteen prior inputs, both 64/128-cycle memory assumptions and all three
diagnostic arms are retained. Two new arms give 190 executions in total:

| Arm | Search contexts/CU | Metadata masters/CU | Parent/burst/reorder slots/master |
| --- | ---: | ---: | ---: |
| Forwarded original | 64 | 8 | 16 |
| Cached, 16 contexts | 16 | 1 | 16 |
| Cached, 64 contexts | 64 | 1 | 16 |
| Cached, 64 contexts, M32 | 64 | 1 | 32 |
| Cached, 64 contexts, M64 | 64 | 1 | 64 |

The new arms also increase that master's request and response FIFO depths to
32/64. These are real buffering/resource changes, not free concurrency. Other
AXI masters retain sixteen parent/burst/reorder slots. There are still four
physical banks with 32 backend credits each. Per-master address, issue and
response bandwidth remains one per cycle. Cache size, II=3, latency=7,
forwarding, clock, PMA layout, ordered updates and final-drain boundary are
unchanged. More parent slots do not imply more physical-bank bandwidth.

All arms start from the same resident full-word PMA. Timing includes preload,
updates, writeback and all acknowledgements/drain; host preparation, DMA,
launch and graph propagation are excluded symmetrically. These are simulator
cycle predictions at 200 MHz, not FPGA measurements. Original and candidate
metadata master counts differ, so this is not a strict equal-resource claim.

## Ownership And Checks

`GraSuNativeConfig::compact_metadata_credits` is default zero, inheriting
existing AXI budgets. Only the explicit compact parallel-search experiment
accepts 16/32/64 overrides. Only its row/binary shared master gets those
buffers. No SST profile selects the new controls.

Configuration and port construction remain in `cpp/src/grasu.cpp`; the
common-G execution helper names the arms. Preparation, execution declaration,
analysis and delivery have a single owner under
`spine_cycle_sim/experiments/evaluation_impact/common_g/metadata_credits/`.
They reuse the shared bounded runner and packager.

Analysis requires all 190 unique declared observations, exact replay of all
114 previous state/time/work/traffic/diagnostic rows, conserved requests and
beats, unchanged physical traffic for new arms, complete PMA equality and the
declared per-port credits. The 10% gates use every nonempty input at both
latencies. A failed row cannot be removed to pass the gate. Even passing
these prediction gates does not admit production HLS or publication timing.

## Results And Interpretation

The table gives candidate cycles divided by the forwarded original, over all
eighteen nonempty inputs in each latency setting. Empty-input controls are
retained in the matrix but excluded from the performance gates.

| Memory latency | M32 range | M64 range |
| --- | ---: | ---: |
| 64 cycles | 0.981995--1.010968 | 0.980439--1.000256 |
| 128 cycles | 0.991411--1.005316 | 0.990422--1.000217 |

For the mixed 65,536-update input:

| Memory latency | Original | Cached 64 contexts, M16 | M32 | M64 |
| --- | ---: | ---: | ---: | ---: |
| 64 cycles | 1,206,069 | 1,870,537 | 1,216,555 | 1,199,004 |
| 128 cycles | 2,384,885 | 3,635,913 | 2,397,420 | 2,379,001 |

Thus explicitly buffering more metadata requests removes the earlier
52--55% large-batch deficit in this single-window model. The same correction
also passes the declared same-key and hot-only cases, not just a selected
mixed batch. No latency, cache-II or multiplicative timing coefficient was
changed. Complete final PMA, work and per-port traffic are unchanged relative
to the M16 candidate. Added buffers affect overlap, not the amount of work.

M32 already passes the declared target; M64 is retained as a sensitivity
control, not a reason to require the larger budget in hardware. The original
still has eight metadata masters per CU, versus one on these candidates.
Neither similarity in cycles nor fewer logical masters proves equal physical
resources. HLS must account for the context table, buffering, arbitration,
cache storage, clock and actual memory interfaces before promotion.

## Regression Evidence

The [verification capsule](verification/index.json) indexes the pre-edit
source freeze, fresh Release build, compiler configuration and raw bounded
test logs. All 31 CTest targets and 100 focused Python tests pass. A freshly
built SST plugin passes discovery and both default-path smokes; parsed
memory/native result JSON matches the preceding diagnostic checkpoint exactly.
These are default-path regressions, not new-candidate SST timing calibration.

The historical frozen-identity suites still fail 30 subassertions across
sixteen tests. Their mismatched path multiset is unchanged from the preceding
checkpoint; no additional path drift is introduced. Frozen manifests are not
rewritten and those suites are not reported green. The capsule retains their
failure logs alongside the passing regressions.

Maximum observed matrix process RSS is 341,716 KiB; fresh core build and SST
build peaks are 700,496 and 1,020,524 KiB respectively. These are maximum
individual-process RSS, not simultaneous process-tree sums. Build and matrix
execution remain serial within their own bounded jobs.

## Reproduction

```bash
cmake -S . -B /path/to/fresh-core -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build /path/to/fresh-core -j1
ctest --test-dir /path/to/fresh-core --output-on-failure -j1

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_credits.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/frozen-114-row-diagnostics/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_credits.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/frozen-114-row-diagnostics/results.json

python3 -m unittest tests.test_grasu_metadata_credits -v

make -C cpp/sst -j1 BUILD_DIR=/path/to/fresh-sst
python3 scripts/run_sst_memory_smoke.py --no-build \
  --lib-dir /path/to/fresh-sst --out-dir /path/to/memory-smoke \
  --channels 4 --requests 64
python3 scripts/run_sst_grasu_regraph_native.py --no-build \
  --lib-dir /path/to/fresh-sst --out-dir /path/to/native-smoke \
  --max-cycles 1000000
```

Frozen pre-edit sources and runtime outputs are under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-metadata-credits-v1/`.
Builds and matrix runs are serial with bounded timeouts, a 1-GiB address-space
limit and an 8-GiB admission reserve. The fresh SST build has its separately
recorded 2-GiB limit. Heavy HLS/routing queue thresholds are unchanged.

## Remaining Gates

Do not promote a model-only buffer change into the routed baseline. Integrated
HLS schedules, finite FIFO implementation and whole-G storage/clock fit need
evidence first. The original reference's complete cache comparison is still
queued. Published timing reproduction, broader temporal inputs, G-to-adapter/R
composition, host windows and the new Spine comparison remain separate gates.
No paper or frozen figure package is changed by this study.
