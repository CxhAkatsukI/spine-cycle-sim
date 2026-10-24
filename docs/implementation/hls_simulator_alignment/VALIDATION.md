# Validation Scope And Reproduction

## Environment And Limits

Checks ran on `trifoliate`, Linux `6.1.0-35-amd64`, x86-64, GCC `15.2.0-14`,
Python `3.13.12`, using HLS 2024.1 headers and `/opt/xilinx/xrt`.
After reboot approximately 225 GiB of 251 GiB RAM was available, with no swap.
Small compile/test jobs ran sequentially with an 8 GiB per-process address-space
limit and a 1200-second timeout. These limits do not constitute aggregate FPGA
build containment. No Vitis synthesis or link job was launched.

G+R tests ran on the source changes subsequently committed as `8a46817`.
Four final command packets were generated from that clean commit. Their inputs
record `GRI_GIT_TRACKED_DIRTY=0` and the external dependency hashes. Small unit
test commands are not FPGA compiler invocations.

## Checks And Interpretation

| Raw log | Result | What is not proved |
| --- | --- | --- |
| `adapter.log` | Weighted, destination-only and unit formats each pass 132 cases and 48,244 packets | Actual burst overlap, achieved II or finite RTL liveness |
| `framed_alias_fix.log` | SSSP/CC/PR, manual and actual-adapter input: 36 checks; integer Apply: 12 checks | A complete on-device multi-round algorithm run |
| `host_prefetch.log`, `host_legacy.log` | Four host programs compile and six-partition CPU preparation/oracles pass | Device invocation, FPGA timing or large-graph convergence |
| `adapter_selection_final.log` | Eleven unittest cases, including four-algorithm/two-target generation and early budget refusal | Actual new XO master metadata or routing |
| `build_regression_final.log` | Ten unittest cases and two top-level generator checks pass | Hardware performance matching |
| `spine_sparse.build.log`, `spine_sparse.run.log` | Forced macro-enabled focused Spine test passes | Synthesis, sparse timing or oracle-replay removal |

The framed C++ model reports a maximum stream depth of 32,768; HLS C++ streams
are not the finite RTL channels. Tests check values, ordering, reset/reuse and
termination, not a cycle-accurate proof of their bounded hardware composition.
Integer Apply tests use the established policy function as oracle and test its
plumbing. PR Gather uses independently computed exact binary-fraction values.
Adapter inputs assume validated monotone/aligned row directories; malformed
input fallback is not correctness admission.

## Preserved Failures

`apply_alias_initial_failure.log` is a genuine C++ failure, before the final fix:
an integer Apply write request overlapped an unfinished old-state read on the
same allocation. The final reader sends a per-burst completion token and the
writer waits before announcing that burst. The successful repeated test covers
both separate and aliased allocations. A C-simulation-only mutex protects the
vendor burst object's non-thread-safe pointer bookkeeping; it is not hardware.
RTL ordering, synthesis alias handling and timing still require validation.

`adapter_selection_initial_failure.log` records a missing `BUILD_DIR` key in a
new test fixture; it was corrected to use the generated build path.
`build_regression_initial_failure.log` records an invocation without required
external source-root environment variables. Neither is a numerical result.
The corresponding `*_final.log` files are the successful reruns; failures were
not overwritten to present an uninterrupted pass history.

## Reproduce G+R Checks

From the pinned G+R HLS repository, choose fresh output directories:

```bash
export GRASU_ROOT=/home/chuxiao/GraSU
export REGRAPH_ROOT=/home/chuxiao/regraph/ReGraph
export HLS_INCLUDE=/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include
export XILINX_XRT=/opt/xilinx/xrt
prlimit --as=8589934592 -- timeout 1200 bash scripts/check_pma_prefetch_compact.sh --out-dir /data/chuxiao/checks/adapter-NEW
prlimit --as=8589934592 -- timeout 1200 bash scripts/check_regraph_framed.sh --out-dir /data/chuxiao/checks/framed-NEW
OUT_DIR=/data/chuxiao/checks/host-NEW prlimit --as=8589934592 -- timeout 1200 bash scripts/check_sharded_k4_native_host.sh --prefetch-compact
OUT_DIR=/data/chuxiao/checks/legacy-NEW prlimit --as=8589934592 -- timeout 1200 bash scripts/check_sharded_k4_native_host.sh
prlimit --as=8589934592 -- timeout 1200 env PYTHONPATH=tests:. python3 -m unittest -v test_pma_adapter_selection
prlimit --as=8589934592 -- timeout 1200 env PYTHONPATH=tests:. python3 -m unittest -v test_check_pipeline_master_budget test_check_xo_master_budget test_prepare_pagerank_pipeline_build test_grasu_kernel_selection test_prepare_algorithm_policy_hls_build
```

The last command also invokes the two top-level generator checks. Test cases
use synthetic XO archives to verify early rejection of the expected 34/39/40
master topology, before sourcing tool settings; these are not synthesized XOs.

To regenerate inspection-only build packets, use the commands in the pinned
[G+R source guide](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/8a46817c102a411d70f43f05fa530e32be0806df/docs/sharded_k4_prefetch_compact/README.md#generate-later-build-packets).
The archived packet scripts contain machine-local paths; do not run them from
this documentation directory. No complete-system link is currently admitted.

## Reproduce Spine Check

From `tests/test_integration` in the pinned Spine HLS repository:

```bash
prlimit --as=8589934592 -- timeout 1200 make -B -j1 host_pagerank_compute_protocol_test SPINE_RESIDUAL_SPARSE_APPLY=1 XILINX_HLS=/data/yxx/tools/xilinx/Vitis_HLS/2024.1 XILINX_XRT=/opt/xilinx/xrt
prlimit --as=8589934592 -- timeout 1200 ./host_pagerank_compute_protocol_test
```

The eighteen-executable host-suite pass is recorded in the pinned Spine guide
from earlier in this task. This package's fresh raw Spine log covers the focused
macro-enabled rebuild/rerun, not a new run of all eighteen executables.
