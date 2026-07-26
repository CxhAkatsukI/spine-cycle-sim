# Spine Candidate10 routed HW evidence

This bundle records Feiyang's routed Candidate10 one-pass Spine implementation
on the Xilinx U55C with a 150 MHz data-clock target. It replaces the older
`9c08763` build as the current native Spine feasibility/PPA anchor. Simulator
cycles remain a separate normalized result and were not fitted to this route.

## Source and artifact identity

- repository revision: `1e61fc0822608f8776399cc10a851f6fe5806f92`
- branch: `reduce-levels-for-routing`
- frozen `spine_partitioned.hpp` SHA-256:
  `d98fb04cb59c3b00b894ba4d615d7dd1a6250f46fe1d998a951bb0a0843c7dbc`
- xclbin SHA-256:
  `551ed1e89755a8b97725efa4003e28007eabd66abb73f480c6ee087a627b9666`
- xclbin size: 52,769,249 bytes
- tool/device: Vitis 2024.1, `xilinx_u55c_gen3x16_xdma_3_202210_1`

The source repository was dirty when the build was frozen. The source-file
hash and retained build snapshot are therefore authoritative; the revision
alone is not sufficient to reproduce identity. The xclbin stays under
`/data/feiyang/` and is not tracked in Git. `artifacts.tsv` pins it by size and
hash.

## Result

- Compile, link, placement, routing, and xclbin generation completed.
- Routed user resources are 127,910 LUT, 149,746 registers, 99 BRAM, 99 URAM,
  and 22 DSP.
- The post-route physical-optimization report closes the 150 MHz setup target:
  WNS is +0.003 ns and TNS is zero. Hold and pulse-width timing also pass.
- The linked design contains one read/maintenance CU and one split-compute CU.
  The compute XO is inherited from the earlier accepted split-compute build;
  Candidate10 changes are in the read/maintenance path.

The selected routed kernel-utilization report identifies itself as `Fully
Placed` despite its filename. The timing report is post-route physical
optimization. Both report states are preserved rather than inferred from file
names.

## Claim boundary

This is native Candidate10 implementation evidence and selected direct-hardware
correctness/timing evidence exists separately. It is not an implementation of
the normalized profile's three algorithm policies, an iso-resource comparison
against GraSU+ReGraph, or cycle-for-cycle calibration for simulator E2E time.

## Files

- `summary.md`: human-readable collector output.
- `artifacts.tsv`: xclbin identity.
- `link_kernels.tsv`: linked kernels and CU multiplicities.
- `connectivity.tsv`: port, stream, memory, and SLR mapping.
- `accelerator_util.tsv`, `slr_util.tsv`: routed utilization.
- `hls_area.tsv`: per-top HLS estimates.
- `timing.tsv`: routed setup/hold/pulse-width timing.
- `commands.tsv`, `system_estimate_*.tsv`, `copied_reports.tsv`: provenance.

The 16.8 MB post-route timing report is stored as deterministic gzip. Its
decompressed and archive hashes are both recorded in `copied_reports.tsv`.

Recreate the tables from the retained build with:

```bash
cd /home/chuxiao/grasu-regraph-integration
python3 scripts/collect_vitis_evidence.py \
  --label spine_candidate10_1e61fc0_hw_150mhz \
  --build-root /data/feiyang/spine-dynamic-graph-builds/pipeline_dirty_frontier_publication_1e61fc0_20260725/production/hw_v5_candidate10_150 \
  --out-dir /tmp/spine_candidate10_1e61fc0_evidence \
  --artifact /data/feiyang/spine-dynamic-graph-builds/pipeline_dirty_frontier_publication_1e61fc0_20260725/production/hw_v5_candidate10_150/xclbin/spine_partitioned_split_e2e.hw.xclbin
```
