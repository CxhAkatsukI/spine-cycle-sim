#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/grasu.hpp"
#include "spine_sim/grasu_native.hpp"
#include "spine_sim/grasu_regraph.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace {

using spine::sim::decode_grasu_pma_destination;
using spine::sim::decode_grasu_pma_weight;
using spine::sim::encode_grasu_pma_edge;
using spine::sim::GraSuEdge;
using spine::sim::GraSuNativeCompactorConfig;
using spine::sim::GraSuNativeCompactorSystem;
using spine::sim::GraSuNativeConfig;
using spine::sim::GraSuNativeReGraphSsspSystem;
using spine::sim::GraSuNativeReorderedGraph;
using spine::sim::GraSuPartitionedPmaLayout;
using spine::sim::GraSuPmaLayout;
using spine::sim::GraSuPmaUpdateSystem;
using spine::sim::GraSuPmaWordAbi;
using spine::sim::GraSuReGraphConfig;
using spine::sim::GraSuReGraphPageRankSystem;
using spine::sim::GraSuReGraphResidualPageRankSystem;
using spine::sim::GraSuReGraphSsspSystem;
using spine::sim::initialize_grasu_pma_layout_payloads;
using spine::sim::is_grasu_pma_empty;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::prepare_grasu_weighted_full_word_graph;
using spine::sim::reorder_grasu_native_graph;
using spine::sim::Scheduler;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::uint32_t read_u32(const std::vector<std::uint8_t> &bytes,
                       std::size_t offset) {
  require(offset + 4 <= bytes.size(), "test payload is too short for u32");
  std::uint32_t value = 0;
  for (std::size_t byte = 0; byte < 4; ++byte) {
    value |= static_cast<std::uint32_t>(bytes[offset + byte]) << (byte * 8);
  }
  return value;
}

void write_u32(std::vector<std::uint8_t> &bytes, std::size_t offset,
               std::uint32_t value) {
  require(offset + 4 <= bytes.size(), "test payload is too short for u32");
  for (std::size_t byte = 0; byte < 4; ++byte) {
    bytes[offset + byte] = static_cast<std::uint8_t>(value >> (byte * 8));
  }
}

void test_native_host_vertex_reorder_matches_current_artifact() {
  std::vector<GraSuEdge> chain64;
  for (std::uint32_t source = 0; source + 1 < 64; ++source) {
    chain64.push_back(
        {.source = source, .destination = source + 1, .weight = 1});
  }
  const GraSuNativeReorderedGraph reordered64 =
      reorder_grasu_native_graph(64, chain64, {});
  const std::map<std::uint32_t, std::uint32_t> expected64 = {
      {0, 33}, {1, 16}, {2, 34},  {15, 47}, {31, 62},
      {32, 1}, {33, 2}, {62, 31}, {63, 63},
  };
  for (const auto [external, internal] : expected64) {
    require(reordered64.external_to_internal.at(external) == internal,
            "native chain64 host vertex permutation drifted");
  }
  require(reordered64.initial_edges.front() ==
              GraSuEdge{.source = 33, .destination = 16, .weight = 1},
          "native host reorder did not remap both edge endpoints");

  std::vector<GraSuEdge> chain16;
  for (std::uint32_t source = 0; source + 1 < 16; ++source) {
    chain16.push_back(
        {.source = source, .destination = source + 1, .weight = 1});
  }
  const GraSuNativeReorderedGraph reordered16 =
      reorder_grasu_native_graph(16, chain16, {});
  require(reordered16.external_to_internal.at(0) == 0,
          "native chain16 host source mapping drifted");

  const std::vector<GraSuEdge> density_initial = {
      {.source = 0, .destination = 1},
      {.source = 1, .destination = 2},
      {.source = 2, .destination = 3},
  };
  const std::vector<GraSuEdge> density_updates = {
      {.source = 2, .destination = 0},
      {.source = 2, .destination = 3, .delete_op = true},
  };
  const GraSuNativeReorderedGraph density =
      reorder_grasu_native_graph(4, density_initial, density_updates);
  require(density.external_to_internal.at(2) == 0,
          "highest native updates-per-segment vertex was not ranked first");
  require(density.updates.at(0).source == 0 &&
              density.updates.at(0).destination ==
                  density.external_to_internal.at(0) &&
              !density.updates.at(0).delete_op,
          "native insertion metadata changed during host reorder");
  require(density.updates.at(1).delete_op,
          "native deletion marker changed during host reorder");

  bool rejected = false;
  try {
    (void)reorder_grasu_native_graph(4, {{.source = 4, .destination = 0}}, {});
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "native host reorder accepted an out-of-range endpoint");
}

std::set<std::pair<std::uint32_t, std::uint32_t>>
edge_set(const std::vector<GraSuEdge> &edges) {
  std::set<std::pair<std::uint32_t, std::uint32_t>> result;
  for (const GraSuEdge &edge : edges) {
    result.emplace(edge.source, edge.destination);
  }
  return result;
}

using WeightedEdgeMap =
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint16_t>;

WeightedEdgeMap weighted_edge_map(const std::vector<GraSuEdge> &edges) {
  WeightedEdgeMap result;
  for (const GraSuEdge &edge : edges) {
    result[{edge.source, edge.destination}] = edge.weight;
  }
  return result;
}

std::vector<std::uint32_t>
weighted_sssp_oracle(std::size_t vertices, const std::vector<GraSuEdge> &edges,
                     std::uint32_t source) {
  using Neighbor = std::pair<std::uint32_t, std::uint16_t>;
  std::vector<std::vector<Neighbor>> adjacency(vertices);
  for (const GraSuEdge &edge : edges) {
    adjacency.at(edge.source).push_back({edge.destination, edge.weight});
  }
  std::vector<std::uint32_t> distances(
      vertices, spine::sim::GraphAlgorithmPolicy::kSsspInfinity);
  using QueueItem = std::pair<std::uint32_t, std::uint32_t>;
  std::priority_queue<QueueItem, std::vector<QueueItem>,
                      std::greater<QueueItem>>
      queue;
  distances.at(source) = 0;
  queue.push({0, source});
  while (!queue.empty()) {
    const auto [distance, vertex] = queue.top();
    queue.pop();
    if (distance != distances[vertex]) {
      continue;
    }
    for (const auto [destination, weight] : adjacency[vertex]) {
      const std::uint32_t candidate =
          distance > spine::sim::GraphAlgorithmPolicy::kSsspInfinity - weight
              ? spine::sim::GraphAlgorithmPolicy::kSsspInfinity
              : distance + weight;
      if (candidate < distances[destination]) {
        distances[destination] = candidate;
        queue.push({candidate, destination});
      }
    }
  }
  return distances;
}

template <typename Real>
std::vector<Real> full_pagerank_oracle(std::size_t vertices,
                                       const std::vector<GraSuEdge> &edges,
                                       std::size_t iterations, Real damping) {
  std::vector<std::uint32_t> degree(vertices);
  for (const GraSuEdge &edge : edges) {
    ++degree.at(edge.source);
  }
  std::vector<Real> rank(vertices, Real{1} / static_cast<Real>(vertices));
  for (std::size_t iteration = 0; iteration < iterations; ++iteration) {
    Real dangling = Real{0};
    for (std::size_t vertex = 0; vertex < vertices; ++vertex) {
      if (degree[vertex] == 0) {
        dangling += rank[vertex];
      }
    }
    const Real initial = (Real{1} - damping) / static_cast<Real>(vertices) +
                         damping * dangling / static_cast<Real>(vertices);
    std::vector<Real> next(vertices, initial);
    for (const GraSuEdge &edge : edges) {
      next[edge.destination] +=
          damping * rank[edge.source] / static_cast<Real>(degree[edge.source]);
    }
    rank = std::move(next);
  }
  return rank;
}

