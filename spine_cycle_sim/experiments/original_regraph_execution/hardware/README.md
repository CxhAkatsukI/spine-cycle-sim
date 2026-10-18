# Original ReGraph Hardware Preflight

This owner audits the original author path before any board launch. It does
not implement a simulator speed factor, program a board, or admit a paper
performance match. The publication A, source A4 and actual adapter/K4 controls
remain separate experiments.

| Module | Responsibility |
| --- | --- |
| `sources.py` | Clean revision and literal reviewed host/device bindings |
| `oracle.py` | Frozen CSR/task gather equality, two explicit fixed-point PR divisor bindings and publication allocation |
| `artifact.py` | Read-only xclbin topology, actual DATA clock and saved timing inspection |
| `study.py` | Fixed six-input audit, bounded extraction and unchanged transitive identities |
| `delivery.py` | Raw recheck and portable metadata/log/source capsule; no promoted hardware claim |
| `checkpoint.py`, `checkpoint.tcl` | Read-only native checkpoint clocks/timing and exact embedded-partial comparison; no altered constraints |
| `checkpoint_run.py` | Independent atomic memory reservation, bounded query and frozen provenance |
| `checkpoint_delivery.py` | Recheck terminal observations and seal a separate metadata/source capsule without admitting hardware timing |
| `control_inputs.py` | Encode descriptors from the exact report/layout/captures pinned by the independent audit; do not silently update an old source checkpoint |
| `control_analysis.py` | Independent oracle hashes, publication padding, guards and complete offline matrix |
| `control_build.py` | Explicit Xilinx OpenCL linkage/runpath and independent loader identity check; reject a generic CUDA ICD |
| `control_validation.py` | Finite-memory Release/UBSan compilation and 48-run offline host validation, including launch rejection |
| `control_delivery.py` | Recheck raw results and package sources/metadata with failed attempts, without board-performance claims |
| [source_build/](source_build/README.md) | Explicit clean-source 11+3/A4 compilation and routing with independent memory admission; no board execution |
| [board_execution/](board_execution/README.md) | Exact-invocation conditional queue, independent artifact readmission and eighteen guarded board controls; no publication-match claim |
| [semantics/](semantics/README.md) | Explicit original fixed-point versus candidate K4 binary32 payload audit; neither default-semantic equivalence nor measured performance |
| [k4_control/](k4_control/README.md) | Actual production-layout offline A4/K4 control, independent values, guards and explicit unsupported inputs; no hardware timing |

Read the [hardware campaign's original-R checkpoint](../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/README.md)
for results and reproduction. The oracle relies on the earlier complete author
layout admission for task scheduling and source-window allocation. It separately
rechecks capture identities, CSR degrees, gather conservation, signed arithmetic
and output bounds. It is one static PR superstep with `arg=0`, not weighted SSSP,
residual PR or convergence. Both bindings are exposed without changing author
device code or claiming that either reproduces the publication's algorithm.

`SYSTEM_METADATA` contains JSON but XRT requires the `RAW` extraction format.
A saved requested-clock timing failure must not be silently treated as a failure
at an automatically reduced bitstream clock. Conversely, an extracted clock
alone does not establish checkpoint/bitstream/timing identity or source equality.

The checkpoint probe uses the same finite-budget admission ledger as routing.
Other FPGA tools do not block it when their full bounded budgets, its 20-GiB
limit, a 24-GiB reserve and an 8-GiB background allowance fit. It requires
cgroup v2 hard/high limits, zero swap and group OOM handling. Its 1,200-second
read-only Vivado query cannot program a board or rewrite the author artifact.

## Guarded Host Control

The optional [C++ host](../../../../cpp/tests/original_regraph/hardware/README.md)
supports the reviewed 11+3 and separately generated A4 device ABIs; the board
owner requires a distinct matching admitted artifact for each. Its offline
layout/oracle checks support both named topologies. Host changes
make publication allocation safe and expose the two divisor bindings explicitly;
the author device code is unchanged.

The fixed matrix is two topologies x three graphs x two divisor bindings x
two repetitions x Release/UBSan = 48 offline runs. Full expected outputs,
publication padding and guards are checked against the independently audited
CSR/task oracle. No device is enumerated or programmed in offline mode.
Both board geometries must reject a missing external lease. Legacy reports
that instead rejected the unsupported A4 ABI remain valid historical offline
evidence but cannot authorize this new A4 board path.

New controls link `/opt/xilinx/xrt/lib/libxilinxopencl.so` explicitly and set
that directory's runpath. Release and UBSan loader checks must resolve that
exact library; the runtime inputs and complete loaded dependencies are pinned.
The earlier generic `-lOpenCL` binary resolved to CUDA on this machine and was
correctly rejected by the board runtime gate before any host launch. Recompile
and repeat the complete offline matrix in a fresh output; do not weaken the
runtime gate or change the old validated binary in place. No device logic or
timing boundary is changed by this host-link repair.

```bash
systemd-run --user --wait --pipe --unit=original-r-control-fresh \
  -p MemoryMax=4G -p MemoryHigh=3584M -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=100% -p AllowedCPUs=123 -p RuntimeMaxSec=900 \
  -p TimeoutStopSec=30 -p KillMode=control-group -p TasksMax=128 \
  --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.control_validation \
  --captures "$PWD/docs/experiments/comparisons/grasu_regraph_stage_validation/input_results.json" \
  --audit /path/to/successful/offline-audit \
  --output /path/to/fresh/offline-control
```

By default memory admission fails immediately if full peer budgets plus the
reserve do not fit. To queue safely, use `--wait-seconds 64800 --poll-seconds 10`
and increase the service's finite lifetime accordingly. The waiting loop freezes
and rechecks source/audit identities before any compiler starts; it admits work
while other FPGA tools remain active when all budgets fit. Unknown/unbounded
peers prevent admission. The service itself retains its 4-GiB hard limit and
zero-swap containment throughout the wait and validation.

`--captures` is the exact **report file** pinned by that audit, not a substitute
raw run directory. Its large captured inputs must still be available and match
their recorded hashes. The older simulator preparation gate remains unchanged:
later source improvements are not silently accepted as historical source
equivalence. This separate hardware control consumes the exact audited captures
and validates them again in the strict C++ loader and independent oracle.
