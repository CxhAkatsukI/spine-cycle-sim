# Resident G-to-R Handoff

## Question And Scope

Can R consume the exact physical PMA left by G, without a free graph rebuild,
while starting at the old graph's converged distances and reaching the new
graph's converged distances? This is a **correctness and boundary test**, not
a matched-performance, original-publication or FPGA claim.

This page preserves the **direct-G checkpoint**. The subsequent
[finite-search bank-routing study](banked/README.md) tests independent metadata
banks and sharded physical handoff, separately from full cached performance.

The preceding independent R study constructs its post-update PMA from logical
edges before timing. That remains valid for its stated compute-only boundary,
but does not establish G-to-R physical integration. This study closes that
specific test gap; it does not retroactively expand the earlier boundary.

## Implementation And Invariants

- Default-off `RoutedReGraphConfig::reuse_resident_pma` requires a drained
  backend. It inspects row bounds, the extent sentinel and all reserved PMA
  segments at the runtime-plan addresses. Mismatches fail; no graph payload
  is repaired, compacted, reallocated or rewritten.
- The existing default still initializes its own prepared graph. No SST
  profile selects the new option and no frozen plugin or bitstream changes.
- One scheduler/backend executes G, drains it, then registers R. The same
  physical update counts and cache geometry produce identical G/R allocation.
- Old graph allocation, all untouched shards, converged state and active seed
  are caller-prepared outside the device windows. In particular, seed `{0}`
  for the weight decreases is not device-generated or a measured host window.
- This checkpoint uses **unchanged direct sharded G**, not the finite
  cached/search candidate. At its frozen revision the latter required
  same-channel metadata. The subsequent bank-routing study removes that
  finite-search restriction; full cached integration remains separate.
- R SSSP runs to quiescence, not one hop. An independent Dijkstra checks every
  final distance; source replicas, traffic conservation and unchanged PMA
  bytes are also checked. Inspection is a test oracle, not modeled bandwidth.

Review [the public contract](../../../../../../cpp/include/spine_sim/routed_regraph.hpp),
[admission](../../../../../../cpp/src/routed_regraph/admission.cpp),
[resident serialization](../../../../../../cpp/src/routed_regraph/resident_memory.cpp),
and [the test owner](../../../../../../cpp/tests/evaluation_impact/handoff/).

## Declared Matrix

Each row runs in both R component-registration orders. Four synthetic graphs
exercise physical allocation, not representative graph performance. A short
chain propagates source-0 weight decreases; extra destination shards contain
real edges, and unused source reservations must remain allocated.

| Vertices | Destination shards | Cache segments/half | Batch | G cycles | R cycles | R rounds |
| --- | --- | --- | --- | --- | --- | --- |
| 129 | 1 | 1 | One weight decrease, delete+insert | 89 | 328805 | 5 |
| 65569 | 2 | 1 | Two weight decreases | 178 | 492645 | 5 |
| 131105 | 3 | 8 | Two decreases; third shard untouched | 178 | 656485 | 5 |
| 65569 | 2 | 1 | Empty, all shards untouched | 0 | 98529 | 1 |

These are declared cycle predictions at 150 MHz, Mock memory latency 7,
32 channels, one issue/channel/cycle, 16 outstanding/channel and response
depth 32. Large padded source-state buffers dominate these tiny-edge fixtures;
the times must not be used to infer application speedups or FPGA timing.

Seven negative controls reject corrupted rows, corrupted slots, corrupted
extent, missing source-0 reservation, changed placement/update allocation,
in-flight G requests and an uninitialized row payload. Rejection itself must
not issue traffic or rewrite the PMA.

## Reproduce And Deliver

The owning Python package separates analysis, bounded execution and packaging:
`spine_cycle_sim/experiments/evaluation_impact/composition/`. It freezes source,
flags, compiler, binaries and the old default output. Use a fresh output path:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.study \
  --output /path/to/fresh-handoff \
  --previous-stdout /path/to/frozen-default-routed.stdout.txt

python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.delivery \
  --report /path/to/fresh-handoff/results.json \
  --output /path/to/fresh-evidence \
  --retained /path/to/pre-edit-freeze \
  --retained /path/to/failed-build \
  --previous-sst /path/to/preceding-sst-verification

python3 -m unittest tests.test_grasu_routed_handoff -v

python3 -m spine_cycle_sim.experiments.evaluation_impact.composition.delivery \
  --checks /path/to/verification-v1 \
  --output /path/to/fresh-verification-capsule
```

Execution is serial with a 2-GiB per-process address-space limit and an 8-GiB
available-memory reserve, saved logs and bounded timeouts. This small
correctness study does not waive the larger pending jobs' admission reserves.
The optional `--core-build` reuses a diagnostic build directory, but rebuilds
all targets and freezes the resulting libraries, executable and flags.

Raw machine-local root:
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/gr-handoff-v1/`.
The first build failure (GCC dangling-reference warning in a test helper)
is retained, not treated as numerical evidence. The helper now copies the
small runtime-region descriptors instead of retaining those references.

## Verification And Evidence

[The evidence index](evidence/index.json) and [portable raw archive](evidence/raw.tar.gz)
contain eight handoffs, seven negative controls, compiler/flags/source pins,
the pre-edit freeze and the retained failed build. All **32 C++ tests** pass.
The default routed test's stdout is byte-identical to the pre-edit output.
A fresh SST library builds and loads; both default SST smoke result JSONs
match the preceding checkpoint in every field, including cycles, traffic and
DRAM counters. These smokes check compatibility, not resident/finite G timing.
The archive excludes executables and libraries; machine-local hashes identify
them in [the complete report](evidence/report.json).
[The delivery verification index](verification/index.json) preserves the
bounded test logs: **54 Python tests**, document layout, catalogs and diff
checks pass. It also retains a failed packaging test that expected the wrong
log filename; the numerical results did not change.

## Remaining Gates

The finite G performance candidate still needs complete sharded integration,
HLS/RTL schedule evidence and hardware validation. R credit/resource controls
and original-publication matching are separate. Device seed preparation and
host orchestration remain outside this test. No new Spine comparison, paper
revision or Figure 7--11 replacement is admitted by a passing handoff.
