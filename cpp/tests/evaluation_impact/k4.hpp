#pragma once

#include <iostream>

#include "control.hpp"
#include "oracle.hpp"

namespace evaluation_impact {
inline void k4(const st::Input& input, const Oracle& oracle, const std::filesystem::path& output,
               std::uint64_t latency, bool reverse, std::uint64_t maximum, const Control& selected) {
  using namespace spine::sim;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  scheduler.add_component(backend);
  RoutedReGraphConfig config;
  config.independent_read_write = true;
  config.adapter.empty_segment_exit_cycles = 0;
  config.adapter.row_line_reads = config.adapter.cross_row_pipeline = true;
  auto& cross = config.adapter.cross_row;
  cross.directory_cache_rows = selected.candidate ? 1024 : 8;
  cross.packet_pipeline = cross.bank_stream = cross.bank_read_beats = selected.candidate;
  if (selected.candidate) {
    cross.bank_fifo_lines = 256;
    cross.reader_pipeline_capacity = 2;
    cross.block_drain_cycles = 2;
  }
  config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
  config.compute.max_pending_requests = selected.k4_parents;
  config.compute.apply_request_window = selected.k4_apply_window;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                               GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), input.initial, config);
  system.register_components(reverse);
  std::uint64_t cycles = 0;
  for (; cycles < maximum && !system.done(); ++cycles) {
    scheduler.step(); system.advance_if_complete();
  }
  if (!system.done() || system.failed()) throw std::runtime_error(system.failure() + system.diagnostic());
  const auto state = system.encoded_state();
  st::require(state == oracle.states.back() && system.rounds().size() == oracle.states.size(),
              "K4 final state/round count differs from independent oracle");
  const auto buffer = system.rounds().size() & 1U;
  for (unsigned copy = 0; copy < 2; ++copy) {
    st::require(system.source_state(copy, buffer) == state, "K4 final source replica mismatch");
    wt::write_words(output / ("replica" + std::to_string(copy) + ".u32le"), state);
  }
  wt::write_words(output / "primary.u32le", state);
  for (std::size_t round = 0; round < system.rounds().size(); ++round) {
    const auto& row = system.rounds()[round];
    st::require(row.active_vertices == oracle.active[round], "K4 active trajectory mismatch");
    std::cout << "DEMO_ROUND {\"arm\":\"" << selected.arm << "\",\"round\":" << round
              << ",\"cycles\":" << row.end - row.start << ",\"active\":" << row.active_vertices << "}\n";
  }
  const auto c = system.counters();
  const auto traffic = backend.traffic_stats();
  const auto rounds = system.rounds().size();
  st::require(c.live_edges == input.edges.size() * rounds && c.axi_requests == c.axi_completions &&
      c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0 &&
      c.packets * 8 == c.live_edges + c.dummy_edges &&
      c.apply_reads == input.compact.aligned_vertices / 16 * rounds && c.apply_writes == c.apply_reads &&
      c.source_writes == c.apply_reads * 2 && c.status_writes == rounds &&
      traffic.writes.bytes == (input.compact.aligned_vertices * 12ull + 4) * rounds &&
      traffic.reads.bytes == (c.extent_reads + c.row_reads + c.segment_reads + c.source_lines + c.apply_reads) * 64,
      "K4 multi-round physical conservation failed");
  std::cout << "DEMO_RESULT {\"arm\":\"" << selected.arm << "\",\"cycles\":" << cycles
            << ",\"rounds\":" << rounds << ",\"read_bytes\":" << traffic.reads.bytes
            << ",\"write_bytes\":" << traffic.writes.bytes << ",\"replicas\":3,\"passed\":true}\n";
  system.unregister_components(); scheduler.remove_component(backend);
}
}  // namespace evaluation_impact
