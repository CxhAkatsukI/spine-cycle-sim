# Occupied-Row RTL Schedule

## Finding

Both measured routed adapters produce the same twelve helper traces. An
empty call completes after 73 clocks. For an occupied call, the helper's
pipeline delay overlaps memory responses and output: it is **not another
73 clocks to append after the last packet**. The final packet handshake
and helper completion occur at the same observed cycle in these tests.

This resolves a modeling ambiguity, not the remaining FPGA timing gap.
No simulator parameter, profile, plugin or hardware source is changed here.
The real-graph v4 campaign retains its separately frozen source identity.

| Begin segment | Segments | Mock response delay | Initial sink stall | Start to done |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 1 | 0 | 73 |
| 0 | 1 | 1 | 0 | 75 |
| 0 | 2 | 1 | 0 | 77 |
| 0 | 8 | 1 | 0 | 89 |
| 0 | 1 | 64 | 0 | 75 |
| 0 | 8 | 64 | 0 | 89 |
| 0 | 1 | 100 | 0 | 105 |
| 0 | 8 | 100 | 0 | 119 |
| 0 | 8 | 1 | 150 | 165 |
| 3 | 8 | 64 | 150 | 165 |
| 3 | 64 | 64 | 0 | 201 |
| 0 | 0 | 1 | 100 | 73 |

All units are helper clocks. With no output stall and mock delays of 1 or
64, the tested occupied calls take `73 + 2 * segments` clocks. This is an
observation for these inputs, not a general whole-adapter timing formula.
Longer responses and output backpressure demonstrably delay completion.

## What Is Checked

The helpers, parent modules and flow-control RTL are pinned to the same
two routed builds as the [empty-row probe](../empty_row_rtl/README.md).
The parent is retained for protocol review but is not elaborated. Repeated
helper calls deassert start on ready and wait for done without resetting
between calls. The test checks every requested address, response count,
edge word, TKEEP/TSTRB, TLAST, packet count and restart/completion handshake.
Offset and segment-count cases cross both even/odd and cache/DDR PMA routes.

The interface is the generated helper's **internal** HLS interface:
ARADDR is a 64-byte word address and ARLEN is a beat count. It is not the
external AXI interface's byte address / beats-minus-one encoding. ARREADY
is always high, RFIFONUM is zero, and a synthetic responder supplies data.
These tests do not reproduce HBM banks, AXI credits or full-system contention.

The first exploratory bench used the wrong address units; the second
checked counts before the clock edge consuming combinational done and the
last packet. Their failing logs are preserved, not admitted. Attempt 3
corrected those testbench issues and passed; the final owner-run replay
reproduces all twelve traces on each helper. Neither RTL body was edited.
The checker requires complete traces and rejects fatal/error messages even
when the simulator process exits with code zero.

## Reproduction And Package

The [report](schedule.json), [hash index](schedule_raw_index.json) and
`raw_schedule.tar.gz` contain both final RTL runs, pinned sources, command
and resource records, exploratory test logs and the small Python owner.
The exact bench is `cpp/tests/routed_regraph/occupied_segment_handshake_tb.sv`.
The execution and packaging owners are `segment_schedule.py` and
`segment_schedule_delivery.py` in `spine_cycle_sim/experiments/sharded_k4_stages/`.

From an extracted `final/original` or `final/candidate` directory:

```bash
xvlog --sv occupied_segment_handshake_tb.sv \
  pma_to_regraph_adapter_pma_to_regraph_adapter_Pipeline_segment_loop.v \
  pma_to_regraph_adapter_flow_control_loop_pipe_sequential_init.v
xelab occupied_segment_handshake_tb -s occupied_segment
xsim occupied_segment -tclbatch run.tcl
```

Add `--define OPTIMIZED` to `xvlog` for the candidate's generated port names.
The automated runner calls Vivado 2024.1 sequentially with a 120-second tool
timeout, 4-GiB child limit and 16-GiB free-memory reserve. Its public entry is
`run_probe(root, sources, output, vivado_bin)`; `sources` must contain
`original/` and `candidate/` with the pinned RTL and `run.tcl`. Output must
be a fresh directory. Package a final run through
`package_probe(root, campaign, output)`, with the run at `campaign/final`.

Portable validation, without Vivado:

```bash
python3 -m unittest tests.test_sharded_k4_segment_schedule \
  tests.test_sharded_k4_segment_schedule_package
```

This is component RTL evidence, **not** new FPGA timing, a full-adapter
calibration, or original-A4 performance matching. In particular it does not
justify adding a constant to make the remaining real-graph mismatch vanish.
