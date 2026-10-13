# Finite Search Cycle Model

## Scope

This is a default-off cycle-engine counterpart to the
[isolated search HLS candidate](../README.md). It keeps the previous flat
64-context/M32 path unchanged and explicitly adds its two arbitration levels,
response routing, bounded lane credits, ordered merge and termination/drain.
Neither this prediction nor similar total cycles establish HLS/RTL timing,
full-G resource fit or original-publication performance equivalence.

## Ownership

| Owner | Responsibility |
| --- | --- |
| `cpp/src/grasu_update/finite_search.cpp` | Factory, wiring, two-phase execution and final channel conservation |
| `cpp/src/grasu_update/finite_search/network.hpp` | Bounded state and channel geometry |
| `cpp/src/grasu_update/finite_search/workers.cpp` | Update input, lane credits, dependent searches and ordered output |
| `cpp/src/grasu_update/finite_search/transport.cpp` | 8x8 request arbitration, metadata AXI and response scatter |
| `spine_cycle_sim/experiments/evaluation_impact/common_g/finite_search/` | Complete-matrix preparation, prediction analysis and delivery |

`GraSuNativeConfig::compact_finite_search` requires the existing explicit
parallel-search flag, 64 contexts and M32 metadata buffering. It remains
false by default; no SST production profile enables it. The core and SST build
lists both include its separate implementation. Source edits are in an isolated
worktree so the already queued experiments' source pins remain unchanged.

All 339 HLS-declared channels are strict registered FIFOs. Ordinary depths are
two; the central request and response depths are 32. Their declared packed token
storage is 38,608 bits/CU. Simulator objects carry decoded semantic fields for
checking, not literal packed RTL registers; their C++ object sizes are not an
FPGA area estimate. Context state, AXI buffering and implementation overhead
are additional resources, as in the HLS study.

## Timing Assumptions

Each transport stage can transfer at most one token per cycle and every FIFO
crossing takes at least one registered cycle. Eight group arbiters/scatterers
operate concurrently; the central arbiter/scatterer each transfer one token.
Workers issue a dependent row or binary request, wait for its response, then
advance the binary search. Lane credits prevent more than one unreleased update
per context. Output order is identical to input order. End tokens and complete
internal drain are included in search completion.

These are explicit **II=1, one-register stage assumptions**, not synthesized
stage schedules. The two-level selection is not free, but this model also does
not know whether HLS implements extra stages or a worse II. The queued isolated
RTL/clock test must resolve that question before promotion.

Updates and metadata allow up to 16 and 32 pending requests respectively;
physical banks, AXI bandwidth, cache timing and cache forwarding are unchanged.
AXI arrivals may be out of order, but HLS loop consumption is modeled in issue
order. Explicit 16-word update and 32-word metadata response windows hold
arrivals until publication, which takes a registered edge and retains the
request's credit while blocked. These windows add 3,120 payload/valid bits/CU;
metadata lane tags add 192 bits/CU. These are declared logical storage minima,
not a synthesized AXI-adapter area estimate or part of the 339 stream channels.
Duplicate, unowned and malformed responses fail closed. A first smoke rejected
valid reordered returns; its logs are retained rather than hiding that failed
attempt or constraining memory service to make the candidate pass.
Invalid source rows, malformed responses and the reserved all-ones HLS sentinel
are rejected. Full-word, single-destination-window restrictions remain.

## Required Evidence

The fixed scope is nineteen inputs, two memory latencies, five unchanged arms
plus `cached_hot64_m32_finite`: 228 executions. All 190 old observations must
replay exactly, including cycles, full-state hashes, work, traffic and read-only
diagnostics. All 38 new observations must conserve the same complete PMA state,
search work and per-port traffic/resources as flat M32. Ratios to the forwarded
source-derived original use every nonempty input, not selected passing rows.
Both a slower-than-10% failure and an unexpectedly faster-than-10% result are
retained. Completing the matrix does not automatically pass either gate.

