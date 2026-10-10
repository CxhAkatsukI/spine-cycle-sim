# Delivery Conclusions

## Bottom Line

The incremental G+R, SST integration and Spine extractions preserve every
observed result field on their frozen regression matrices. Independent G,
original-R, resource-matched A4 and adapter+A4 controls now have separately
owned implementations, complete state checks and finite-resource ledgers.

**The requested original-publication speed match within approximately 10%
has not been established.** No independent stage in this delivery has an
admitted original-paper timing comparison. Functional agreement, HLS schedule
constraints and predicted cycles do not close that gap. Complete-system host
orchestration and an actual G-produced-PMA-to-R handoff were not measured.
The stage-performance objective remains blocked, not completed by these
control experiments.

## What Was Verified

| Work | Verified outcome | Limit |
| --- | --- | --- |
| G+R extraction | Five before/after SST result files are byte-identical | Fixed regression fixtures, not publication calibration |
| SST and Spine extraction | All fourteen results are byte-identical across before, after-SST and after-Spine builds; ten pass correctness and four retain their known rejection | Preserves existing behavior, including existing failures; not universal correctness |
| Isolated G | Eight prepared-source and eight guarded host-prepared functional cases; twelve DDR RTL controls; twelve complete finite configurations with exact repetitions | Source16 geometry; synthetic prepared inputs; full-G timing not admitted |
| Original R, A | Eight complete 11-Little/3-Big controls with repeated state and ledgers | One PR iteration, explicit tail-allocation compatibility padding, declared mock memory; not the unknown paper-selected optimum |
| Same-resource R, A4 | Eight complete four-Little/zero-Big controls | Independent original-R family, not proof of equality to our routed K4 placement |
| Adapter+R, B | Eight matched A4/B controls preserve all state replicas and common downstream resources; traffic and overlapping windows are recorded | Predicted timing; constructed PMAs, not outputs of the original G run |

The [refactor report](../../../repository/sst_spine_refactor/README.md),
[G report](FINITE_GRASU.md), [A report](MIXED_GRAPH_EXECUTION.md),
[A4 report](A4_GRAPH_EXECUTION.md) and [B report](FINITE_PMA_R.md) contain
their contracts, input identities, source pins, commands, negative attempts,
raw archives and verification logs. The [code map](../../../../cpp/README.md)
identifies implementation owners. Large SST bootstrap/serialization and other
legacy units still need incremental cleanup; this is not a claim that all
monoliths have been removed.

## Integration Finding

The matched B/A4 model reports elapsed-cycle ratios of **73.959--790.769**,
not FPGA slowdown measurements. This is a negative finding, not an accepted
implementation-performance equivalence. In the Amazon control, compact A4
reads 5,165,928 padded edge entries, whereas B visits 43,560,256 PMA entries
and performs 35,295,600 row-word reads across 48 tasks. Repeated row accesses
are modeled as separate 64-byte bus transactions. The conserved extra work
is substantial even before uncertainty in the timing assumptions.

Only the input representation/reader changes in this comparison. Original
A4 task assignment, downstream resources, graph, initial state, iteration
count and comparison clock stay fixed. That isolates this particular adapter
control; it does not identify overhead of the different routed K4/23-channel
implementation. Reader and compute windows overlap, so isolated elapsed
times must not be added as if the stages were serialized.

## Why Publication Matching Remains Open

For G, the paper describes eight destination slots per segment, whereas all
inspected reachable author versions use sixteen. The unchanged public host
also fails two bounds controls. Complete AU/SU/WK temporal traces have been
counted twice, but the original conversion, update-operation sequence and
throughput aggregation have not been recovered. A post-hoc arithmetic clue
matches rounded Table 4 numerators; it is not an admitted update workload.
The [temporal audit](PUBLICATION_WORKLOADS.md) and
[complete reachable-history audit](PUBLICATION_HISTORY.md) retain these
findings without inventing a converter or fitting a rate multiplier.

For R, released computation and the inspected HEAD are materially the same
for an explicit dense-partition argument. However, the publication's selected
topology/cut and exact timing window are not determined for the target row.
The 11+3 control additionally needs declared allocation padding. Its memory
and clock assumptions are not an admitted reconstruction of that paper row.

These are comparability and configuration gaps, not a measured error greater
than 10%. There is no valid percentage error to report yet. Increasing the
number of synthetic cases cannot supply missing original conditions.

## What Would Unblock The Next Comparison

1. Recover an author-converted G input/batch sequence, its operation/counting
   rule, the matching eight-slot source/configuration or an explicit source16
   reference, and corresponding kernel-event logs at a known DDR/run clock.
2. Obtain one original-R reference run with graph hash, transformation,
   iterations, Little/Big count, dense cut, clock, memory placement and event
   window. Author logs or a new run of the admitted original artifact can
   serve as a reference; our modified port's total time cannot substitute.
3. Freeze those conditions before fitting any component. Predeclare a
   calibration row and neighboring holdout checks, then report all rows and
   the requested rate error. A measured mismatch is an acceptable outcome.
4. Validate the actual G-to-adapter data handoff and its ID/layout mapping;
   then measure G, adapter+R and host windows separately in system C. The
   existing two-source ABI fixture is not a valid complete graph input for B.

This does not require changing the paper or replacing frozen figures. Nor
does this study independently invalidate or revalidate their FPGA results:
matching our hardware and matching the original publications are distinct
questions.

## Delivery Check

[Delivery audit](delivery_audit.json) records a final read-only identity and
preservation check. Its status does not upgrade the timing evidence. Recheck
raw refactor results, complete stage archives and A4/B resource consistency:

```bash
python3 -m unittest discover -s tests -p test_stage_validation_delivery.py
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
```

This final check reads the original raw packages; it does not rerun SST,
FPGA, synthesis or the large graph simulations. The delivery leaves the
paper, frozen figure package and unrelated local v4 calibration edits intact.