template <typename Real> struct ResidualPageRankOracle {
  std::vector<Real> ranks;
  std::vector<Real> residuals;
  std::size_t iterations{};
  std::uint64_t active_edges{};
  bool converged{};
};

template <typename Real>
ResidualPageRankOracle<Real> residual_pagerank_oracle(
    std::size_t vertices, const std::vector<GraSuEdge> &edges,
    std::size_t max_iterations, Real damping, Real epsilon) {
  std::vector<std::vector<std::uint32_t>> adjacency(vertices);
  std::vector<std::uint32_t> degree(vertices);
  for (const GraSuEdge &edge : edges) {
    adjacency.at(edge.source).push_back(edge.destination);
    ++degree.at(edge.source);
  }
  ResidualPageRankOracle<Real> result;
  result.ranks.assign(vertices, Real{0});
  result.residuals.assign(vertices,
                          (Real{1} - damping) / static_cast<Real>(vertices));
  std::vector<std::uint32_t> active(vertices);
  std::iota(active.begin(), active.end(), 0U);
  const Real threshold = epsilon / static_cast<Real>(vertices);
  for (std::size_t iteration = 0; iteration < max_iterations; ++iteration) {
    std::vector<Real> deltas(vertices, Real{0});
    Real dangling = Real{0};
    for (const std::uint32_t source : active) {
      const Real delta = result.residuals[source];
      deltas[source] = delta;
      result.residuals[source] = Real{0};
      result.ranks[source] += delta;
      if (degree[source] == 0) {
        dangling += delta;
      } else {
        result.active_edges += adjacency[source].size();
      }
    }
    std::vector<Real> incoming(vertices, Real{0});
    for (std::size_t source = 0; source < vertices; ++source) {
      if (deltas[source] == Real{0} || degree[source] == 0) {
        continue;
      }
      const Real contribution =
          damping * deltas[source] / static_cast<Real>(degree[source]);
      for (const std::uint32_t destination : adjacency[source]) {
        incoming[destination] += contribution;
      }
    }
    const Real dangling_share =
        damping * dangling / static_cast<Real>(vertices);
    std::vector<std::uint32_t> next;
    for (std::size_t vertex = 0; vertex < vertices; ++vertex) {
      result.residuals[vertex] += incoming[vertex] + dangling_share;
      if (std::fabs(result.residuals[vertex]) > threshold) {
        next.push_back(static_cast<std::uint32_t>(vertex));
      }
    }
    ++result.iterations;
    if (next.empty()) {
      result.converged = true;
      break;
    }
    active = std::move(next);
  }
  return result;
}

void initialize_partitioned_pma_payloads(
    MockMemoryBackend &backend, const GraSuPartitionedPmaLayout &layout,
    const GraSuReGraphConfig &compute_config) {
  for (std::size_t partition = 0; partition < layout.partitions.size();
       ++partition) {
    const std::uint64_t offset =
        partition * compute_config.partition_address_stride;
    GraSuNativeConfig config;
    config.cache_segments_per_half = compute_config.cache_segments_per_half;
    config.update_base += offset;
    config.row_offset_base = compute_config.row_offset_base + offset;
    config.binary_base += offset;
    config.pma_base = compute_config.pma_base + offset;
    initialize_grasu_pma_layout_payloads(backend, layout.partitions[partition],
                                         config);
  }
}

void test_weighted_pma_edge_abi_matches_regraph() {
  const std::uint32_t encoded = encode_grasu_pma_edge(0x7ffffU, 0xfffU);
  require(!is_grasu_pma_empty(encoded) &&
              decode_grasu_pma_destination(encoded) == 0x7ffffU &&
              decode_grasu_pma_weight(encoded) == 0xfffU,
          "weighted PMA edge ABI did not preserve ReGraph fields");
  require((encoded & 0x8000'0000U) == 0,
          "weighted PMA edge collided with the dummy marker");
  bool rejected = false;
  try {
    (void)encode_grasu_pma_edge(0x80000U, 1);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "weighted PMA ABI accepted an oversized destination");

  rejected = false;
  try {
    (void)encode_grasu_pma_edge(1, 0x1000U);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "weighted PMA ABI accepted an oversized weight");

  rejected = false;
  try {
    (void)decode_grasu_pma_destination(spine::sim::kGraSuPmaEmpty);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "weighted PMA ABI decoded an empty slot");

  rejected = false;
  try {
    (void)GraSuPmaLayout::build(spine::sim::kGraSuPmaLocalVertexCapacity + 1,
                                {}, {});
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "weighted PMA accepted more than one local partition");

  const GraSuPmaLayout duplicate_layout =
      GraSuPmaLayout::build(8,
                            {{.source = 0, .destination = 1, .weight = 3},
                             {.source = 0, .destination = 1, .weight = 7}},
                            {});
  const auto duplicate_edges = duplicate_layout.live_edges();
  require(duplicate_edges.size() == 1 && duplicate_edges.front().weight == 7,
          "weighted PMA initial duplicate is not last-write-wins");
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

void test_partitioned_pma_layout_preserves_global_destinations() {
  constexpr std::size_t kVertices = 17;
  constexpr std::size_t kPartitionVertices = 8;
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 7, .weight = 2},
      {.source = 0, .destination = 8, .weight = 3},
      {.source = 16, .destination = 0, .weight = 4},
      {.source = 8, .destination = 16, .weight = 5},
  };
  const std::vector<GraSuEdge> reserved = {
      {.source = 1, .destination = 15, .weight = 6},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, initial, reserved);

  require(layout.partitions.size() == 3,
          "partitioned PMA did not preserve the partial final partition");
  require(layout.partitions[0].destination_base == 0 &&
              layout.partitions[0].destination_vertices == 8 &&
              layout.partitions[1].destination_base == 8 &&
              layout.partitions[1].destination_vertices == 8 &&
              layout.partitions[2].destination_base == 16 &&
              layout.partitions[2].destination_vertices == 1,
          "partitioned PMA destination windows mismatch");
  require(edge_set(layout.live_edges()) == edge_set(initial),
          "partitioned PMA did not restore global destinations");
  require(layout.partition_for({.source = 0, .destination = 8})
                      .local_destination(8) == 0 &&
              layout.partition_for({.source = 8, .destination = 16})
                      .local_destination(16) == 0,
          "partitioned PMA did not localize destination boundaries");
  const auto reserved_segment = layout.partitions[1].segment_for(
      {.source = 1, .destination = 15, .weight = 6});
  require(reserved_segment < layout.partitions[1].segments.size(),
          "partitioned PMA lost a reserved cross-partition insertion");

  bool rejected = false;
  try {
    (void)layout.partitions[0].segment_for(
        {.source = 0, .destination = 8, .weight = 3});
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "PMA partition accepted a destination from its neighbor");
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

void test_weighted_dynamic_pma_regraph_matches_dijkstra() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1, .weight = 8},
      {.source = 0, .destination = 2, .weight = 2},
      {.source = 1, .destination = 3, .weight = 1},
      {.source = 2, .destination = 3, .weight = 8},
      {.source = 3, .destination = 4, .weight = 1},
  };
  const std::vector<GraSuEdge> updates = {
      {.source = 0, .destination = 1, .weight = 3},
      {.source = 2, .destination = 3, .weight = 4},
      {.source = 0, .destination = 2, .weight = 10},
      {.source = 2, .destination = 4, .weight = 2},
      {.source = 1, .destination = 3, .weight = 1, .delete_op = true},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(8, initial, updates);

  WeightedEdgeMap expected = weighted_edge_map(initial);
  for (const GraSuEdge &edge : updates) {
    const auto key = std::pair(edge.source, edge.destination);
    if (edge.delete_op) {
      expected.erase(key);
    } else {
      expected[key] = edge.weight;
    }
  }

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-weighted-dynamic", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
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
          "weighted GraSU update did not complete: " + update_system.failure());
  const std::vector<GraSuEdge> final_edges = update_system.live_edges();
  require(weighted_edge_map(final_edges) == expected,
          "weighted PMA payload differs from the edge-state oracle");
  const auto update_counters = update_system.counters();
  require(update_counters.inserts == 1 && update_counters.deletes == 1 &&
              update_counters.weight_decreases == 2 &&
              update_counters.weight_increases == 1,
          "weighted GraSU update classification is incorrect");

  GraSuReGraphConfig compute_config;
  compute_config.cache_segments_per_half = 1;
  compute_config.partition_vertices = 16;
  compute_config.source_buffer_vertices = 16;
  compute_config.axis_fifo_depth = 2;
  compute_config.reader_buffer_batches = 4;
  GraSuReGraphSsspSystem compute(scheduler, core, backend, layout, 0,
                                 compute_config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      2'000'000);
  require(compute.done() && !compute.failed(),
          "weighted PMA-native ReGraph did not complete");
  const std::vector<std::uint32_t> oracle =
      weighted_sssp_oracle(layout.vertices, final_edges, 0);
  require(compute.distances() == oracle,
          "weighted PMA-native ReGraph differs from Dijkstra oracle");
  require(oracle[1] == 3 && oracle[2] == 10 && oracle[3] == 14 &&
              oracle[4] == 12,
          "weighted dynamic test oracle does not exercise intended paths");
  const auto compute_counters = compute.counters();
  std::cout << "EVIDENCE grasu_regraph_weighted_dynamic update_cycles="
            << update_counters.end_cycle - update_counters.start_cycle
            << " compute_cycles="
            << compute_counters.end_cycle - compute_counters.start_cycle
            << " inserts=" << update_counters.inserts
            << " deletes=" << update_counters.deletes
            << " decreases=" << update_counters.weight_decreases
            << " increases=" << update_counters.weight_increases
            << " supersteps=" << compute_counters.supersteps << '\n';
}

