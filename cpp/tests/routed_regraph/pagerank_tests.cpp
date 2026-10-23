#include "spine_sim/routed_regraph.hpp"

#include <cmath>
#include <iostream>

namespace {
using namespace spine::sim;
void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

// Independent double-precision fixed-point oracle, including dangling mass.
std::vector<double> ranks(std::size_t vertices, const std::vector<GraSuEdge> &edges) {
  std::vector<std::size_t> degree(vertices);
  for (const auto &edge : edges) ++degree[edge.source];
  std::vector<double> rank(vertices, 1.0 / vertices), next(vertices);
  for (std::size_t iteration = 0; iteration < 1000; ++iteration) {
    double dangling = 0;
    for (std::size_t v = 0; v < vertices; ++v) if (!degree[v]) dangling += rank[v];
    std::fill(next.begin(), next.end(), (1.0 - double(0.85F) + double(0.85F) * dangling) / vertices);
    for (const auto &edge : edges)
      next[edge.destination] += double(0.85F) * rank[edge.source] / degree[edge.source];
    double error = 0;
    for (std::size_t v = 0; v < vertices; ++v) error = std::max(error, std::fabs(next[v] - rank[v]));
    rank.swap(next);
    if (error < 1e-14) return rank;
  }
  throw std::runtime_error("independent PageRank oracle did not converge");
}

struct Result {
  RoutedReGraphCounters counters;
  std::vector<RoutedReGraphRound> rounds;
  std::vector<std::uint32_t> rank, residual;
  bool operator==(const Result &) const = default;
};

Result run(bool reverse, bool optimized, bool pressure, bool multipart) {
  const std::size_t vertices = multipart ? 65540 : 65;
  std::vector<GraSuEdge> old{{0, 1, 1, false}, {1, 2, 1, false}, {2, 0, 1, false},
                            {4, 5, 1, false}, {5, 4, 1, false}};
  if (multipart) old.push_back({65536, 65537, 1, false});
  auto graph = old;
  graph.insert(graph.end(), {{0, 3, 1, false}, {3, 4, 1, false}});
  if (multipart) graph.push_back({5, 65536, 1, false});
  AlgorithmInitialState initial;
  for (double value : ranks(vertices, old)) initial.primary.push_back(GraphAlgorithmPolicy::float_to_word(value));
  initial.auxiliary.resize(vertices);
  RoutedReGraphConfig config;
  config.algorithm = {.kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = vertices, .epsilon = float(1e-5 / vertices),
      .residual_contract = ResidualPageRankContract::kHardwareWarmDanglingLinf};
  config.old_out_degrees.resize(vertices);
  config.degree_deltas.resize(vertices);
  for (const auto &edge : old) ++config.old_out_degrees[edge.source];
  config.degree_deltas[0] = config.degree_deltas[3] = 1;
  if (multipart) config.degree_deltas[5] = 1;
  config.compute.split_pagerank_state = true;
  config.compute.vertex_state_base = 0;
  config.compute.residual_state_base = 0x100000;
  config.compute.degree_base = 0x200000;
  config.status_address = 0x300000;
  config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = 0x100000;
  config.compute.cache_segments_per_half = 1;
  config.compute.max_supersteps = 256;
  config.compute.apply_request_window = pressure ? 1 : 8;
  if (optimized) {
    config.input_path = RoutedInputPath::kTriplePrefetchElasticExperimental;
    config.experimental_directory_tiles = 2;
    config.experimental_full_burst_refill = true;
    config.adapter.cross_row.bank_read_beats = true;
    config.adapter.read_pipeline_cycles = 3;
    config.source_loading = RoutedSourceLoading::kIndependentExperimental;
    config.apply_topology = RoutedApplyTopology::kSplitMastersExperimental;
    config.gather_schedule = RoutedGatherSchedule::kReadyBurstsExperimental;
    config.experimental_gather_reuse = true;
    config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 2;
  }
  auto layout = GraSuPartitionedPmaLayout::build(vertices, 65536, graph, {}, GraSuPmaWordAbi::kWeightedFullWord);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{.channels = 32,
      .latency_cycles = pressure ? 37U : 7U, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = pressure ? 2U : 16U,
      .response_queue_depth = pressure ? 2U : 32U,
      .registered_round_robin_arbitration = true});
  scheduler.add_component(backend);
  RoutedReGraphSystem system(scheduler, clock, backend, layout, initial, config);
  system.register_components(reverse);
  for (std::uint64_t cycle = 0; cycle < 40000000 && !system.done(); ++cycle) {
    scheduler.step(); system.advance_if_complete();
  }
  if (!system.done()) throw std::runtime_error(system.diagnostic());
  require(!system.failed(), "warm ResPR did not converge");
  const auto rank = system.distances(), residual = system.residual_words();
  const auto oracle = ranks(vertices, graph);
  double maximum_error = 0, l1_error = 0;
  for (std::size_t v = 0; v < vertices; ++v) {
    maximum_error = std::max(maximum_error,
        std::fabs(double(GraphAlgorithmPolicy::word_to_float(rank[v])) - oracle[v]));
    l1_error += std::fabs(double(GraphAlgorithmPolicy::word_to_float(rank[v])) - oracle[v]);
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(residual[v])) <= config.algorithm.epsilon,
            "ResPR terminated with above-threshold residual");
  }
  // A per-vertex residual threshold bounds the L1 error by N*epsilon/(1-d).
  // PageRank's column-stochastic operator is not an L-infinity contraction.
  const auto error_bound = vertices * double(config.algorithm.epsilon) / (1.0 - double(config.algorithm.damping));
  if (l1_error >= error_bound) {
    std::cerr << "PR mismatch max_error=" << maximum_error << " epsilon=" << config.algorithm.epsilon
              << " rounds=" << system.rounds().size() << '\n';
    for (std::size_t v = 0; v < std::min<std::size_t>(vertices, 8); ++v)
      std::cerr << v << " rank=" << GraphAlgorithmPolicy::word_to_float(rank[v])
                << " expected=" << oracle[v] << " residual=" << GraphAlgorithmPolicy::word_to_float(residual[v]) << '\n';
    throw std::runtime_error("warm ResPR disagrees with independent fixed-point oracle");
  }
  const auto counters = system.counters();
  const auto traffic = backend.traffic_stats();
  const auto bursts = (vertices + 15) / 16;
  require(counters.prepare_state_reads == bursts && counters.prepare_degree_reads == bursts + 1 &&
              counters.prepare_degree_writes == 1 && counters.prepare_source_writes == bursts * 2 &&
              counters.prepare_cycles > 128 && counters.degree_reads > 0,
          "PageRank device degree/correction preparation was not charged");
  require(counters.axi_requests == counters.axi_completions &&
              counters.axi_beats == counters.axi_completed_beats && backend.outstanding() == 0 &&
              traffic.reads.bytes + traffic.writes.bytes + 60 * system.rounds().size() == counters.axi_beats * 64,
          "PageRank physical memory ledger did not close");
  require(system.source_state(0, system.rounds().size() & 1U) ==
              system.source_state(1, system.rounds().size() & 1U), "PageRank source replicas differ");
  Result result{counters, system.rounds(), rank, residual};
  std::cout << "ResPR optimized=" << optimized << " pressure=" << pressure << " multipart=" << multipart
            << " reverse=" << reverse << " rounds=" << system.rounds().size()
            << " cycles=" << counters.end_cycle - counters.start_cycle << " beats=" << counters.axi_beats
            << " max_error=" << maximum_error << " l1_error=" << l1_error << '\n';
  system.unregister_components(); scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "PageRank scheduler components leaked");
  return result;
}
} // namespace

int main() {
  try {
    for (bool optimized : {false, true})
      for (bool pressure : {false, true})
        require(run(false, optimized, pressure, false) == run(true, optimized, pressure, false),
                "PageRank state, cycles or traffic depend on registration order");
    require(run(false, true, false, true) == run(true, true, false, true),
            "multipart PageRank depends on registration order");
    std::cout << "PASS: warm PageRank, independent fixed-point oracle, dangling mass, degree RMW, finite pressure and order\n";
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
