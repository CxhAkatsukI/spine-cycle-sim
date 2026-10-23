#include "spine_sim/routed_regraph.hpp"

#include <iostream>
#include <numeric>
#include <set>

namespace {
using namespace spine::sim;
void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

std::vector<std::uint32_t> labels(std::size_t vertices, const std::vector<GraSuEdge> &edges) {
  std::vector<std::uint32_t> parent(vertices);
  std::iota(parent.begin(), parent.end(), 0U);
  auto root = [&](std::uint32_t v) {
    while (parent[v] != v) v = parent[v] = parent[parent[v]];
    return v;
  };
  for (const auto &edge : edges) {
    const auto a = root(edge.source), b = root(edge.destination);
    parent[std::max(a, b)] = std::min(a, b);
  }
  for (auto &v : parent) v = root(v);
  return parent;
}

struct Result {
  RoutedReGraphCounters counters;
  std::vector<RoutedReGraphRound> rounds;
  std::vector<std::uint32_t> state;
  bool operator==(const Result &) const = default;
};

Result cc(bool reverse, bool optimized, bool pressure, bool multipart) {
  const std::size_t vertices = multipart ? 65540 : 129;
  std::vector<GraSuEdge> old;
  auto link = [](auto &edges, std::uint32_t a, std::uint32_t b) {
    edges.push_back(GraSuEdge{a, b, 7, false});
    edges.push_back(GraSuEdge{b, a, 3, false});
  };
  link(old, 0, 1); link(old, 1, 32); link(old, 64, 65);
  if (multipart) link(old, 65536, 65537);
  auto graph = old;
  link(graph, 32, 64);
  if (multipart) link(graph, 65, 65536);
  AlgorithmInitialState initial{.primary = labels(vertices, old), .auxiliary = {},
                               .active_vertices = {32, 64}};
  if (multipart) {
    initial.active_vertices.push_back(65);
    initial.active_vertices.push_back(65536);
  }
  auto layout = GraSuPartitionedPmaLayout::build(vertices, 65536, graph, {},
                                               GraSuPmaWordAbi::kWeightedFullWord);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{.channels = 32,
      .latency_cycles = pressure ? 37U : 7U, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = pressure ? 2U : 16U,
      .response_queue_depth = pressure ? 2U : 32U,
      .registered_round_robin_arbitration = true});
  scheduler.add_component(backend);
  RoutedReGraphConfig config;
  config.algorithm.kind = GraphAlgorithmKind::kConnectedComponents;
  config.compute.cache_segments_per_half = 1;
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
  RoutedReGraphSystem system(scheduler, clock, backend, layout, initial, config);
  system.register_components(reverse);
  for (std::uint64_t cycle = 0; cycle < 40000000 && !system.done(); ++cycle) {
    scheduler.step(); system.advance_if_complete();
  }
  if (!system.done()) throw std::runtime_error(system.diagnostic());
  require(!system.failed(), "CC did not converge");
  require(system.distances() == labels(vertices, graph), "warm CC differs from independent DSU oracle");
  require(system.rounds().back().active_vertices == 0, "CC stopped with active labels");
  const auto encoded = system.encoded_state();
  const auto final_labels = system.distances();
  for (std::size_t v = 0; v < vertices; ++v)
    require(encoded[v] == final_labels[v], "CC left active or SSSP infinity bits in labels");
  const auto counters = system.counters();
  const auto traffic = backend.traffic_stats();
  require(counters.axi_requests == counters.axi_completions &&
              counters.axi_beats == counters.axi_completed_beats && backend.outstanding() == 0 &&
              (traffic.reads.bytes + traffic.writes.bytes + 60 * system.rounds().size()) == counters.axi_beats * 64,
          "CC finite-memory request or byte ledger did not close");
  const auto buffer = system.rounds().size() & 1U;
  require(system.source_state(0, buffer) == encoded && system.source_state(1, buffer) == encoded,
          "CC source replicas differ from final state");
  Result result{counters, system.rounds(), encoded};
  std::cout << "CC optimized=" << optimized << " pressure=" << pressure << " multipart=" << multipart
            << " reverse=" << reverse << " rounds=" << system.rounds().size()
            << " cycles=" << counters.end_cycle - counters.start_cycle
            << " beats=" << counters.axi_beats << '\n';
  system.unregister_components(); scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "CC scheduler components leaked");
  return result;
}
} // namespace

int main() {
  try {
    for (bool optimized : {false, true})
      for (bool pressure : {false, true})
        for (bool multipart : {false, true})
          require(cc(false, optimized, pressure, multipart) == cc(true, optimized, pressure, multipart),
                  "CC state, cycles or traffic depend on registration order");
    std::cout << "PASS: warm CC, independent DSU, weighted-input ignored, physical/optimized inputs, finite pressure, source replicas and order\n";
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
