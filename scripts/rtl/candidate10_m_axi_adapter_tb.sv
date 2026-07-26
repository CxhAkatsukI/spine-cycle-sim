`timescale 1ns/1ps

module candidate10_m_axi_adapter_tb;
  localparam integer QUEUE_DEPTH = 512;

  logic clk = 1'b0;
  logic reset = 1'b1;
  always #5 clk = ~clk;

  integer op_arg;
  integer requests_arg;
  integer start_word_arg;
  integer beats_arg;
  integer stride_words_arg;
  integer response_delay_arg;
  integer ar_stall_period_arg;
  integer ar_stall_width_arg;
  integer aw_stall_period_arg;
  integer aw_stall_width_arg;
  integer w_stall_period_arg;
  integer w_stall_width_arg;
  integer r_stall_period_arg;
  integer r_stall_width_arg;
  integer child_r_stall_period_arg;
  integer child_r_stall_width_arg;
  integer child_b_stall_period_arg;
  integer child_b_stall_width_arg;
  integer max_cycles_arg;
  integer trace_arg;
  integer plusarg_status;
  integer cycle_count;
  integer errors;

  wire [0:0] awid;
  wire [63:0] awaddr;
  wire [7:0] awlen;
  wire [2:0] awsize;
  wire [1:0] awburst;
  wire [1:0] awlock;
  wire [3:0] awcache;
  wire [2:0] awprot;
  wire [3:0] awqos;
  wire [3:0] awregion;
  wire [0:0] awuser;
  wire awvalid;
  wire awready;
  wire [0:0] wid;
  wire [63:0] wdata;
  wire [7:0] wstrb;
  wire wlast;
  wire [0:0] wuser;
  wire wvalid;
  wire wready;
  logic [0:0] bid = 0;
  logic [1:0] bresp = 0;
  logic [0:0] buser = 0;
  wire bvalid;
  wire bready;

  wire [0:0] arid;
  wire [63:0] araddr;
  wire [7:0] arlen;
  wire [2:0] arsize;
  wire [1:0] arburst;
  wire [1:0] arlock;
  wire [3:0] arcache;
  wire [2:0] arprot;
  wire [3:0] arqos;
  wire [3:0] arregion;
  wire [0:0] aruser;
  wire arvalid;
  wire arready;
  logic [0:0] rid = 0;
  logic [63:0] rdata = 0;
  logic [1:0] rresp = 0;
  wire rlast;
  logic [0:0] ruser = 0;
  wire rvalid;
  wire rready;

  wire [63:0] child_awaddr;
  wire [31:0] child_awlen;
  wire child_awvalid;
  wire child_awready;
  wire [63:0] child_wdata;
  wire [7:0] child_wstrb;
  wire child_wvalid;
  wire child_wready;
  wire child_bvalid;
  wire child_bready;
  wire [63:0] child_araddr;
  wire [31:0] child_arlen;
  wire child_arvalid;
  wire child_arready;
  wire [63:0] child_rdata;
  wire child_rvalid;
  wire child_rready;
  wire [8:0] child_rfifonum;

  integer child_requests_accepted;
  integer child_write_beats_accepted;
  integer child_read_beats_accepted;
  integer child_responses_accepted;
  integer child_request_stall_cycles;
  integer child_data_stall_cycles;
  integer child_response_stall_cycles;
  integer child_first_request_cycle;
  integer child_last_request_cycle;
  integer child_first_write_cycle;
  integer child_last_write_cycle;
  integer child_first_read_cycle;
  integer child_last_read_cycle;
  integer child_first_response_cycle;
  integer child_last_response_cycle;

  wire child_r_allow = child_r_stall_period_arg == 0 ||
      (cycle_count % child_r_stall_period_arg) >= child_r_stall_width_arg;
  wire child_b_allow = child_b_stall_period_arg == 0 ||
      (cycle_count % child_b_stall_period_arg) >= child_b_stall_width_arg;

  assign child_awvalid = !reset && op_arg == 1 &&
      child_requests_accepted < requests_arg;
  assign child_awaddr = start_word_arg +
      child_requests_accepted * stride_words_arg;
  assign child_awlen = beats_arg;
  assign child_wvalid = !reset && op_arg == 1 &&
      child_write_beats_accepted < requests_arg * beats_arg;
  assign child_wdata = child_write_beats_accepted;
  assign child_wstrb = 8'hff;
  assign child_bready = !reset && child_b_allow;

  assign child_arvalid = !reset && op_arg == 0 &&
      child_requests_accepted < requests_arg;
  assign child_araddr = start_word_arg +
      child_requests_accepted * stride_words_arg;
  assign child_arlen = beats_arg;
  assign child_rready = !reset && child_r_allow;

  reg [63:0] burst_address [0:QUEUE_DEPTH-1];
  reg [31:0] burst_beats [0:QUEUE_DEPTH-1];
  reg [31:0] burst_issue_cycle [0:QUEUE_DEPTH-1];
  integer external_bursts;
  integer external_beats;
  integer external_outstanding;
  integer max_external_outstanding;
  integer external_address_stall_cycles;
  integer external_data_stall_cycles;
  integer external_response_stall_cycles;
  integer external_first_data_cycle;
  integer external_last_data_cycle;
  integer external_first_response_cycle;
  integer external_last_response_cycle;
  integer external_data_events;
  integer external_response_events;

  reg [31:0] read_remaining [0:QUEUE_DEPTH-1];
  reg [31:0] read_ready_cycle [0:QUEUE_DEPTH-1];
  integer read_head;
  integer read_tail;
  integer read_queued;

  reg [31:0] write_remaining [0:QUEUE_DEPTH-1];
  integer write_head;
  integer write_tail;
  integer write_queued;
  reg [31:0] b_ready_cycle [0:QUEUE_DEPTH-1];
  integer b_head;
  integer b_tail;
  integer b_queued;

  wire ar_allow = ar_stall_period_arg == 0 ||
      (cycle_count % ar_stall_period_arg) >= ar_stall_width_arg;
  wire aw_allow = aw_stall_period_arg == 0 ||
      (cycle_count % aw_stall_period_arg) >= aw_stall_width_arg;
  wire w_allow = w_stall_period_arg == 0 ||
      (cycle_count % w_stall_period_arg) >= w_stall_width_arg;
  wire r_allow = r_stall_period_arg == 0 ||
      (cycle_count % r_stall_period_arg) >= r_stall_width_arg;

  assign arready = !reset && ar_allow && read_queued < QUEUE_DEPTH;
  assign rvalid = !reset && r_allow && read_queued != 0 &&
      cycle_count >= read_ready_cycle[read_head];
  assign rlast = rvalid && read_remaining[read_head] == 1;

  assign awready = !reset && aw_allow && write_queued < QUEUE_DEPTH;
  assign wready = !reset && w_allow && write_queued != 0;
  assign bvalid = !reset && b_queued != 0 &&
      cycle_count >= b_ready_cycle[b_head];

  wire ar_handshake = arvalid && arready;
  wire read_handshake = rvalid && rready;
  wire read_last_handshake = read_handshake &&
      read_remaining[read_head] == 1;
  wire aw_handshake = awvalid && awready;
  wire write_handshake = wvalid && wready;
  wire write_last_handshake = write_handshake &&
      write_queued != 0 && write_remaining[write_head] == 1;
  wire b_handshake = bvalid && bready;

  spine_partconv_rdmaint_kernel_gmem_p0_m_axi #(
      .CONSERVATIVE(1),
      .MAX_READ_BURST_LENGTH(16),
      .MAX_WRITE_BURST_LENGTH(16),
      .C_M_AXI_ID_WIDTH(1),
      .C_M_AXI_ADDR_WIDTH(64),
      .C_M_AXI_DATA_WIDTH(64),
      .C_M_AXI_AWUSER_WIDTH(1),
      .C_M_AXI_ARUSER_WIDTH(1),
      .C_M_AXI_WUSER_WIDTH(1),
      .C_M_AXI_RUSER_WIDTH(1),
      .C_M_AXI_BUSER_WIDTH(1),
      .C_TARGET_ADDR(0),
      .CH0_USER_DW(64),
      .CH0_USER_AW(64),
      .NUM_READ_OUTSTANDING(16),
      .NUM_WRITE_OUTSTANDING(16),
      .CH0_USER_RFIFONUM_WIDTH(9),
      .USER_MAXREQS(70),
      .MAXI_BUFFER_IMPL("block")
  ) dut (
      .ACLK(clk), .ARESET(reset), .ACLK_EN(1'b1),
      .AWID(awid), .AWADDR(awaddr), .AWLEN(awlen), .AWSIZE(awsize),
      .AWBURST(awburst), .AWLOCK(awlock), .AWCACHE(awcache),
      .AWPROT(awprot), .AWQOS(awqos), .AWREGION(awregion),
      .AWUSER(awuser), .AWVALID(awvalid), .AWREADY(awready),
      .WID(wid), .WDATA(wdata), .WSTRB(wstrb), .WLAST(wlast),
      .WUSER(wuser), .WVALID(wvalid), .WREADY(wready),
      .BID(bid), .BRESP(bresp), .BUSER(buser), .BVALID(bvalid),
      .BREADY(bready),
      .ARID(arid), .ARADDR(araddr), .ARLEN(arlen), .ARSIZE(arsize),
      .ARBURST(arburst), .ARLOCK(arlock), .ARCACHE(arcache),
      .ARPROT(arprot), .ARQOS(arqos), .ARREGION(arregion),
      .ARUSER(aruser), .ARVALID(arvalid), .ARREADY(arready),
      .RID(rid), .RDATA(rdata), .RRESP(rresp), .RLAST(rlast),
      .RUSER(ruser), .RVALID(rvalid), .RREADY(rready),
      .I_CH0_AWADDR(child_awaddr), .I_CH0_AWLEN(child_awlen),
      .I_CH0_AWVALID(child_awvalid), .I_CH0_AWREADY(child_awready),
      .I_CH0_WDATA(child_wdata), .I_CH0_WSTRB(child_wstrb),
      .I_CH0_WVALID(child_wvalid), .I_CH0_WREADY(child_wready),
      .I_CH0_BVALID(child_bvalid), .I_CH0_BREADY(child_bready),
      .I_CH0_ARADDR(child_araddr), .I_CH0_ARLEN(child_arlen),
      .I_CH0_ARVALID(child_arvalid), .I_CH0_ARREADY(child_arready),
      .I_CH0_RDATA(child_rdata), .I_CH0_RVALID(child_rvalid),
      .I_CH0_RREADY(child_rready), .I_CH0_RFIFONUM(child_rfifonum)
  );

  task report_and_finish;
    integer index;
    begin
      for (index = 0; index < external_bursts; index = index + 1) begin
        $display("AXI_ADAPTER_BURST op=%0d index=%0d addr=%0d beats=%0d issue_cycle=%0d",
                 op_arg, index, burst_address[index], burst_beats[index],
                 burst_issue_cycle[index]);
      end
      $display("AXI_ADAPTER_RTL op=%0d requests=%0d start_word=%0d beats=%0d stride_words=%0d response_delay=%0d cycles=%0d child_requests=%0d child_write_beats=%0d child_read_beats=%0d child_responses=%0d external_bursts=%0d external_beats=%0d max_outstanding=%0d child_request_stalls=%0d child_data_stalls=%0d child_response_stalls=%0d external_address_stalls=%0d external_data_stalls=%0d external_response_stalls=%0d child_first_request_cycle=%0d child_last_request_cycle=%0d child_first_write_cycle=%0d child_last_write_cycle=%0d child_first_read_cycle=%0d child_last_read_cycle=%0d child_first_response_cycle=%0d child_last_response_cycle=%0d external_first_data_cycle=%0d external_last_data_cycle=%0d external_first_response_cycle=%0d external_last_response_cycle=%0d errors=%0d",
               op_arg, requests_arg, start_word_arg, beats_arg,
               stride_words_arg, response_delay_arg, cycle_count,
               child_requests_accepted, child_write_beats_accepted,
               child_read_beats_accepted, child_responses_accepted,
               external_bursts, external_beats, max_external_outstanding,
               child_request_stall_cycles, child_data_stall_cycles,
               child_response_stall_cycles, external_address_stall_cycles,
               external_data_stall_cycles, external_response_stall_cycles,
               child_first_request_cycle, child_last_request_cycle,
               child_first_write_cycle, child_last_write_cycle,
               child_first_read_cycle, child_last_read_cycle,
               child_first_response_cycle, child_last_response_cycle,
               external_first_data_cycle, external_last_data_cycle,
               external_first_response_cycle, external_last_response_cycle,
               errors);
      $finish;
    end
  endtask

  always @(posedge clk) begin
    if (reset) begin
      cycle_count <= 0;
      errors <= 0;
      child_requests_accepted <= 0;
      child_write_beats_accepted <= 0;
      child_read_beats_accepted <= 0;
      child_responses_accepted <= 0;
      child_request_stall_cycles <= 0;
      child_data_stall_cycles <= 0;
      child_response_stall_cycles <= 0;
      child_first_request_cycle <= -1;
      child_last_request_cycle <= -1;
      child_first_write_cycle <= -1;
      child_last_write_cycle <= -1;
      child_first_read_cycle <= -1;
      child_last_read_cycle <= -1;
      child_first_response_cycle <= -1;
      child_last_response_cycle <= -1;
      external_bursts <= 0;
      external_beats <= 0;
      external_outstanding <= 0;
      max_external_outstanding <= 0;
      external_address_stall_cycles <= 0;
      external_data_stall_cycles <= 0;
      external_response_stall_cycles <= 0;
      external_first_data_cycle <= -1;
      external_last_data_cycle <= -1;
      external_first_response_cycle <= -1;
      external_last_response_cycle <= -1;
      external_data_events <= 0;
      external_response_events <= 0;
      read_head <= 0;
      read_tail <= 0;
      read_queued <= 0;
      write_head <= 0;
      write_tail <= 0;
      write_queued <= 0;
      b_head <= 0;
      b_tail <= 0;
      b_queued <= 0;
    end else begin
      cycle_count <= cycle_count + 1;

      if ((child_awvalid && child_awready) ||
          (child_arvalid && child_arready)) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=child_request op=%0d index=%0d cycle=%0d",
                   op_arg, child_requests_accepted, cycle_count);
        child_requests_accepted <= child_requests_accepted + 1;
        if (child_first_request_cycle < 0)
          child_first_request_cycle <= cycle_count;
        child_last_request_cycle <= cycle_count;
      end
      if ((child_awvalid && !child_awready) ||
          (child_arvalid && !child_arready))
        child_request_stall_cycles <= child_request_stall_cycles + 1;
      if (child_wvalid && child_wready) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=child_data op=1 index=%0d cycle=%0d",
                   child_write_beats_accepted, cycle_count);
        child_write_beats_accepted <= child_write_beats_accepted + 1;
        if (child_first_write_cycle < 0)
          child_first_write_cycle <= cycle_count;
        child_last_write_cycle <= cycle_count;
      end
      if (child_wvalid && !child_wready)
        child_data_stall_cycles <= child_data_stall_cycles + 1;
      if (child_rvalid && child_rready) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=child_data op=0 index=%0d cycle=%0d",
                   child_read_beats_accepted, cycle_count);
        child_read_beats_accepted <= child_read_beats_accepted + 1;
        if (child_first_read_cycle < 0)
          child_first_read_cycle <= cycle_count;
        child_last_read_cycle <= cycle_count;
      end
      if (child_rvalid && !child_rready)
        child_response_stall_cycles <= child_response_stall_cycles + 1;
      if (child_bvalid && child_bready) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=child_response op=1 index=%0d cycle=%0d",
                   child_responses_accepted, cycle_count);
        child_responses_accepted <= child_responses_accepted + 1;
        if (child_first_response_cycle < 0)
          child_first_response_cycle <= cycle_count;
        child_last_response_cycle <= cycle_count;
      end
      if (child_bvalid && !child_bready)
        child_response_stall_cycles <= child_response_stall_cycles + 1;

      if ((arvalid && !arready) || (awvalid && !awready))
        external_address_stall_cycles <= external_address_stall_cycles + 1;
      if (wvalid && !wready)
        external_data_stall_cycles <= external_data_stall_cycles + 1;
      if ((rvalid && !rready) || (bvalid && !bready))
        external_response_stall_cycles <= external_response_stall_cycles + 1;

      if (ar_handshake) begin
        burst_address[external_bursts] <= araddr;
        burst_beats[external_bursts] <= arlen + 1;
        burst_issue_cycle[external_bursts] <= cycle_count;
        external_bursts <= external_bursts + 1;
        external_beats <= external_beats + arlen + 1;
        read_remaining[read_tail] <= arlen + 1;
        read_ready_cycle[read_tail] <= cycle_count + response_delay_arg;
        read_tail <= (read_tail + 1) % QUEUE_DEPTH;
        if (arsize != 3 || arburst != 1)
          errors <= errors + 1;
      end
      if (read_handshake) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=external_data op=0 index=%0d cycle=%0d last=%0d",
                   external_data_events,
                   cycle_count, read_last_handshake);
        external_data_events <= external_data_events + 1;
        rdata <= rdata + 1;
        if (external_first_data_cycle < 0)
          external_first_data_cycle <= cycle_count;
        external_last_data_cycle <= cycle_count;
        if (read_remaining[read_head] == 1) begin
          read_head <= (read_head + 1) % QUEUE_DEPTH;
        end else begin
          read_remaining[read_head] <= read_remaining[read_head] - 1;
        end
      end

      case ({ar_handshake, read_last_handshake})
        2'b10: read_queued <= read_queued + 1;
        2'b01: read_queued <= read_queued - 1;
        default: read_queued <= read_queued;
      endcase

      if (aw_handshake) begin
        burst_address[external_bursts] <= awaddr;
        burst_beats[external_bursts] <= awlen + 1;
        burst_issue_cycle[external_bursts] <= cycle_count;
        external_bursts <= external_bursts + 1;
        external_beats <= external_beats + awlen + 1;
        write_remaining[write_tail] <= awlen + 1;
        write_tail <= (write_tail + 1) % QUEUE_DEPTH;
        if (awsize != 3 || awburst != 1)
          errors <= errors + 1;
      end
      if (write_handshake) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=external_data op=1 index=%0d cycle=%0d last=%0d",
                   external_data_events, cycle_count,
                   write_last_handshake);
        external_data_events <= external_data_events + 1;
        if (external_first_data_cycle < 0)
          external_first_data_cycle <= cycle_count;
        external_last_data_cycle <= cycle_count;
        if (write_queued == 0) begin
          errors <= errors + 1;
        end else if ((write_remaining[write_head] == 1) != wlast) begin
          errors <= errors + 1;
        end
        if (write_queued != 0 && write_remaining[write_head] == 1) begin
          write_head <= (write_head + 1) % QUEUE_DEPTH;
          b_ready_cycle[b_tail] <= cycle_count + response_delay_arg;
          b_tail <= (b_tail + 1) % QUEUE_DEPTH;
        end else if (write_queued != 0) begin
          write_remaining[write_head] <= write_remaining[write_head] - 1;
        end
      end
      if (b_handshake) begin
        if (trace_arg != 0)
          $display("AXI_ADAPTER_EVENT kind=external_response op=1 index=%0d cycle=%0d",
                   external_response_events, cycle_count);
        external_response_events <= external_response_events + 1;
        b_head <= (b_head + 1) % QUEUE_DEPTH;
        if (external_first_response_cycle < 0)
          external_first_response_cycle <= cycle_count;
        external_last_response_cycle <= cycle_count;
      end

      case ({aw_handshake, write_last_handshake})
        2'b10: write_queued <= write_queued + 1;
        2'b01: write_queued <= write_queued - 1;
        default: write_queued <= write_queued;
      endcase
      case ({write_last_handshake, b_handshake})
        2'b10: b_queued <= b_queued + 1;
        2'b01: b_queued <= b_queued - 1;
        default: b_queued <= b_queued;
      endcase
      case ({ar_handshake || aw_handshake,
             read_last_handshake || b_handshake})
        2'b10: begin
          external_outstanding <= external_outstanding + 1;
          if (external_outstanding + 1 > max_external_outstanding)
            max_external_outstanding <= external_outstanding + 1;
        end
        2'b01: external_outstanding <= external_outstanding - 1;
        default: external_outstanding <= external_outstanding;
      endcase

      if (cycle_count >= max_cycles_arg) begin
        $display("AXI_ADAPTER_TIMEOUT cycle=%0d", cycle_count);
        errors <= errors + 1;
        report_and_finish();
      end else if (op_arg == 0 &&
                   child_requests_accepted == requests_arg &&
                   child_read_beats_accepted == requests_arg * beats_arg &&
                   read_queued == 0 && external_outstanding == 0) begin
        report_and_finish();
      end else if (op_arg == 1 &&
                   child_requests_accepted == requests_arg &&
                   child_write_beats_accepted == requests_arg * beats_arg &&
                   child_responses_accepted == requests_arg &&
                   write_queued == 0 && b_queued == 0 &&
                   external_outstanding == 0) begin
        report_and_finish();
      end
    end
  end

  initial begin
    op_arg = 0;
    requests_arg = 1;
    start_word_arg = 0;
    beats_arg = 1;
    stride_words_arg = 64;
    response_delay_arg = 1;
    ar_stall_period_arg = 0;
    ar_stall_width_arg = 0;
    aw_stall_period_arg = 0;
    aw_stall_width_arg = 0;
    w_stall_period_arg = 0;
    w_stall_width_arg = 0;
    r_stall_period_arg = 0;
    r_stall_width_arg = 0;
    child_r_stall_period_arg = 0;
    child_r_stall_width_arg = 0;
    child_b_stall_period_arg = 0;
    child_b_stall_width_arg = 0;
    max_cycles_arg = 100000;
    trace_arg = 0;
    plusarg_status = $value$plusargs("OP=%d", op_arg);
    plusarg_status = $value$plusargs("REQUESTS=%d", requests_arg);
    plusarg_status = $value$plusargs("START_WORD=%d", start_word_arg);
    plusarg_status = $value$plusargs("BEATS=%d", beats_arg);
    plusarg_status = $value$plusargs("STRIDE_WORDS=%d", stride_words_arg);
    plusarg_status = $value$plusargs("RESPONSE_DELAY=%d", response_delay_arg);
    plusarg_status = $value$plusargs("AR_STALL_PERIOD=%d", ar_stall_period_arg);
    plusarg_status = $value$plusargs("AR_STALL_WIDTH=%d", ar_stall_width_arg);
    plusarg_status = $value$plusargs("AW_STALL_PERIOD=%d", aw_stall_period_arg);
    plusarg_status = $value$plusargs("AW_STALL_WIDTH=%d", aw_stall_width_arg);
    plusarg_status = $value$plusargs("W_STALL_PERIOD=%d", w_stall_period_arg);
    plusarg_status = $value$plusargs("W_STALL_WIDTH=%d", w_stall_width_arg);
    plusarg_status = $value$plusargs("R_STALL_PERIOD=%d", r_stall_period_arg);
    plusarg_status = $value$plusargs("R_STALL_WIDTH=%d", r_stall_width_arg);
    plusarg_status = $value$plusargs(
        "CHILD_R_STALL_PERIOD=%d", child_r_stall_period_arg);
    plusarg_status = $value$plusargs(
        "CHILD_R_STALL_WIDTH=%d", child_r_stall_width_arg);
    plusarg_status = $value$plusargs(
        "CHILD_B_STALL_PERIOD=%d", child_b_stall_period_arg);
    plusarg_status = $value$plusargs(
        "CHILD_B_STALL_WIDTH=%d", child_b_stall_width_arg);
    plusarg_status = $value$plusargs("MAX_CYCLES=%d", max_cycles_arg);
    plusarg_status = $value$plusargs("TRACE=%d", trace_arg);
    if (op_arg < 0 || op_arg > 1 || requests_arg < 1 ||
        requests_arg > 128 || beats_arg < 1 || beats_arg > 256 ||
        stride_words_arg < beats_arg || response_delay_arg < 0)
      $fatal(1, "invalid adapter oracle arguments");
    repeat (10) @(posedge clk);
    reset <= 1'b0;
  end

  wire unused = &{1'b0, awid, awlock, awcache, awprot, awqos, awregion,
                   awuser, wid, wdata, wstrb, wuser, bid, bresp, buser,
                   arid, arlock, arcache, arprot, arqos, arregion, aruser,
                   rid, rresp, ruser, child_rdata, child_rfifonum, trace_arg};
endmodule
