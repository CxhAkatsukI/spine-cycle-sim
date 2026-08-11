# Current-FPGA global hot-promotion alignment

Date: 2026-08-11

## Scope

The routed full-graph Spine artifacts use HLS source revision
`3678ad488e0d0fe8538a36a11d87ddffa182fa99`.  Its host classifier consumes one
global descending-indegree candidate sequence until every cold partition fits.
It does not skip a candidate merely because that candidate's partition already
fits.  The current simulator mirrors that exact behavior at revision
`f742a1ebb17bd1e17c6819087504f9f6dfe76231`.

This current-FPGA alignment supersedes the skip-fit behavior described in
`spine_skip_fit_hot_promotion_v7_20260730.md` for hardware-calibrated results.
Formal-v7 remains a valid historical optimized architecture, but its affected
rows cannot calibrate the routed current-FPGA baseline.

The aligned implementations are:

- `cpp/src/spine_l0.cpp::classify_spine_resident_snapshot`;
- `spine_cycle_sim/sst_binding.py::_spine_automatic_hot_vertices`;
- `spine_cycle_sim/models/spine.py::classify_hot_cold`.

## StackOverflow CC discriminator

The reciprocal StackOverflow workload exposes the difference.  The skip-fit
simulator promoted 4,038 vertices and 7,059,356 edges, then emitted 1,333 range
tasks.  The routed FPGA reported 4,841 vertices, 8,216,144 edges, and 1,503
range tasks.  A cycle scale must not be fitted across that structural mismatch.

With the routed global order, the correctness-gated simulator reports:

| Quantity | Simulator | Routed FPGA |
| --- | ---: | ---: |
| resident hot vertices | 4,841 | 4,841 |
| resident hot edges | 8,216,144 | 8,216,144 |
| iterations | 1 | 1 |
| range tasks | `[1503]` | `[1503]` |
| processed edges | `[17630]` | `[17630]` |
| simulator cycles | 567,909 | not used for structural admission |

The simulator row is:

```text
/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811/
  runs_v4_large/so/spine/connected_components_hls_global_promotion_v3
```

It passes both correctness oracles and the memory, FIFO, owner, dispatch, and
work-credit ledgers.  The immutable plugin has SHA-256
`f99b13a0bdf5410f3ab201d75d63dde609565f27893c2fe51790c7a2e3260ab5`.

## G+R transition

The source transition changes only Spine resident classification and
Spine-specific counters.  G+R was nevertheless rerun under both plugin images
for all three calibrated algorithms.  Weighted SSSP, CC, and residual PageRank
produce exact matching `result.json` payloads at 99,885, 201,893, and 1,487,890
cycles.  The machine-readable report is:

```text
docs/evidence/current_fpga_grasu_plugin_transition_v4_20260811.json
```

Therefore the long-running G+R matrix produced by the prior immutable plugin
is reusable in v4.  This equivalence does not admit prior Spine rows whose
resident classifier entered automatic hot promotion; those require an exact
v4 successor.

## Reproduction

```bash
python3 -m unittest \
  tests.test_grasu_plugin_transition \
  tests.test_sst_memory_binding \
  tests.test_spine_sim

cmake --build /data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-cmake \
  -j8 --target spine_cycle_core_tests
/data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-cmake/cpp/spine_cycle_core_tests \
  spine_resident_hls_global_promotion_order

make -C cpp/sst -j8 BUILD_DIR=build/sst-current-fpga-v4
sha256sum cpp/sst/build/sst-current-fpga-v4/libspine_cycle.so

python3 scripts/audit_grasu_plugin_transition.py \
  --source-revision f742a1ebb17bd1e17c6819087504f9f6dfe76231 \
  --pair weighted_sssp=/data/tmp/chuxiao/plugin_equivalence_f742/grasu_weighted_v1,/data/tmp/chuxiao/plugin_equivalence_f742/grasu_weighted_v4 \
  --pair connected_components=/data/tmp/chuxiao/plugin_equivalence_f742/grasu_cc_v1,/data/tmp/chuxiao/plugin_equivalence_f742/grasu_cc_v4 \
  --pair residual_pagerank=/data/tmp/chuxiao/plugin_equivalence_f742/grasu_respr_v1,/data/tmp/chuxiao/plugin_equivalence_f742/grasu_respr_v4 \
  --output docs/evidence/current_fpga_grasu_plugin_transition_v4_20260811.json
```
