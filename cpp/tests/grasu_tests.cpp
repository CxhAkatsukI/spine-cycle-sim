#include <algorithm>
#include <cstdint>
#include <functional>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/grasu.hpp"
#include "spine_sim/grasu_regraph.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace {

using spine::sim::GraSuEdge;
using spine::sim::GraSuNativeConfig;
using spine::sim::GraSuPmaLayout;
using spine::sim::GraSuPmaUpdateSystem;
using spine::sim::GraSuReGraphConfig;
using spine::sim::GraSuReGraphSsspSystem;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::Scheduler;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::set<std::pair<std::uint32_t, std::uint32_t>>
edge_set(const std::vector<GraSuEdge> &edges) {
  std::set<std::pair<std::uint32_t, std::uint32_t>> result;
  for (const GraSuEdge &edge : edges) {
    result.emplace(edge.source, edge.destination);
  }
  return result;
}

void test_pma_layout_preserves_segment_reservations() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 2},
      {.source = 0, .destination = 40},
      {.source = 1, .destination = 7},
  };
  std::vector<GraSuEdge> reserved;
  for (std::uint32_t destination = 1; destination <= 40; ++destination) {
    reserved.push_back({.source = 0, .destination = destination});
  }
  const GraSuPmaLayout layout = GraSuPmaLayout::build(64, initial, reserved);
  require(layout.row_slot_bounds[0] ==
              std::pair<std::uint32_t, std::uint32_t>(0, 48),
          "GraSU row was not rounded to three 16-slot segments");
  require(layout.binary_heads.size() == 4,
          "GraSU binary-head count did not match reserved PMA segments");
  require(layout.segment_for({.source = 0, .destination = 17}) == 1,
          "GraSU binary search selected the wrong reserved segment");
  require(edge_set(layout.live_edges()) == edge_set(initial),
          "GraSU PMA layout changed initial live edges");
}

void test_native_update_crosses_cache_ddr_and_parity() {
  std::vector<GraSuEdge> initial;
  std::vector<GraSuEdge> reserved;
  for (std::uint32_t source = 0; source < 4; ++source) {
    for (std::uint32_t lane = 0; lane < 48; ++lane) {
      const std::uint32_t destination = source * 64 + lane;
      reserved.push_back({.source = source, .destination = destination});
      if ((lane % 5) == 0) {
        initial.push_back({.source = source, .destination = destination});
      }
    }
  }
  const std::vector<GraSuEdge> updates = {
      {.source = 0, .destination = 1},
      {.source = 0, .destination = 16},
      {.source = 0, .destination = 32},
      {.source = 1, .destination = 65},
      {.source = 0, .destination = 5, .delete_op = true},
      {.source = 1, .destination = 80},
      {.source = 2, .destination = 129},
      {.source = 3, .destination = 193},
      {.source = 0, .destination = 2},
      {.source = 0, .destination = 3},
  };

  GraSuPmaLayout layout = GraSuPmaLayout::build(256, initial, reserved);
  std::set<std::pair<std::uint32_t, std::uint32_t>> oracle = edge_set(initial);
  for (const GraSuEdge &edge : updates) {
    const auto key = std::pair(edge.source, edge.destination);
    if (edge.delete_op) {
      oracle.erase(key);
    } else {
      oracle.insert(key);
    }
  }

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-kernel", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 7,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  GraSuNativeConfig config;
  config.cache_segments_per_half = 1;
  config.axis_fifo_depth = 2;
  config.lane_fifo_depth = 2;
  GraSuPmaUpdateSystem system(scheduler, core, backend, std::move(layout),
                              updates, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      2'000'000);

  require(!system.failed(), "GraSU native update failed: " + system.failure());
  require(system.done(), "GraSU native update did not drain");
  require(edge_set(system.live_edges()) == oracle,
          "GraSU payload-backed PMA differs from independent edge oracle");
  const auto counters = system.counters();
  require(counters.updates == updates.size() && counters.inserts == 9 &&
              counters.deletes == 1,
          "GraSU operation counters mismatch");
  require(counters.cache_updates > 0 && counters.ddr_updates > 0,
          "GraSU test did not cover both cache and DDR routes");
  require(counters.row_reads == updates.size() && counters.binary_probes > 0,
          "GraSU direct search did not issue expected metadata traffic");
  require(counters.pma_reads == updates.size() &&
              counters.pma_writes == updates.size(),
          "GraSU PMA RMW ledger mismatch");
  require(counters.update_read_bytes == updates.size() * 8 &&
              counters.row_read_bytes == updates.size() * 8 &&
              counters.binary_read_bytes == counters.binary_probes * 8 &&
              counters.pma_read_bytes == updates.size() * 64 &&
              counters.pma_write_bytes == updates.size() * 64,
          "GraSU byte ledger mismatch");
  std::cout << "EVIDENCE grasu_native_update cycles=" << counters.end_cycle
            << " updates=" << counters.updates
            << " cache=" << counters.cache_updates
            << " ddr=" << counters.ddr_updates
            << " binary_probes=" << counters.binary_probes << " read_bytes="
            << (counters.update_read_bytes + counters.row_read_bytes +
                counters.binary_read_bytes + counters.pma_read_bytes)
            << " write_bytes=" << counters.pma_write_bytes
            << " hbm_stalls=" << backend.stats().submit_stalls << '\n';
}

