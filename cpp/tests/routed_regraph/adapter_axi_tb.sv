`timescale 1ns/1ps
// External AXI byte addresses and LEN=beats-1, unlike the helper-only probe.
module adapter_axi_tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst_n = 0;
  reg awvalid = 0, wvalid = 0, bready = 0;
  reg [6:0] awaddr = 0;
  reg [31:0] wdata = 0;
  wire awready, wready, bvalid;
  wire [1:0] bresp;
  wire arvalid, rready, outvalid, outlast, mem_awvalid, mem_wvalid;
  wire [63:0] araddr, outkeep, outstrb;
  wire [7:0] arlen;
  wire [2:0] arsize;
  wire [1:0] arburst;
  wire arid;
  reg rvalid = 0, rlast = 0, rid = 0, outready = 1;
  reg [511:0] rdata = 0;
  wire [511:0] outdata;

  pma_to_regraph_adapter dut (
    .ap_clk(clk), .ap_rst_n(rst_n),
    .s_axi_control_AWVALID(awvalid), .s_axi_control_AWREADY(awready),
    .s_axi_control_AWADDR(awaddr), .s_axi_control_WVALID(wvalid),
    .s_axi_control_WREADY(wready), .s_axi_control_WDATA(wdata),
    .s_axi_control_WSTRB(4'hf), .s_axi_control_BVALID(bvalid),
    .s_axi_control_BREADY(bready), .s_axi_control_BRESP(bresp),
    .s_axi_control_ARVALID(1'b0), .s_axi_control_ARADDR(7'b0),
    .s_axi_control_RREADY(1'b1),
    .m_axi_gmem0_AWVALID(mem_awvalid), .m_axi_gmem0_AWREADY(1'b0),
    .m_axi_gmem0_WVALID(mem_wvalid), .m_axi_gmem0_WREADY(1'b0),
    .m_axi_gmem0_BVALID(1'b0), .m_axi_gmem0_BRESP(2'b0),
    .m_axi_gmem0_BID(1'b0), .m_axi_gmem0_BUSER(1'b0),
    .m_axi_gmem0_ARVALID(arvalid), .m_axi_gmem0_ARREADY(1'b1),
    .m_axi_gmem0_ARADDR(araddr), .m_axi_gmem0_ARLEN(arlen),
    .m_axi_gmem0_ARSIZE(arsize), .m_axi_gmem0_ARBURST(arburst),
    .m_axi_gmem0_ARID(arid), .m_axi_gmem0_RVALID(rvalid),
    .m_axi_gmem0_RREADY(rready), .m_axi_gmem0_RDATA(rdata),
    .m_axi_gmem0_RLAST(rlast), .m_axi_gmem0_RID(rid),
    .m_axi_gmem0_RRESP(2'b0), .m_axi_gmem0_RUSER(1'b0),
    .edge_burst_out_TREADY(outready), .edge_burst_out_TVALID(outvalid),
    .edge_burst_out_TDATA(outdata), .edge_burst_out_TKEEP(outkeep),
    .edge_burst_out_TSTRB(outstrb), .edge_burst_out_TLAST(outlast)
  );

  localparam [63:0] ROW_BASE = 64'h80000;
  reg [63:0] rows [0:71];
  reg [511:0] banks [0:3][0:127];
  reg [511:0] expected [0:255];
  reg [63:0] request_address [0:511];
  integer request_length [0:511], request_size [0:511], due [0:511];
  reg request_id [0:511];
  integer cycle = 0, trial = -1, vertices = 0, slots = 0;
  integer issued = 0, retired = 0, beat = 0, responses = 0, packets = 0;
  integer row_requests = 0, row_beats = 0, pma_requests = 0, pma_beats = 0;
  integer row_transfer_bytes = 0, pma_transfer_bytes = 0;
  integer delay_cycles = 1, sink_delay = 0, expected_packets = 0;
  integer accepted = -1, completed = -1, first_packet = -1, last_packet = -1;
  integer lane, source, segment, bank, local_index, half, cursor, index;
  reg [63:0] address;
  reg [31:0] raw;
  reg held_output = 0, held_last = 0;
  reg [511:0] held_data = 0;
  reg [63:0] held_keep = 0, held_strb = 0;

  function [511:0] read_word(input [63:0] byte_address);
    integer b, i, j;
    reg [63:0] aligned;
    begin
      aligned = byte_address & ~64'd63;
      read_word = 0;
      if (aligned >= ROW_BASE && aligned < ROW_BASE + 576) begin
        i = (aligned - ROW_BASE) / 8;
        for (j = 0; j < 8; j = j + 1) read_word[j*64 +: 64] = rows[i+j];
      end else begin
        b = (aligned / 65536) - 1;
        i = (aligned % 65536) / 64;
        if (b < 0 || b > 3 || i >= 128) $fatal(1, "unmapped read %h", byte_address);
        read_word = banks[b][i];
      end
    end
  endfunction

  always @(posedge clk) begin
    cycle <= cycle + 1;
    if (rst_n) begin
      if (held_output && (!outvalid || outdata !== held_data || outlast !== held_last
                          || outkeep !== held_keep || outstrb !== held_strb))
        $fatal(1, "AXIS packet changed under backpressure");
      held_output = outvalid && !outready;
      held_data = outdata; held_last = outlast; held_keep = outkeep; held_strb = outstrb;
      if (mem_awvalid || mem_wvalid) $fatal(1, "read-only adapter issued a write");
      // This HLS control deasserts ap_idle combinationally when ap_start rises.
      if (dut.ap_start && accepted < 0) accepted = cycle;
      if (dut.ap_done && completed < 0) completed = cycle;
      if (arvalid) begin
        if (issued >= 512 || arsize > 6 || arburst !== 2'b01
            || araddr % (1 << arsize) != 0
            || (araddr % 4096) + ((arlen + 1) << arsize) > 4096)
          $fatal(1, "invalid AXI read burst");
        request_address[issued] = araddr;
        request_length[issued] = arlen + 1;
        request_size[issued] = 1 << arsize;
        request_id[issued] = arid;
        due[issued] = cycle + delay_cycles;
        issued = issued + 1;
        if (araddr >= ROW_BASE) begin
          if (araddr + ((arlen + 1) << arsize) > ROW_BASE + ((vertices == 0 ? 8 : vertices + 7) / 8) * 64)
            $fatal(1, "row read outside padded row table");
          row_requests = row_requests + 1;
          row_beats = row_beats + arlen + 1;
          row_transfer_bytes = row_transfer_bytes + ((arlen + 1) << arsize);
        end else begin
          pma_requests = pma_requests + 1;
          pma_beats = pma_beats + arlen + 1;
          pma_transfer_bytes = pma_transfer_bytes + ((arlen + 1) << arsize);
        end
        $display("AXI_AR trial=%0d cycle=%0d address=%0d beats=%0d size=%0d", trial, cycle, araddr, arlen+1, 1 << arsize);
      end
      if (rvalid && rready) begin
        $display("AXI_R trial=%0d cycle=%0d address=%0d size=%0d last=%0d", trial, cycle,
                 request_address[retired] + beat * request_size[retired],
                 request_size[retired], rlast);
        responses = responses + 1;
        beat = beat + 1;
        if (beat == request_length[retired]) begin
          retired = retired + 1;
          beat = 0;
        end
        rvalid <= 0;
      end
      if ((!rvalid || rready) && retired < issued && cycle >= due[retired]) begin
        address = request_address[retired] + beat * request_size[retired];
        rdata <= read_word(address);
        rlast <= beat + 1 == request_length[retired];
        rid <= request_id[retired];
        rvalid <= 1;
      end
      if (outvalid && outready) begin
        if (packets >= expected_packets || outdata !== expected[packets]
            || outkeep !== 64'hffffffffffffffff || outstrb !== 64'hffffffffffffffff
            || outlast !== (packets + 1 == expected_packets))
          $fatal(1, "packet or sideband differs trial=%0d packet=%0d", trial, packets);
        if (first_packet < 0) first_packet = cycle;
        last_packet = cycle;
        packets = packets + 1;
      end
    end else held_output = 0;
  end

  task write_control(input [6:0] offset, input [31:0] value);
    integer began;
    begin
      @(negedge clk); awaddr = offset; awvalid = 1; began = cycle;
      do @(posedge clk); while (!awready && cycle - began < 100);
      if (!awready) $fatal(1, "AXI-Lite address timeout");
      @(negedge clk); awvalid = 0; wdata = value; wvalid = 1;
      do @(posedge clk); while (!wready && cycle - began < 100);
      if (!wready) $fatal(1, "AXI-Lite data timeout");
      @(negedge clk); wvalid = 0;
      while (!bvalid && cycle - began < 100) @(negedge clk);
      if (!bvalid || bresp !== 0) $fatal(1, "AXI-Lite response failed");
      bready = 1;
      @(negedge clk); bready = 0;
    end
  endtask

  task run_case(input integer count, input integer placement, input integer length,
                input integer latency, input integer stall);
    begin
      @(negedge clk); rst_n = 0; rvalid = 0; awvalid = 0; wvalid = 0;
      repeat (5) @(negedge clk);
      trial = trial + 1; vertices = count; slots = 0; expected_packets = 0;
      issued = 0; retired = 0; beat = 0; responses = 0; packets = 0;
      row_requests = 0; row_beats = 0; pma_requests = 0; pma_beats = 0;
      row_transfer_bytes = 0; pma_transfer_bytes = 0;
      accepted = -1; completed = -1; first_packet = -1; last_packet = -1;
      delay_cycles = latency; sink_delay = stall; outready = stall == 0;
      for (index = 0; index < 72; index = index + 1) rows[index] = 0;
      for (bank = 0; bank < 4; bank = bank + 1)
        for (index = 0; index < 128; index = index + 1) banks[bank][index] = 0;
      for (source = 0; source < count; source = source + 1) begin
        cursor = slots;
        if (placement == 0 || (placement == 1 && source + 1 == count)
            || (placement == 2 && source == 0) || (placement == 3 && source % 7 == 0)) begin
          for (segment = 0; segment < length; segment = segment + 1) begin
            bank = ((slots / 16) < 4 ? 0 : 1) + (((slots / 16) % 2) ? 2 : 0);
            local_index = slots / 32;
            for (lane = 0; lane < 16; lane = lane + 1) begin
              raw = ((slots / 16 + 1) << 19) | (lane % 32);
              if (lane % 3 == 0) raw = raw | 32'h80000000;
              banks[bank][local_index][lane*32 +: 32] = raw;
              half = lane / 8;
              expected[expected_packets + half][(lane%8)*64 +: 32] =
                  source | (lane % 3 == 0 ? 32'h80000000 : 0);
              expected[expected_packets + half][(lane%8)*64+32 +: 32] = raw;
            end
            expected_packets = expected_packets + 2;
            slots = slots + 16;
          end
        end
        rows[source] = (64'(cursor) << 32) | slots;
      end
      rst_n = 1;
      repeat (5) @(negedge clk);
      write_control('h10, 'h10000); write_control('h14, 0);
      write_control('h1c, 'h20000); write_control('h20, 0);
      write_control('h28, 'h30000); write_control('h2c, 0);
      write_control('h34, 'h40000); write_control('h38, 0);
      write_control('h40, ROW_BASE); write_control('h44, 0);
      write_control('h4c, count); write_control('h54, slots);
      write_control('h5c, 2); write_control('h64, 65536);
      write_control('h6c, 32); write_control('h00, 1);
      index = cycle;
      while (completed < 0 && cycle - index < 20000) begin
        @(negedge clk);
        if (accepted >= 0 && cycle - accepted >= sink_delay) outready = 1;
      end
      repeat (3) @(negedge clk);
      if (accepted < 0 || completed < accepted || issued != retired || rvalid
          || responses != row_beats + pma_beats || packets != expected_packets)
        $fatal(1, "incomplete adapter trial=%0d requests=%0d retired=%0d packets=%0d", trial, issued, retired, packets);
      $display("AXI_CASE trial=%0d vertices=%0d placement=%0d length=%0d latency=%0d stall=%0d start=%0d cycles=%0d row_requests=%0d row_beats=%0d row_transfer_bytes=%0d pma_requests=%0d pma_beats=%0d pma_transfer_bytes=%0d packets=%0d first_packet=%0d last_packet=%0d done=%0d", trial, count, placement, length, latency, stall, accepted, completed-accepted, row_requests, row_beats, row_transfer_bytes, pma_requests, pma_beats, pma_transfer_bytes, packets, first_packet, last_packet, completed);
    end
  endtask

  initial begin
    run_case(0, 0, 1, 1, 0);
    run_case(1, 0, 1, 1, 0);
    run_case(8, 0, 1, 1, 0);
    run_case(9, 0, 1, 1, 0);
    run_case(17, 0, 1, 1, 0);
    run_case(17, 0, 1, 64, 0);
    run_case(17, 0, 1, 128, 0);
    run_case(17, 0, 3, 64, 0);
    run_case(17, 1, 1, 64, 0);
    run_case(17, 2, 1, 64, 0);
    run_case(17, 3, 1, 64, 0);
    run_case(17, 0, 1, 64, 1000);
    $display("ADAPTER_AXI_PASS cases=12");
    $finish;
  end
endmodule
