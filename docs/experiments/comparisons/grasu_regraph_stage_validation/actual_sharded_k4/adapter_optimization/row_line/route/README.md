# Whole-Line Production Route Checkpoint

## Decision

**Environment preflight passed; route was not started because of memory
admission.** This package contains no new xclbin, routed timing, board cycles,
calibration result or original-A4 performance comparison.

The exact whole-line adapter and padded SSSP host passed their prerequisite
checks. All eleven historical production XOs and the connectivity config
match the historical route inputs before replacement. The prepared command
replaces only the adapter XO; the other ten kernels, connectivity, U55C
platform and requested 150-MHz clock are unchanged.

| Item | Value |
| --- | --- |
| Candidate XO SHA-256 | `752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2` |
| Host | Checked `candidate/sssp/sharded_k4_sssp_native_host`, `ROW_LINE_READ=1` |
| Preflight | Vitis, Vivado, GCC, G++, thread compilation and execution: all six passed |
| Available memory at admission | 57,706,188,800 bytes, approximately 53.74 GiB |
| Required memory | 40-GiB process-tree budget plus 16-GiB reserve = 56 GiB |
| Admission | `ADMISSION_REJECTED_NOT_STARTED`, execution exit code 2 |

The memory threshold was not lowered. Preflight used a 4-GiB tree budget,
16-GiB live reserve and 90-second timeout per command. A later route would
use two synthesis/implementation jobs and a 14,400-second timeout, with
the existing aggregate RSS watchdog and pidfd-bound descendant cleanup.
These are sampled process-tree guards, not cgroup containment.

## Review And Reproduction

[verification.json](evidence/verification.json) contains the complete
command, admission, six preflight records, environment contract, archive
identity and per-member hashes. [raw_environment_admission.tar.gz](evidence/raw_environment_admission.tar.gz)
contains the original manifests, logs, config and selected small source
snapshots. Its SHA-256 is
`a4f2bca394c01544e11aee7ba3ec9e81321bd4722cf39e058d3759eda7aeff56`.
The XOs, host binary and proprietary tools are identity-indexed rather than
redistributed in this non-start archive; prerequisite artifacts belong to
the [whole-line HLS/host package](../README.md).

`route_preparation.py` owns prerequisite and exact-version binding;
`route.py` composes the existing environment/preflight, admission and link
owners. It does not introduce another route supervisor. Six focused tests
cover single-XO replacement, host padding, changed-input rejection, memory
refusal, failed preflight/link and immutable output directories.
All 304 sharded-K4 Python tests and 15 repository-structure tests pass;
documentation layout, catalogs and whitespace checks pass. Bounded Python
regression logs and the resource record are in
[regression.json](evidence/regression.json) and
[raw_regression.tar.gz](evidence/raw_regression.tar.gz).

The semantic admission recheck uses the original pinned paths. This is a
sealed, source-bound non-start record, **not** a portable route rebuild or
independently rerunnable hardware result. Archive member hashes can be
checked separately without those external dependencies.

From the simulator root, use a fresh output directory:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.row_line.route \
  --build /data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806 \
  --study /data/chuxiao/experiments/sharded_k4_row_line_20261011/attempt-v1 \
  --host /data/chuxiao/experiments/sharded_k4_row_line_20261011/host-v2 \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output /data/chuxiao/experiments/fresh_row_line_route \
  --execute

python3 -m unittest discover -s tests -p 'test_sharded_k4_row_line_route.py'
```

The recorded attempt is
`/data/chuxiao/experiments/sharded_k4_row_line_route_20261011/attempt-v1`.
Keep it unchanged. A retry must use a new directory and recheck all inputs.
Even a successful link still requires routed timing/connectivity admission
and paired resident board executions before admitting FPGA timing. The
[resident-graph model evidence](../model/real_graph/README.md) remains a
separate prediction checkpoint, not a substitute for that gate.
