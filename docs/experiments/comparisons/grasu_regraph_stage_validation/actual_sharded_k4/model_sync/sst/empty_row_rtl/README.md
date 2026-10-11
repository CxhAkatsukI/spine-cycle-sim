# Empty-Row RTL Exit

## Finding

The segment-loop helper in **both measured routed adapters** takes 73 clocks
from start to completion for an empty row. Its exit condition is accepted
after one clock, but completion follows 72 clocks later. There are no AXI
read requests or edge-output transfers during that interval. This is an
HLS control/pipeline-exit cost, not a 73-cycle HBM read and not a value fitted
to the FPGA end-to-end time.

The current v1--v3 simulator skips directly to the next source when the row's
begin and end offsets are equal. It therefore lacks this separate wait.
The [fixed-PMA board sweep](../empty_rows/README.md) had already isolated a
related discrepancy: roughly 981--993 ns per added empty row on the old
FPGA, versus 520 ns in the model. The RTL finding is a concrete candidate
explanation; incorporating it does not by itself admit whole-system timing.

## Experiment

This is direct simulation of the generated Verilog helper copied from each
routed link directory, not a new synthesis of today's HLS worktree. The
parent module is retained to audit its start/ready/done protocol. The test
deasserts start when the helper accepts it and waits for done, exactly as the
parent does. Repeated calls do not reset the helper.

| Invocation | Empty begin/end, segments | Output-ready delay, cycles | Start to exit | Start to done |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0 | 0 | 1 | 73 |
| 2 | 16 | 0 | 1 | 73 |
| 3 | 4096 | 0 | 1 | 73 |
| 4 | 16 | 20 | 1 | 73 |
| 5 | 16 | 100 | 1 | 73 |
| 6 | 0 | 0 | 1 | 73 |

Both adapters pass all six invocations. The delay of 100 keeps output ready
low beyond completion, checking that an empty call does not depend on a
consumer. Any AXI ARVALID, edge TVALID, stale completion, missing handshake
or completion timeout fails the test. Memory never returns a response.

The old parent asserts helper start in state 148, retires it on helper ready,
and remains in state 149 until helper done. The optimized parent uses states
77/78 for the corresponding call/wait. The helpers retain a 36-iteration
exit pipeline with II=2. Their exact source identities and elapsed traces,
not this explanatory arithmetic alone, establish the 73-clock result.

## Evidence Boundary

- This is an RTL component observation. It is not a new board measurement,
  an exclusive FPGA stage counter, or a complete adapter timing calibration.
- It covers empty rows that are actually visited. Stop-after-last must still
  skip trailing rows; no delay should be charged to rows never invoked.
- It does not establish the exit latency after an occupied row, or the
  timing of prefetch, source service, AXI transport and host relaunch.
- Keep the 71-cycle model read-to-use floor and this exit cost conceptually
  separate. Changing a memory-delay multiplier would conceal the issue.
- A new model must preserve old profiles/results and validate both empty
  and nonempty paths, early stream completion, restart and finite traffic.

The first exploratory test incorrectly held start until done, allowing
repeated loop injections. Its logs and testbench are retained as rejected
evidence. Only the corrected start/ready handshake test is admitted; a
printed PASS banner from the first test is not an acceptance gate.

## Reproduction

The raw package includes both routed helpers, their flow-control module,
parents, testbenches and Vivado 2024.1 command/resource records. Run the
following separately in each extracted arm directory:

The sealed [report](rtl.json) and [file index](rtl_raw_index.json) identify
`raw_rtl.tar.gz`, the tested sources, both target bitstreams, and the rejected
first test. The helpers came from the following routed IP directories, not
from a synthesis of the current integration worktree:

- Original: `/data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806/build/link/link/sys_link/iprepo/xilinx_com_hls_pma_to_regraph_adapter_1_0/hdl/verilog/`.
- Optimized: `/data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/route_combined_sssp/link/link/sys_link/iprepo/xilinx_com_hls_pma_to_regraph_adapter_1_0/hdl/verilog/`.

```bash
xvlog --sv pma_to_regraph_adapter_flow_control_loop_pipe_sequential_init.v \
  pma_to_regraph_adapter_pma_to_regraph_adapter_Pipeline_segment_loop.v \
  empty_segment_handshake_tb.sv
xelab empty_segment_handshake_tb -s empty_segment_handshake
xsim empty_segment_handshake -tclbatch run.tcl
```

The parent is inspected but not elaborated by this isolated test. Each tool
invocation used a 120-second timeout, 4-GiB child limit and 16-GiB available
memory reserve. Testbench port names differ between the two generated
helpers; neither helper body is edited.