void test_weighted_full_word_hls_contract_matches_sw_emu_oracle() {
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1, .weight = 8},
      {.source = 0, .destination = 2, .weight = 2},
      {.source = 1, .destination = 3, .weight = 1},
      {.source = 2, .destination = 3, .weight = 8},
      {.source = 3, .destination = 4, .weight = 1},
  };
  const std::vector<GraSuEdge> logical_updates = {
      {.source = 0, .destination = 1, .weight = 3},
      {.source = 0, .destination = 2, .weight = 10},
      {.source = 1, .destination = 3, .weight = 1, .delete_op = true},
      {.source = 2, .destination = 3, .weight = 4},
      {.source = 2, .destination = 4, .weight = 2},
  };
  const auto prepared =
      prepare_grasu_weighted_full_word_graph(8, initial, logical_updates);
  require(
      prepared.logical_updates == 5 && prepared.physical_updates.size() == 8,
      "weighted HLS host did not lower five logical updates to eight PMA ops");
  require(prepared.external_to_internal ==
                  std::vector<std::uint32_t>({0, 2, 1, 3, 4, 5, 6, 7}) &&
              prepared.internal_to_external ==
                  std::vector<std::uint32_t>({0, 2, 1, 3, 4, 5, 6, 7}),
          "weighted HLS physical-update density reorder drifted");
  require(prepared.physical_updates[0].delete_op &&
              prepared.physical_updates[0].weight == 8 &&
              !prepared.physical_updates[1].delete_op &&
              prepared.physical_updates[1].weight == 3,
          "weighted HLS weight change was not delete-old then insert-new");

  GraSuPmaLayout layout = GraSuPmaLayout::build(
      8, prepared.initial_edges, prepared.physical_updates,
      GraSuPmaWordAbi::kWeightedFullWord);
  require(layout.pma_word_abi == GraSuPmaWordAbi::kWeightedFullWord,
          "weighted HLS layout lost its full-word ABI");
  const GraSuEdge old_variant = prepared.physical_updates[0];
  const GraSuEdge new_variant = prepared.physical_updates[1];
  require(layout.segment_for(old_variant) == layout.segment_for(new_variant),
          "weighted HLS PMA did not reserve both encoded weight variants");

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-weighted-hls", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 16,
                                             .response_queue_depth = 128});
  GraSuNativeConfig update_config;
  update_config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  update_config.cache_segments_per_half = 1;
  GraSuPmaUpdateSystem update_system(scheduler, core, backend, layout,
                                     prepared.physical_updates, update_config);
  update_system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] { return update_system.done() || update_system.failed(); },
      2'000'000);
  require(update_system.done() && !update_system.failed(),
          "weighted full-word GraSU update did not complete: " +
              update_system.failure());
  require(weighted_edge_map(update_system.live_edges()) ==
              weighted_edge_map(prepared.final_edges),
          "weighted full-word PMA differs from the independent edge oracle");
  const auto update_counters = update_system.counters();
  require(update_counters.updates == 8 && update_counters.inserts == 4 &&
              update_counters.deletes == 4 &&
              update_counters.weight_decreases == 0 &&
              update_counters.weight_increases == 0 &&
              update_counters.pma_reads == 8 && update_counters.pma_writes == 8,
          "weighted full-word physical update ledger mismatch");

  GraSuReGraphConfig compute_config;
  compute_config.cache_segments_per_half = 1;
  compute_config.partition_vertices = 16;
  compute_config.source_buffer_vertices = 16;
  compute_config.edge_lanes = 8;
  compute_config.gather_banks = 8;
  compute_config.axis_fifo_depth = 32;
  compute_config.reader_buffer_batches = 32;
  compute_config.max_pending_requests = 16;
  compute_config.max_outstanding_bursts = 16;
  compute_config.apply_request_window = 16;
  const std::uint32_t source_internal = prepared.external_to_internal.at(0);
  GraSuReGraphSsspSystem compute(
      scheduler, core, backend, layout,
      spine::sim::GraphAlgorithmPolicy(spine::sim::AlgorithmPolicyConfig{
          .kind = spine::sim::GraphAlgorithmKind::kWeightedSssp,
          .vertices = layout.vertices,
          .source = source_internal,
      }),
      {}, 4, compute_config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      3'000'000);
  require(compute.done() && !compute.failed(),
          "weighted full-word fixed-round ReGraph did not complete");
  const auto internal_oracle =
      weighted_sssp_oracle(8, prepared.final_edges, source_internal);
  require(compute.distances() == internal_oracle,
          "weighted full-word ReGraph differs from internal Dijkstra oracle");
  require(compute.counters().supersteps == 4,
          "weighted HLS profile did not execute exactly four host rounds");
  std::vector<std::uint32_t> external_distances(8);
  for (std::size_t internal = 0; internal < external_distances.size();
       ++internal) {
    const std::uint32_t distance = compute.distances()[internal];
    external_distances[prepared.internal_to_external[internal]] =
        distance == spine::sim::GraphAlgorithmPolicy::kSsspInfinity
            ? 2147483646U
            : distance;
  }
  require(external_distances ==
              std::vector<std::uint32_t>(
                  {0, 3, 10, 14, 12, 2147483646U, 2147483646U, 2147483646U}),
          "weighted HLS simulator differs from the sw_emu external oracle");

  bool unlowered_rejected = false;
  try {
    GraSuPmaLayout bad_layout = GraSuPmaLayout::build(
        8, initial, logical_updates, GraSuPmaWordAbi::kWeightedFullWord);
    GraSuPmaUpdateSystem bad_update(scheduler, core, backend, bad_layout,
                                    logical_updates, update_config);
  } catch (const std::invalid_argument &) {
    unlowered_rejected = true;
  }
  require(unlowered_rejected,
          "weighted full-word PMA silently accepted an in-place weight change");
  std::cout << "EVIDENCE grasu_weighted_hls_full_word logical_updates=5"
            << " physical_updates=" << update_counters.updates
            << " supersteps=" << compute.counters().supersteps
            << " mismatches=0\n";
}

