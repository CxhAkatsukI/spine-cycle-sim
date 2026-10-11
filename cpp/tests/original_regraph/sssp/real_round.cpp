#include <iostream>

#include "real_input.hpp"
#include "../whole_graph/compact_source.hpp"
#include "../whole_graph/compute_wiring.hpp"
#include "spine_sim/original_regraph/sssp_apply.hpp"

namespace st = original_regraph_sssp_real_test;
namespace wt = original_regraph_whole_test;
namespace rg = spine::sim::original_regraph;

namespace {
std::uint64_t expected_active(const st::Input& input) {
  return std::count_if(input.compact.expected.begin(), input.compact.expected.end(),
                       [](auto word) { return (word & rg::kSsspActive) != 0; });
}

std::uint64_t run_a4(const st::Input& input, const std::filesystem::path& output,
                     std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  // Shared MemoryFixture service is selected explicitly; PR defaults stay frozen.
  wt::ComputeOptions options;
  options.udf = rg::Udf::kWeightedSssp;
  options.memory = {150, 32, 32};
  options.apply_timing = rg::kSsspSchedulePostReadTiming;
  options.sssp_response_anchored = true;
  wt::ComputeWiring<wt::CompactSource, rg::SsspApply> model(
      wt::CompactSource(input.compact, rg::Udf::kWeightedSssp), 2, latency, reverse, 2, options);
  model.initialize();
  model.begin();
  std::uint64_t cycles = 0;
  for (; cycles < maximum; ++cycles) {
    model.memory.scheduler.step();
    model.advance(cycles + 1);
    if (model.finished()) { ++cycles; break; }
  }
  st::require(model.finished(), "A4 real-topology round timed out");
  const auto& c = input.compact;
  for (unsigned replica = 0; replica < 4; ++replica) {
    const auto payload = model.memory.backend->inspect_payload(replica * 2 + 1, wt::kOutputAddress,
                                                              c.aligned_vertices * 4ull + 64);
    std::vector<std::uint32_t> actual(c.aligned_vertices);
    for (std::size_t v = 0; v < actual.size(); ++v) {
      for (unsigned b = 0; b < 4; ++b) actual[v] |= std::uint32_t{payload[v * 4 + b]} << (b * 8);
      st::require(actual[v] == c.expected[v], "A4 real-topology full replica differs from oracle");
    }
    st::require(std::all_of(payload.end() - 64, payload.end(), [](auto b) { return b == 0xa5; }),
                "A4 real-topology writer changed guard");
    wt::write_words(output / ("a4_replica" + std::to_string(replica) + ".u32le"), actual);
  }
  std::uint64_t edge_reads = 0, source_reads = 0, valid = 0, dummy = 0;
  for (const auto& path : model.paths) {
    edge_reads += path.components.reader->counters().read_bytes;
    source_reads += path.components.source->counters().read_bytes;
    valid += path.components.gather->counters().valid_updates;
    dummy += path.components.gather->counters().dummy_updates;
    st::require(path.starts.size() == c.partitions && path.completions.size() == c.partitions &&
                path.components.source->counters().rounds == path.components.source->counters().acknowledgements,
                "A4 source/partition acknowledgement mismatch");
  }
  const auto traffic = model.memory.backend->traffic_stats();
  st::require(valid == c.logical_edges && dummy == c.dummy_edges && edge_reads == c.physical_edges * 8 &&
              model.apply->counters().active_vertices == expected_active(input) &&
              traffic.reads.bytes == edge_reads + source_reads + c.published_vertices * 4ull &&
              traffic.writes.bytes == c.published_vertices * 16ull &&
              model.apply->counters().old_state_responses == c.published_vertices / 16 &&
              model.writer->counters().write_requests == model.writer->counters().acknowledgements,
              "A4 real-topology traffic or acknowledgement conservation failed");
  std::cout << "REAL_ROUND {\"path\":\"a4\",\"passed\":true,\"cycles\":" << cycles
            << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
            << ",\"edge_read_bytes\":" << edge_reads << ",\"source_read_bytes\":" << source_reads
            << ",\"active_vertices\":" << model.apply->counters().active_vertices
            << ",\"physical_edges\":" << c.physical_edges << ",\"dummy_edges\":" << dummy
            << ",\"checked_words_per_replica\":" << c.aligned_vertices << ",\"replicas\":4"
            << ",\"full_state_and_traffic_pass\":true}\n";
  return cycles;
}

std::uint64_t run_k4(const st::Input& input, const std::filesystem::path& output,
                     std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  using namespace spine::sim;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  scheduler.add_component(backend);
  RoutedReGraphConfig config;
  config.fixed_rounds = 1;
  config.independent_read_write = true;
  config.adapter.empty_segment_exit_cycles = 73;
  config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
  config.compute.apply_request_window = 16;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                              GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), input.initial, config);
  system.register_components(reverse);
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
              system.rounds().front().active_vertices == expected_active(input) &&
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
  return cycles;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    st::require(argc == 6, "usage: real_round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES");
    const auto input = st::Input::load(argv[1]);
    const auto output = std::filesystem::path(argv[2]);
    st::require(std::filesystem::is_directory(output), "missing unique output directory");
    const auto latency = std::stoull(argv[3]), maximum = std::stoull(argv[5]);
    const bool reverse = std::stoul(argv[4]) != 0;
    st::require(latency && maximum, "invalid bounded service or cycle limit");
    run_a4(input, output, latency, reverse, maximum);
    run_k4(input, output, latency, reverse, maximum);
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
