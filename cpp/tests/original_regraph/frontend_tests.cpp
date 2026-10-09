#include "frontend_execution.hpp"

namespace {
using namespace original_regraph_frontend_test;

void test_positive_matrix() {
  const auto zero = run("source_window0", {0, 0});
  const auto one = run("source_window1", {1, 1});
  const auto sequential = run("source_windows012", {0, 1, 2});
  require(zero.completed && one.completed && sequential.completed, "original positive Scatter fixtures failed");
  require(zero.normal_requests == 2 && one.normal_requests == 3 && sequential.normal_requests == 4 &&
          zero.checked_words + one.checked_words + sequential.checked_words == 224,
          "request-dependent original-source matrix work differs");
  const auto reversed = run("reverse_registration", {0, 1, 2}, {.reverse_registration = true});
  require(reversed == sequential, "registration order changed frontend cycles/counters");
  const auto pressured = run("depth1_slow_sink", {0, 1, 2}, {
      .fifo_depth = 1, .sink_interval = 37, .sink_start = 6000});
  require(pressured.completed && pressured.scatter_stalls && pressured.source_response_stalls &&
          pressured.cycles > sequential.cycles && pressured.source_bytes == sequential.source_bytes,
          "finite pressure did not preserve work or propagate to source port");
  const auto limited = run("one_outstanding", {0, 1, 2}, {.outstanding = 1});
  require(limited.completed && limited.cycles > sequential.cycles &&
          limited.source_bytes == sequential.source_bytes, "outstanding budget had no modeled effect");
  const auto latency = run("memory_latency128", {0, 1, 2}, {.memory_latency = 128});
  require(latency.completed && latency.cycles > sequential.cycles, "memory latency had no effect");
  const auto gathered = run("a4_memory_to_merged", {0, 1, 2}, {
      .little = 4, .gather = true, .destination_offset = 65536});
  require(gathered.completed && gathered.checked_words == 65536 && gathered.normal_requests == 16 &&
          gathered.source_bytes == 262144 && gathered.edge_bytes == 3072,
          "complete four-Little input/Gather work mismatch");
}

void test_gaps_and_allocation_boundary() {
  const auto initial_gap = run("source_initial_round2", {2});
  require(initial_gap.completed && initial_gap.checked_words == 32 && initial_gap.normal_requests == 3,
          "original signed source-gap guard was modeled as unsigned wraparound");
  const auto internal_gap = run("source_gap0_to3", {0, 3});
  require(internal_gap.completed && internal_gap.checked_words == 64 && internal_gap.normal_requests == 4,
          "original internal source-gap request sequence mismatch");
  bool rejected = false;
  try { run("unallocated_lookahead", {0}, {.property_vertices = 4096}); }
  catch (const std::out_of_range& error) {
    rejected = true;
    std::cout << "FRONTEND_REJECTION {\"id\":\"unallocated_lookahead\","
                 "\"expected_rejection\":true,\"boundary\":\"source_allocation\"}\n";
    require(std::string(error.what()).find("lookahead exceeds") != std::string::npos,
            "unexpected out-of-range error instead of source allocation rejection");
  }
  require(rejected, "source lookahead silently read outside its allocation");
}
}  // namespace

int main() {
  try {
    const auto port = axi_config(1, 0, {});
    const rg::LittleTiming timing;
    std::cout << "FRONTEND_CONFIG {\"clock_mhz\":210,\"source_window_vertices\":"
              << rg::kSourceWindowVertices << ",\"partition_vertices\":" << rg::kLittleVertices
              << ",\"axi_data_bytes\":" << port.data_width_bytes
              << ",\"axi_max_burst_beats\":" << port.max_burst_beats
              << ",\"default_outstanding\":" << port.max_outstanding_bursts
              << ",\"read_reorder_capacity\":" << port.read_reorder_capacity
              << ",\"edge_latency\":" << rg::kEdgeReaderTiming.latency
              << ",\"scatter_latency\":" << rg::kScatterTiming.latency
              << ",\"gather_latency\":" << timing.gather.latency
              << ",\"drain_latency\":" << timing.drain.latency
              << ",\"local_merge_latency\":" << timing.local_merge.latency
              << ",\"global_merge_latency\":" << timing.global_merge.latency << "}\n";
    test_positive_matrix();
    test_gaps_and_allocation_boundary();
    std::cout << "Original Little memory/frontend checks passed (one expected allocation rejection)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
