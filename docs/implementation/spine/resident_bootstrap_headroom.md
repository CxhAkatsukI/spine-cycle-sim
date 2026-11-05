# Resident Bootstrap Headroom

## Scope

The persistent update experiment accepts an explicit bootstrap minimum level.
The default remains L2. Selecting L4 reserves L0--L3 for subsequent updates;
it does not increase any level capacity or remove update, carry, directory,
or host-preparation work from timing. This is an offline initial-layout policy,
not an online free compaction or an FPGA timing-calibration result.

The motivation is the retained PK failure in the
[portable Fig. 8 cohort](../../experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105/fresh_simulator/portable_fig8/README.md):
the old bootstrap occupied all of cold family 0's L2--L10. The fourth update
batch then had no capacity-safe free carry target. A larger hierarchy was not
silently substituted for that failed run.

## Invariants And Ownership

- `classify_spine_resident_snapshot(snapshot, config, minimum_level)` computes
  each family's usable bootstrap capacity from only the selected levels.
- `preload_spine_resident_snapshot(snapshot, config, classification, minimum_level)`
  uses that same range for placement. Classifier and allocator cannot disagree
  about the capacity reserved for incoming updates.
- The minimum is an integer from 2 through 10. A graph that cannot fit within
  the resulting finite family budgets must fail; it cannot spill into reserved
  levels or silently discard records.
- Destination classification remains global degree-descending, vertex-ID tie
  breaking. Every original record and its payload must survive placement.
- Persistent host preparation and device initialization receive the same
  minimum. Other figure experiments retain their existing default; the SST
  wrapper rejects a nondefault minimum outside persistent update/host modes.

The focused `spine_resident_preload_tests` target checks default compatibility,
finite per-level capacity, reserved empty levels, preserved record multisets,
over-capacity rejection, invalid arguments, and unchanged caller configuration
when classification fails. The persistent runner builds and runs this test
before its SST correctness smoke and real-input execution.

## Experiment Use

Add `--preload-minimum-level 4` to the existing persistent-study command. The
result receipt records `spine_preload_minimum_level`; every device and host
configuration records `preload_minimum_level`. All usual source, compiler,
input, build, raw-output, correctness, and conservation pins remain required.
Declare one policy for the complete cohort, including unsuccessful cases.

A changed minimum intentionally changes placement and may change cycles,
traffic, hot-set selection, and host time. It must not be exported as an exact
numerical replay of the old L2 cohort. Keep that cohort and its failure intact,
then publish a separately named experiment with its own raw receipts. This
change alone is not evidence that PK, or the complete cohort, now passes.

## HLS Correspondence

The HLS host helpers in `tests/test_integration/host_split.hpp` already expose
`plan_partitioned_compacted_baseline(edge_count, minimum_level)` and separate
hot/cold classifier budgets. To implement this bootstrap policy there, compute
the sum of the selected L4--L10 capacities, use that sum for the family,
cold-partition-target, and hot-shard classifier caps, and call every family
planner with minimum level 4. Leaving classifier caps at L2--L10 while moving
only the planner to L4 is inconsistent and can reject the resulting layout.

This is a source-level implementation recipe, not a claim that existing routed
images or their deployed hosts already use L4. Those hardware measurements
retain their recorded layouts. A corresponding host change needs independent
layout/oracle checks and fresh measurements before it can be described as
hardware evidence for this policy.
