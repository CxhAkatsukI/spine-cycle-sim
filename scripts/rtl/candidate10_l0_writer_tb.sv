`timescale 1ns/1ps

module candidate10_axi_write_sink #(
    parameter integer DATA_WIDTH = 64,
    parameter integer PHASE = 0
) (
    input  logic                  clk,
    input  logic                  rst,
    input  integer                stall_period,
    input  integer                stall_width,
    input  wire                   awvalid,
    output wire                   awready,
    input  wire [31:0]            awlen,
    input  wire                   wvalid,
    output wire                   wready,
    input  wire [DATA_WIDTH-1:0]  wdata,
    input  wire                   wlast,
    output wire                   bvalid,
    input  wire                   bready,
    output integer                aw_count,
    output integer                w_count,
    output integer                b_count,
    output integer                max_awlen,
    output integer                requested_w_beats
);
  integer cycle_count;
  integer pending_b;
  wire allow = stall_period == 0 ||
               ((cycle_count + PHASE) % stall_period) >= stall_width;

  assign awready = allow;
  assign wready = allow;
  assign bvalid = allow && pending_b != 0;

  always @(posedge clk) begin
    if (rst) begin
      cycle_count <= 0;
      pending_b <= 0;
      aw_count <= 0;
      w_count <= 0;
      b_count <= 0;
      max_awlen <= 0;
      requested_w_beats <= 0;
    end else begin
      cycle_count <= cycle_count + 1;
      if (awvalid && awready) begin
        aw_count <= aw_count + 1;
        requested_w_beats <= requested_w_beats + awlen;
        if (awlen > max_awlen)
          max_awlen <= awlen;
      end
      if (wvalid && wready)
        w_count <= w_count + 1;
      // This is the HLS child-to-adapter request protocol: one B response is
      // returned per accepted AW request, while AWLEN is the actual beat count.
      case ({awvalid && awready, bvalid && bready})
        2'b10: pending_b <= pending_b + 1;
        2'b01: pending_b <= pending_b - 1;
        default: pending_b <= pending_b;
      endcase
      if (bvalid && bready)
        b_count <= b_count + 1;
    end
  end

  wire unused = &{1'b0, wdata};
endmodule

module candidate10_axi_read_source #(
    parameter integer DATA_WIDTH = 64,
    parameter integer EDGE_DATA = 0,
    parameter integer PHASE = 0,
    parameter integer QUEUE_DEPTH = 64
) (
    input  logic                  clk,
    input  logic                  rst,
    input  integer                stall_period,
    input  integer                stall_width,
    input  integer                pattern,
    input  integer                source_stride,
    input  integer                group_size,
    input  wire [63:0]            base_address,
    input  wire                   arvalid,
    output wire                   arready,
    input  wire [63:0]            araddr,
    input  wire [31:0]            arlen,
    output wire                   rvalid,
    input  wire                   rready,
    output wire [DATA_WIDTH-1:0]  rdata,
    output wire                   rlast,
    output integer                ar_count,
    output integer                r_count,
    output integer                max_arlen,
    output integer                requested_r_beats
);
  reg [63:0] address_queue [0:QUEUE_DEPTH-1];
  reg [31:0] length_queue [0:QUEUE_DEPTH-1];
  reg [31:0] beat_queue [0:QUEUE_DEPTH-1];
  integer head;
  integer tail;
  integer queued;
  integer cycle_count;
  integer edge_index;
  integer source;
  integer destination;
  integer key_index;
  reg [127:0] edge_payload;
  wire allow = stall_period == 0 ||
               ((cycle_count + PHASE) % stall_period) >= stall_width;
  wire enqueue = arvalid && arready;
  wire consume = rvalid && rready;
  wire consume_last = consume && rlast;

  assign arready = allow && queued < QUEUE_DEPTH;
  assign rvalid = allow && queued != 0;
  assign rlast = queued != 0 &&
                 (length_queue[head] == 0 ||
                  beat_queue[head] + 1 >= length_queue[head]);

  always @(*) begin
    edge_index = 0;
    source = 0;
    destination = 0;
    key_index = 0;
    edge_payload = 128'b0;
    if (queued != 0) begin
      edge_index = address_queue[head] - base_address + beat_queue[head];
      case (pattern)
        0: begin
          source = 0;
          destination = edge_index;
        end
        1: begin
          source = edge_index * source_stride;
          destination = edge_index;
        end
        2: begin
          key_index = edge_index / 2;
          source = key_index * source_stride;
          destination = key_index;
        end
        3: begin
          source = edge_index * source_stride;
          destination = (edge_index & 1) ? 1048576 + edge_index : edge_index;
        end
        4: begin
          key_index = edge_index / group_size;
          source = key_index * source_stride;
          destination = edge_index;
        end
        default: begin
          source = edge_index * source_stride;
          destination = edge_index;
        end
      endcase
      edge_payload = {source[31:0], destination[31:0], 16'b0,
                      16'd1, 16'b0, 16'd1};
    end
  end

  generate
    if (EDGE_DATA != 0) begin : g_edge_data
      assign rdata = edge_payload[DATA_WIDTH-1:0];
    end else begin : g_zero_data
      assign rdata = {DATA_WIDTH{1'b0}};
    end
  endgenerate

  always @(posedge clk) begin
    if (rst) begin
      head <= 0;
      tail <= 0;
      queued <= 0;
      cycle_count <= 0;
      ar_count <= 0;
      r_count <= 0;
      max_arlen <= 0;
      requested_r_beats <= 0;
    end else begin
      cycle_count <= cycle_count + 1;
      if (enqueue) begin
        address_queue[tail] <= araddr;
        length_queue[tail] <= arlen;
        beat_queue[tail] <= 0;
        tail <= (tail + 1) % QUEUE_DEPTH;
        ar_count <= ar_count + 1;
        requested_r_beats <= requested_r_beats + arlen;
        if (arlen > max_arlen)
          max_arlen <= arlen;
      end
      if (consume) begin
        r_count <= r_count + 1;
        if (consume_last) begin
          head <= (head + 1) % QUEUE_DEPTH;
        end else begin
          beat_queue[head] <= beat_queue[head] + 1;
        end
      end
      case ({enqueue, consume_last})
        2'b10: queued <= queued + 1;
        2'b01: queued <= queued - 1;
        default: queued <= queued;
      endcase
    end
  end
endmodule

module candidate10_l0_writer_tb;
  localparam [63:0] GRAPH_BASE = 64'h0000_0000_2000_0000;
  localparam [63:0] SORTER_BASE = 64'h0000_0000_1000_0000;
  localparam [63:0] META_BASE = 64'h0000_0000_3000_0000;

  logic ap_clk = 1'b0;
  logic ap_rst = 1'b1;
  logic ap_start = 1'b0;
  wire ap_done;
  wire ap_idle;
  wire ap_ready;

  integer inputs_arg;
  integer edges_arg;
  integer rows_arg;
  integer pattern_arg;
  integer source_stride_arg;
  integer group_size_arg;
  integer stall_period_arg;
  integer stall_width_arg;
  integer max_cycles_arg;
  integer trace_arg;
  integer active_cycles;
  logic started = 1'b0;

  wire graph_awvalid;
  wire graph_awready;
  wire [63:0] graph_awaddr;
  wire [31:0] graph_awlen;
  wire graph_wvalid;
  wire graph_wready;
  wire [63:0] graph_wdata;
  wire graph_wlast;
  wire graph_bvalid;
  wire graph_bready;
  integer graph_aw_count;
  integer graph_w_count;
  integer graph_b_count;
  integer graph_max_awlen;
  integer graph_requested_w_beats;

  wire sorter_arvalid;
  wire sorter_arready;
  wire [63:0] sorter_araddr;
  wire [31:0] sorter_arlen;
  wire sorter_rvalid;
  wire sorter_rready;
  wire [127:0] sorter_rdata;
  wire sorter_rlast;
  integer sorter_ar_count;
  integer sorter_r_count;
  integer sorter_max_arlen;
  integer sorter_requested_r_beats;

  wire meta_awvalid;
  wire meta_awready;
  wire [63:0] meta_awaddr;
  wire [31:0] meta_awlen;
  wire meta_wvalid;
  wire meta_wready;
  wire [63:0] meta_wdata;
  wire meta_wlast;
  wire meta_bvalid;
  wire meta_bready;
  wire meta_arvalid;
  wire meta_arready;
  wire [63:0] meta_araddr;
  wire [31:0] meta_arlen;
  wire meta_rvalid;
  wire meta_rready;
  wire [63:0] meta_rdata;
  wire meta_rlast;
  integer meta_aw_count;
  integer meta_w_count;
  integer meta_b_count;
  integer meta_max_awlen;
  integer meta_requested_w_beats;
  integer meta_ar_count;
  integer meta_r_count;
  integer meta_max_arlen;
  integer meta_requested_r_beats;

  wire [31:0] result_edges;
  wire [31:0] result_rows;
  wire [31:0] result_epoch;
  wire [31:0] result_pages;
  wire result_occupied;
  wire [31:0] result_pages_stamped;
  wire result_overflow;
  wire [31:0] result_page_ids_written;
  wire [31:0] result_validation_failures;
  wire [31:0] result_outputs;

  always #1 ap_clk = ~ap_clk;

  candidate10_axi_write_sink #(.DATA_WIDTH(64), .PHASE(0)) graph_sink (
      .clk(ap_clk), .rst(ap_rst),
      .stall_period(stall_period_arg), .stall_width(stall_width_arg),
      .awvalid(graph_awvalid), .awready(graph_awready), .awlen(graph_awlen),
      .wvalid(graph_wvalid), .wready(graph_wready), .wdata(graph_wdata),
      .wlast(graph_wlast), .bvalid(graph_bvalid), .bready(graph_bready),
      .aw_count(graph_aw_count), .w_count(graph_w_count),
      .b_count(graph_b_count), .max_awlen(graph_max_awlen),
      .requested_w_beats(graph_requested_w_beats));

  candidate10_axi_read_source #(.DATA_WIDTH(128), .EDGE_DATA(1), .PHASE(1)) sorter_source (
      .clk(ap_clk), .rst(ap_rst),
      .stall_period(stall_period_arg), .stall_width(stall_width_arg),
      .pattern(pattern_arg), .source_stride(source_stride_arg),
      .group_size(group_size_arg),
      .base_address(SORTER_BASE >> 4), .arvalid(sorter_arvalid),
      .arready(sorter_arready), .araddr(sorter_araddr), .arlen(sorter_arlen),
      .rvalid(sorter_rvalid), .rready(sorter_rready), .rdata(sorter_rdata),
      .rlast(sorter_rlast), .ar_count(sorter_ar_count), .r_count(sorter_r_count),
      .max_arlen(sorter_max_arlen),
      .requested_r_beats(sorter_requested_r_beats));

  candidate10_axi_write_sink #(.DATA_WIDTH(64), .PHASE(2)) meta_sink (
      .clk(ap_clk), .rst(ap_rst),
      .stall_period(stall_period_arg), .stall_width(stall_width_arg),
      .awvalid(meta_awvalid), .awready(meta_awready), .awlen(meta_awlen),
      .wvalid(meta_wvalid), .wready(meta_wready), .wdata(meta_wdata),
      .wlast(meta_wlast), .bvalid(meta_bvalid), .bready(meta_bready),
      .aw_count(meta_aw_count), .w_count(meta_w_count),
      .b_count(meta_b_count), .max_awlen(meta_max_awlen),
      .requested_w_beats(meta_requested_w_beats));

  candidate10_axi_read_source #(.DATA_WIDTH(64), .EDGE_DATA(0), .PHASE(3)) meta_source (
      .clk(ap_clk), .rst(ap_rst),
      .stall_period(stall_period_arg), .stall_width(stall_width_arg),
      .pattern(pattern_arg), .source_stride(source_stride_arg),
      .group_size(group_size_arg),
      .base_address(META_BASE >> 3), .arvalid(meta_arvalid), .arready(meta_arready),
      .araddr(meta_araddr), .arlen(meta_arlen), .rvalid(meta_rvalid),
      .rready(meta_rready), .rdata(meta_rdata), .rlast(meta_rlast),
      .ar_count(meta_ar_count), .r_count(meta_r_count),
      .max_arlen(meta_max_arlen),
      .requested_r_beats(meta_requested_r_beats));

  spine_partconv_rdmaint_kernel_partitioned_write_l0_family dut (
      .ap_clk(ap_clk), .ap_rst(ap_rst), .ap_start(ap_start),
      .ap_done(ap_done), .ap_idle(ap_idle), .ap_ready(ap_ready),

      .m_axi_gmem_p0_AWVALID(graph_awvalid),
      .m_axi_gmem_p0_AWREADY(graph_awready),
      .m_axi_gmem_p0_AWADDR(graph_awaddr),
      .m_axi_gmem_p0_AWLEN(graph_awlen),
      .m_axi_gmem_p0_WVALID(graph_wvalid),
      .m_axi_gmem_p0_WREADY(graph_wready),
      .m_axi_gmem_p0_WDATA(graph_wdata),
      .m_axi_gmem_p0_WLAST(graph_wlast),
      .m_axi_gmem_p0_ARREADY(1'b0),
      .m_axi_gmem_p0_RVALID(1'b0), .m_axi_gmem_p0_RDATA(64'b0),
      .m_axi_gmem_p0_RLAST(1'b0), .m_axi_gmem_p0_RID(1'b0),
      .m_axi_gmem_p0_RFIFONUM(9'b0), .m_axi_gmem_p0_RUSER(1'b0),
      .m_axi_gmem_p0_RRESP(2'b0), .m_axi_gmem_p0_BVALID(graph_bvalid),
      .m_axi_gmem_p0_BREADY(graph_bready), .m_axi_gmem_p0_BRESP(2'b0),
      .m_axi_gmem_p0_BID(1'b0), .m_axi_gmem_p0_BUSER(1'b0),
      .graph(GRAPH_BASE),

      .m_axi_gmem_sorter_AWREADY(1'b0),
      .m_axi_gmem_sorter_WREADY(1'b0),
      .m_axi_gmem_sorter_ARVALID(sorter_arvalid),
      .m_axi_gmem_sorter_ARREADY(sorter_arready),
      .m_axi_gmem_sorter_ARADDR(sorter_araddr),
      .m_axi_gmem_sorter_ARLEN(sorter_arlen),
      .m_axi_gmem_sorter_RVALID(sorter_rvalid),
      .m_axi_gmem_sorter_RREADY(sorter_rready),
      .m_axi_gmem_sorter_RDATA(sorter_rdata),
      .m_axi_gmem_sorter_RLAST(sorter_rlast),
      .m_axi_gmem_sorter_RID(1'b0), .m_axi_gmem_sorter_RFIFONUM(9'b0),
      .m_axi_gmem_sorter_RUSER(1'b0), .m_axi_gmem_sorter_RRESP(2'b0),
      .m_axi_gmem_sorter_BVALID(1'b0), .m_axi_gmem_sorter_BRESP(2'b0),
      .m_axi_gmem_sorter_BID(1'b0), .m_axi_gmem_sorter_BUSER(1'b0),
      .sorted_edges(SORTER_BASE),

      .m_axi_gmem_meta_AWVALID(meta_awvalid),
      .m_axi_gmem_meta_AWREADY(meta_awready),
      .m_axi_gmem_meta_AWADDR(meta_awaddr),
      .m_axi_gmem_meta_AWLEN(meta_awlen),
      .m_axi_gmem_meta_WVALID(meta_wvalid),
      .m_axi_gmem_meta_WREADY(meta_wready),
      .m_axi_gmem_meta_WDATA(meta_wdata),
      .m_axi_gmem_meta_WLAST(meta_wlast),
      .m_axi_gmem_meta_ARVALID(meta_arvalid),
      .m_axi_gmem_meta_ARREADY(meta_arready),
      .m_axi_gmem_meta_ARADDR(meta_araddr),
      .m_axi_gmem_meta_ARLEN(meta_arlen),
      .m_axi_gmem_meta_RVALID(meta_rvalid),
      .m_axi_gmem_meta_RREADY(meta_rready),
      .m_axi_gmem_meta_RDATA(meta_rdata),
      .m_axi_gmem_meta_RLAST(meta_rlast),
      .m_axi_gmem_meta_RID(1'b0), .m_axi_gmem_meta_RFIFONUM(9'b0),
      .m_axi_gmem_meta_RUSER(1'b0), .m_axi_gmem_meta_RRESP(2'b0),
      .m_axi_gmem_meta_BVALID(meta_bvalid),
      .m_axi_gmem_meta_BREADY(meta_bready), .m_axi_gmem_meta_BRESP(2'b0),
      .m_axi_gmem_meta_BID(1'b0), .m_axi_gmem_meta_BUSER(1'b0),
      .level_meta_io(META_BASE),

      .family(5'd0), .rows(rows_arg), .edges(edges_arg),
      .num_edges(inputs_arg[18:0]), .p_read5(32'b0), .p_read6(32'b0),
      .p_read7(32'b0), .p_read8(1'b0), .p_read9(32'b0),
      .p_read10(32'b0), .p_read11(32'b0), .idx1(24'b0),
      .ap_return_0(result_edges), .ap_return_1(result_rows),
      .ap_return_2(result_epoch), .ap_return_3(result_pages),
      .ap_return_4(result_occupied), .ap_return_5(result_pages_stamped),
      .ap_return_8(result_overflow),
      .ap_return_9(result_page_ids_written),
      .ap_return_10(result_validation_failures),
      .ap_return_11(result_outputs));

  initial begin
    if (!$value$plusargs("INPUTS=%d", inputs_arg)) inputs_arg = 1;
    if (!$value$plusargs("EDGES=%d", edges_arg)) edges_arg = inputs_arg;
    if (!$value$plusargs("ROWS=%d", rows_arg)) rows_arg = 1;
    if (!$value$plusargs("PATTERN=%d", pattern_arg)) pattern_arg = 0;
    if (!$value$plusargs("SOURCE_STRIDE=%d", source_stride_arg)) source_stride_arg = 1;
    if (!$value$plusargs("GROUP_SIZE=%d", group_size_arg)) group_size_arg = 4;
    if (!$value$plusargs("STALL_PERIOD=%d", stall_period_arg)) stall_period_arg = 0;
    if (!$value$plusargs("STALL_WIDTH=%d", stall_width_arg)) stall_width_arg = 0;
    if (!$value$plusargs("MAX_CYCLES=%d", max_cycles_arg)) max_cycles_arg = 2000000;
    if (!$value$plusargs("TRACE=%d", trace_arg)) trace_arg = 0;
    active_cycles = 0;
    repeat (5) @(posedge ap_clk);
    ap_rst <= 1'b0;
    repeat (3) @(posedge ap_clk);
    ap_start <= 1'b1;
    @(posedge ap_clk);
    ap_start <= 1'b0;
    started <= 1'b1;
  end

  always @(posedge ap_clk) begin
    if (trace_arg != 0 && sorter_arvalid && sorter_arready)
      $display("L0_TRACE cycle=%0d sorter_ar addr=%h len=%0d",
               active_cycles, sorter_araddr, sorter_arlen);
    if (trace_arg != 0 && sorter_rvalid && sorter_rready)
      $display("L0_TRACE cycle=%0d sorter_r index=%0d data=%h last=%0d",
               active_cycles, sorter_source.edge_index, sorter_rdata,
               sorter_rlast);
    if (trace_arg != 0 && graph_awvalid && graph_awready)
      $display("L0_TRACE cycle=%0d graph_aw addr=%h len=%0d",
               active_cycles, graph_awaddr, graph_awlen);
    if (trace_arg != 0 && graph_wvalid && graph_wready)
      $display("L0_TRACE cycle=%0d graph_w data=%h last=%0d",
               active_cycles, graph_wdata, graph_wlast);
    if (trace_arg != 0 && meta_arvalid && meta_arready)
      $display("L0_TRACE cycle=%0d meta_ar addr=%h len=%0d",
               active_cycles, meta_araddr, meta_arlen);
    if (trace_arg != 0 && meta_awvalid && meta_awready)
      $display("L0_TRACE cycle=%0d meta_aw addr=%h len=%0d",
               active_cycles, meta_awaddr, meta_awlen);
    if (started && !ap_done)
      active_cycles <= active_cycles + 1;
    if (started && ap_done) begin
      $display("L0_WRITER_RTL inputs=%0d edges=%0d rows=%0d pattern=%0d source_stride=%0d group_size=%0d stall_period=%0d stall_width=%0d cycles=%0d result_edges=%0d result_rows=%0d result_epoch=%0d result_pages=%0d result_occupied=%0d result_pages_stamped=%0d result_overflow=%0d result_page_ids=%0d result_validation=%0d result_outputs=%0d graph_aw=%0d graph_w=%0d graph_b=%0d graph_max_awlen=%0d graph_requested_w_beats=%0d sorter_ar=%0d sorter_r=%0d sorter_max_arlen=%0d sorter_requested_r_beats=%0d meta_aw=%0d meta_w=%0d meta_b=%0d meta_max_awlen=%0d meta_requested_w_beats=%0d meta_ar=%0d meta_r=%0d meta_max_arlen=%0d meta_requested_r_beats=%0d",
               inputs_arg, edges_arg, rows_arg, pattern_arg, source_stride_arg,
               group_size_arg, stall_period_arg, stall_width_arg, active_cycles,
               result_edges, result_rows, result_epoch, result_pages,
               result_occupied, result_pages_stamped, result_overflow,
               result_page_ids_written, result_validation_failures,
               result_outputs, graph_aw_count, graph_w_count, graph_b_count,
               graph_max_awlen, graph_requested_w_beats, sorter_ar_count,
               sorter_r_count, sorter_max_arlen, sorter_requested_r_beats,
               meta_aw_count, meta_w_count, meta_b_count, meta_max_awlen,
               meta_requested_w_beats, meta_ar_count, meta_r_count,
               meta_max_arlen, meta_requested_r_beats);
      $finish;
    end
    if (active_cycles > max_cycles_arg) begin
      $display("L0_WRITER_RTL_TIMEOUT cycles=%0d state=%h graph_aw=%0d graph_w=%0d graph_b=%0d sorter_ar=%0d sorter_r=%0d meta_aw=%0d meta_w=%0d meta_b=%0d meta_ar=%0d meta_r=%0d",
               active_cycles, dut.ap_CS_fsm, graph_aw_count, graph_w_count,
               graph_b_count, sorter_ar_count, sorter_r_count, meta_aw_count,
               meta_w_count, meta_b_count, meta_ar_count, meta_r_count);
      $fatal(1, "Candidate10 L0-writer RTL oracle timed out");
    end
  end
endmodule
