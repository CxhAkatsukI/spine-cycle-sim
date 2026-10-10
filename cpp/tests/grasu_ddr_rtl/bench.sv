`timescale 1ns/1ps

module grasu_ddr_bench;
  logic clk = 0, reset_n = 0;
  always #2.5 clk = ~clk;
  logic [3:0] arvalid, arready, rvalid, rready, rlast, rid, arid;
  logic [3:0] awvalid, awready, wvalid, wready, wlast, bvalid, bready, bid, awid;
  logic [63:0] araddr[4], awaddr[4], wstrb[4];
  logic [7:0] arlen[4], awlen[4];
  logic [2:0] arsize[4], awsize[4];
  logic [1:0] arburst[4], awburst[4];
  logic [511:0] rdata[4], wdata[4];
  logic awv = 0, awr, wv = 0, wr, bv, br = 1;
  logic [5:0] control_address = 0;
  logic [31:0] control_data = 0;
  logic stream_valid = 0, stream_ready;
  logic [95:0] stream_data = 0, updates[64];
  logic memory_idle;
  integer update_count, gap, max_cycles, done_cycle = -1, first_start = -1, output_file;
  string updates_path, output_path;

  grasu_shared_memory memory(.clk(clk), .reset_n(reset_n), .arvalid(arvalid), .arready(arready),
    .araddr(araddr), .arlen(arlen), .arsize(arsize), .arburst(arburst), .arid(arid),
    .rvalid(rvalid), .rready(rready), .rdata(rdata), .rlast(rlast), .rid(rid),
    .awvalid(awvalid), .awready(awready), .awaddr(awaddr), .awlen(awlen), .awsize(awsize),
    .awburst(awburst), .awid(awid), .wvalid(wvalid), .wready(wready), .wdata(wdata),
    .wstrb(wstrb), .wlast(wlast), .bvalid(bvalid), .bready(bready), .bid(bid), .idle(memory_idle));

`define MEMORY_PORT(N) \
    .m_axi_gmem``N``_ARVALID(arvalid[N]), .m_axi_gmem``N``_ARREADY(arready[N]), \
    .m_axi_gmem``N``_ARADDR(araddr[N]), .m_axi_gmem``N``_ARLEN(arlen[N]), \
    .m_axi_gmem``N``_ARSIZE(arsize[N]), .m_axi_gmem``N``_ARBURST(arburst[N]), .m_axi_gmem``N``_ARID(arid[N]), \
    .m_axi_gmem``N``_RVALID(rvalid[N]), .m_axi_gmem``N``_RREADY(rready[N]), .m_axi_gmem``N``_RDATA(rdata[N]), \
    .m_axi_gmem``N``_RLAST(rlast[N]), .m_axi_gmem``N``_RID(rid[N]), .m_axi_gmem``N``_RRESP(2'b00), .m_axi_gmem``N``_RUSER(1'b0), \
    .m_axi_gmem``N``_AWVALID(awvalid[N]), .m_axi_gmem``N``_AWREADY(awready[N]), \
    .m_axi_gmem``N``_AWADDR(awaddr[N]), .m_axi_gmem``N``_AWLEN(awlen[N]), \
    .m_axi_gmem``N``_AWSIZE(awsize[N]), .m_axi_gmem``N``_AWBURST(awburst[N]), .m_axi_gmem``N``_AWID(awid[N]), \
    .m_axi_gmem``N``_WVALID(wvalid[N]), .m_axi_gmem``N``_WREADY(wready[N]), .m_axi_gmem``N``_WDATA(wdata[N]), \
    .m_axi_gmem``N``_WSTRB(wstrb[N]), .m_axi_gmem``N``_WLAST(wlast[N]), \
    .m_axi_gmem``N``_BVALID(bvalid[N]), .m_axi_gmem``N``_BREADY(bready[N]), .m_axi_gmem``N``_BID(bid[N]), \
    .m_axi_gmem``N``_BRESP(2'b00), .m_axi_gmem``N``_BUSER(1'b0)

  process_ddr dut(.ap_clk(clk), .ap_rst_n(reset_n),
    .s_axi_control_AWVALID(awv), .s_axi_control_AWREADY(awr), .s_axi_control_AWADDR(control_address),
    .s_axi_control_WVALID(wv), .s_axi_control_WREADY(wr), .s_axi_control_WDATA(control_data), .s_axi_control_WSTRB(4'hf),
    .s_axi_control_BVALID(bv), .s_axi_control_BREADY(br), .s_axi_control_ARVALID(1'b0),
    .s_axi_control_ARADDR(6'b0), .s_axi_control_RREADY(1'b1),
    .update_stream_TVALID(stream_valid), .update_stream_TREADY(stream_ready), .update_stream_TDATA(stream_data),
    .update_stream_TKEEP(12'hfff), .update_stream_TSTRB(12'hfff), .update_stream_TLAST(1'b0),
    `MEMORY_PORT(0), `MEMORY_PORT(1), `MEMORY_PORT(2), `MEMORY_PORT(3));
`undef MEMORY_PORT

  task automatic control_write(input logic [5:0] address, input logic [31:0] value);
    @(negedge clk); control_address = address; awv = 1;
    do @(posedge clk); while (!awr);
    @(negedge clk); awv = 0; control_data = value; wv = 1;
    do @(posedge clk); while (!wr);
    @(negedge clk); wv = 0;
    do @(posedge clk); while (!bv);
  endtask

  task automatic send(input logic [95:0] value);
    @(negedge clk); stream_data = value; stream_valid = 1;
    do @(posedge clk); while (!stream_ready);
    $display("DDR_INPUT cycle=%0d data=%024h", memory.cycle, value);
    @(negedge clk); stream_valid = 0;
  endtask

  always @(negedge clk) begin
    if (reset_n && dut.ap_start && first_start < 0) first_start = memory.cycle;
    if (reset_n && dut.ap_done && done_cycle < 0) done_cycle = memory.cycle;
    if (reset_n && memory.cycle > max_cycles) $fatal(1, "DDR RTL did not complete and drain");
  end

  initial begin
    if (!$value$plusargs("COUNT=%d", update_count) || update_count < 0 || update_count > 64 ||
        !$value$plusargs("GAP=%d", gap) || gap < 0 || !$value$plusargs("MAX_CYCLES=%d", max_cycles) ||
        !$value$plusargs("UPDATES=%s", updates_path) || !$value$plusargs("OUTPUT=%s", output_path))
      $fatal(1, "missing DDR RTL fixture arguments");
    if (update_count > 0) $readmemh(updates_path, updates, 0, update_count - 1);
    repeat (8) @(negedge clk); reset_n = 1;
    // All four host arguments alias one original physical PMA allocation.
    control_write(6'h10, 0); control_write(6'h14, 0);
    control_write(6'h1c, 0); control_write(6'h20, 0);
    control_write(6'h28, 0); control_write(6'h2c, 0);
    control_write(6'h34, 0); control_write(6'h38, 0);
    control_write(0, 1);
    for (integer i = 0; i < update_count; i = i + 1) begin
      if (i > 0) repeat (gap) @(negedge clk);
      send(updates[i]);
    end
    send(96'h00000000ffffffffffffffff);
    wait (done_cycle >= 0 && memory_idle);
    repeat (3) @(negedge clk);
    if (memory.reads != update_count || memory.writes != update_count ||
        memory.read_acks != update_count || memory.write_acks != update_count ||
        memory.service_count != update_count * 2 || !memory_idle || first_start < 0)
      $fatal(1, "DDR RTL request/ack/service conservation failed");
    output_file = $fopen(output_path, "w");
    if (!output_file) $fatal(1, "cannot write complete RTL memory capture");
    for (integer i = 0; i < 32; i = i + 1) $fdisplay(output_file, "%0128h", memory.memory[i]);
    $fclose(output_file);
    $display("DDR_RTL_RESULT {\"protocol_passed\":true,\"updates\":%0d,\"start_cycle\":%0d,\"done_cycle\":%0d,\"drained_cycle\":%0d,\"reads\":%0d,\"writes\":%0d,\"read_acks\":%0d,\"write_acks\":%0d}",
      update_count, first_start, done_cycle, memory.cycle, memory.reads, memory.writes, memory.read_acks, memory.write_acks);
    $finish;
  end
endmodule