void test_partitioned_regraph_sssp_crosses_destination_windows() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 16, .weight = 1},
      {.source = 16, .destination = 1, .weight = 1},
      {.source = 1, .destination = 32, .weight = 1},
      {.source = 32, .destination = 17, .weight = 1},
      {.source = 17, .destination = 0, .weight = 9},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, edges, {});

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("partitioned-regraph-sssp", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.partition_vertices = kPartitionVertices;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  initialize_partitioned_pma_payloads(backend, layout, config);
  GraSuReGraphSsspSystem system(scheduler, core, backend, layout, 0, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      5'000'000);

  require(!system.failed() && system.done(),
          "partitioned PMA-native ReGraph SSSP did not complete");
  require(system.distances() == weighted_sssp_oracle(kVertices, edges, 0),
          "partitioned PMA-native ReGraph SSSP differs from Dijkstra");
  const auto counters = system.counters();
  require(counters.destination_partitions == 3 && counters.supersteps == 5 &&
              counters.partition_passes == 15 &&
              counters.row_reads == kVertices * counters.partition_passes &&
              counters.live_edges_scanned ==
                  edges.size() * counters.supersteps &&
              counters.apply_state_reads == counters.partition_passes &&
              counters.source_state_writes == 2 * counters.partition_passes,
          "partitioned ReGraph SSSP work ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_partitioned_sssp cycles="
            << counters.end_cycle - counters.start_cycle
            << " partitions=" << counters.destination_partitions
            << " supersteps=" << counters.supersteps
            << " partition_passes=" << counters.partition_passes
            << " row_reads=" << counters.row_reads << '\n';
}

void test_partitioned_weighted_full_word_update_preserves_variants() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  std::vector<GraSuEdge> initial;
  for (std::uint32_t destination = 16; destination < 32; ++destination) {
    initial.push_back(
        {.source = 0, .destination = destination, .weight = 31});
  }
  const std::vector<GraSuEdge> physical_updates = {
      {.source = 0, .destination = 17, .weight = 31, .delete_op = true},
      {.source = 0, .destination = 17, .weight = 2},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, initial, physical_updates,
      GraSuPmaWordAbi::kWeightedFullWord);
  require(layout.partitions.at(1).pma_word_abi ==
              GraSuPmaWordAbi::kWeightedFullWord &&
              layout.partitions.at(1).segments.size() == 2,
          "partitioned weighted layout lost its full-word reservations");

  Scheduler scheduler;
  const auto core =
      scheduler.add_clock_mhz("partitioned-weighted-full-word", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 2,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 16,
                                             .response_queue_depth = 64});
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = 1;
  GraSuPmaUpdateSystem update(scheduler, core, backend, layout,
                              physical_updates, config);
  update.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return update.done() || update.failed(); },
                      500'000);
  require(update.done() && !update.failed(),
          "partitioned weighted full-word update failed: " +
              update.failure());
  const auto live = weighted_edge_map(update.live_edges());
  require(live.at({0, 17}) == 2 && live.size() == initial.size(),
          "partitioned full-word update produced the wrong edge state");
}

void test_partitioned_regraph_sssp_uses_two_compute_pipelines() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 16, .weight = 1},
      {.source = 16, .destination = 1, .weight = 1},
      {.source = 1, .destination = 32, .weight = 1},
      {.source = 32, .destination = 17, .weight = 1},
      {.source = 17, .destination = 0, .weight = 9},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, edges, {});

  Scheduler scheduler;
  const auto core =
      scheduler.add_clock_mhz("partitioned-regraph-sssp-k2", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.compute_pipelines = 2;
  config.partition_vertices = kPartitionVertices;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  initialize_partitioned_pma_payloads(backend, layout, config);
  GraSuReGraphSsspSystem system(scheduler, core, backend, layout, 0, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      5'000'000);

  require(!system.failed() && system.done(),
          "two-pipeline PMA-native ReGraph SSSP did not complete");
  require(system.distances() == weighted_sssp_oracle(kVertices, edges, 0),
          "two-pipeline PMA-native ReGraph SSSP differs from Dijkstra");
  const auto counters = system.counters();
  require(counters.compute_pipelines == 2 &&
              counters.max_parallel_partitions == 2 &&
              counters.destination_partitions == 3 &&
              counters.partition_passes ==
                  counters.destination_partitions * counters.supersteps &&
              counters.pipeline_busy_cycles >
                  counters.end_cycle - counters.start_cycle &&
              counters.row_reads == kVertices * counters.partition_passes &&
              counters.live_edges_scanned == edges.size() * counters.supersteps,
          "two-pipeline ReGraph SSSP work/parallelism ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_partitioned_sssp_k2 cycles="
            << counters.end_cycle - counters.start_cycle
            << " partitions=" << counters.destination_partitions
            << " pipelines=" << counters.compute_pipelines
            << " max_parallel=" << counters.max_parallel_partitions
            << " busy_cycles=" << counters.pipeline_busy_cycles << '\n';
}

void test_partitioned_update_times_degree_rmw_and_feeds_pagerank() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  constexpr std::size_t kIterations = 2;
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 16, .weight = 5},
      {.source = 0, .destination = 1, .weight = 2},
      {.source = 1, .destination = 32, .weight = 3},
      {.source = 2, .destination = 17, .weight = 4},
  };
  const std::vector<GraSuEdge> updates = {
      {.source = 0, .destination = 32, .weight = 1},
      {.source = 0, .destination = 16, .weight = 5, .delete_op = true},
      {.source = 0, .destination = 1, .weight = 1},
      {.source = 2, .destination = 0, .weight = 2},
      {.source = 1, .destination = 32, .weight = 3, .delete_op = true},
      {.source = 2, .destination = 17, .weight = 7},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, initial, updates);
  WeightedEdgeMap expected_edges = weighted_edge_map(initial);
  for (const GraSuEdge &edge : updates) {
    const auto key = std::pair(edge.source, edge.destination);
    if (edge.delete_op) {
      expected_edges.erase(key);
    } else {
      expected_edges[key] = edge.weight;
    }
  }

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("partitioned-grasu-update", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuNativeConfig update_config;
  update_config.cache_segments_per_half = 1;
  update_config.maintain_out_degree = true;
  update_config.degree_fifo_depth = 2;
  GraSuNativeConfig undersized_config = update_config;
  undersized_config.degree_reorder_entries = updates.size() - 1;
  bool undersized_rejected = false;
  try {
    GraSuPmaUpdateSystem undersized(scheduler, core, backend, layout, updates,
                                    undersized_config);
  } catch (const std::invalid_argument &) {
    undersized_rejected = true;
  }
  require(undersized_rejected,
          "undersized degree completion scoreboard was not rejected");
  GraSuPmaUpdateSystem update_system(scheduler, core, backend, layout, updates,
                                     update_config);
  update_system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] { return update_system.done() || update_system.failed(); },
      5'000'000);

  require(!update_system.failed() && update_system.done(),
          "partitioned GraSU update with degree RMW did not complete");
  const auto final_edges = update_system.live_edges();
  require(weighted_edge_map(final_edges) == expected_edges,
          "partitioned GraSU PMA differs from edge-state oracle");
  const auto update_counters = update_system.counters();
  require(update_counters.update_record_bytes == 16 &&
              update_counters.destination_partitions_touched == 3 &&
              update_counters.partition_routes == updates.size() &&
              update_counters.inserts == 2 && update_counters.deletes == 2 &&
              update_counters.weight_decreases == 1 &&
              update_counters.weight_increases == 1 &&
              update_counters.degree_reads == 4 &&
              update_counters.degree_writes == 4 &&
              update_counters.degree_read_bytes == 16 &&
              update_counters.degree_write_bytes == 16 &&
              update_counters.degree_fifo_max_occupancy > 0 &&
              update_counters.degree_fifo_max_occupancy <=
                  update_config.degree_fifo_depth &&
              update_counters.degree_reorder_max_occupancy > 1 &&
              update_counters.degree_reorder_max_occupancy <= updates.size(),
          "partitioned GraSU update or degree ledger mismatch");

  const auto degree_bytes = backend.inspect_payload(
      update_config.degree_channel, update_config.degree_base, kVertices * 4);
  std::vector<std::uint32_t> degrees(kVertices);
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    degrees[vertex] = read_u32(degree_bytes, vertex * 4);
  }
  require(degrees[0] == 2 && degrees[1] == 0 && degrees[2] == 2 &&
              std::accumulate(degrees.begin(), degrees.end(), 0U) ==
                  final_edges.size(),
          "timed GraSU degree HBM payload differs from final PMA state");

  GraSuReGraphConfig compute_config;
  compute_config.partition_vertices = kPartitionVertices;
  compute_config.source_buffer_vertices = 16;
  compute_config.edge_lanes = 4;
  compute_config.gather_banks = 4;
  compute_config.initialize_degree_payload = false;
  const std::vector<std::uint32_t> poisoned_host_degrees(kVertices, 99);
  GraSuReGraphPageRankSystem compute(scheduler, core, backend, layout,
                                     poisoned_host_degrees, kIterations, 0.85F,
                                     compute_config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      5'000'000);
  require(!compute.failed() && compute.done(),
          "PageRank did not consume the timed dynamic degree state");
  const std::vector<GraSuEdge> oracle_edges = [&] {
    std::vector<GraSuEdge> result;
    result.reserve(expected_edges.size());
    for (const auto &[key, weight] : expected_edges) {
      result.push_back(
          {.source = key.first, .destination = key.second, .weight = weight});
    }
    return result;
  }();
  const auto expected =
      full_pagerank_oracle<float>(kVertices, oracle_edges, kIterations, 0.85F);
  const auto actual = compute.ranks();
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    require(std::fabs(actual[vertex] - expected[vertex]) < 1.0e-6F,
            "PageRank after partitioned updates differs at vertex " +
                std::to_string(vertex));
  }
  const auto compute_counters = compute.counters();
  std::cout << "EVIDENCE grasu_partitioned_update_degree update_cycles="
            << update_counters.end_cycle - update_counters.start_cycle
            << " update_bytes=" << update_counters.update_read_bytes
            << " degree_rmw=" << update_counters.degree_reads
            << " degree_reorder_max="
            << update_counters.degree_reorder_max_occupancy
            << " pagerank_cycles="
            << compute_counters.end_cycle - compute_counters.start_cycle
            << '\n';
}

