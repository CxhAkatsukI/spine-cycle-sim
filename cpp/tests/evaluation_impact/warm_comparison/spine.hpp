#pragma once

#include "input.hpp"
#include "spine_sim/spine_system.hpp"
#include <fstream>
#include <iostream>

namespace warm_comparison {
inline void spine_with_backend(const Input& input, const std::filesystem::path& output,
    Scheduler& scheduler, ClockId clock, MemoryBackend& backend, std::uint64_t maximum) {
  SpineL0Config config;
  config.maintenance_architecture = SpineMaintenanceArchitecture::kCandidate10OnePass;
  config.segmented_fallback = true;
  config.reader_active_record_control_cycles = 520;
  config.segmented_fallback_setup_cycles = 3185887;
  SpineEdgeSlice snapshot{.vertices = input.after.compact.vertices, .edges = {}, .case_name = "old_graph"};
  for (const auto& edge : input.before)
    snapshot.edges.push_back({edge.source, edge.destination, edge.weight, 1});
  SpineResidentClassification classification;
  auto state = preload_spine_resident_snapshot(snapshot, config, &classification);
  SpineEdgeSlice batch{.vertices = snapshot.vertices, .edges = {}, .case_name = "three_shortcuts"};
  for (const auto& edge : input.updates) batch.edges.push_back({edge.source, edge.destination, edge.weight, 1});
  // The resident Spine ABI consumes an already source/destination-sorted batch.
  std::sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst) < std::tie(b.src, b.dst);
  });
  SpineVerticalSliceSystem system(scheduler, clock, backend, batch, input.root, 4096, config,
      std::move(state), SpineAxiInterfaceProfile{}, 7, 4, SpineOnChipMemoryProfile{}, false,
      input.after.initial, SpineOwnerSchedulerConfig{});
  system.register_components(); scheduler.add_component(backend);
  const auto result = system.run_sssp_to_convergence(128, maximum);
  std::cout << "WARM_SPINE_STATUS {\"converged\":" << result.converged
      << ",\"failed\":" << result.failed << ",\"rounds\":" << result.rounds.size()
      << ",\"owner_closed\":" << result.owner_ledger_closed
      << ",\"owner_quiescent\":" << result.owner_quiescent
      << ",\"reader_status\":" << system.reader_counters().source_protocol_status
      << ",\"reader_error\":" << system.reader_counters().range_task_error
      << ",\"reader_overflow\":" << system.reader_counters().done_overflow
      << ",\"compute_overflow\":" << system.compute_counters().done_overflow
      << ",\"outstanding\":" << backend.outstanding() << "}" << std::endl;
  require(result.converged && !result.failed && result.owner_ledger_closed && result.owner_quiescent &&
      backend.outstanding() == 0, "Spine failed to converge and close its owner ledger");
  const auto expected = dijkstra(snapshot.vertices, input.after.edges, input.root);
  require(system.compute().values() == expected, "Spine differs from independent new-graph Dijkstra");
  const auto traffic = backend.traffic_stats();
  for (const auto kind : {SpineAxiPortKind::kGraph, SpineAxiPortKind::kSortedEdges,
                         SpineAxiPortKind::kActiveBins, SpineAxiPortKind::kMetadata,
                         SpineAxiPortKind::kMaintenanceResult, SpineAxiPortKind::kVertexState,
                         SpineAxiPortKind::kActiveOut, SpineAxiPortKind::kActiveBitmap,
                         SpineAxiPortKind::kComputeResult}) {
    const auto& stats = system.axi_stats(kind);
    require(stats.requests_accepted == stats.requests_completed &&
        stats.beats_issued == stats.beats_completed, "Spine AXI ledger did not drain");
  }
  ei::wt::write_words(output / "final.u32le", system.compute().values());
  std::ofstream rounds(output / "rounds.csv");
  rounds.exceptions(std::ios::failbit | std::ios::badbit);
  rounds << "round,start,end,active_in,reader_sources,active_out\n";
  for (const auto& round : result.rounds)
    rounds << round.round << ',' << round.start_cycle << ',' << round.end_cycle << ','
        << round.active_in.size() << ',' << round.reader_sources.size() << ',' << round.active_out.size() << '\n';
  rounds.close();
  std::cout << "WARM_RESULT {\"arm\":\"spine\",\"cycles\":" << result.end_cycle - result.start_cycle
      << ",\"rounds\":" << result.rounds.size() << ",\"read_bytes\":" << traffic.reads.bytes
      << ",\"write_bytes\":" << traffic.writes.bytes << ",\"host_handoffs\":" << result.host_handoffs.size()
      << ",\"owner_control_cycles\":" << result.owner_control_cycles
      << ",\"hot_vertices\":" << classification.hot_vertices.size()
      << ",\"correctness\":true,\"ledger_closed\":true}" << std::endl;
}
inline void spine(const Input& input, const std::filesystem::path& output,
                  std::uint64_t latency, std::uint64_t maximum) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  spine_with_backend(input, output, scheduler, clock, backend, maximum);
}
}  // namespace warm_comparison
