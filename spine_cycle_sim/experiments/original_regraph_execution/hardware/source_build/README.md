# Fresh Original-R Source Build

This package owns a fresh author-source 11-Little/3-Big build on U55C at
150 MHz. It is separate from the read-only prebuilt probe and from board
execution. It does not reproduce the original publication's graph-selected
best configuration or its original clock/platform performance.

| Module | Responsibility |
| --- | --- |
| `configuration.py` | Six unique XOs, eighteen CUs, fixed signed-PR macros, isolated compiler directories and exact host ABI |
| `snapshot.py` | Clean pinned author revision, tracked-file snapshot, six permitted topology-generator outputs and unchanged identities |
| `gates.py` | Compiled arguments/macros/control protocol, HLS part/clock, routed HBM/CU/clock topology and strict setup/hold/pulse timing |
| `execution.py` | Independent atomic finite-memory admission, sequential XO compilation, routing watchdog and retained failure/provenance |
| `__main__.py` | Thin CLI |

The author's topology generator runs with `11 3 true false`. No device
algorithm source is edited. `KERNEL_NUM=14` is explicit build bookkeeping;
the original Makefile supplied an empty value and no device code uses it.
The author mergers are free-running (`ap_ctrl_none`) with stream arguments
only. Apply, wrapper and scatter/gather use `ap_ctrl_chain`; the guarded host
launches those kernels, not the mergers. HBM arguments preserve the author
bank mapping, including the apply divisor on bank 30.

Compilation requires the passing independent input audit and the complete
48-run Release/UBSan offline host control, with all their pins unchanged.
This does not convert offline correctness into a hardware measurement.
Both explicit divisor bindings remain separate board controls.

## Memory And Concurrency

Launch in a cgroup v2 service with 40-GiB hard, 36-GiB high and zero-swap
limits, `OOMPolicy=kill`, and a bounded lifetime. Atomic admission requires
available memory to cover this full 40-GiB limit, every other bounded build's
full limit, a 24-GiB reserve and 8-GiB background allowance. Other FPGA tools
need not exit if those budgets fit. Unknown/unbounded peers prevent launch.
The process-tree watchdog retains a 32-GiB live reserve, limits tree RSS to
40 GiB and kills only owned workers on timeout, error or budget exhaustion.
Each XO has 1,800 seconds; link has 21,600 seconds. XOs compile sequentially
inside this one budget; the independent G build may continue concurrently.

```bash
systemd-run --user --unit=original-r-source-fresh \
  -p MemoryMax=40G -p MemoryHigh=36G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=400% -p RuntimeMaxSec=36000 -p TasksMax=4096 \
  -p TimeoutStopSec=30 -p KillMode=control-group \
  --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build \
  --upstream /path/to/clean/pinned/regraph \
  --audit /path/to/passing/input-audit \
  --control /path/to/passing/offline-control \
  --environment /path/to/reviewed/2024.1/environment.json \
  --output /path/to/fresh/source-build
```

Source copies, environment, commands, unique temporary directories, compiler
logs and resource records remain under that fresh output directory. Raw runs
stay outside Git. No source/tool/profile identity may change during a build.
Automatic DATA-frequency reduction is rejected, as are failed setup, hold
or pulse-width timing. Successful implementation is only
`ORIGINAL_R_ROUTED_CLOCK_TOPOLOGY_TIMING_PASS_AWAITING_BOARD`; guarded board
correctness, repetitions, performance comparison and publication matching
remain later gates. No board is programmed by this runner.
