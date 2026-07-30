# RQ3 direct stage ledger and resident fallback

## Scope

This milestone adds a direct, exclusive cycle ledger for the six maintenance
stages that precede graph propagation:

- `T_xfer`;
- `T_reduce`;
- `T_carry`;
- `T_dir`;
- `T_seed`;
- `T_switch`.

Every active `SpineL0Maintenance` cycle is assigned to exactly one stage. The
result writer emits the six counters and `maintenance_stage_ledger_closed`.
The simulator fails closed if their sum differs from
`maintenance_end_cycle - maintenance_start_cycle`.

The names describe work inside the current device measurement boundary. The
input is already a resident sorted update buffer, so `T_xfer` does not include
host DMA and `T_reduce` does not claim an untimed external FLiMS sort. Likewise,
`T_seed` currently measures dirty-source publication and scheduling; residual
PageRank's host-side old/new-rank correction remains a separately declared
boundary until it is execution-driven.

## Resident graph admission

The Orkut full-graph canary exposed a second admission case after the
skip-already-fit correction. A snapshot can fit every fixed 11-level family but
fail the native single-L10 preload because several promoted destinations hash
to one hot shard.

The classifier now uses two bounded attempts:

1. preserve the HLS host's L10 preload policy when the cold L9 target and hot
   L10 shard capacities both fit;
2. otherwise, admit only if a placement fits each family's aggregate fixed
   11-level capacity, then use the existing explicitly reported
   `resident_multilevel_fallback` bootstrap.

No level, family, HBM channel, or online update capacity is enlarged. A
destination larger than one aggregate fixed family and a snapshot that cannot
fit aggregate cold/hot families remain hard errors. The fallback is a
simulator-only resident initialization mechanism and is excluded from dynamic
E2E timing; it is not native-HLS evidence.

## Reproduction

```bash
python3 -m unittest \
  tests.test_sst_memory_binding \
  tests.test_spine_sim \
  tests.test_large_real_pagerank

cmake --build build/cycle-core -j4 --target spine_cycle_core_tests
for test in \
  spine_resident_hot_hash_collision_fallback \
  spine_resident_hot_classification \
  spine_resident_superhub_capacity \
  spine_resident_multilevel \
  spine_candidate10_writer_backpressure \
  spine_candidate10_zero_edge \
  spine_candidate10_one_pass; do
  build/cycle-core/cpp/spine_cycle_core_tests "$test"
done

make -C cpp/sst -j4
```

The focused Python suite passes 26 tests. All seven listed C++ tests pass. A
four-edge forced-L1 smoke closes the new direct stage ledger at 4,951 cycles:

```text
T_xfer=145, T_reduce=131, T_carry=760, T_dir=1331,
T_seed=290, T_switch=2294, sum=4951
```

The next evidence step is an Orkut `max_cycles=1` admission canary using an
isolated plugin. It must complete classification and resident preload before a
full execution is resumed under the campaign memory reservation.
