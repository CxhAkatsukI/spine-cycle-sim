`timescale 1ns/1ps
// Read-only observer of the unchanged production XO and AXI bench.
`define TB adapter_axi_tb
`define ROW_HELPER `TB.dut.`ADAPTER_HELPER
module occupied_row_monitor;
  reg previous_start = 0;
  reg active = 0;
  integer source = -1;
  always @(posedge `TB.clk) begin
    if (!`TB.rst_n) begin
      previous_start = 0;
      active = 0;
      source = -1;
    end else begin
      if (`ROW_HELPER.ap_start && !previous_start) begin
        if (active) $fatal(1, "overlapping occupied-row helper invocation");
        active = 1;
        source = `ROW_HELPER.src;
        $display("ROW_START trial=%0d cycle=%0d source=%0d begin=%0d end=%0d",
                 `TB.trial, `TB.cycle, source, `ROW_HELPER.begin_r, `ROW_HELPER.end_r);
      end
      // HLS also holds ap_done high while this helper is idle after reset.
      if (`ROW_HELPER.ap_done && active) begin
        $display("ROW_DONE trial=%0d cycle=%0d source=%0d", `TB.trial, `TB.cycle, source);
        active = 0;
      end
      if (`TB.outvalid && `TB.outready)
        $display("ROW_PACKET trial=%0d cycle=%0d source=%0d",
                 `TB.trial, `TB.cycle, `TB.outdata[30:0]);
      previous_start = `ROW_HELPER.ap_start;
    end
  end
endmodule
