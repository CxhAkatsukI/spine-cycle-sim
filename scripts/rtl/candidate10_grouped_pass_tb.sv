`timescale 1ns/1ps

module candidate10_grouped_pass_tb;
  logic ap_clk = 1'b0;
  logic ap_rst = 1'b1;
  logic ap_start = 1'b0;
  wire ap_done;
  wire ap_idle;
  wire ap_ready;

  wire sorter_awvalid;
  logic sorter_awready;
  wire [31:0] sorter_awlen;
  wire sorter_wvalid;
  logic sorter_wready;
  wire sorter_wlast;
  wire sorter_arvalid;
  logic sorter_arready;
  wire [31:0] sorter_arlen;
  logic sorter_rvalid = 1'b0;
  wire sorter_rready;
  logic [127:0] sorter_rdata = 128'b0;
  logic sorter_rlast = 1'b1;
  logic sorter_bvalid = 1'b0;
  wire sorter_bready;

  wire meta_awvalid;
  logic meta_awready;
  wire [31:0] meta_awlen;
  wire meta_wvalid;
  logic meta_wready;
  wire meta_wlast;
  wire meta_arvalid;
  logic meta_arready;
  wire [31:0] meta_arlen;
  logic meta_rvalid = 1'b0;
  wire meta_rready;
  logic [63:0] meta_rdata = 64'b0;
  logic meta_rlast = 1'b1;
  logic meta_bvalid = 1'b0;
  wire meta_bready;

  wire [17:0] result_word_reads;
  wire [17:0] result_word_writes;
  wire [17:0] result_new_bits;
  wire [17:0] result_new_count;
  wire [16:0] result_scratch_words;

  integer unique_arg = 1;
  integer stride_arg = 1;
  integer bitmap_arg = 0;
  integer empty_arg = 0;
  integer probe_arg = 0;
  integer max_cycles_arg = 10000000;
  integer cycles = 0;
  integer active_cycles = 0;
  integer meta_read_count = 0;
  integer sorter_read_count = 0;
  integer sorter_write_count = 0;
  integer meta_write_count = 0;
  integer sorter_read_pending = 0;
  integer meta_read_pending = 0;
  integer sorter_b_pending = 0;
  integer meta_b_pending = 0;
  integer meta_response_count = 0;
  integer plusarg_found = 0;
  logic started = 1'b0;

  always #3.333 ap_clk = ~ap_clk;

  assign sorter_arready = 1'b1;
  assign sorter_awready = 1'b1;
  assign sorter_wready = 1'b1;
  assign meta_arready = 1'b1;
  assign meta_awready = 1'b1;
  assign meta_wready = 1'b1;

  spine_partconv_rdmaint_kernel_partitioned_frontier_publish_grouped_pass dut (
      .ap_clk(ap_clk),
      .ap_rst(ap_rst),
      .ap_start(ap_start),
      .ap_done(ap_done),
      .ap_idle(ap_idle),
      .ap_ready(ap_ready),
      .m_axi_gmem_sorter_AWVALID(sorter_awvalid),
      .m_axi_gmem_sorter_AWREADY(sorter_awready),
      .m_axi_gmem_sorter_AWLEN(sorter_awlen),
      .m_axi_gmem_sorter_WVALID(sorter_wvalid),
      .m_axi_gmem_sorter_WREADY(sorter_wready),
      .m_axi_gmem_sorter_WLAST(sorter_wlast),
      .m_axi_gmem_sorter_ARVALID(sorter_arvalid),
      .m_axi_gmem_sorter_ARREADY(sorter_arready),
      .m_axi_gmem_sorter_ARLEN(sorter_arlen),
      .m_axi_gmem_sorter_RVALID(sorter_rvalid),
      .m_axi_gmem_sorter_RREADY(sorter_rready),
      .m_axi_gmem_sorter_RDATA(sorter_rdata),
      .m_axi_gmem_sorter_RLAST(sorter_rlast),
      .m_axi_gmem_sorter_RID(1'b0),
      .m_axi_gmem_sorter_RFIFONUM(9'b0),
      .m_axi_gmem_sorter_RUSER(1'b0),
      .m_axi_gmem_sorter_RRESP(2'b0),
      .m_axi_gmem_sorter_BVALID(sorter_bvalid),
      .m_axi_gmem_sorter_BREADY(sorter_bready),
      .m_axi_gmem_sorter_BRESP(2'b0),
      .m_axi_gmem_sorter_BID(1'b0),
      .m_axi_gmem_sorter_BUSER(1'b0),
      .persistent_hbm16(64'b0),
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
      .unique_count(unique_arg[17:0]),
      .bitmap_phase(bitmap_arg[0:0]),
      .empty_proven(empty_arg[0:0]),
      .probe_only(probe_arg[0:0]),
      .ap_return_0(result_word_reads),
      .ap_return_1(result_word_writes),
      .ap_return_2(result_new_bits),
      .ap_return_3(result_new_count),
      .ap_return_4(result_scratch_words)
  );

  initial begin
    plusarg_found = $value$plusargs("UNIQUE=%d", unique_arg);
    plusarg_found = $value$plusargs("STRIDE=%d", stride_arg);
    plusarg_found = $value$plusargs("BITMAP=%d", bitmap_arg);
    plusarg_found = $value$plusargs("EMPTY=%d", empty_arg);
    plusarg_found = $value$plusargs("PROBE=%d", probe_arg);
    plusarg_found = $value$plusargs("MAX_CYCLES=%d", max_cycles_arg);
    if (unique_arg <= 0 || unique_arg > 131072 || stride_arg <= 0) begin
      $fatal(1, "invalid UNIQUE/STRIDE arguments");
    end
    repeat (8) @(posedge ap_clk);
    ap_rst <= 1'b0;
    repeat (2) @(posedge ap_clk);
    ap_start <= 1'b1;
    @(posedge ap_clk);
    ap_start <= 1'b0;
  end

  always_ff @(posedge ap_clk) begin
    integer source;
    integer sorter_read_pending_next;
    integer meta_read_pending_next;
    integer sorter_b_pending_next;
    integer meta_b_pending_next;
    cycles <= cycles + 1;
    if (ap_start || active_cycles != 0) begin
      active_cycles <= active_cycles + 1;
    end
    if (ap_start) started <= 1'b1;

    if (ap_rst) begin
      sorter_rvalid <= 1'b0;
      sorter_bvalid <= 1'b0;
      sorter_read_pending <= 0;
      sorter_b_pending <= 0;
      meta_rvalid <= 1'b0;
      meta_bvalid <= 1'b0;
      meta_read_pending <= 0;
      meta_b_pending <= 0;
      meta_response_count <= 0;
      started <= 1'b0;
    end else begin
      sorter_read_pending_next = sorter_read_pending;
      if (sorter_arvalid && sorter_arready)
        sorter_read_pending_next = sorter_read_pending_next + 1;
      if (sorter_rvalid && sorter_rready) begin
        sorter_read_pending_next = sorter_read_pending_next - 1;
        sorter_read_count <= sorter_read_count + 1;
      end
      sorter_read_pending <= sorter_read_pending_next;
      if (sorter_read_pending_next > 0) begin
        sorter_rvalid <= 1'b1;
        sorter_rdata <= 128'b0;
        sorter_rlast <= 1'b1;
      end else begin
        sorter_rvalid <= 1'b0;
      end

      sorter_b_pending_next = sorter_b_pending;
      if (sorter_wvalid && sorter_wready) begin
        sorter_b_pending_next = sorter_b_pending_next + 1;
        sorter_write_count <= sorter_write_count + 1;
      end
      if (sorter_bvalid && sorter_bready)
        sorter_b_pending_next = sorter_b_pending_next - 1;
      sorter_b_pending <= sorter_b_pending_next;
      sorter_bvalid <= sorter_b_pending_next > 0;

      meta_read_pending_next = meta_read_pending;
      if (meta_arvalid && meta_arready)
        meta_read_pending_next = meta_read_pending_next + 1;
      if (meta_rvalid && meta_rready) begin
        meta_read_pending_next = meta_read_pending_next - 1;
        meta_read_count <= meta_read_count + 1;
        meta_response_count <= meta_response_count + 1;
      end
      meta_read_pending <= meta_read_pending_next;
      if (meta_read_pending_next > 0) begin
        source = (meta_response_count +
                  ((meta_rvalid && meta_rready) ? 1 : 0)) % unique_arg;
        source = source * stride_arg;
        meta_rvalid <= 1'b1;
        meta_rdata <= {32'b1, source[31:0]};
        meta_rlast <= 1'b1;
      end else begin
        meta_rvalid <= 1'b0;
      end

      meta_b_pending_next = meta_b_pending;
      if (meta_wvalid && meta_wready) begin
        meta_b_pending_next = meta_b_pending_next + 1;
        meta_write_count <= meta_write_count + 1;
      end
      if (meta_bvalid && meta_bready)
        meta_b_pending_next = meta_b_pending_next - 1;
      meta_b_pending <= meta_b_pending_next;
      meta_bvalid <= meta_b_pending_next > 0;
    end

    if (started && ap_done) begin
      $display("RTL_ORACLE unique=%0d stride=%0d bitmap=%0d empty=%0d probe=%0d cycles=%0d meta_reads=%0d sorter_reads=%0d sorter_writes=%0d meta_writes=%0d word_reads=%0d word_writes=%0d new_bits=%0d new_count=%0d scratch_words=%0d",
               unique_arg, stride_arg, bitmap_arg, empty_arg, probe_arg,
               active_cycles, meta_read_count, sorter_read_count,
               sorter_write_count, meta_write_count, result_word_reads,
               result_word_writes, result_new_bits, result_new_count,
               result_scratch_words);
      $finish;
    end
    if (active_cycles > max_cycles_arg) begin
      $display("RTL_ORACLE_TIMEOUT active=%0d state=%h meta_reads=%0d sorter_reads=%0d sorter_writes=%0d meta_writes=%0d meta_arvalid=%0d meta_rvalid=%0d meta_rready=%0d sorter_awvalid=%0d sorter_wvalid=%0d sorter_bvalid=%0d sorter_bready=%0d",
               active_cycles, dut.ap_CS_fsm, meta_read_count,
               sorter_read_count, sorter_write_count, meta_write_count,
               meta_arvalid, meta_rvalid, meta_rready, sorter_awvalid,
               sorter_wvalid, sorter_bvalid, sorter_bready);
      $fatal(1, "candidate10 grouped-pass RTL oracle timed out");
    end
  end
endmodule