Focused C++ tests cover zero and lane-boundary counts, mixed insert/delete
weights, exact binary-search heads, paused output, registration-order
independence, every channel's conservation/drain and invalid geometry. Fresh
default core and SST regressions are required separately. The pre-edit freeze
preserves source, compiler, reference reports and external input/binary pins.

## Results

The complete **228/228** matrix passes. All **190** preceding observations
replay exactly, including full state, cycles, work, traffic and diagnostics.
All **38** finite-network observations match flat M32's complete PMA state,
work and per-port traffic/resources. Both declared performance checks pass on
all 36 nonempty new observations; the two empty controls remain in the report.

| Memory-latency assumption | Finite G / forwarded original G, minimum | Maximum | Worst case |
| --- | ---: | ---: | --- |
| 64 cycles | 0.984045 | 1.045460 | 65,536-edit dispersed batch |
| 128 cycles | 0.992395 | 1.021739 | 65,536-edit dispersed batch |

Thus the largest observed slowdown is **4.55%**, not an inherited flat-model
2% claim. The finite network adds up to 3.64% over flat M32 at latency 64 and
1.64% at latency 128. Small batches can have identical whole-G cycles because
cache preload is longer than search; this is not a claim of zero search-stage
cost. Nothing changes the fixed physical-bank service, cache schedule or
forwarded original. No predicted cycles were rescaled.

Fresh Release core regressions pass **31/31 CTest targets**. The initial focused
Python suite passes **95 tests**. A fresh SST build and all three default checks
pass; the two default numerical smoke outputs exactly match the predecessor.
These default checks establish noninterference, **not candidate SST calibration**.
The first invalid root build target and the first reordered-response failure
are both retained with their nonzero exit codes.
The [post-package focused check](verification/final_checks.json) passes **98
tests**, including rejection of unsafe verification bounds and offline integrity
checks of both delivered capsules; its separate logs preserve that later scope.

### Evidence

1. [Matrix index](evidence/index.json), [all executions](evidence/matrix.json)
   and [frozen predecessor](evidence/previous_metadata.json).
2. [Raw logs and diagnostics](evidence/raw_runs.tar.gz), with member hashes in
   the matrix index. Complete multi-gigabyte output states are hash-checked by
   delivery and indexed at their machine-local paths, not committed as binaries.
3. [Regression index](verification/index.json) and
   [logs, pre-edit metadata and build configuration](verification/regressions.tar.gz).
   The pre-edit source tarball and compiled binaries retain machine-local
   identities; proprietary vendor installations are not bundled.
4. `tests/test_grasu_finite_search.py` checks matrix rejection and outcome bounds;
   `tests/test_grasu_finite_search_delivery.py` verifies the committed capsules
   offline, without requiring machine-local raw paths.

**Decision:** the declared finite-network G prediction-retention gate passes.
Whole-G HLS feasibility, stage schedules, original-publication timing,
production/SST promotion, temporal workload coverage and actual G-to-R
composition remain open. No new Spine comparison or figure replacement is
admitted by this checkpoint. The R credit study and HLS/route jobs retain their
existing memory admission rules and have not been restarted or repinned.

## Reproduction

Use fresh output paths and a fresh Release core build. The predecessor is the
complete metadata-buffer report, not a figure or a selected subset.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/g-metadata-credits-v1/matrix/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/g-metadata-credits-v1/matrix/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.verification \
  --base /path/to/g-finite-search-model-v1 \
  --previous /path/to/g-metadata-credits-v1 --output /path/to/fresh-verification

python3 -m unittest tests.test_grasu_finite_search \
  tests.test_grasu_finite_search_delivery -v
```

Runtime attempts are owned by
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-finite-search-model-v1/`.
Build/test processes are serial and bounded, with unique logs and output paths.
Prediction runs use a 1-GiB per-process address-space cap and 8-GiB reserve;
builds/regressions use at most 2 GiB with the same reserve. The observed fresh
SST compilation process peak is 1,020,388 KiB; it is a process peak, not a
simultaneous process-tree measurement. The full matrix is serial on CPU 127;
packaging and focused checks use CPU 126.
Heavy HLS/routing admission reserves are not reduced. Paper and frozen figure
packages are not edited.
