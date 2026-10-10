`timescale 1ns/1ps

// Four AXI ports share one physical store and one beat-service arbiter.
// Requests are finite; read data is captured at service, not at AR acceptance.
module grasu_shared_memory (
    input logic clk, reset_n,
    input logic [3:0] arvalid, rready, awvalid, wvalid, bready,
    input logic [63:0] araddr [4], awaddr [4],
    input logic [7:0] arlen [4], awlen [4],
    input logic [2:0] arsize [4], awsize [4],
    input logic [1:0] arburst [4], awburst [4],
    input logic [3:0] arid, awid, wlast,
    input logic [511:0] wdata [4],
    input logic [63:0] wstrb [4],
    output logic [3:0] arready, rvalid, rlast, rid, awready, wready, bvalid, bid,
    output logic [511:0] rdata [4],
    output logic idle
);
  localparam integer DEPTH = 16;
  localparam integer FIRST = 131072;
  logic [511:0] memory [32];
  integer latency, cycle, rr, service_count, reads, writes, read_acks, write_acks;
  integer rq_head[4], rq_tail[4], rq_count[4], aq_head[4], aq_tail[4], aq_count[4];
  integer wq_head[4], wq_tail[4], wq_count[4];
  integer rq_line[4][DEPTH], rq_due[4][DEPTH], aq_line[4][DEPTH], aq_due[4][DEPTH], wq_due[4][DEPTH];
  logic rq_id[4][DEPTH], aq_id[4][DEPTH];
  logic [511:0] wq_data[4][DEPTH];
  string initial_path;
  integer chosen, port, line_index;
  integer response_line[4];

  initial begin
    if (!$value$plusargs("LATENCY=%d", latency) || latency < 1) $fatal(1, "missing/invalid latency");
    if (!$value$plusargs("INITIAL=%s", initial_path)) $fatal(1, "missing initial memory");
    $readmemh(initial_path, memory);
  end

  function automatic integer index_of(input logic [63:0] address);
    if ($isunknown(address) || address[5:0] != 0 || address / 64 < FIRST || address / 64 >= FIRST + 32)
      $fatal(1, "shared memory address outside the admitted cold region: %h", address);
    return integer'(address / 64 - FIRST);
  endfunction

  always_comb begin
    idle = !(|rvalid) && !(|bvalid);
    for (integer p = 0; p < 4; p = p + 1)
      idle = idle && rq_count[p] == 0 && aq_count[p] == 0 && wq_count[p] == 0;
  end

  always @(posedge clk) begin
    if (!reset_n) begin
      cycle = 0; rr = 0; service_count = 0; reads = 0; writes = 0; read_acks = 0; write_acks = 0;
      arready <= 0; awready <= 0; wready <= 0; rvalid <= 0; bvalid <= 0;
      rlast <= 0; rid <= 0; bid <= 0;
      for (integer p = 0; p < 4; p = p + 1) begin
        rq_head[p] = 0; rq_tail[p] = 0; rq_count[p] = 0;
        aq_head[p] = 0; aq_tail[p] = 0; aq_count[p] = 0;
        wq_head[p] = 0; wq_tail[p] = 0; wq_count[p] = 0;
        rdata[p] <= 0;
      end
    end else begin
      cycle = cycle + 1;
      for (integer p = 0; p < 4; p = p + 1) begin
        if (rvalid[p] && rready[p]) begin
          rvalid[p] <= 0; read_acks = read_acks + 1;
          $display("DDR_RACK cycle=%0d port=%0d line=%0d", cycle, p, response_line[p]);
        end
        if (bvalid[p] && bready[p]) begin
          bvalid[p] <= 0; write_acks = write_acks + 1;
          $display("DDR_BACK cycle=%0d port=%0d line=%0d", cycle, p, response_line[p]);
        end
        if (arvalid[p] && arready[p]) begin
          if (p >= 2 || arlen[p] != 0 || arsize[p] != 6 || arburst[p] != 1 || rq_count[p] >= DEPTH)
            $fatal(1, "invalid read port/burst/capacity");
          rq_line[p][rq_tail[p]] = index_of(araddr[p]);
          rq_due[p][rq_tail[p]] = cycle + latency;
          rq_id[p][rq_tail[p]] = arid[p];
          rq_tail[p] = (rq_tail[p] + 1) % DEPTH; rq_count[p] = rq_count[p] + 1; reads = reads + 1;
          $display("DDR_AR cycle=%0d port=%0d line=%0d", cycle, p, index_of(araddr[p]));
        end
        if (awvalid[p] && awready[p]) begin
          if (p < 2 || awlen[p] != 0 || awsize[p] != 6 || awburst[p] != 1 || aq_count[p] >= DEPTH)
            $fatal(1, "invalid write port/burst/capacity");
          aq_line[p][aq_tail[p]] = index_of(awaddr[p]);
          aq_due[p][aq_tail[p]] = cycle + latency; aq_id[p][aq_tail[p]] = awid[p];
          aq_tail[p] = (aq_tail[p] + 1) % DEPTH; aq_count[p] = aq_count[p] + 1;
          $display("DDR_AW cycle=%0d port=%0d line=%0d", cycle, p, index_of(awaddr[p]));
        end
        if (wvalid[p] && wready[p]) begin
          if (p < 2 || !wlast[p] || wstrb[p] != 64'hffffffffffffffff || wq_count[p] >= DEPTH)
            $fatal(1, "invalid write beat/strobe/capacity");
          wq_data[p][wq_tail[p]] = wdata[p]; wq_due[p][wq_tail[p]] = cycle + latency;
          wq_tail[p] = (wq_tail[p] + 1) % DEPTH; wq_count[p] = wq_count[p] + 1; writes = writes + 1;
          $display("DDR_W cycle=%0d port=%0d", cycle, p);
        end
      end
      chosen = -1;
      for (integer offset = 0; offset < 4; offset = offset + 1) begin
        port = (rr + offset) % 4;
        if (chosen < 0 && port < 2 && rq_count[port] > 0 && !rvalid[port] && rq_due[port][rq_head[port]] <= cycle)
          chosen = port;
        if (chosen < 0 && port >= 2 && aq_count[port] > 0 && wq_count[port] > 0 && !bvalid[port] &&
            aq_due[port][aq_head[port]] <= cycle && wq_due[port][wq_head[port]] <= cycle) chosen = port;
      end
      if (chosen >= 0) begin
        port = chosen; rr = (port + 1) % 4; service_count = service_count + 1;
        if (port < 2) begin
          line_index = rq_line[port][rq_head[port]];
          response_line[port] = line_index;
          rdata[port] <= memory[line_index]; rid[port] <= rq_id[port][rq_head[port]];
          rvalid[port] <= 1; rlast[port] <= 1;
          rq_head[port] = (rq_head[port] + 1) % DEPTH; rq_count[port] = rq_count[port] - 1;
          $display("DDR_READ cycle=%0d port=%0d line=%0d", cycle, port, line_index);
        end else begin
          line_index = aq_line[port][aq_head[port]];
          response_line[port] = line_index;
          memory[line_index] = wq_data[port][wq_head[port]];
          bid[port] <= aq_id[port][aq_head[port]]; bvalid[port] <= 1;
          aq_head[port] = (aq_head[port] + 1) % DEPTH; aq_count[port] = aq_count[port] - 1;
          wq_head[port] = (wq_head[port] + 1) % DEPTH; wq_count[port] = wq_count[port] - 1;
          $display("DDR_WRITE cycle=%0d port=%0d line=%0d", cycle, port, line_index);
        end
      end
      for (integer p = 0; p < 4; p = p + 1) begin
        arready[p] <= p < 2 && rq_count[p] < DEPTH;
        awready[p] <= p >= 2 && aq_count[p] < DEPTH;
        wready[p] <= p >= 2 && wq_count[p] < DEPTH;
      end
    end
  end
endmodule
