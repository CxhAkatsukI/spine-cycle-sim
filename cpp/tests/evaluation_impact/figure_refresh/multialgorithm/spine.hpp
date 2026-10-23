#pragma once

#include "input.hpp"
#include "../../progress.hpp"
#include "spine_sim/spine_system.hpp"

namespace figure_refresh::multi {
inline void spine(const Input& input, const std::filesystem::path& output, Scheduler& scheduler,
                  ClockId clock, MemoryBackend& backend, std::uint64_t maximum) {
  auto config = spine_config();
  SpineResidentClassification classification;
  auto resident = preload_spine_resident_snapshot(slice(input.graph, false), config, &classification);
  auto batch = slice(input.graph, true);
  std::sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
    return std::tie(a.src, a.dst) < std::tie(b.src, b.dst);
  });
  std::uint64_t start = 0, end = 0;
  std::size_t rounds_count = 0;
  double error = 0;
  std::vector<std::uint32_t> final;
  std::ofstream rounds(output / "rounds.csv");
  rounds.exceptions(std::ios::failbit | std::ios::badbit);
  rounds << "round,start,end,active_in,reader_sources,active_out\n";
  const auto record = [&](const auto& result) {
    std::cout << "MULTI_SPINE_STATUS {\"converged\":" << result.converged
        << ",\"failed\":" << result.failed << ",\"rounds\":" << result.rounds.size()
        << ",\"owner_closed\":" << result.owner_ledger_closed
        << ",\"owner_quiescent\":" << result.owner_quiescent
        << ",\"outstanding\":" << backend.outstanding() << "}" << std::endl;
    require(result.converged && !result.failed && result.owner_ledger_closed &&
        result.owner_quiescent && backend.outstanding() == 0, "Spine convergence/owner ledger failed");
    start = result.start_cycle;
    end = result.end_cycle;
    rounds_count = result.rounds.size();
    for (const auto& r : result.rounds) {
      const auto sources = [&] {
        if constexpr (requires { r.reader_sources; }) return r.reader_sources.size();
        else return r.active_in.size();
      }();
      rounds << r.round << ',' << r.start_cycle << ',' << r.end_cycle << ','
          << r.active_in.size() << ',' << sources << ',' << r.active_out.size() << '\n';
    }
  };
  if (input.algorithm.kind == GraphAlgorithmKind::kConnectedComponents) {
    SpineVerticalSliceSystem system(scheduler, clock, backend, batch, 0, 4096, config,
        std::move(resident), SpineAxiInterfaceProfile{}, 7, 4, SpineOnChipMemoryProfile{}, false,
        input.graph.after.initial, SpineOwnerSchedulerConfig{}, std::nullopt, input.algorithm.kind);
    system.register_components(); scheduler.add_component(backend);
    record(system.run_sssp_to_convergence(256, maximum));
    final = system.compute().values();
    require(final == input.expected_labels, "Spine CC differs from independent union-find oracle");
    for (const auto kind : {SpineAxiPortKind::kGraph, SpineAxiPortKind::kSortedEdges,
          SpineAxiPortKind::kActiveBins, SpineAxiPortKind::kMetadata,
          SpineAxiPortKind::kMaintenanceResult, SpineAxiPortKind::kVertexState,
          SpineAxiPortKind::kActiveOut, SpineAxiPortKind::kActiveBitmap,
          SpineAxiPortKind::kComputeResult}) {
      const auto& stats = system.axi_stats(kind);
      require(stats.requests_accepted == stats.requests_completed && stats.beats_issued == stats.beats_completed,
              "Spine CC AXI ledger did not drain");
    }
  } else {
    auto execution = slice(input.graph, false);
    for (const auto& e : batch.edges) execution.edges.push_back(e);
    auto initial = input.graph.after.initial;
    initial.auxiliary = input.correction.seed_words;
    initial.active_vertices = input.correction.active_vertices;
    SpinePageRankVerticalSliceSystem system(scheduler, clock, backend, batch,
        GraphAlgorithmPolicy(input.algorithm), config, SpineAxiInterfaceProfile{}, AlgorithmPipelineConfig{},
        SpineSplitPageRankCompute::kDefaultMemoryRequestWindow, std::move(resident), execution,
        std::nullopt, initial, input.correction, SpineOwnerSchedulerConfig{});
    system.register_components(); scheduler.add_component(backend);
    record(system.run_frontier_to_convergence(256, maximum));
    final = system.compute().rank_words();
    const auto residual = system.compute().residual_words();
    error = validate_rank(input, final, residual);
    wc::ei::wt::write_words(output / "residual.u32le", residual);
    const auto& c = system.initial_active_counters();
    require(c.enabled && c.residual_correction_timed && c.request_ledger_closed &&
        c.memory_requests_issued == c.memory_requests_completed && c.end_cycle > c.start_cycle &&
        c.touched_sources == input.correction.touched_sources.size(), "Spine PR correction ledger failed");
    std::cout << "CORRECTION_TRACE {\"oracle_directed\":true,\"cycles\":" << c.end_cycle - c.start_cycle
        << ",\"touched_sources\":" << c.touched_sources << ",\"physical_edges\":" << c.physical_edge_records
        << ",\"seeded_vertices\":" << c.seeded_vertices << ",\"active_vertices\":" << c.active_vertices
        << ",\"rank_read_bytes\":" << c.rank_read_bytes << ",\"degree_read_bytes\":" << c.degree_read_bytes
        << ",\"graph_read_bytes\":" << c.graph_read_bytes << ",\"residual_read_bytes\":" << c.residual_read_bytes
        << ",\"degree_write_bytes\":" << c.degree_write_bytes << ",\"residual_write_bytes\":" << c.residual_write_bytes
        << ",\"active_write_bytes\":" << c.write_bytes << "}" << std::endl;
  }
  rounds.close();
  wc::ei::wt::write_words(output / "final.u32le", final);
  const auto traffic = backend.traffic_stats();
  std::cout << "WARM_RESULT {\"arm\":\"spine\",\"cycles\":" << end - start
      << ",\"rounds\":" << rounds_count << ",\"read_bytes\":" << traffic.reads.bytes
      << ",\"write_bytes\":" << traffic.writes.bytes << ",\"oracle_max_error\":" << error
      << ",\"hot_vertices\":" << classification.hot_vertices.size()
      << ",\"correction_oracle_directed\":" << (input.algorithm.kind == GraphAlgorithmKind::kResidualPageRank ? "true" : "false")
      << ",\"correctness\":true,\"ledger_closed\":true}" << std::endl;
}
} // namespace figure_refresh::multi