void test_unreserved_and_invalid_updates_are_rejected() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1},
  };
  const GraSuPmaLayout layout = GraSuPmaLayout::build(8, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-kernel", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 3,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 32});
  bool unreserved_failed = false;
  try {
    GraSuPmaUpdateSystem system(scheduler, core, backend, layout,
                                {{.source = 0, .destination = 2}},
                                GraSuNativeConfig{});
  } catch (const std::invalid_argument &error) {
    unreserved_failed =
        std::string(error.what()).find("not reserved") != std::string::npos;
  }
  require(unreserved_failed, "GraSU accepted an unreserved PMA insertion");

  bool invalid_delete_failed = false;
  try {
    GraSuPmaUpdateSystem system(
        scheduler, core, backend, layout,
        {{.source = 0, .destination = 1, .delete_op = true},
         {.source = 0, .destination = 1, .delete_op = true}},
        GraSuNativeConfig{});
  } catch (const std::invalid_argument &error) {
    invalid_delete_failed =
        std::string(error.what()).find("not live") != std::string::npos;
  }
  require(invalid_delete_failed, "GraSU accepted a repeated deletion");
}

void test_native_shared_channel_contention_is_visible() {
  std::vector<GraSuEdge> updates;
  for (std::uint32_t source = 0; source < 128; ++source) {
    updates.push_back({.source = source, .destination = source + 128});
  }
  GraSuPmaLayout layout = GraSuPmaLayout::build(256, {}, updates);
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-kernel", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 3,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 1,
                                             .response_queue_depth = 256});
  GraSuNativeConfig config;
  config.axis_fifo_depth = 1;
  config.lane_fifo_depth = 1;
  GraSuPmaUpdateSystem system(scheduler, core, backend, std::move(layout),
                              updates, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      2'000'000);
  require(!system.failed() && system.done(),
          "GraSU contention workload did not complete");
  const auto counters = system.counters();
  require(counters.axi_backend_submit_stalls > 0 &&
              backend.stats().submit_stalls > 0,
          "GraSU shared-channel AXI contention was not observed");
  require(counters.axis_push_stalls > 0 || counters.lane_queue_stalls > 0,
          "GraSU finite queues did not propagate pressure");
  require(edge_set(system.live_edges()) == edge_set(updates),
          "GraSU contention workload corrupted PMA payload");
  std::cout << "EVIDENCE grasu_native_contention cycles=" << counters.end_cycle
            << " updates=" << counters.updates
            << " axi_backend_stalls=" << counters.axi_backend_submit_stalls
            << " axis_push_stalls=" << counters.axis_push_stalls
            << " lane_queue_stalls=" << counters.lane_queue_stalls << '\n';
}

