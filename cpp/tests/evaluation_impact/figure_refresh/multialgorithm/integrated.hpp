#pragma once

#include "input.hpp"
#include "../../warm_comparison/resident_g.hpp"
#include "../../k4_config.hpp"
#include "../../progress.hpp"

namespace figure_refresh::multi {
inline void integrated(const Input& input, const std::filesystem::path& output, Scheduler& scheduler,
                       ClockId clock, MemoryBackend& backend, std::uint64_t maximum) {
  scheduler.add_component(backend);
  const auto resident = wc::resident_g(input.graph, scheduler, clock, backend, maximum);
  auto config = wc::ei::k4_configuration(wc::ei::control("prefetch_gather_reuse"));
  config.algorithm = input.algorithm;
  config.reuse_resident_pma = true;
  config.compute.cache_segments_per_half = 131072;
  config.compute.runtime_physical_updates_per_shard = resident.physical_counts;
  const auto stride = input.graph.after.compact.aligned_vertices * 4ull;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = stride;
  config.status_address = stride;
  const bool pr = input.algorithm.kind == GraphAlgorithmKind::kResidualPageRank;
  if (pr) {
    config.old_out_degrees = input.old_degree;
    config.degree_deltas.resize(input.old_degree.size());
    for (std::size_t v = 0; v < input.old_degree.size(); ++v)
      config.degree_deltas[v] = std::int32_t(input.new_degree[v]) - std::int32_t(input.old_degree[v]);
    config.compute.split_pagerank_state = true;
    config.compute.residual_state_base = stride;
    config.compute.degree_base = stride * 2;
    config.status_address = stride * 3;
    config.compute.max_supersteps = 256;
  }
  RoutedReGraphSystem r(scheduler, clock, backend, resident.layout, input.graph.after.initial, config);
  require(handoff_test::same_placement(resident.plan, r.runtime_plan()) &&
      handoff_test::graph_bytes(backend, resident.layout, resident.plan) == resident.graph &&
      backend.traffic_stats().reads.bytes == resident.traffic.reads.bytes &&
      backend.traffic_stats().writes.bytes == resident.traffic.writes.bytes,
      "R initialization changed PMA or issued memory traffic");
  r.register_components();
  for (std::uint64_t i = 0; i < maximum && !r.done() && !r.failed(); ++i) {
    scheduler.step(); r.advance_if_complete();
  }
  if (!r.done() || r.failed()) throw std::runtime_error(r.diagnostic());
  const auto state = r.distances();
  const double error = pr ? validate_rank(input, state, r.residual_words()) : 0;
  if (!pr) require(state == input.expected_labels, "CC differs from independent union-find oracle");
  require(r.source_state(0, r.rounds().size() & 1U) == r.source_state(1, r.rounds().size() & 1U),
          "R final source replicas differ");
  const auto rc = r.counters();
  const auto rt = subtract_memory_traffic(backend.traffic_stats(), resident.traffic);
  const auto read_beats = rc.extent_reads + rc.row_reads + rc.segment_reads + rc.source_lines +
      rc.apply_reads + rc.degree_reads + rc.prepare_state_reads + rc.prepare_degree_reads;
  require(rc.axi_requests == rc.axi_completions && rc.axi_beats == rc.axi_completed_beats &&
      backend.outstanding() == 0 && rt.reads.bytes == 64 * read_beats &&
      rt.reads.bytes + rt.writes.bytes + 60 * r.rounds().size() == rc.axi_beats * 64 &&
      rc.live_edges == input.graph.after.edges.size() * r.rounds().size() &&
      rc.packets * 8 == rc.live_edges + rc.dummy_edges &&
      handoff_test::graph_bytes(backend, resident.layout, resident.plan) == resident.graph,
      "R physical request/byte/graph ledger did not close");
  if (pr) require(rc.prepare_state_reads > 0 && rc.prepare_source_writes > 0 &&
      rc.prepare_degree_writes > 0 && rc.degree_reads > 0, "PR preparation was omitted");
  wc::ei::write_progress(r, output);
  wc::ei::wt::write_words(output / "final.u32le", state);
  if (pr) wc::ei::wt::write_words(output / "residual.u32le", r.residual_words());
  const auto& gc = resident.counters;
  const auto& gt = resident.traffic;
  std::cout << "WARM_RESULT {\"arm\":\"gr\",\"g_cycles\":" << gc.end_cycle - gc.start_cycle
      << ",\"r_cycles\":" << rc.end_cycle - rc.start_cycle << ",\"cycles\":" << rc.end_cycle - gc.start_cycle
      << ",\"rounds\":" << r.rounds().size() << ",\"g_read_bytes\":" << gt.reads.bytes
      << ",\"g_write_bytes\":" << gt.writes.bytes << ",\"read_bytes\":" << gt.reads.bytes + rt.reads.bytes
      << ",\"write_bytes\":" << gt.writes.bytes + rt.writes.bytes << ",\"oracle_max_error\":" << error
      << ",\"preparation_cycles\":" << rc.prepare_cycles << ",\"physical_handoff\":true,\"correctness\":true,\"ledger_closed\":true}" << std::endl;
  r.unregister_components(); scheduler.remove_component(backend);
}
} // namespace figure_refresh::multi
