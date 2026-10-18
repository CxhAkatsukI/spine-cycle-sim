# Remote Production Routing

## Scope

Use the high-memory `seele` host for compilation/routing, not FPGA measurement.
It has no Xilinx FPGA device. Board admission and measurement remain on
`trifoliate`. The production source, eleven XOs, 22 CUs, connections, SLR
placement, 150-MHz target and two-job settings are unchanged. This is a new
attempt with an explicitly recorded remote toolchain/platform, not a retry
written over the earlier attempt or a new algorithm-performance result.

The owning code is
`spine_cycle_sim/experiments/evaluation_impact/common_g/complete_pipeline/hardware/remote/`:
`capsule.py` exports/verifies immutable inputs and relocates only tool/output
paths; `environment.py` captures the explicit vendor/platform closure;
`study.py` owns admission, preflight and the bounded link; `__main__.py` is
the thin CLI. The production board gate must separately admit a returned
artifact and its remote provenance; no old manifest is rewritten to do so.

## Inputs And Environment

The parent is the [reviewed production packet](../README.md), raw directory
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-production-route-v1`.
Its manifest SHA-256 is
`f75ec64b70c5e65d2d7c79658b59097387eb9af3a5ac6b11e28b4cab6a663ae0`.
All 2485 parent pins were checked while exporting the fresh relocation capsule.
The original manifest is copied byte-for-byte. Every copied XO, source member,
connectivity file and compiler shim has an indexed hash tied to that parent.
Paths in legacy include flags remain unchanged: this run links frozen XOs,
not source files. An include path is not evidence of fresh source compilation.

Remote roots:

- Tools: `/data/feiyang/xilinx`, Vitis/Vivado/Vitis_HLS 2024.1.
- Compatibility libraries: `/data/feiyang/xilinx/compat-2024.1`.
- Platform: `/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm`.
- Owned outputs: `/data/chuxiao/baseline_hardware_validation_20261017/`.

Freeze the runner with `git archive` at the tested commit, transfer that
archive and the capsule, and extract them in new directories. The environment
capture pins settings/loaders, launchers, host compilers, platform files and
compatibility libraries. It does not claim to hash every vendor executable.
Six checks must pass before routing: Vitis/Vivado/GCC/G++ versions, host-thread
compilation with the reviewed shim, and execution of that test binary.

## Resource Contract

The inspection found 499 GiB total and approximately 488 GiB available RAM,
128 logical CPUs and 1.2 TiB free under `/data`. These are observations, not
permission for unbounded concurrency. Each route retains a 40-GiB hard limit,
36-GiB high watermark, zero swap and group OOM kill. Admission reserves 32 GiB
for the system, 8 GiB for background activity, and each peer build's full
finite limit. Unknown/unbounded FPGA compiler peers block admission. Concurrent
bounded builds are allowed when the budgets fit; no all-tools-idle rule exists.

At least 160 GiB free build disk is required before environment preparation.
The link deadline is twelve hours, admission queue is at most one day, and the
service lifetime must cover both. The live tree-RSS/available-memory watchdog
remains active after admission. Use `OOMPolicy=kill` with systemd; the kernel
`memory.oom.group` value is independently checked by the runner.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote prepare \
  --parent /path/to/frozen-production-route \
  --output /path/to/fresh-capsule

# Run from the frozen runner inside its bounded user service on seele.
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote execute \
  --capsule /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-sssp-route-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

## Acceptance And Figures

`execution.json` records live/terminal status, and `manifest.json` freezes
the relocated command and inputs. `LINK_PASS_AWAITING_TIMING_AND_BOARD` means
only that linking returned successfully and produced the indexed binary.
Strict routed timing/topology, production G state/metadata, resident physical
PMA handoff and board performance remain separate gates.

The same-platform original A4 control now passes its fresh 18-row FPGA matrix
in `a4-board-supervisor-v3` (invocation
`e0c7225785574947aa931e5646025dea`): three graphs, two argument bindings,
three repetitions. Its boundary is one resident signed fixed-point PR
superstep, not convergence or host-inclusive dynamic update. It is not a
published-throughput reproduction. The original publication topology and
this resource-matched control must not be substituted for one another.

Final Figures 7--11 still require the latest integrated baseline and fixed
Spine comparisons. Keep FPGA latency, host-inclusive throughput, conserved
traffic/modeled HBM energy, predicted normalized stages, and realized-work
model validation distinct. No historical figure or paper is changed by the
remote route launch.