void test_pma_native_regraph_sssp_matches_oracle() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1}, {.source = 0, .destination = 2},
      {.source = 1, .destination = 3}, {.source = 2, .destination = 3},
      {.source = 3, .destination = 4}, {.source = 5, .destination = 6},
  };
  const std::vector<GraSuEdge> reserved_updates = {
      {.source = 1, .destination = 4},
      {.source = 2, .destination = 5},
  };
  const std::vector<GraSuEdge> updates = {
      {.source = 1, .destination = 4},
      {.source = 2, .destination = 5},
      {.source = 3, .destination = 4, .delete_op = true},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(16, initial, reserved_updates);

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-regraph", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuNativeConfig update_config;
  update_config.cache_segments_per_half = 1;
  GraSuPmaUpdateSystem update_system(scheduler, core, backend, layout, updates,
                                     update_config);
  update_system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] { return update_system.done() || update_system.failed(); },
      2'000'000);
  require(update_system.done() && !update_system.failed(),
          "GraSU update prelude failed");

  GraSuReGraphConfig compute_config;
  compute_config.cache_segments_per_half = 1;
  compute_config.partition_vertices = 16;
  compute_config.axis_fifo_depth = 2;
  compute_config.reader_buffer_batches = 4;
  GraSuReGraphSsspSystem compute_system(scheduler, core, backend, layout, 0,
                                        compute_config);
  compute_system.register_components();
  scheduler.run_until(
      [&] { return compute_system.done() || compute_system.failed(); },
      2'000'000);

  require(!compute_system.failed(),
          "PMA-native ReGraph failed: " + compute_system.failure());
  require(compute_system.done(), "PMA-native ReGraph did not drain");
  const auto distances = compute_system.distances();
  const std::vector<std::uint32_t> expected = {
      0,
      1,
      1,
      2,
      2,
      2,
      3,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
      spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
  };
  require(distances == expected,
          "PMA-native ReGraph distances differ from independent oracle");
  const auto counters = compute_system.counters();
  require(counters.supersteps == 4,
          "PMA-native ReGraph superstep count mismatch");
  const std::uint64_t expected_source_requests = 2 * counters.supersteps;
  const std::uint64_t expected_source_lines =
      expected_source_requests * compute_config.source_buffer_vertices / 16;
  require(counters.row_reads == layout.vertices * counters.supersteps &&
              counters.source_state_reads == expected_source_requests &&
              counters.source_cache_requests == expected_source_requests &&
              counters.source_state_read_bytes ==
                  expected_source_requests *
                      compute_config.source_buffer_vertices * 4 &&
              counters.source_cache_lines == expected_source_lines &&
              counters.source_cache_lane_writes ==
                  expected_source_lines * compute_config.edge_lanes &&
              counters.source_cache_request_markers == counters.supersteps &&
              counters.source_cache_response_markers == counters.supersteps,
          "PMA-native ReGraph did not scan all source metadata");
  require(counters.pma_segment_reads ==
                  layout.segments.size() * counters.supersteps &&
              counters.pma_slots_scanned ==
                  layout.segments.size() * 16 * counters.supersteps,
          "PMA-native ReGraph PMA capacity scan ledger mismatch");
  require(counters.apply_state_reads == counters.supersteps &&
              counters.apply_state_writes == counters.supersteps &&
              counters.gather_rows_emitted == 8 * counters.supersteps &&
              counters.merger_rows_consumed == counters.gather_rows_emitted &&
              counters.merger_bursts_emitted == counters.supersteps &&
              counters.apply_input_bursts == counters.supersteps &&
              counters.hbm_wrapper_input_bursts == counters.supersteps &&
              counters.source_state_writes == 2 * counters.supersteps &&
              counters.source_state_write_bytes ==
                  2 * counters.apply_write_bytes,
          "PMA-native ReGraph partition apply ledger mismatch");
  require(counters.gather_bank_conflict_cycles == 0 &&
              counters.gather_bank_updates == counters.active_edges_mapped &&
              counters.gather_bypass_hits + counters.gather_bypass_misses ==
                  counters.gather_bank_updates &&
              counters.gather_bypass_hits > 0,
          "PMA-native ReGraph did not exercise lane-local RAW forwarding");
  std::cout << "EVIDENCE grasu_regraph_sssp cycles="
            << counters.end_cycle - counters.start_cycle
            << " supersteps=" << counters.supersteps
            << " pma_segments=" << counters.pma_segment_reads
            << " slots=" << counters.pma_slots_scanned
            << " live_edges=" << counters.live_edges_scanned
            << " active_edges=" << counters.active_edges_mapped
            << " read_bytes="
            << (counters.row_read_bytes + counters.source_state_read_bytes +
                counters.pma_read_bytes + counters.apply_read_bytes)
            << " write_bytes="
            << counters.apply_write_bytes + counters.source_state_write_bytes
            << " source_state_writes=" << counters.source_state_writes << '\n';
}