void test_pma_native_regraph_full_pagerank_matches_oracle() {
  constexpr std::size_t kVertices = 4;
  constexpr std::size_t kIterations = 3;
  constexpr float kDamping = 0.85F;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 1},
      {.source = 0, .destination = 2},
      {.source = 1, .destination = 2},
      {.source = 2, .destination = 0},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(kVertices, edges, {});
  std::vector<std::uint32_t> degrees(kVertices);
  for (const GraSuEdge &edge : edges) {
    ++degrees[edge.source];
  }

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-regraph-pagerank", 150.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.partition_vertices = 16;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  config.pagerank_source_map_latency = 3;
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  require(initializer.done(), "PageRank PMA initializer did not drain");
  GraSuReGraphPageRankSystem system(scheduler, core, backend, layout, degrees,
                                    kIterations, kDamping, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      2'000'000);

  require(!system.failed(),
          "PMA-native ReGraph PageRank failed: " + system.failure());
  require(system.done(), "PMA-native ReGraph PageRank did not drain");
  const auto expected =
      full_pagerank_oracle<float>(kVertices, edges, kIterations, kDamping);
  const auto mathematical = full_pagerank_oracle<double>(
      kVertices, edges, kIterations, static_cast<double>(kDamping));
  const auto actual = system.ranks();
  require(actual.size() == expected.size(),
          "PMA-native ReGraph PageRank rank count mismatch");
  for (std::size_t vertex = 0; vertex < actual.size(); ++vertex) {
    require(std::fabs(actual[vertex] - expected[vertex]) < 1.0e-6F,
            "PMA-native ReGraph PageRank differs from CPU oracle at vertex " +
                std::to_string(vertex) +
                ": actual=" + std::to_string(actual[vertex]) +
                " expected=" + std::to_string(expected[vertex]));
    require(
        std::fabs(static_cast<double>(actual[vertex]) - mathematical[vertex]) <
            1.0e-6,
        "PMA-native ReGraph PageRank differs from float64 oracle at vertex " +
            std::to_string(vertex));
  }
  float rank_sum = 0.0F;
  for (float value : actual) {
    rank_sum += value;
  }
  require(std::fabs(rank_sum - 1.0F) < 1.0e-5F,
          "PMA-native ReGraph PageRank lost dangling mass");

  const auto counters = system.counters();
  require(counters.supersteps == kIterations &&
              counters.row_reads == kVertices * kIterations &&
              counters.source_prepare_state_reads == 1 &&
              counters.source_prepare_degree_reads == 1 &&
              counters.source_prepare_writes == 2 &&
              counters.source_prepare_cycles > 128 &&
              counters.degree_reads == counters.apply_state_reads +
                                           counters.source_prepare_degree_reads &&
              counters.degree_read_bytes ==
                  counters.degree_reads * 16 *
                      sizeof(std::uint32_t) &&
              counters.source_map_cycles == 0 &&
              counters.active_edges_mapped == edges.size() * kIterations &&
              counters.apply_state_reads == kIterations &&
              counters.apply_state_writes == kIterations &&
              counters.source_state_writes ==
                  2 * kIterations + counters.source_prepare_writes,
          "PMA-native ReGraph PageRank work ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_full_pagerank cycles="
            << counters.end_cycle - counters.start_cycle
            << " iterations=" << counters.supersteps
            << " degree_reads=" << counters.degree_reads
            << " source_prepare_cycles=" << counters.source_prepare_cycles
            << " source_prepare_reads="
            << counters.source_prepare_state_reads
            << " source_prepare_writes=" << counters.source_prepare_writes
            << " source_map_cycles=" << counters.source_map_cycles
            << " active_edges=" << counters.active_edges_mapped
            << " rank_sum=" << rank_sum
            << " l1_error=" << counters.last_iteration_error << '\n';
}

void test_partitioned_regraph_pagerank_counts_dangling_once() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  constexpr std::size_t kIterations = 3;
  constexpr float kDamping = 0.85F;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 16},
      {.source = 16, .destination = 1},
      {.source = 1, .destination = 32},
      {.source = 32, .destination = 17},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, edges, {});
  std::vector<std::uint32_t> degrees(kVertices);
  for (const GraSuEdge &edge : edges) {
    ++degrees[edge.source];
  }

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("partitioned-regraph-pr", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.compute_pipelines = 2;
  config.partition_vertices = kPartitionVertices;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  initialize_partitioned_pma_payloads(backend, layout, config);
  GraSuReGraphPageRankSystem system(scheduler, core, backend, layout, degrees,
                                    kIterations, kDamping, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      5'000'000);

  require(!system.failed() && system.done(),
          "partitioned PMA-native ReGraph PageRank did not complete");
  const auto expected =
      full_pagerank_oracle<float>(kVertices, edges, kIterations, kDamping);
  const auto actual = system.ranks();
  float rank_sum = 0.0F;
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    require(std::fabs(actual[vertex] - expected[vertex]) < 1.0e-6F,
            "partitioned PageRank differs from float32 oracle at vertex " +
                std::to_string(vertex));
    rank_sum += actual[vertex];
  }
  require(std::fabs(rank_sum - 1.0F) < 1.0e-5F,
          "partitioned PageRank counted dangling mass more than once");
  const auto counters = system.counters();
  require(counters.compute_pipelines == 2 &&
              counters.max_parallel_partitions == 2 &&
              counters.destination_partitions == 3 &&
              counters.partition_passes == 3 * kIterations &&
              counters.row_reads == 3 * kVertices * kIterations &&
              counters.source_prepare_state_reads == 3 &&
              counters.source_prepare_degree_reads == 3 &&
              counters.source_prepare_writes == 6 &&
              counters.degree_reads == counters.partition_passes +
                                           counters.source_prepare_degree_reads &&
              counters.active_edges_mapped == edges.size() * kIterations,
          "partitioned PageRank work ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_partitioned_pagerank cycles="
            << counters.end_cycle - counters.start_cycle
            << " partitions=" << counters.destination_partitions
            << " degree_reads=" << counters.degree_reads
            << " source_prepare_cycles=" << counters.source_prepare_cycles
            << " rank_sum=" << rank_sum << '\n';
}

