#pragma once

#include "bootstrap.hpp"
#include "spine_sim/axi.hpp"
#include <iostream>

namespace figure_refresh {
inline SpineEdgeSlice ordered_batch(const SpineEdgeSlice& trace, std::size_t index,
                                   std::size_t count) {
  const auto begin = trace.edges.begin() + index * trace.edges.size() / count;
  const auto end = trace.edges.begin() + (index + 1) * trace.edges.size() / count;
  SpineEdgeSlice batch{.vertices = trace.vertices, .edges = {begin, end},
                       .case_name = trace.case_name};
  std::stable_sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst, a.weight, a.diff) < std::tie(b.src, b.dst, b.weight, b.diff);
  });
  return batch;
}

inline void update_spine(const wc::Input& input, Scheduler& scheduler, ClockId clock,
                         MemoryBackend& backend, std::uint64_t maximum,
                         std::size_t batches) {
  const auto trace = slice(input, true);
  require(batches > 0 && batches <= trace.edges.size(), "batch count would create empty batches");
  auto config = spine_config();
  auto state = preload_spine_resident_snapshot(slice(input, false), config);
  std::vector<std::unique_ptr<FixedAxiPort>> graph;
  SpineL0Ports ports;
  for (std::size_t i = 0; i < ports.graph.size(); ++i) {
    graph.push_back(std::make_unique<FixedAxiPort>("graph" + std::to_string(i), clock,
        FixedAxiPortConfig{.memory_channels = 32, .channel = i,
                          .initiator_id = static_cast<std::uint32_t>(800 + i)}, backend));
    ports.graph[i] = graph.back().get();
  }
  FixedAxiPort sorted("sorted", clock, {.memory_channels = 32, .channel = 16,
      .initiator_id = 816, .data_width_bytes = 16, .stream_read_beats = true}, backend);
  FixedAxiPort metadata("metadata", clock, {.memory_channels = 32, .channel = 20, .initiator_id = 820}, backend);
  FixedAxiPort result("result", clock, {.memory_channels = 32, .channel = 21, .initiator_id = 821}, backend);
  ports.sorted_edges = &sorted; ports.metadata = &metadata; ports.result = &result;
  SpineL0Maintenance maintenance("maintenance", clock, config, ordered_batch(trace, 0, batches), ports, state);
  scheduler.add_component(maintenance);
  for (auto& port : graph) port->register_components(scheduler);
  sorted.register_components(scheduler); metadata.register_components(scheduler); result.register_components(scheduler);
  scheduler.add_component(backend);
  const auto drained = [&] {
    return maintenance.done() && backend.outstanding() == 0 && sorted.idle() && metadata.idle() && result.idle() &&
        std::all_of(graph.begin(), graph.end(), [](const auto& port) { return port->idle(); });
  };
  struct BatchWork {
    std::uint64_t cycles, read_bytes, write_bytes;
    std::size_t updates;
  };
  std::vector<BatchWork> work;
  for (std::size_t index = 0; index < batches; ++index) {
    if (index) maintenance.reset_batch(ordered_batch(trace, index, batches));
    const auto start = scheduler.clock(clock).completed_cycles;
    const auto before = backend.traffic_stats();
    scheduler.run_until([&] { return drained() || maintenance.failed(); }, maximum - start);
    if (maintenance.failed()) throw std::runtime_error(maintenance.failure());
    require(drained(), "maintenance exhausted cycle budget");
    const auto traffic = subtract_memory_traffic(backend.traffic_stats(), before);
    work.push_back({scheduler.clock(clock).completed_cycles - start, traffic.reads.bytes,
                    traffic.writes.bytes, (index + 1) * trace.edges.size() / batches -
                                              index * trace.edges.size() / batches});
  }
  // Materialize the signed sum independently, including old LSM versions.
  std::map<std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>, std::int64_t> actual, expected;
  for (const auto& edge : input.after.edges) ++expected[{edge.source, edge.destination, edge.weight}];
  for (const auto* levels : {&state.cold_levels, &state.hot_levels})
    for (const auto& partition : *levels) for (const auto& level : partition)
      for (const auto& edge : level) actual[{edge.src, edge.dst, edge.weight}] += edge.diff;
  for (auto it = actual.begin(); it != actual.end(); )
    if (!it->second) it = actual.erase(it); else ++it;
  require(actual == expected, "maintenance final graph differs from insertion oracle");
  validate_physical_image(state, input.after.compact.vertices, config, backend);
  auto check = [](const auto& port) {
    const auto& s = port.master().stats();
    require(s.requests_accepted == s.requests_completed && s.beats_issued == s.beats_completed,
            "maintenance AXI did not drain");
  };
  for (const auto& port : graph) check(*port);
  check(sorted); check(metadata); check(result);
  if (batches > 1) {
    for (std::size_t index = 0; index < work.size(); ++index) {
      const auto& batch = work[index];
      std::cout << "WARM_BATCH {\"batch\":" << index << ",\"updates\":" << batch.updates
          << ",\"cycles\":" << batch.cycles << ",\"read_bytes\":" << batch.read_bytes
          << ",\"write_bytes\":" << batch.write_bytes << "}\n";
    }
  }
  const auto traffic = backend.traffic_stats();
  std::cout << "WARM_RESULT {\"arm\":\"spine\",\"cycles\":" << scheduler.clock(clock).completed_cycles
      << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
      << ",\"correctness\":true,\"physical_image_checked\":true,\"ledger_closed\":true}" << std::endl;
}
} // namespace figure_refresh
