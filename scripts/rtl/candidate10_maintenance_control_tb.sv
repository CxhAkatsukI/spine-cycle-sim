`timescale 1ns/1ps

module candidate10_axi_zero_child #(
    parameter integer DATA_WIDTH = 64,
    parameter integer QUEUE_DEPTH = 128
) (
    input  logic                  clk,
    input  logic                  rst,
    input  wire                   awvalid,
    output wire                   awready,
    input  wire [31:0]            awlen,
    input  wire                   wvalid,
    output wire                   wready,
    input  wire                   wlast,
    output wire                   bvalid,
    input  wire                   bready,
    input  wire                   arvalid,
    output wire                   arready,
    input  wire [31:0]            arlen,
    output wire                   rvalid,
    input  wire                   rready,
    output wire [DATA_WIDTH-1:0]  rdata,
    output wire                   rlast,
    output integer                aw_count,
    output integer                w_count,
    output integer                b_count,
    output integer                ar_count,
    output integer                r_count,
    output integer                requested_w_beats,
    output integer                requested_r_beats
);
  reg [31:0] read_length [0:QUEUE_DEPTH-1];
  reg [31:0] read_beat [0:QUEUE_DEPTH-1];
  reg [31:0] write_length [0:QUEUE_DEPTH-1];
  reg [31:0] write_beat [0:QUEUE_DEPTH-1];
  integer read_head;
  integer read_tail;
  integer read_queued;
  integer write_head;
  integer write_tail;
  integer write_queued;
  integer pending_b;
  wire enqueue_write = awvalid && awready;
  wire consume_write = wvalid && wready;
  wire consume_write_last = consume_write &&
                            (write_length[write_head] == 0 ||
                             write_beat[write_head] + 1 >=
                                 write_length[write_head]);
  wire enqueue_read = arvalid && arready;
  wire consume_read = rvalid && rready;
  wire consume_read_last = consume_read && rlast;

  assign awready = write_queued < QUEUE_DEPTH;
  assign wready = write_queued != 0;
  assign bvalid = pending_b != 0;
  assign arready = read_queued < QUEUE_DEPTH;
  assign rvalid = read_queued != 0;
  assign rdata = {DATA_WIDTH{1'b0}};
  assign rlast = read_queued != 0 &&
                 (read_length[read_head] == 0 ||
                  read_beat[read_head] + 1 >= read_length[read_head]);

  always @(posedge clk) begin
    if (rst) begin
      read_head <= 0;
      read_tail <= 0;
      read_queued <= 0;
      write_head <= 0;
      write_tail <= 0;
      write_queued <= 0;
      pending_b <= 0;
      aw_count <= 0;
      w_count <= 0;
      b_count <= 0;
      ar_count <= 0;
      r_count <= 0;
      requested_w_beats <= 0;
      requested_r_beats <= 0;
    end else begin
      if (enqueue_write) begin
        write_length[write_tail] <= awlen;
        write_beat[write_tail] <= 0;
        write_tail <= (write_tail + 1) % QUEUE_DEPTH;
        aw_count <= aw_count + 1;
        requested_w_beats <= requested_w_beats + awlen;
      end
      if (consume_write) begin
        w_count <= w_count + 1;
        if (consume_write_last) begin
          write_head <= (write_head + 1) % QUEUE_DEPTH;
        end else begin
          write_beat[write_head] <= write_beat[write_head] + 1;
        end
      end
      if (bvalid && bready)
        b_count <= b_count + 1;
      case ({consume_write_last, bvalid && bready})
        2'b10: pending_b <= pending_b + 1;
        2'b01: pending_b <= pending_b - 1;
        default: pending_b <= pending_b;
      endcase
      case ({enqueue_write, consume_write_last})
        2'b10: write_queued <= write_queued + 1;
        2'b01: write_queued <= write_queued - 1;
        default: write_queued <= write_queued;
      endcase

      if (enqueue_read) begin
        read_length[read_tail] <= arlen;
        read_beat[read_tail] <= 0;
        read_tail <= (read_tail + 1) % QUEUE_DEPTH;
        ar_count <= ar_count + 1;
        requested_r_beats <= requested_r_beats + arlen;
      end
      if (consume_read) begin
        r_count <= r_count + 1;
        if (consume_read_last) begin
          read_head <= (read_head + 1) % QUEUE_DEPTH;
        end else begin
          read_beat[read_head] <= read_beat[read_head] + 1;
        end
      end
      case ({enqueue_read, consume_read_last})
        2'b10: read_queued <= read_queued + 1;
        2'b01: read_queued <= read_queued - 1;
        default: read_queued <= read_queued;
      endcase
    end
  end

  wire unused = &{1'b0, wlast};
endmodule

module candidate10_maintenance_control_tb;
  logic ap_clk = 1'b0;
  logic ap_rst = 1'b1;
  logic ap_start = 1'b0;
  wire ap_done;
  wire ap_idle;
  wire ap_ready;

  wire meta_awvalid;
  wire meta_awready;
  wire [31:0] meta_awlen;
  wire meta_wvalid;
  wire meta_wready;
  wire meta_wlast;
  wire meta_bvalid;
  wire meta_bready;
  wire meta_arvalid;
  wire meta_arready;
  wire [31:0] meta_arlen;
  wire meta_rvalid;
  wire meta_rready;
  wire [63:0] meta_rdata;
  wire meta_rlast;
  integer meta_aw_count;
  integer meta_w_count;
  integer meta_b_count;
  integer meta_ar_count;
  integer meta_r_count;
  integer meta_requested_w_beats;
  integer meta_requested_r_beats;

  wire result_awvalid;
  wire result_awready;
  wire [31:0] result_awlen;
  wire result_wvalid;
  wire result_wready;
  wire result_wlast;
  wire result_bvalid;
  wire result_bready;
  integer result_aw_count;
  integer result_w_count;
  integer result_b_count;
  integer result_ar_count;
  integer result_r_count;
  integer result_requested_w_beats;
  integer result_requested_r_beats;

  wire sorter_awvalid;
  wire sorter_wvalid;
  wire sorter_arvalid;
  integer active_cycles = 0;
  integer measured_cycles = 0;
  integer max_cycles_arg = 200000;
  integer plusarg_found = 0;
  logic started = 1'b0;

  always #3.333 ap_clk = ~ap_clk;

  candidate10_axi_zero_child #(.DATA_WIDTH(64)) meta_memory (
      .clk(ap_clk), .rst(ap_rst),
      .awvalid(meta_awvalid), .awready(meta_awready), .awlen(meta_awlen),
      .wvalid(meta_wvalid), .wready(meta_wready), .wlast(meta_wlast),
      .bvalid(meta_bvalid), .bready(meta_bready),
      .arvalid(meta_arvalid), .arready(meta_arready), .arlen(meta_arlen),
      .rvalid(meta_rvalid), .rready(meta_rready), .rdata(meta_rdata),
      .rlast(meta_rlast), .aw_count(meta_aw_count),
      .w_count(meta_w_count), .b_count(meta_b_count),
      .ar_count(meta_ar_count), .r_count(meta_r_count),
      .requested_w_beats(meta_requested_w_beats),
      .requested_r_beats(meta_requested_r_beats));

  candidate10_axi_zero_child #(.DATA_WIDTH(64)) result_memory (
      .clk(ap_clk), .rst(ap_rst),
      .awvalid(result_awvalid), .awready(result_awready),
      .awlen(result_awlen), .wvalid(result_wvalid),
      .wready(result_wready), .wlast(result_wlast),
      .bvalid(result_bvalid), .bready(result_bready),
      .arvalid(1'b0), .arready(), .arlen(32'b0),
      .rvalid(), .rready(1'b0), .rdata(), .rlast(),
      .aw_count(result_aw_count), .w_count(result_w_count),
      .b_count(result_b_count), .ar_count(result_ar_count),
      .r_count(result_r_count),
      .requested_w_beats(result_requested_w_beats),
      .requested_r_beats(result_requested_r_beats));

`define TIE_GRAPH_AXI_INPUTS(P) \
      .m_axi_gmem_``P``_AWREADY(1'b1), \
      .m_axi_gmem_``P``_WREADY(1'b1), \
      .m_axi_gmem_``P``_ARREADY(1'b1), \
      .m_axi_gmem_``P``_RVALID(1'b0), \
      .m_axi_gmem_``P``_RDATA(64'b0), \
      .m_axi_gmem_``P``_RLAST(1'b0), \
      .m_axi_gmem_``P``_RID(1'b0), \
      .m_axi_gmem_``P``_RFIFONUM(9'b0), \
      .m_axi_gmem_``P``_RUSER(1'b0), \
      .m_axi_gmem_``P``_RRESP(2'b0), \
      .m_axi_gmem_``P``_BVALID(1'b0), \
      .m_axi_gmem_``P``_BRESP(2'b0), \
      .m_axi_gmem_``P``_BID(1'b0), \
      .m_axi_gmem_``P``_BUSER(1'b0)

  spine_partconv_rdmaint_kernel_partitioned_run_maintenance dut (
      .ap_clk(ap_clk), .ap_rst(ap_rst), .ap_start(ap_start),
      .ap_done(ap_done), .ap_idle(ap_idle), .ap_ready(ap_ready),

      `TIE_GRAPH_AXI_INPUTS(p0), .graph0(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p1), .graph1(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p2), .graph2(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p3), .graph3(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p4), .graph4(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p5), .graph5(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p6), .graph6(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p7), .graph7(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p8), .graph8(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p9), .graph9(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p10), .graph10(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p11), .graph11(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p12), .graph12(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p13), .graph13(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p14), .graph14(64'b0),
      `TIE_GRAPH_AXI_INPUTS(p15), .graph15(64'b0),

      .m_axi_gmem_sorter_AWVALID(sorter_awvalid),
      .m_axi_gmem_sorter_AWREADY(1'b1),
      .m_axi_gmem_sorter_WVALID(sorter_wvalid),
      .m_axi_gmem_sorter_WREADY(1'b1),
      .m_axi_gmem_sorter_ARVALID(sorter_arvalid),
      .m_axi_gmem_sorter_ARREADY(1'b1),
      .m_axi_gmem_sorter_RVALID(1'b0),
      .m_axi_gmem_sorter_RDATA(128'b0),
      .m_axi_gmem_sorter_RLAST(1'b0),
      .m_axi_gmem_sorter_RID(1'b0),
      .m_axi_gmem_sorter_RFIFONUM(9'b0),
      .m_axi_gmem_sorter_RUSER(1'b0),
      .m_axi_gmem_sorter_RRESP(2'b0),
      .m_axi_gmem_sorter_BVALID(1'b0),
      .m_axi_gmem_sorter_BRESP(2'b0),
      .m_axi_gmem_sorter_BID(1'b0),
      .m_axi_gmem_sorter_BUSER(1'b0),
      .sorted_edges(64'b0),

      .m_axi_gmem_meta_AWVALID(meta_awvalid),
      .m_axi_gmem_meta_AWREADY(meta_awready),
      .m_axi_gmem_meta_AWLEN(meta_awlen),
      .m_axi_gmem_meta_WVALID(meta_wvalid),
      .m_axi_gmem_meta_WREADY(meta_wready),
      .m_axi_gmem_meta_WLAST(meta_wlast),
      .m_axi_gmem_meta_ARVALID(meta_arvalid),
      .m_axi_gmem_meta_ARREADY(meta_arready),
      .m_axi_gmem_meta_ARLEN(meta_arlen),
      .m_axi_gmem_meta_RVALID(meta_rvalid),
      .m_axi_gmem_meta_RREADY(meta_rready),
      .m_axi_gmem_meta_RDATA(meta_rdata),
      .m_axi_gmem_meta_RLAST(meta_rlast),
      .m_axi_gmem_meta_RID(1'b0),
      .m_axi_gmem_meta_RFIFONUM(9'b0),
      .m_axi_gmem_meta_RUSER(1'b0),
      .m_axi_gmem_meta_RRESP(2'b0),
      .m_axi_gmem_meta_BVALID(meta_bvalid),
      .m_axi_gmem_meta_BREADY(meta_bready),
      .m_axi_gmem_meta_BRESP(2'b0),
      .m_axi_gmem_meta_BID(1'b0),
      .m_axi_gmem_meta_BUSER(1'b0),
      .level_meta_io(64'b0),

      .m_axi_gmem_result_AWVALID(result_awvalid),
      .m_axi_gmem_result_AWREADY(result_awready),
      .m_axi_gmem_result_AWLEN(result_awlen),
      .m_axi_gmem_result_WVALID(result_wvalid),
      .m_axi_gmem_result_WREADY(result_wready),
      .m_axi_gmem_result_WLAST(result_wlast),
      .m_axi_gmem_result_ARREADY(1'b1),
      .m_axi_gmem_result_RVALID(1'b0),
      .m_axi_gmem_result_RDATA(64'b0),
      .m_axi_gmem_result_RLAST(1'b0),
      .m_axi_gmem_result_RID(1'b0),
      .m_axi_gmem_result_RFIFONUM(9'b0),
      .m_axi_gmem_result_RUSER(1'b0),
      .m_axi_gmem_result_RRESP(2'b0),
      .m_axi_gmem_result_BVALID(result_bvalid),
      .m_axi_gmem_result_BREADY(result_bready),
      .m_axi_gmem_result_BRESP(2'b0),
      .m_axi_gmem_result_BID(1'b0),
      .m_axi_gmem_result_BUSER(1'b0),
      .result_out(64'b0),
      .num_edges(32'b0), .num_vertices(32'd1));

`undef TIE_GRAPH_AXI_INPUTS

  initial begin
    plusarg_found = $value$plusargs("MAX_CYCLES=%d", max_cycles_arg);
    repeat (8) @(posedge ap_clk);
    ap_rst <= 1'b0;
    repeat (2) @(posedge ap_clk);
    ap_start <= 1'b1;
    @(posedge ap_clk);
    ap_start <= 1'b0;
  end

  always @(posedge ap_clk) begin
    if (ap_rst) begin
      active_cycles <= 0;
      started <= 1'b0;
    end else begin
      if (ap_start)
        started <= 1'b1;
      if (ap_start || started)
        active_cycles <= active_cycles + 1;
      if (started && ap_done) begin
        measured_cycles = active_cycles;
        #1;
        $display("MAINT_CONTROL_RTL case=zero cycles=%0d meta_ar=%0d meta_requested_r=%0d meta_r=%0d meta_aw=%0d meta_requested_w=%0d meta_w=%0d meta_b=%0d result_aw=%0d result_requested_w=%0d result_w=%0d result_b=%0d sorter_aw=%0d sorter_w=%0d sorter_ar=%0d",
                 measured_cycles,
                 meta_ar_count, meta_requested_r_beats, meta_r_count,
                 meta_aw_count, meta_requested_w_beats, meta_w_count, meta_b_count,
                 result_aw_count, result_requested_w_beats, result_w_count, result_b_count,
                 sorter_awvalid, sorter_wvalid, sorter_arvalid);
        $finish;
      end
      if (active_cycles > max_cycles_arg) begin
        $display("MAINT_CONTROL_RTL_TIMEOUT cycles=%0d state=%h meta_ar=%0d meta_r=%0d meta_aw=%0d meta_w=%0d result_aw=%0d result_w=%0d",
                 active_cycles, dut.ap_CS_fsm, meta_ar_count, meta_r_count,
                 meta_aw_count, meta_w_count, result_aw_count, result_w_count);
        $fatal(1, "Candidate10 maintenance-control RTL oracle timed out");
      end
    end
  end
endmodule