void test_partitioned_residual_pagerank_unions_active_frontiers() {
  constexpr std::size_t kVertices = 33;
  constexpr std::size_t kPartitionVertices = 16;
  constexpr std::size_t kMaxIterations = 256;
  constexpr float kDamping = 0.85F;
  constexpr float kEpsilon = 1.0e-4F;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 16}, {.source = 16, .destination = 1},
      {.source = 1, .destination = 32}, {.source = 32, .destination = 17},
      {.source = 17, .destination = 0},
  };
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, kPartitionVertices, edges, {});
  std::vector<std::uint32_t> degrees(kVertices);
  for (const GraSuEdge &edge : edges) {
    ++degrees[edge.source];
  }
  const auto expected = residual_pagerank_oracle<float>(
      kVertices, edges, kMaxIterations, kDamping, kEpsilon);
  require(expected.converged,
          "partitioned residual PageRank oracle did not converge");

  Scheduler scheduler;
  const auto core =
      scheduler.add_clock_mhz("partitioned-regraph-residual-pr", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.compute_pipelines = 2;
  config.partition_vertices = kPartitionVertices;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  initialize_partitioned_pma_payloads(backend, layout, config);
  GraSuReGraphResidualPageRankSystem system(scheduler, core, backend, layout,
                                            degrees, kMaxIterations, kDamping,
                                            kEpsilon, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      20'000'000);

  require(!system.failed() && system.done(),
          "partitioned residual PageRank did not complete");
  const auto ranks = system.ranks();
  const auto residuals = system.residuals();
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    require(std::fabs(ranks[vertex] - expected.ranks[vertex]) < 1.0e-6F &&
                std::fabs(residuals[vertex] - expected.residuals[vertex]) <
                    1.0e-6F,
            "partitioned residual PageRank differs from oracle at vertex " +
                std::to_string(vertex));
  }
  const auto counters = system.counters();
  const auto execution_frontier = system.frontier_out_sizes();
  require(counters.compute_pipelines == 2 &&
              counters.max_parallel_partitions == 2 &&
              counters.supersteps == expected.iterations &&
              counters.partition_passes ==
                  layout.partitions.size() * expected.iterations &&
              counters.active_edges_mapped == expected.active_edges &&
              execution_frontier.size() == counters.supersteps &&
              !execution_frontier.empty() && execution_frontier.back() == 0,
          "partitioned residual PageRank frontier ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_partitioned_residual cycles="
            << counters.end_cycle - counters.start_cycle
            << " iterations=" << counters.supersteps
            << " partition_passes=" << counters.partition_passes
            << " active_edges=" << counters.active_edges_mapped << '\n';
}

void test_pma_native_regraph_residual_pagerank_matches_oracles() {
  constexpr std::size_t kVertices = 4;
  constexpr std::size_t kMaxIterations = 256;
  constexpr float kDamping = 0.85F;
  constexpr float kEpsilon = 1.0e-6F;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 1},
      {.source = 0, .destination = 2},
      {.source = 1, .destination = 2},
      {.source = 2, .destination = 0},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(kVertices, edges, {});
  std::vector<std::uint32_t> degrees(kVertices);
  for (const GraSuEdge &edge : edges) {
    ++degrees[edge.source];
  }
  const auto architecture = residual_pagerank_oracle<float>(
      kVertices, edges, kMaxIterations, kDamping, kEpsilon);
  require(architecture.converged,
          "residual PageRank architecture oracle did not converge");

  Scheduler scheduler;
  const auto core =
      scheduler.add_clock_mhz("grasu-regraph-residual-pagerank", 150.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 7,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.partition_vertices = 16;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  config.pagerank_source_map_latency = 3;
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  require(initializer.done(),
          "residual PageRank PMA initializer did not drain");
  GraSuReGraphResidualPageRankSystem system(scheduler, core, backend, layout,
                                            degrees, kMaxIterations, kDamping,
                                            kEpsilon, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      10'000'000);

  require(!system.failed(),
          "PMA-native ReGraph residual PageRank failed: " + system.failure());
  require(system.done(), "PMA-native ReGraph residual PageRank did not drain");
  const auto ranks = system.ranks();
  const auto residuals = system.residuals();
  require(ranks.size() == architecture.ranks.size() &&
              residuals.size() == architecture.residuals.size(),
          "residual PageRank state size mismatch");
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    require(std::fabs(ranks[vertex] - architecture.ranks[vertex]) < 1.0e-6F &&
                std::fabs(residuals[vertex] - architecture.residuals[vertex]) <
                    1.0e-6F,
            "PMA-native ReGraph residual PageRank differs from float32 oracle");
  }
  const auto mathematical = full_pagerank_oracle<double>(
      kVertices, edges, 200, static_cast<double>(kDamping));
  double max_mathematical_error = 0.0;
  for (std::size_t vertex = 0; vertex < kVertices; ++vertex) {
    max_mathematical_error = std::max(
        max_mathematical_error,
        std::fabs(static_cast<double>(ranks[vertex]) - mathematical[vertex]));
  }
  require(max_mathematical_error < 5.0e-6,
          "residual PageRank did not approach the float64 fixed point");

  const auto counters = system.counters();
  const auto execution_frontier = system.frontier_out_sizes();
  require(counters.state_bytes_per_vertex == 8 &&
              counters.supersteps == architecture.iterations &&
              counters.source_prepare_state_reads == 1 &&
              counters.source_prepare_degree_reads == 1 &&
              counters.source_prepare_writes == 2 &&
              counters.source_prepare_cycles > 128 &&
              counters.degree_reads == counters.apply_state_reads +
                                           counters.source_prepare_degree_reads &&
              counters.source_map_cycles == 0 &&
              counters.active_edges_mapped == architecture.active_edges &&
              execution_frontier.size() == counters.supersteps &&
              !execution_frontier.empty() && execution_frontier.back() == 0 &&
              counters.apply_read_bytes == counters.apply_state_reads * 128 &&
              counters.apply_write_bytes == counters.apply_state_writes * 128 &&
              counters.source_state_write_bytes ==
                  counters.source_state_writes * 64,
          "PMA-native ReGraph residual PageRank packed-state ledger mismatch");
  std::cout << "EVIDENCE grasu_regraph_residual_pagerank cycles="
            << counters.end_cycle - counters.start_cycle
            << " iterations=" << counters.supersteps
            << " active_edges=" << counters.active_edges_mapped
            << " source_prepare_cycles=" << counters.source_prepare_cycles
            << " state_bytes=" << counters.state_bytes_per_vertex
            << " max_math_error=" << max_mathematical_error << '\n';
}

