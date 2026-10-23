#pragma once

#include "bootstrap.hpp"
#include "spine_sim/axi.hpp"
#include <chrono>
#include <iostream>

namespace figure_refresh {
inline void update_spine(const wc::Input& input, Scheduler& scheduler, ClockId clock,
                         MemoryBackend& backend, std::uint64_t maximum) {
  auto config = spine_config();
  auto state = preload_spine_resident_snapshot(slice(input, false), config);
  auto batch = slice(input, true);
  std::stable_sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst, a.weight, a.diff) < std::tie(b.src, b.dst, b.weight, b.diff);
  });
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
  SpineL0Maintenance maintenance("maintenance", clock, config, batch, ports, state);
  scheduler.add_component(maintenance);
  for (auto& port : graph) port->register_components(scheduler);
  sorted.register_components(scheduler); metadata.register_components(scheduler); result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until([&] { return maintenance.done() && sorted.idle() && metadata.idle() && result.idle() &&
      std::all_of(graph.begin(), graph.end(), [](const auto& port) { return port->idle(); }); }, maximum);
  require(maintenance.done() && !maintenance.failed() && backend.outstanding() == 0,
          "maintenance failed or exhausted cycle budget");
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
  const auto traffic = backend.traffic_stats();
  std::cout << "WARM_RESULT {\"arm\":\"spine\",\"cycles\":" << scheduler.clock(clock).completed_cycles
      << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
      << ",\"correctness\":true,\"physical_image_checked\":true,\"ledger_closed\":true}" << std::endl;
}
} // namespace figure_refresh
