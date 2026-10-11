#include <algorithm>
#include <charconv>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#include "../../original_regraph/sssp/real_input.hpp"

namespace st = original_regraph_sssp_real_test;
namespace wt = original_regraph_whole_test;
namespace rg = spine::sim::original_regraph;

namespace {
std::uint64_t number(const char* argument) {
  const std::string_view text(argument);
  std::uint64_t value = 0;
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  st::require(parsed.ec == std::errc{} && parsed.ptr == text.data() + text.size(),
              "invalid unsigned integer argument");
  return value;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    st::require(argc == 7, "usage: round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES EMPTY_EXIT");
    const auto latency = number(argv[3]), reverse = number(argv[4]);
    const auto maximum = number(argv[5]), empty_exit = number(argv[6]);
    st::require(latency && maximum && reverse <= 1, "invalid bounded service, order or cycle limit");
    st::require(empty_exit == 73 || empty_exit == 0, "EMPTY_EXIT must be 73 or 0");
    const auto output = std::filesystem::path(argv[2]);
    st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                "output must be an existing empty directory");
    const auto input = st::Input::load(argv[1]);
    const auto expected_active = static_cast<std::uint64_t>(std::count_if(
        input.compact.expected.begin(), input.compact.expected.end(),
        [](auto word) { return (word & rg::kSsspActive) != 0; }));

    using namespace spine::sim;
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("core", 150);
    MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
    scheduler.add_component(backend);
    RoutedReGraphConfig config;
    config.fixed_rounds = 1;
    config.independent_read_write = true;
    config.adapter.empty_segment_exit_cycles = empty_exit;
    config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
    config.compute.apply_request_window = 16;
    config.compute.vertex_state_base = config.compute.source_state_base = 0;
    config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
    config.status_address = config.compute.source_state_buffer_stride;
    auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                                GraSuPmaWordAbi::kWeightedFullWord);
    RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), input.initial, config);
    system.register_components(reverse != 0);
    std::cout << "SENSITIVITY {\"mode\":\""
              << (empty_exit == 73 ? "legacy_v4_control" : "empty_helper_bypass_uncalibrated")
              << "\",\"empty_segment_exit_cycles\":" << config.adapter.empty_segment_exit_cycles
              << ",\"hardware_timing_admitted\":false,\"publication_match_admitted\":false}\n";

    std::uint64_t cycles = 0;
    for (; cycles < maximum && !system.done(); ++cycles) {
      scheduler.step();
      system.advance_if_complete();
    }
    if (!system.done() || system.failed()) throw std::runtime_error(system.failure() + system.diagnostic());
    const auto state = system.encoded_state();
    st::require(state == input.compact.expected && system.rounds().size() == 1,
                "actual K4 real-topology full state differs from oracle");
    wt::write_words(output / "k4_primary.u32le", state);
    for (unsigned copy = 0; copy < 2; ++copy) {
      const auto replica = system.source_state(copy, 1);
      st::require(replica == state, "actual K4 real-topology source replica differs from primary");
      wt::write_words(output / ("k4_source" + std::to_string(copy) + ".u32le"), replica);
    }
    const auto c = system.counters();
    const auto traffic = backend.traffic_stats();
    st::require(c.live_edges == input.edges.size() && c.axi_requests == c.axi_completions &&
                c.packets * 8 == c.live_edges + c.dummy_edges &&
                system.rounds().front().active_vertices == expected_active &&
                c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0 &&
                c.apply_reads == input.compact.aligned_vertices / 16 &&
                c.apply_writes == c.apply_reads && c.source_writes == c.apply_reads * 2 && c.status_writes == 1 &&
                traffic.writes.bytes == input.compact.aligned_vertices * 12ull + 4 &&
                traffic.reads.bytes == (c.extent_reads + c.row_reads + c.segment_reads +
                                       c.source_lines + c.apply_reads) * 64,
                "actual K4 real-topology request/state conservation failed");
    std::cout << "REAL_ROUND {\"path\":\"actual_k4\",\"passed\":true,\"cycles\":" << cycles
              << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
              << ",\"extent_reads\":" << c.extent_reads
              << ",\"row_reads\":" << c.row_reads << ",\"segment_reads\":" << c.segment_reads
              << ",\"source_lines\":" << c.source_lines << ",\"physical_packets\":" << c.packets
              << ",\"live_edges\":" << c.live_edges << ",\"dummy_edges\":" << c.dummy_edges
              << ",\"active_vertices\":" << system.rounds().front().active_vertices
              << ",\"checked_words_per_replica\":" << state.size() << ",\"replicas\":3"
              << ",\"full_state_and_traffic_pass\":true}\n";
    system.unregister_components();
    scheduler.remove_component(backend);
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
