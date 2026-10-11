`timescale 1ns/1ps
// Internal HLS interface: ARADDR uses 64-byte words; ARLEN is a beat count.
module occupied_segment_handshake_tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst = 1, start = 0, ready = 1;
  reg [27:0] begin_segment = 0;
  reg [28:0] end_segment = 0;
  wire done, helper_ready, arvalid, rready, outvalid, outlast;
  wire [63:0] araddr, outkeep, outstrb;
  wire [31:0] arlen;
  wire [511:0] outdata;
  reg rvalid = 0;
  reg [511:0] rdata = 0;
  integer cycle = 0, issued = 0, responded = 0, packets = 0;
  integer due [0:255];
  integer delay_cycles = 1, first_packet = -1, last_packet = -1;
  integer lane, segment;
  reg [63:0] expected_address;
  reg [31:0] expected_dst;

  pma_to_regraph_adapter_pma_to_regraph_adapter_Pipeline_segment_loop dut (
    .ap_clk(clk), .ap_rst(rst), .ap_start(start), .ap_done(done), .ap_ready(helper_ready),
    .m_axi_gmem0_AWREADY(1'b0), .m_axi_gmem0_WREADY(1'b0),
    .m_axi_gmem0_ARREADY(1'b1), .m_axi_gmem0_ARVALID(arvalid),
    .m_axi_gmem0_ARADDR(araddr), .m_axi_gmem0_ARLEN(arlen),
    .m_axi_gmem0_RVALID(rvalid), .m_axi_gmem0_RREADY(rready), .m_axi_gmem0_RDATA(rdata),
    .m_axi_gmem0_RLAST(1'b1), .m_axi_gmem0_RID(1'b0),
    .m_axi_gmem0_RFIFONUM(9'b0), .m_axi_gmem0_RUSER(1'b0), .m_axi_gmem0_RRESP(2'b0),
    .m_axi_gmem0_BVALID(1'b0), .m_axi_gmem0_BRESP(2'b0),
    .m_axi_gmem0_BID(1'b0), .m_axi_gmem0_BUSER(1'b0),
    .edge_burst_out_TREADY(ready), .edge_burst_out_TVALID(outvalid),
    .edge_burst_out_TDATA(outdata), .edge_burst_out_TKEEP(outkeep),
    .edge_burst_out_TSTRB(outstrb), .edge_burst_out_TLAST(outlast),
`ifdef OPTIMIZED
    .zext_ln246(begin_segment), .zext_ln247(end_segment),
    .zext_ln128({begin_segment, 4'b0}), .zext_ln241({end_segment[27:0], 4'b0}),
    .zext_ln211({end_segment[27:0], 4'b0}), .zext_ln208(33'd4),
`else
    .zext_ln201(begin_segment), .zext_ln202(end_segment),
    .zext_ln108({begin_segment, 4'b0}), .zext_ln196({end_segment[27:0], 4'b0}),
    .zext_ln181({end_segment[27:0], 4'b0}), .zext_ln178(33'd4),
`endif
    .emitted_slots({32'b0, begin_segment, 4'b0}),
    .part_vertex_count(32'd65536), .out_src(32'h80000003), .src(32'd3),
    .pma0(64'h100000), .pma2(64'h200000), .pma1(64'h300000), .pma3(64'h400000)
  );

  always @(posedge clk) begin
    cycle <= cycle + 1;
    if (rst || (start && helper_ready)) start <= 0;
    if (!rst && arvalid) begin
      segment = begin_segment + issued;
      expected_address = ((segment < 4 ? 64'h100000 : 64'h300000)
                         + (segment % 2 ? 64'h100000 : 0)) / 64 + segment / 2;
      if (issued >= 256 || segment >= end_segment || araddr !== expected_address || arlen !== 1)
        $fatal(1, "unexpected segment request index=%0d addr=%h expected=%h len=%0d", issued, araddr, expected_address, arlen);
      due[issued] = cycle + delay_cycles;
      issued = issued + 1;
    end
    if (!rst && rvalid && rready) begin
      responded = responded + 1;
      rvalid <= 0;
    end
    if (!rst && (!rvalid || rready) && responded < issued && cycle >= due[responded]) begin
      for (lane = 0; lane < 16; lane = lane + 1)
        rdata[lane * 32 +: 32] <= 32'h80000 + responded * 16 + lane;
      rvalid <= 1;
    end
    if (!rst && outvalid && ready) begin
      for (lane = 0; lane < 8; lane = lane + 1) begin
        expected_dst = 32'h80000 + packets * 8 + lane;
        if (outdata[lane * 64 +: 32] !== 3 || outdata[lane * 64 + 32 +: 32] !== expected_dst)
          $fatal(1, "edge payload differs packet=%0d lane=%0d", packets, lane);
      end
      if (outkeep !== 64'hffffffffffffffff || outstrb !== 64'hffffffffffffffff
          || outlast !== (packets + 1 == 2 * (end_segment - begin_segment)))
        $fatal(1, "edge sideband differs");
      if (first_packet < 0) first_packet = cycle;
      last_packet = cycle;
      packets = packets + 1;
    end
  end

  task run_case(input integer offset, input integer count, input integer latency, input integer ready_delay);
    integer accepted, exit_cycle, done_cycle;
    begin
      @(negedge clk);
      if (rvalid || issued != responded) $fatal(1, "unfinished memory responses");
      begin_segment = offset;
      end_segment = offset + count;
      issued = 0; responded = 0; packets = 0;
      first_packet = -1; last_packet = -1;
      delay_cycles = latency;
      ready = (ready_delay == 0);
      start = 1; accepted = cycle; exit_cycle = -1;
      #1;
      if (done) $fatal(1, "stale completion");
      while (!done && cycle - accepted < 5000) begin
        @(negedge clk);
        if (helper_ready && exit_cycle < 0) exit_cycle = cycle;
        if (cycle - accepted >= ready_delay) ready = 1;
      end
      done_cycle = cycle;
      // Sample the rising edge that consumes the combinational done/last beat.
      @(negedge clk);
      if (!done || start || exit_cycle < accepted || issued != count || responded != count || packets != count * 2)
        $fatal(1, "incomplete helper: done=%b requests=%0d responses=%0d packets=%0d", done, issued, responded, packets);
      $display("SEGMENT offset=%0d count=%0d latency=%0d ready_delay=%0d start=%0d exit=%0d first_packet=%0d last_packet=%0d done=%0d elapsed=%0d", offset, count, latency, ready_delay, accepted, exit_cycle, first_packet, last_packet, done_cycle, done_cycle - accepted);
      repeat (5) @(negedge clk);
    end
  endtask

  initial begin
    repeat (5) @(negedge clk);
    rst = 0;
    repeat (5) @(negedge clk);
    run_case(0, 0, 1, 0);
    run_case(0, 1, 1, 0);
    run_case(0, 2, 1, 0);
    run_case(0, 8, 1, 0);
    run_case(0, 1, 64, 0);
    run_case(0, 8, 64, 0);
    run_case(0, 1, 100, 0);
    run_case(0, 8, 100, 0);
    run_case(0, 8, 1, 150);
    run_case(3, 8, 64, 150);
    run_case(3, 64, 64, 0);
    run_case(0, 0, 1, 100);
    $display("SEGMENT_PASS cases=12");
    $finish;
  end
endmodule