void test_grasu_delta_hls_residual_uses_warm_seed_frontier() {
  constexpr std::size_t kVertices = 4;
  constexpr float kDamping = 0.5F;
  constexpr float kEpsilon = 0.04F;
  const std::vector<GraSuEdge> edges = {
      {.source = 0, .destination = 1},
      {.source = 1, .destination = 2},
      {.source = 2, .destination = 3},
      {.source = 3, .destination = 0},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(kVertices, edges, {});
  std::vector<std::uint32_t> degrees(kVertices, 1);
  const spine::sim::AlgorithmInitialState warm{
      .primary = {
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.1F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.2F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.3F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.4F),
      },
      .auxiliary = {
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.0F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.06F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.0F),
          spine::sim::GraphAlgorithmPolicy::float_to_word(0.0F),
      },
      .active_vertices = {1},
  };

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("delta-hls-warm-grasu", 200.0);
  MockMemoryBackend backend("delta-hls-warm-grasu-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 4,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  config.partition_vertices = 16;
  config.source_buffer_vertices = 16;
  config.edge_lanes = 4;
  config.gather_banks = 4;
  GraSuPmaUpdateSystem initializer(scheduler, core, backend, layout, {},
                                   GraSuNativeConfig{});
  initializer.register_components();
  require(initializer.done(), "Delta.hls warm PMA initializer did not drain");
  GraSuReGraphResidualPageRankSystem system(
      scheduler, core, backend, layout, degrees, 8, kDamping, kEpsilon, config,
      spine::sim::ResidualPageRankContract::kDeltaHlsSinkFreeLinfWarm, warm);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() || system.failed(); },
                      1'000'000);

  const auto ranks = system.ranks();
  const auto residuals = system.residuals();
  const auto counters = system.counters();
  require(!system.failed() && system.done() && counters.supersteps == 1 &&
              counters.active_edges_mapped == 1 &&
              system.frontier_out_sizes() == std::vector<std::size_t>{0} &&
              std::fabs(ranks[1] - 0.26F) < 1.0e-6F &&
              std::fabs(residuals[2] - 0.03F) < 1.0e-6F,
          "GraSU+ReGraph Delta.hls warm residual seed was not isolated or drained");
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

  bool unchanged_weight_failed = false;
  try {
    GraSuPmaLayout layout = GraSuPmaLayout::build(
        8, {{.source = 0, .destination = 1, .weight = 7}}, {});
    GraSuPmaUpdateSystem system(scheduler, core, backend, std::move(layout),
                                {{.source = 0, .destination = 1, .weight = 7}},
                                GraSuNativeConfig{});
    (void)system;
  } catch (const std::invalid_argument &error) {
    unchanged_weight_failed =
        std::string(error.what()).find("does not change") != std::string::npos;
  }
  require(unchanged_weight_failed,
          "GraSU accepted a same-weight update as useful work");

  bool wrong_weight_delete_failed = false;
  try {
    GraSuPmaLayout layout = GraSuPmaLayout::build(
        8, {{.source = 0, .destination = 1, .weight = 7}}, {});
    GraSuPmaUpdateSystem system(
        scheduler, core, backend, std::move(layout),
        {{.source = 0, .destination = 1, .weight = 6, .delete_op = true}},
        GraSuNativeConfig{});
    (void)system;
  } catch (const std::invalid_argument &error) {
    wrong_weight_delete_failed =
        std::string(error.what()).find("not live") != std::string::npos;
  }
  require(wrong_weight_delete_failed,
          "GraSU accepted a delete with the wrong edge weight");
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

void test_native_raw_pma_compactor_matches_hls_edge_array() {
  constexpr std::size_t kVertices = 64;
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1},
      {.source = 0, .destination = 2},
      {.source = 1, .destination = 3},
      {.source = 3, .destination = 4},
  };
  const std::vector<GraSuEdge> updates = {
      {.source = 0, .destination = 2, .delete_op = true},
      {.source = 1, .destination = 5},
  };
  GraSuPmaLayout layout = GraSuPmaLayout::build(kVertices, initial, updates);

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("grasu-native-conversion", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 5,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 8,
                                             .response_queue_depth = 128});
  GraSuNativeConfig update_config;
  update_config.pma_word_abi = GraSuPmaWordAbi::kNativeRawDestination;
  GraSuPmaUpdateSystem update(scheduler, core, backend, layout, updates,
                              update_config);
  update.register_components();
  bool early_update_unregister_rejected = false;
  try {
    update.unregister_components();
  } catch (const std::logic_error &) {
    early_update_unregister_rejected = true;
  }
  require(early_update_unregister_rejected,
          "running native update was allowed to unregister");
  scheduler.add_component(backend);
  scheduler.run_until([&] { return update.done() || update.failed(); },
                      1'000'000);
  require(!update.failed() && update.done(),
          "native raw-PMA update did not complete");
  const std::vector<GraSuEdge> final_edges = update.live_edges();
  require(edge_set(final_edges) ==
              std::set<std::pair<std::uint32_t, std::uint32_t>>{
                  {0, 1}, {1, 3}, {1, 5}, {3, 4}},
          "native raw-PMA update differs from edge-state oracle");
  for (std::size_t segment = 0; segment < layout.segments.size(); ++segment) {
    for (std::uint32_t word : update.inspect_segment(segment)) {
      if (!is_grasu_pma_empty(word)) {
        require(word < kVertices,
                "native PMA payload retained normalized weight bits");
      }
    }
  }
  const auto update_end_cycle = update.counters().end_cycle;
  const auto update_components = scheduler.component_count();
  update.unregister_components();
  require(scheduler.component_count() < update_components && update.done() &&
              update.counters().end_cycle == update_end_cycle,
          "completed native update did not unregister with frozen timing");

  GraSuNativeCompactorConfig compact_config;
  GraSuNativeCompactorSystem compactor(scheduler, core, backend, layout, 32,
                                       compact_config);
  compactor.register_components();
  bool early_compactor_unregister_rejected = false;
  try {
    compactor.unregister_components();
  } catch (const std::logic_error &) {
    early_compactor_unregister_rejected = true;
  }
  require(early_compactor_unregister_rejected,
          "running native compactor was allowed to unregister");
  scheduler.run_until([&] { return compactor.done() || compactor.failed(); },
                      1'000'000);
  require(!compactor.failed() && compactor.done(),
          "native raw-PMA compactor did not drain: " + compactor.failure());
  const std::vector<GraSuEdge> compacted_edges =
      compactor.compacted_live_edges();
  require(edge_set(compacted_edges) == edge_set(final_edges),
          "native compactor edge array differs from PMA state");
  require(std::all_of(compacted_edges.begin(), compacted_edges.end(),
                      [](const GraSuEdge &edge) { return edge.weight == 1; }),
          "native compactor did not inject ReGraph unit weights");
  const auto payload = compactor.edge_array_payload();
  require(payload.size() == 32 * 8,
          "native compactor edge-array payload size mismatch");
  for (std::size_t slot = final_edges.size(); slot < 32; ++slot) {
    require(
        (read_u32(payload, slot * 8) & spine::sim::kGraSuPmaEmpty) != 0 &&
            (read_u32(payload, slot * 8 + 4) & spine::sim::kGraSuPmaEmpty) != 0,
        "native compactor padding did not use HLS dummy markers");
  }
  const auto counters = compactor.counters();
  require(
      counters.completion_token_reads == 4 && counters.barrier_cycles == 4 &&
          counters.row_reads == kVertices + 1 &&
          counters.pma_segment_reads == layout.segments.size() &&
          counters.pma_slots_scanned ==
              layout.segments.size() * spine::sim::kGraSuSegmentSlots &&
          counters.lane_pipeline_cycles ==
              layout.segments.size() * compact_config.lane_pipeline_latency &&
          counters.valid_edges_seen == final_edges.size() &&
          counters.emitted_edge_slots == 32 &&
          counters.dummy_edge_slots == 32 - final_edges.size() &&
          counters.edge_array_writes == 4 &&
          counters.row_read_bytes == (kVertices + 1) * 8 &&
          counters.pma_read_bytes == layout.segments.size() * 64 &&
          counters.edge_array_write_bytes == 4 * 64,
      "native compactor component ledger mismatch");
  std::cout << "EVIDENCE grasu_native_compactor cycles="
            << counters.end_cycle - counters.start_cycle
            << " barrier_cycles=" << counters.barrier_cycles
            << " rows=" << counters.row_reads
            << " segments=" << counters.pma_segment_reads
            << " valid_edges=" << counters.valid_edges_seen
            << " output_slots=" << counters.emitted_edge_slots << '\n';
  const auto compactor_components = scheduler.component_count();
  compactor.unregister_components();
  require(scheduler.component_count() < compactor_components &&
              compactor.done() &&
              compactor.counters().end_cycle == counters.end_cycle,
          "completed native compactor did not unregister with frozen timing");

  constexpr std::size_t kSupersteps = 4;
  GraSuReGraphConfig compute_config;
  GraSuNativeReGraphSsspSystem compute(scheduler, core, backend, kVertices, 32,
                                       0, kSupersteps, compute_config);
  compute.register_components();
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      1'000'000);
  require(!compute.failed() && compute.done(),
          "native edge-array ReGraph did not drain: " + compute.failure());
  require(compute.distances() ==
              weighted_sssp_oracle(kVertices, final_edges, 0),
          "native edge-array ReGraph differs from unit-weight SSSP oracle");
  const auto compute_counters = compute.counters();
  require(compute_counters.pipeline.supersteps == kSupersteps &&
              compute_counters.pipeline.partition_passes == kSupersteps &&
              compute_counters.pipeline.row_reads == 0 &&
              compute_counters.pipeline.pma_segment_reads == 0 &&
              compute_counters.pipeline.pma_slots_scanned == 0 &&
              compute_counters.pipeline.pma_read_bytes == 0 &&
              compute_counters.edge_array_requests == kSupersteps &&
              compute_counters.edge_array_bursts == 4 * kSupersteps &&
              compute_counters.edge_array_slots_scanned == 32 * kSupersteps &&
              compute_counters.edge_array_read_bytes == 32 * 8 * kSupersteps &&
              compute_counters.pipeline.live_edges_scanned ==
                  final_edges.size() * kSupersteps &&
              compute_counters.cross_source_round_bursts == 0,
          "native edge-array ReGraph component ledger mismatch");
  std::cout << "EVIDENCE grasu_native_regraph cycles="
            << compute_counters.pipeline.end_cycle -
                   compute_counters.pipeline.start_cycle
            << " supersteps=" << compute_counters.pipeline.supersteps
            << " edge_array_bursts=" << compute_counters.edge_array_bursts
            << " edge_array_bytes=" << compute_counters.edge_array_read_bytes
            << " live_edges=" << compute_counters.pipeline.live_edges_scanned
            << '\n';
}

