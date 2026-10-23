#pragma once

#include "input.hpp"
#include "resident_g.hpp"
#include "../k4_config.hpp"
#include "../handoff/memory.hpp"
#include "../progress.hpp"
#include <iostream>

namespace warm_comparison {
inline void integrated_with_backend(const Input& input, const std::filesystem::path& output,
    Scheduler& scheduler, ClockId clock, MemoryBackend& backend, bool reverse,
    std::uint64_t maximum, bool update_only = false) {
  const auto external_components = scheduler.component_count();
  scheduler.add_component(backend);
  const auto resident = resident_g(input, scheduler, clock, backend, maximum);
  const auto& layout = resident.layout;
  const auto& plan = resident.plan;
  const auto& gc = resident.counters;
  const auto& gt = resident.traffic;
  if (update_only) {
    std::cout << "WARM_RESULT {\"arm\":\"gr\",\"cycles\":" << gc.end_cycle - gc.start_cycle
        << ",\"read_bytes\":" << gt.reads.bytes << ",\"write_bytes\":" << gt.writes.bytes
        << ",\"correctness\":true,\"ledger_closed\":true}" << std::endl;
    return;
  }
  const auto& graph = resident.graph;
  auto config = ei::k4_configuration(ei::control("prefetch_gather_reuse"));
  config.reuse_resident_pma = true;
  config.compute.cache_segments_per_half = 131072;
  config.compute.runtime_physical_updates_per_shard = resident.physical_counts;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.after.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  RoutedReGraphSystem r(scheduler, clock, backend, layout, input.after.initial, config);
  require(handoff_test::same_placement(plan, r.runtime_plan()), "G/R placement mismatch");
  require(handoff_test::graph_bytes(backend, layout, plan) == graph &&
      backend.traffic_stats().reads.bytes == gt.reads.bytes &&
      backend.traffic_stats().writes.bytes == gt.writes.bytes, "R initialization rewrote PMA or injected traffic");
  r.register_components(reverse);
  for (std::uint64_t i = 0; i < maximum && !r.done() && !r.failed(); ++i) {
    scheduler.step(); r.advance_if_complete();
  }
  require(r.done() && !r.failed(), "R failed or exhausted cycle budget");
  require(r.encoded_state() == input.oracle.states.back() &&
      r.rounds().size() == input.oracle.states.size(), "R did not reach the common new-graph oracle");
  for (std::size_t i = 0; i < r.rounds().size(); ++i)
    require(r.rounds()[i].active_vertices == input.oracle.active[i], "R active trajectory mismatch");
  for (unsigned copy = 0; copy < 2; ++copy)
    require(r.source_state(copy, r.rounds().size() & 1U) == r.encoded_state(), "R final replica mismatch");
  require(handoff_test::graph_bytes(backend, layout, plan) == graph, "R modified resident PMA");
  const auto rc = r.counters();
  const auto rt = subtract_memory_traffic(backend.traffic_stats(), gt);
  require(rc.start_cycle >= gc.end_cycle && rc.axi_requests == rc.axi_completions &&
      rc.axi_beats == rc.axi_completed_beats && backend.outstanding() == 0 &&
      rc.live_edges == input.after.edges.size() * r.rounds().size() &&
      rc.packets * 8 == rc.live_edges + rc.dummy_edges &&
      rt.reads.bytes == (rc.extent_reads + rc.row_reads + rc.segment_reads + rc.source_lines + rc.apply_reads) * 64 &&
      rt.writes.bytes == (input.after.compact.aligned_vertices * 12ull + 4) * r.rounds().size(),
      "R physical ledger or non-overlap mismatch");
  ei::write_progress(r, output);
  ei::wt::write_words(output / "final.u32le", r.distances());
  std::cout << "WARM_RESULT {\"arm\":\"gr\",\"g_cycles\":" << gc.end_cycle - gc.start_cycle
      << ",\"r_cycles\":" << rc.end_cycle - rc.start_cycle << ",\"cycles\":" << rc.end_cycle - gc.start_cycle
      << ",\"handoff_cycle_gap\":" << rc.start_cycle - gc.end_cycle
      << ",\"rounds\":" << r.rounds().size() << ",\"g_read_bytes\":" << gt.reads.bytes
      << ",\"g_write_bytes\":" << gt.writes.bytes << ",\"read_bytes\":" << gt.reads.bytes + rt.reads.bytes
      << ",\"write_bytes\":" << gt.writes.bytes + rt.writes.bytes
      << ",\"physical_handoff\":true,\"correctness\":true,\"ledger_closed\":true}" << std::endl;
  r.unregister_components(); scheduler.remove_component(backend);
  require(scheduler.component_count() == external_components, "G/R leaked scheduler components");
}
inline void integrated(const Input& input, const std::filesystem::path& output,
                       std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  integrated_with_backend(input, output, scheduler, clock, backend, reverse, maximum);
}
}  // namespace warm_comparison
