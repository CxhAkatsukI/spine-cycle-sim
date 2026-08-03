# Paper Architecture Alignment

## Goal

Align the Spine cycle simulator and HLS implementation with the frozen
Delta.hls architecture, calibrate the existing routed refactor31 SSSP artifact,
and preserve a hash-bound path from source and workload to FPGA evidence.

The frozen authority is:

```text
configs/contracts/spine_paper_architecture_alignment_v1.json
SHA-256: 6358e13196d7c65007eb0c49b198ecae5e9935b7feacaa6d0faa78ed41ecc8b2
```

The contract binds paper revision `dc34c54574b645273106eb974a3fa5b78f380c03`,
the 16-partition/32-family/11-level/4-lane target, the 23-pseudo-channel U55C
mapping, finite queues, the device-active timing boundary, four algorithm
policies, and calibration/holdout gates.

## Isolated Worktrees

No pre-existing dirty worktree was modified.

```text
/home/chuxiao/spine-cycle-sim-architecture-alignment
  branch: codex/paper-architecture-alignment

/home/chuxiao/spine-dynamic-graph-paper-alignment
  branch: codex/paper-architecture-alignment
```

## Refactor31 Reconstruction

The routed artifact is not plain `cc7e3f9`. It was built from that base plus a
frozen source diff:

```text
base revision: cc7e3f95ee9209a8f3f0435493f34e214de50b3d
source diff:   82e31d80a91d733bc79aa21d2deb990bab31371403b1a0d34950639680840283
xclbin:        16ca09f5597d974e6963ac19ada4f59a8e2b0d6b7ef5ea8f668e5ffb520a1629
```

The reconstructed files match the source snapshot byte-for-byte:

```text
src/common_types.hpp
  36379d943b177c1ae63c57175140a865b7d67e49bc3f9e3707a2541a50cc2e31
src/spine_partitioned.hpp
  5b4281d79dbefd8dd973fd311c2c8e9927c330e9a9cc117b2e33982fd1fc41c5
```

The reconstruction is committed as `d422263` in the HLS alignment branch. The
artifact routes on U55C at 160 MHz with post-route WNS `+0.003 ns`.

The complete evidence manifest is:

```text
configs/evidence/spine_refactor31_routed_baseline_v1.json
```

The corresponding simulator profile is:

```text
configs/architectures/spine_refactor31_routed_native_v1.json
```

It is intentionally labeled `fpga_calibration_baseline`; it is not the final
150-MHz paper-aligned target.

## Verified Tests

The HLS reconstruction passed these host/reference tests:

```text
exact payload task-feed reference tests
windowed exact task-feed reference tests (52 ordered-equivalence cases)
partitioned CSR model test
```

The split-equivalence binary could not be rebuilt from the current account
because Feiyang's Vitis `settings64.sh` and `ap_int.h` include tree are not
readable. This is an environment limitation, not a source mismatch.

Reproduce the simulator-side checks with:

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
python3 -m unittest tests.test_alignment_contract tests.test_architecture_profiles -v
python3 scripts/export_hls_architecture_contract.py \
  --output /tmp/spine_paper_architecture_contract.hpp
python3 scripts/analyze_refactor31_fpga_calibration.py \
  --out-dir docs/evidence/refactor31_fpga_calibration
```

Reproduce the available HLS host tests with:

```bash
cd /home/chuxiao/spine-dynamic-graph-paper-alignment/tests/test_integration
make -j2 \
  host_exact_payload_task_feed_reference_test \
  host_windowed_exact_task_feed_reference_test \
  host_partitioned_csr_model_test
./host_exact_payload_task_feed_reference_test
./host_windowed_exact_task_feed_reference_test
./host_partitioned_csr_model_test
```

## Calibration Gates

Calibration uses synthetic boundary workloads plus 100K, 500K, 1M, and 4M
edge real slices. A separate 2M--8M edge holdout remains immutable after model
freeze. Every FPGA case is repeated at least five times.

For non-tiny workloads, acceptance requires:

- total-cycle median absolute error at most 15 percent;
- maximum total-cycle error at most 30 percent;
- component-cycle median absolute error at most 20 percent;
- workload-order Spearman correlation at least 0.9; and
- exact correctness, request conservation, and work-ledger closure.

## Remaining Implementation Order

1. [done] Export the frozen contract into the HLS branch and add compile-time
   guards.
2. [partial] Build the refactor31-native raw-log parser and freeze the transfer
   matrix. Existing timing evidence is parsed; the generic real-slice FPGA host
   remains pending.
3. [host-tested in simulator and HLS] Add the per-partition owner FIFO and
   `queued/in_flight/dirty` state machine. The HLS owner kernel is not yet
   synthesized or routed.
4. [host-tested in simulator and HLS] Add lossless reactivation and work-credit
   quiescence for SSSP. PageRank/CC policy-shell integration remains pending.
5. [host-tested in simulator and HLS] Add dormant-ID activation and
   validity-bitmap vertex deactivation. The HBM-backed simulator component is
   wired into persistent SSSP transactions; the HLS lifecycle kernel and
   fixed-domain guards pass host tests but are not yet synthesized or routed.
6. [native micro-calibration complete] Freeze the refactor31 SSSP micro-profile
   and run the one-tile calibration/tile-shape holdout. Exact-path transfer is
   accepted; multi-tile fallback remains an 18% launch-to-finish residual.
   Medium real-slice calibration and immutable real-slice holdout are pending.
7. Specialize the shared shell for SSSP, CC, Residual PageRank, and Full
   PageRank; route and validate each policy kernel.

The integrated SSSP owner evidence and exact reproduction command are in
`docs/spine_device_owner_scheduler_20260803.md`.
The corresponding vertex-lifecycle evidence is in
`docs/spine_vertex_lifecycle_system_20260803.md`.
The native micro-calibration and its explicit claim boundary are in
`docs/refactor31_sim_fpga_mechanism_transfer_20260803.md`.

The current Full/Residual PageRank and CC simulator shell still uses the
legacy source-preparation protocol to read rank/residual/degree state before
edge emission. It is correctness-tested but is not claimed to be a routed
paper-policy kernel. Refactor31 SSSP host-active records are authoritative and
do not use that source-refresh path.

Payload-distinct parallel edges are deliberately excluded from this version.
They require a separately versioned record-identity change across sorting,
carry, latest-view resolution, and application logic.