void test_regraph_gather_lane_forwarding_and_cross_bank_merge() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1}, {.source = 0, .destination = 2},
      {.source = 0, .destination = 3}, {.source = 1, .destination = 4},
      {.source = 2, .destination = 4}, {.source = 3, .destination = 0},
      {.source = 3, .destination = 4},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(8, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("regraph-gather-raw", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  scheduler.add_component(backend);
  require(initializer.done(), "gather RAW initializer did not drain");

  GraSuReGraphConfig config;
  config.partition_vertices = 16;
  config.source_buffer_vertices = 16;
  config.axis_fifo_depth = 2;
  config.reader_buffer_batches = 4;
  GraSuReGraphSsspSystem compute(scheduler, core, backend, layout, 0, config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      2'000'000);
  require(!compute.failed() && compute.done(),
          "lane-local gather RAW test did not complete");
  const auto counters = compute.counters();
  require(compute.distances()[4] == 2,
          "lane-local and cross-bank gather merge changed SSSP result");
  require(counters.gather_bank_conflict_cycles == 0 &&
              counters.gather_bypass_hits > 0 &&
              counters.gather_cross_bank_reductions > 0 &&
              counters.gather_bank_updates == counters.active_edges_mapped &&
              counters.gather_bypass_hits + counters.gather_bypass_misses ==
                  counters.gather_bank_updates,
          "gather did not expose both RAW forwarding and cross-bank reduction");
  require(counters.gather_pipeline_drain_cycles ==
              counters.supersteps * (config.gather_pipeline_latency - 1),
          "gather did not drain the report-derived nine-stage pipeline");
  std::cout << "EVIDENCE regraph_gather_raw cycles="
            << counters.end_cycle - counters.start_cycle
            << " updates=" << counters.gather_bank_updates
            << " bypass_hits=" << counters.gather_bypass_hits
            << " bypass_misses=" << counters.gather_bypass_misses
            << " cross_bank_reductions="
            << counters.gather_cross_bank_reductions
            << " pipeline_drain=" << counters.gather_pipeline_drain_cycles
            << '\n';
}

void test_regraph_source_cache_crosses_ping_pong_windows() {
  constexpr std::size_t kVertices = 4097;
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 4096},
      {.source = 4096, .destination = 1},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(kVertices, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("regraph-source-cache", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  scheduler.add_component(backend);
  require(initializer.done(), "source-cache initializer did not drain");

  GraSuReGraphConfig config;
  config.partition_vertices = 12288;
  config.axis_fifo_depth = 2;
  config.reader_buffer_batches = 4;
  GraSuReGraphSsspSystem compute(scheduler, core, backend, layout, 0, config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      2'000'000);
  require(!compute.failed() && compute.done(),
          "cross-window source-cache test did not complete");
  require(compute.distances()[1] == 2,
          "cross-window source cache changed the SSSP result");

  const auto counters = compute.counters();
  const std::uint64_t expected_requests = 3 * counters.supersteps;
  const std::uint64_t expected_lines =
      expected_requests * config.source_buffer_vertices / 16;
  require(counters.supersteps == 3 &&
              counters.source_cache_requests == expected_requests &&
              counters.source_state_reads == expected_requests &&
              counters.source_cache_lines == expected_lines &&
              counters.source_cache_lane_writes ==
                  expected_lines * config.edge_lanes &&
              counters.source_cache_request_markers == counters.supersteps &&
              counters.source_cache_response_markers == counters.supersteps &&
              counters.source_cache_wait_cycles > 0,
          "source-cache ping-pong request/response ledger mismatch");
  std::cout << "EVIDENCE regraph_source_cache_windows cycles="
            << counters.end_cycle - counters.start_cycle
            << " supersteps=" << counters.supersteps
            << " requests=" << counters.source_cache_requests
            << " lines=" << counters.source_cache_lines
            << " wait_cycles=" << counters.source_cache_wait_cycles << '\n';
}

void test_native_partition_scan_cost_is_explicit() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(16, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-regraph-native", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  scheduler.add_component(backend);
  require(initializer.done(), "empty GraSU initializer did not drain");

  GraSuReGraphConfig compute_config;
  compute_config.partition_vertices = 65536;
  GraSuReGraphSsspSystem compute_system(scheduler, core, backend, layout, 0,
                                        compute_config);
  compute_system.register_components();
  scheduler.run_until(
      [&] { return compute_system.done() || compute_system.failed(); },
      2'000'000);
  require(!compute_system.failed() && compute_system.done(),
          "native-partition PMA compute did not complete");
  const auto counters = compute_system.counters();
  require(counters.supersteps == 2,
          "native-partition test expected two SSSP supersteps");
  require(counters.gather_reset_cycles == 32768 &&
              counters.gather_merge_cycles == 2 * 32768,
          "native ReGraph gather did not preserve first-round-only reset and "
          "per-round merge sweeps");
  require(counters.apply_state_reads == 2 * 4096 &&
              counters.apply_state_writes == 2 * 4096 &&
              counters.gather_rows_emitted == 2 * 32768 &&
              counters.merger_rows_consumed == counters.gather_rows_emitted &&
              counters.merger_bursts_emitted == counters.apply_state_reads &&
              counters.apply_input_bursts == counters.apply_state_reads &&
              counters.hbm_wrapper_input_bursts == counters.apply_state_reads &&
              counters.source_state_writes == 2 * counters.apply_state_writes,
          "native ReGraph apply did not scan the full 65536-vertex partition");
  require(counters.end_cycle - counters.start_cycle <
                  counters.gather_reset_cycles + counters.gather_merge_cycles +
                      counters.apply_state_reads &&
              counters.gather_merger_fifo_max_occupancy > 0 &&
              counters.gather_merger_fifo_max_occupancy <=
                  compute_config.gather_merger_fifo_depth &&
              counters.merger_apply_fifo_max_occupancy > 0 &&
              counters.merger_apply_fifo_max_occupancy <=
                  compute_config.merger_apply_fifo_depth &&
              counters.apply_wrapper_fifo_max_occupancy > 0 &&
              counters.apply_wrapper_fifo_max_occupancy <=
                  compute_config.apply_wrapper_fifo_depth,
          "native ReGraph finite stream chain did not overlap or bound queues");
  require(counters.apply_max_reads_inflight > 1 &&
              counters.apply_max_pipeline_occupancy > 1 &&
              counters.apply_max_writes_inflight > 1,
          "native ReGraph apply did not execute as an outstanding pipeline");
  require(compute_system.distances()[1] == 1,
          "native-partition SSSP result is incorrect");
  std::cout << "EVIDENCE grasu_regraph_native_partition cycles="
            << counters.end_cycle - counters.start_cycle
            << " gather_sweep_cycles="
            << counters.gather_reset_cycles + counters.gather_merge_cycles
            << " apply_bursts=" << counters.apply_state_reads
            << " source_state_writes=" << counters.source_state_writes
            << " max_read_inflight=" << counters.apply_max_reads_inflight
            << " max_pipeline=" << counters.apply_max_pipeline_occupancy
            << " max_write_inflight=" << counters.apply_max_writes_inflight
            << " merger_fifo_max=" << counters.merger_apply_fifo_max_occupancy
            << " wrapper_pipeline_max="
            << counters.hbm_wrapper_max_pipeline_occupancy << '\n';
}

void test_normalized_four_lane_batches_are_executed() {
  std::vector<GraSuEdge> initial;
  for (std::uint32_t destination = 1; destination <= 8; ++destination) {
    initial.push_back({.source = 0, .destination = destination});
  }
  GraSuPmaLayout layout = GraSuPmaLayout::build(16, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-regraph-four-lane", 150.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  scheduler.add_component(backend);
  require(initializer.done(), "four-lane initializer did not drain");

  GraSuReGraphConfig config;
  config.partition_vertices = 16;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  config.axis_fifo_depth = 2;
  config.reader_buffer_batches = 4;
  GraSuReGraphSsspSystem compute(scheduler, core, backend, layout, 0, config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      2'000'000);
  require(!compute.failed() && compute.done(),
          "four-lane PMA compute did not complete");
  const auto counters = compute.counters();
  require(counters.supersteps == 2 && counters.pma_segment_reads == 2 &&
              counters.edge_batches_scanned == 8 &&
              counters.pma_slots_scanned == 32,
          "four-lane PMA batch accounting mismatch");
  const auto distances = compute.distances();
  require(std::all_of(distances.begin() + 1, distances.begin() + 9,
                      [](std::uint32_t value) { return value == 1; }),
          "four-lane PMA compute produced incorrect distances");
  std::cout << "EVIDENCE grasu_regraph_four_lane cycles="
            << counters.end_cycle - counters.start_cycle
            << " segments=" << counters.pma_segment_reads
            << " batches=" << counters.edge_batches_scanned << '\n';
}

void test_pma_native_compute_propagates_contention() {
  std::vector<GraSuEdge> initial;
  for (std::uint32_t destination = 1; destination <= 128; ++destination) {
    initial.push_back({.source = 0, .destination = destination});
  }
  GraSuPmaLayout layout = GraSuPmaLayout::build(256, initial, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-regraph-contention", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 9,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 1,
                                             .response_queue_depth = 128});
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  scheduler.add_component(backend);
  require(initializer.done(), "contention initializer did not drain");

  GraSuReGraphConfig config;
  config.partition_vertices = 256;
  config.axis_fifo_depth = 1;
  config.gather_merger_fifo_depth = 1;
  config.merger_apply_fifo_depth = 1;
  config.apply_wrapper_fifo_depth = 1;
  config.reader_buffer_batches = 2;
  config.max_outstanding_bursts = 16;
  config.apply_request_window = 1;
  config.apply_pipeline_capacity = 2;
  config.hbm_wrapper_pipeline_capacity = 1;
  GraSuReGraphSsspSystem compute(scheduler, core, backend, layout, 0, config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      2'000'000);
  require(!compute.failed() && compute.done(),
          "contention PMA compute did not complete");
  const auto counters = compute.counters();
  require(counters.axi_backend_submit_stalls > 0 &&
              backend.stats().submit_stalls > 0,
          "PMA compute did not expose shared-channel HBM contention");
  require(counters.axis_push_stalls > 0,
          "PMA compute did not propagate finite AXIS backpressure");
  require(counters.gather_output_stall_cycles > 0 &&
              counters.merger_output_stall_cycles > 0 &&
              counters.apply_output_stall_cycles > 0 &&
              counters.hbm_wrapper_pipeline_capacity_stalls > 0 &&
              counters.gather_merger_fifo_max_occupancy == 1 &&
              counters.merger_apply_fifo_max_occupancy == 1 &&
              counters.apply_wrapper_fifo_max_occupancy == 1,
          "ReGraph finite stream chain did not propagate downstream pressure");
  require(counters.live_edges_scanned == initial.size() * 2,
          "contention PMA compute scan ledger mismatch");
  const auto distances = compute.distances();
  require(std::all_of(distances.begin() + 1, distances.begin() + 129,
                      [](std::uint32_t value) { return value == 1; }),
          "contention PMA compute corrupted SSSP distances");
  std::cout << "EVIDENCE grasu_regraph_contention cycles="
            << counters.end_cycle - counters.start_cycle
            << " axi_backend_stalls=" << counters.axi_backend_submit_stalls
            << " axis_push_stalls=" << counters.axis_push_stalls
            << " gather_output_stalls=" << counters.gather_output_stall_cycles
            << " merger_output_stalls=" << counters.merger_output_stall_cycles
            << " apply_output_stalls=" << counters.apply_output_stall_cycles
            << " wrapper_pipeline_stalls="
            << counters.hbm_wrapper_pipeline_capacity_stalls
            << " wrapper_write_stalls="
            << counters.hbm_wrapper_write_window_stalls << '\n';
}

} // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"pma_layout_reservations",
       test_pma_layout_preserves_segment_reservations},
      {"native_update_routes", test_native_update_crosses_cache_ddr_and_parity},
      {"invalid_updates", test_unreserved_and_invalid_updates_are_rejected},
      {"native_contention", test_native_shared_channel_contention_is_visible},
      {"pma_native_regraph_sssp", test_pma_native_regraph_sssp_matches_oracle},
      {"regraph_gather_raw",
       test_regraph_gather_lane_forwarding_and_cross_bank_merge},
      {"regraph_source_cache_windows",
       test_regraph_source_cache_crosses_ping_pong_windows},
      {"native_partition_scan", test_native_partition_scan_cost_is_explicit},
      {"normalized_four_lane", test_normalized_four_lane_batches_are_executed},
      {"pma_compute_contention", test_pma_native_compute_propagates_contention},
  };
  std::size_t failures = 0;
  for (const auto &[name, test] : tests) {
    try {
      test();
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception &error) {
      ++failures;
      std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    }
  }
  if (failures != 0) {
    std::cerr << failures << " GraSU test(s) failed\n";
    return 1;
  }
  std::cout << tests.size() << " GraSU test(s) passed\n";
  return 0;
}
