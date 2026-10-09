# Candidate10 maintenance control timing decomposition (2026-07-26)

## Scope

This milestone separates three timing scopes for the frozen Candidate10
read-maintenance kernel:

1. `partitioned_run_maintenance` RTL control, from `ap_start` to `ap_done`,
   with deterministic one-cycle child-protocol responders.
2. The execution-driven cycle simulator, including the Candidate10 AXI
   adapters and SST/DRAMSim3 memory path.
3. The routed U55C kernel event measured with XRT
   `CL_PROFILING_COMMAND_START/END` at 150 MHz.

The frozen XO is:

```text
/data/feiyang/spine-dynamic-graph-builds/
  pipeline_dirty_frontier_publication_1e61fc0_20260725/production/
  hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo
SHA256 629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5
```

## Direct RTL oracle

The collector recursively extracts the 125-module dependency closure rooted
at `spine_partconv_rdmaint_kernel_partitioned_run_maintenance` and runs it in
XSim. The zero-edge path completes in **4,490 cycles**. The responder ledger
closes exactly:

| Port | Address bursts | Requested beats | Retired beats/responses |
| --- | ---: | ---: | ---: |
| metadata read | 370 | 373 | 373 R beats |
| metadata write | 49 | 162 | 162 W beats, 49 B responses |
| result write | 67 | 88 | 88 W beats, 67 B responses |
| sorted edges | 0 | 0 | 0 |

The HLS synthesis report's 1,517-cycle static minimum is not the observed
top-level control latency. It is a report bound for a synthesized function
group and does not include the complete dynamic child-call schedule.

## Simulator change

Candidate10 now has a 4,490-cycle zero-edge completion floor. It is a
concurrent lower bound, not an additive correction: AXI or memory execution
may extend beyond it. It is intentionally restricted to empty batches because
that is the only complete maintenance path covered by this oracle.

After the change:

| Scope | Zero-edge cycles |
| --- | ---: |
| direct maintenance RTL, ideal child responders | 4,490 |
| execution-driven simulator | 4,490 |
| routed U55C XRT event | 39,016.2 |
| routed event minus direct RTL | 34,526.2 |

The remaining 34,526.2 cycles are **not identified as an L0 writer or wrapper
constant**. They include the U55C shell/interconnect/HBM service window and any
remaining top-wrapper mismatch.

## Hardware matrix

The source-matched 11-case matrix was rerun. Raw simulator error remains:

| Case | Edges | Sim cycles | HW cycles | Raw error |
| --- | ---: | ---: | ---: | ---: |
| zero | 0 | 4,490 | 39,016 | -88.49% |
| one | 1 | 4,731 | 38,769 | -87.80% |
| adjacent L0 | 128 | 38,246 | 77,249 | -50.49% |
| duplicate-heavy | 128 | 24,756 | 58,779 | -57.88% |
| dirty boundary | 4,096 | 737,297 | 827,778 | -10.93% |
| forced fallback | 4,112 | 738,410 | 815,093 | -9.41% |
| mixed fallback | 8,193 | 262,404 | 480,377 | -45.38% |

The zero-edge floor closes the proven kernel-control gap without pretending to
fix the board-level timing gap. The large streaming cases remain much closer
than tiny/sparse cases, which is consistent with an unresolved fixed shell
window plus workload-dependent external memory service.

## What happens next

The remaining work is split by ownership:

1. **L0 writer:** keep the existing record/page/packer state machine and the
   56-case full-function RTL schedule oracle. Extend the direct maintenance RTL
   oracle to representative nonempty family/page/source boundaries before
   adding any new control term.
2. **AXI adapter:** keep the exact burst splitting, 4 KiB boundary, read-address
   pipeline, write-buffer pipeline, outstanding limit, and finite response
   queues already verified by the 29-case RTL oracle.
3. **Shared AXI/HBM:** add per-pseudo-channel arbitration, bank/row timing,
   read/write turnaround, bounded command/response queues, and contention among
   initiators. This layer, not the L0 writer, owns external service stalls.
4. **Backpressure validation:** drive deterministic R/W/B stalls through the
   direct RTL oracle, match queue occupancy and retirement traces, then repeat
   with unseen stall patterns as holdouts.
5. **Board validation:** collect repeated sequential/random burst,
   read/write-mix, outstanding-depth, and multi-port contention microbenchmarks.
   Validate distributions and trends; do not fit a single opaque residual.

Until those steps are complete, the simulator supports structural bottleneck
and trend claims, exact claims for the isolated writer/adapter oracles, and
functional end-to-end claims. It does not support absolute U55C event-time or
energy claims for tiny/sparse maintenance workloads.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/collect_candidate10_maintenance_control_rtl_oracle.py \
  --out docs/evidence/candidate10_maintenance_control_rtl_20260726.json \
  --build-dir /data/tmp/chuxiao/candidate10_maintenance_control_dev

cmake --build build/cycle-core --target spine_cycle_core_tests -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_candidate10_zero_edge

make -C cpp/sst -j2
python3 scripts/run_candidate10_maintenance_matrix.py \
  --out-dir results/candidate10_maintenance_control_floor_20260726 \
  --no-build

python3 -m unittest \
  tests.test_candidate10_maintenance_control_rtl_oracle
```

The architecture/timing scope diagram is
`docs/figures/candidate10_maintenance_timing_layers_20260726.svg`.
