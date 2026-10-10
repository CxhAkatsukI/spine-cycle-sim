`timescale 1ns/1ps

// Independent AXI master: no GraSU RTL participates in this bus-model test.
module grasu_memory_test;
  logic clk = 0, reset_n = 0;
  always #2.5 clk = ~clk;
  logic [3:0] arvalid = 0, rready = 0, awvalid = 0, wvalid = 0, bready = 0;
  logic [63:0] araddr[4], awaddr[4], wstrb[4];
  logic [7:0] arlen[4], awlen[4];
  logic [2:0] arsize[4], awsize[4];
  logic [1:0] arburst[4], awburst[4];
  logic [3:0] arid = 0, awid = 0, wlast = 4'hf;
  logic [511:0] wdata[4], rdata[4];
  logic [3:0] arready, rvalid, rlast, rid, awready, wready, bvalid, bid;
  logic idle;
  integer mode, services = 0;
  logic [511:0] original, held;
  localparam logic [511:0] VALUE = {16{32'h12345678}};
  grasu_shared_memory memory(.*);

  always @(negedge clk) if (reset_n) begin
    if (memory.cycle > 8000) $fatal(1, "bus selftest timeout");
    if (memory.service_count - services < 0 || memory.service_count - services > 1)
      $fatal(1, "more than one shared service per cycle");
    services = memory.service_count;
  end

  task automatic address(input integer p, input integer line_index, input bit write_address);
    @(negedge clk);
    if (write_address) begin
      awaddr[p] = (131072 + line_index) * 64; awvalid[p] = 1;
      do @(posedge clk); while (!awready[p]);
      @(negedge clk); awvalid[p] = 0;
    end else begin
      araddr[p] = (131072 + line_index) * 64; arvalid[p] = 1;
      do @(posedge clk); while (!arready[p]);
      @(negedge clk); arvalid[p] = 0;
    end
  endtask

  task automatic data(input integer p);
    @(negedge clk); wdata[p] = VALUE; wvalid[p] = 1;
    do @(posedge clk); while (!wready[p]);
    @(negedge clk); wvalid[p] = 0;
  endtask

  task automatic accept_write(input integer p);
    wait (bvalid[p]);
    repeat (8) begin
      @(negedge clk);
      if (!bvalid[p] || bid[p] != awid[p]) $fatal(1, "write response changed under backpressure");
    end
    bready[p] = 1;
    @(negedge clk); bready[p] = 0;
  endtask

  task automatic accept_read(input integer p, input logic [511:0] expected);
    wait (rvalid[p]);
    held = rdata[p];
    repeat (8) begin
      @(negedge clk);
      if (!rvalid[p] || !rlast[p] || rid[p] != arid[p] || rdata[p] !== held || held !== expected)
        $fatal(1, "read response data/id changed or alias store differs");
    end
    rready[p] = 1;
    @(negedge clk); rready[p] = 0;
  endtask

  initial begin
    if (!$value$plusargs("MODE=%d", mode)) $fatal(1, "missing bus selftest mode");
    for (integer p = 0; p < 4; p = p + 1) begin
      araddr[p] = 131072 * 64; awaddr[p] = 131072 * 64;
      arlen[p] = 0; awlen[p] = 0; arsize[p] = 6; awsize[p] = 6;
      arburst[p] = 1; awburst[p] = 1; wstrb[p] = '1; wdata[p] = VALUE;
    end
    repeat (8) @(negedge clk); reset_n = 1;
    repeat (2) @(negedge clk);
    if (arready[3:2] || awready[1:0] || wready[1:0]) $fatal(1, "unsupported port supplied credit");
    if (mode == 1 || mode == 2) begin
      araddr[0] = 131072 * 64 + (mode == 1 ? 1 : 0);
      arlen[0] = mode == 2 ? 1 : 0;
      arvalid[0] = 1;
      repeat (4) @(negedge clk);
      $fatal(1, "invalid read was not rejected");
    end
    if (mode == 3) begin
      wstrb[2] = 1;
      data(2);
      $fatal(1, "partial write was not rejected");
    end
    if (mode != 0) $fatal(1, "unknown bus test mode");
    original = memory.memory[0];
    awid[2] = 1;
    address(2, 0, 1);
    repeat (80) @(negedge clk);
    if (bvalid[2] || memory.memory[0] !== original) $fatal(1, "AW without W modified memory");
    data(2);
    // AR precedes visibility of the write but is serviced after it.
    address(0, 0, 0);
    accept_write(2);
    accept_read(0, VALUE);
    arid[1] = 1; awid[3] = 1;
    data(3);
    repeat (80) @(negedge clk);
    if (bvalid[3]) $fatal(1, "W without AW produced a response");
    address(3, 1, 1);
    accept_write(3);
    address(1, 1, 0);
    accept_read(1, VALUE);
    // One held response and sixteen pending reads exhaust this port.
    for (integer i = 0; i < 17; i = i + 1) address(0, 0, 0);
    repeat (80) @(negedge clk);
    if (memory.rq_count[0] != 16 || arready[0] || !rvalid[0]) $fatal(1, "finite read queue did not saturate");
    held = rdata[0]; arvalid[0] = 1;
    repeat (24) begin
      @(negedge clk);
      if (arready[0] || memory.rq_count[0] != 16 || rdata[0] !== held)
        $fatal(1, "queue or held response changed without credit");
    end
    rready[0] = 1;
    do @(posedge clk); while (!arready[0]);
    @(negedge clk); arvalid[0] = 0;
    wait (idle);
    repeat (3) @(negedge clk);
    if (memory.reads != 20 || memory.read_acks != 20 || memory.writes != 2 || memory.write_acks != 2 || services != 22)
      $fatal(1, "bus selftest complete conservation differs");
    $display("DDR_BUS_SELFTEST_PASS alias=1 delayed_pairing=1 stable_responses=1 finite_backpressure=1 one_service=1 reads=20 writes=2");
    $finish;
  end
endmodule