void test_native_compactor_rejects_normalized_pma_payload() {
  const std::vector<GraSuEdge> edges = {{.source = 0, .destination = 1}};
  GraSuPmaLayout layout = GraSuPmaLayout::build(16, edges, {});
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("native-abi-guard", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 2,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 8,
                                             .response_queue_depth = 64});
  initialize_grasu_pma_layout_payloads(backend, layout, GraSuNativeConfig{});
  GraSuNativeCompactorSystem compactor(scheduler, core, backend, layout, 32);
  compactor.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return compactor.done() || compactor.failed(); },
                      100'000);
  require(compactor.failed() && !compactor.done(),
          "native compactor silently accepted normalized weighted PMA words");
}

void test_native_edge_array_flags_cross_source_window_hls_contract() {
  constexpr std::size_t kVertices = 4097;
  constexpr std::uint32_t kSource = 4096;
  constexpr std::uint32_t kUnitWeight = 1U << spine::sim::kGraSuPmaWeightShift;
  Scheduler scheduler;
  const auto core =
      scheduler.add_clock_mhz("native-cross-source-window", 200.0);
  MockMemoryBackend backend("shared-hbm", core,
                            MockMemoryConfig{.channels = 32,
                                             .latency_cycles = 2,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 8,
                                             .response_queue_depth = 128});
  GraSuReGraphConfig config;
  GraSuNativeReGraphSsspSystem compute(scheduler, core, backend, kVertices, 8,
                                       kSource, 1, config);

  std::vector<std::uint8_t> edge_array(64);
  write_u32(edge_array, 0, 4095);
  write_u32(edge_array, 4, 2 | kUnitWeight);
  write_u32(edge_array, 8, kSource);
  write_u32(edge_array, 12, 1 | kUnitWeight);
  for (std::size_t lane = 2; lane < 8; ++lane) {
    write_u32(edge_array, lane * 8, spine::sim::kGraSuPmaEmpty);
    write_u32(edge_array, lane * 8 + 4,
              spine::sim::kGraSuPmaEmpty | kUnitWeight);
  }
  backend.initialize_payload(config.edge_array_channel, config.edge_array_base,
                             edge_array);
  compute.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return compute.done() || compute.failed(); },
                      500'000);
  require(!compute.failed() && compute.done(),
          "native cross-window ReGraph case did not drain");
  const auto counters = compute.counters();
  require(counters.cross_source_round_bursts == 1,
          "native model did not expose the HLS lane-0 source-window contract");
  const auto distances = compute.distances();
  require(distances.at(1) == spine::sim::GraphAlgorithmPolicy::kSsspInfinity,
          "native model silently fixed the current HLS cross-window behavior");
  require(distances !=
              weighted_sssp_oracle(kVertices,
                                   {{.source = 4095, .destination = 2},
                                    {.source = kSource, .destination = 1}},
                                   kSource),
          "cross-window guard no longer exposes the native HLS mismatch");
  std::cout << "EVIDENCE grasu_native_cross_source_window bursts="
            << counters.edge_array_bursts
            << " unsafe_bursts=" << counters.cross_source_round_bursts
            << " oracle_match=false\n";
}

} // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"native_host_vertex_reorder",
       test_native_host_vertex_reorder_matches_current_artifact},
      {"weighted_pma_abi", test_weighted_pma_edge_abi_matches_regraph},
      {"pma_layout_reservations",
       test_pma_layout_preserves_segment_reservations},
      {"partitioned_pma_layout",
       test_partitioned_pma_layout_preserves_global_destinations},
      {"native_update_routes", test_native_update_crosses_cache_ddr_and_parity},
      {"weighted_dynamic_sssp",
       test_weighted_dynamic_pma_regraph_matches_dijkstra},
      {"weighted_full_word_hls",
       test_weighted_full_word_hls_contract_matches_sw_emu_oracle},
      {"partitioned_weighted_full_word",
       test_partitioned_weighted_full_word_update_preserves_variants},
      {"partitioned_sssp",
       test_partitioned_regraph_sssp_crosses_destination_windows},
      {"partitioned_sssp_k2",
       test_partitioned_regraph_sssp_uses_two_compute_pipelines},
      {"partitioned_update_degree",
       test_partitioned_update_times_degree_rmw_and_feeds_pagerank},
      {"full_pagerank", test_pma_native_regraph_full_pagerank_matches_oracle},
      {"partitioned_pagerank",
       test_partitioned_regraph_pagerank_counts_dangling_once},
      {"partitioned_residual_pagerank",
       test_partitioned_residual_pagerank_unions_active_frontiers},
      {"residual_pagerank",
       test_pma_native_regraph_residual_pagerank_matches_oracles},
      {"delta_hls_warm_residual",
       test_grasu_delta_hls_residual_uses_warm_seed_frontier},
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
      {"native_raw_pma_compactor",
       test_native_raw_pma_compactor_matches_hls_edge_array},
      {"native_compactor_abi_guard",
       test_native_compactor_rejects_normalized_pma_payload},
      {"native_cross_source_window_guard",
       test_native_edge_array_flags_cross_source_window_hls_contract},
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
