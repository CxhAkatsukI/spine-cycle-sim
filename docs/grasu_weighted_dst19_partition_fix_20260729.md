# GraSU weighted destination-partition boundary

## Failure exposed by the real-graph campaign

The first 11-dataset main-E2E launch rejected GraSU+ReGraph Weighted SSSP on
`sx_superuser` before cycle simulation.  Its normalized graph contains 567,316
vertex IDs, just above the 524,288 values representable by the weighted PMA
word's 19-bit destination field.  The host preprocessing incorrectly applied
that local-field limit to the whole graph even though the downstream
`GraSuPartitionedPmaLayout` already stores each edge in a destination partition
and subtracts the partition base before encoding it.

Candidate87 removes only that stale global check.  Global host-reordered vertex
IDs remain 32-bit.  The PMA word still contains the same 19-bit
partition-local destination and 12-bit weight, so this does not widen the ABI
or add hardware.  Runtime-packed per-partition row/PMA buffers remain subject
to the frozen 512 MiB pseudo-channel capacity checks.

## Validation

The C++ regression constructs a 524,289-vertex graph with an edge into vertex
524,288.  Host preprocessing retains the global ID, the partitioned layout
creates nine 65,536-vertex destination windows, and the final partition encodes
that destination as local ID zero.  All 31 GraSU core tests pass.

Candidate87 was rebuilt with native-host PGO from commit `53ff75c`:

```bash
export BUILD=/data/tmp/chuxiao/candidate87-dst19-partition-pgo-build-20260729
export PGO=/data/tmp/chuxiao/candidate87-dst19-partition-pgo-data-20260729
export DRAMSIM3=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729

make -C cpp/sst pgo-native-generate -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO" DRAMSIM3_ROOT="$DRAMSIM3"

# Run the frozen syn_spread_e512 residual PageRank PGO training pair here.

make -C cpp/sst pgo-native-use -j8 \
  BUILD_DIR="$BUILD" PGO_PROFILE_DIR="$PGO" DRAMSIM3_ROOT="$DRAMSIM3"
sha256sum "$BUILD/libspine_cycle.so"
```

The training pair remains cycle-identical to Candidate86: 4,778,979 Spine
cycles and 15,310,428 GraSU+ReGraph cycles, both correctness-gated.  The final
plugin SHA-256 is
`abaf251ea41e41ac8164f7948131ae05c0c7764b173a34ce9096424cfcd4fadf`.

Candidate87 is retained as the isolated dst19 partition milestone. It was
superseded as the formal campaign plugin by the later capacity-safe Spine
resident-hierarchy build; the publication contract must be consulted for the
current pinned plugin identity.
