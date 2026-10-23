#include "spine_sim/routed_regraph.hpp"

#include <iostream>
#include <set>
#include <tuple>

namespace {
using namespace spine::sim;
constexpr auto kInf = GraphAlgorithmPolicy::kSsspInfinity;
constexpr std::uint32_t kWireInf = 0x7ffffffeU, kActive = 0x80000000U;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

struct Fixture {
  std::size_t vertices;
  std::vector<GraSuEdge> edges;
  AlgorithmInitialState initial;
};

std::vector<std::vector<std::uint32_t>> oracle(const Fixture &f, std::size_t fixed_rounds) {
  auto state = f.initial.primary;
  std::set<std::uint32_t> active(f.initial.active_vertices.begin(), f.initial.active_vertices.end());
  const auto padded = ((f.vertices + 65535) / 65536) * 65536;
  std::vector<std::vector<std::uint32_t>> history;
  do {
    auto next = state;
    for (const auto &edge : f.edges)
      if (active.contains(edge.source) && state[edge.source] != kInf)
        next[edge.destination] = std::min(next[edge.destination], state[edge.source] + edge.weight);
    active.clear();
    std::vector<std::uint32_t> encoded(padded, 0);
    for (std::size_t vertex = 0; vertex < f.vertices; ++vertex) {
      const bool changed = next[vertex] < state[vertex];
      if (changed) active.insert(vertex);
      encoded[vertex] = (next[vertex] == kInf ? kWireInf : next[vertex]) | (changed ? kActive : 0);
    }
    state = std::move(next);
    history.push_back(std::move(encoded));
  } while (fixed_rounds ? history.size() < fixed_rounds : !active.empty());
  return history;
}

struct Result {
  RoutedReGraphCounters counters;
  std::vector<RoutedReGraphInvocation> invocations;
  std::vector<RoutedReGraphRound> rounds;
  std::vector<std::uint32_t> state;
  bool operator==(const Result &) const = default;
};

Result run(const Fixture &f, bool reverse, bool stop, bool pressure, std::size_t fixed = 0,
           std::size_t limit = 128, bool independent = false, std::size_t stream_depth = 16,
           bool row_line_reads = false,
           RoutedSourceTopology topology = RoutedSourceTopology::kFourDedicated) {
  const auto expected = oracle(f, fixed ? fixed : 0);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{.channels = 32,
      .latency_cycles = pressure ? 31U : 7U, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = pressure ? 2U : 16U,
      .response_queue_depth = pressure ? 2U : 32U, .registered_round_robin_arbitration = true});
  scheduler.add_component(backend);
  RoutedReGraphConfig config;
  config.adapter.stop_after_last = stop;
  config.adapter.row_line_reads = row_line_reads;
  config.compute.cache_segments_per_half = 1;
  config.compute.max_supersteps = limit;
  config.fixed_rounds = fixed;
  config.independent_read_write = independent;
  config.source_topology = topology;
  config.adapter_stream_depth = stream_depth;
  config.gather_stream_depth = stream_depth;
  config.mux_stream_depth = stream_depth;
  if (pressure) {
    config.compute.max_pending_requests = 2;
    config.compute.max_outstanding_bursts = 2;
    config.compute.apply_request_window = 2;
    config.compute.apply_pipeline_capacity = 2;
    config.compute.hbm_wrapper_pipeline_capacity = 2;
    config.shared_master_capacity = 2;
  }
  auto layout = GraSuPartitionedPmaLayout::build(f.vertices, 65536, f.edges, {},
                                                 GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), f.initial, config);
  const bool paired = topology == RoutedSourceTopology::kTwoPairwise;
  const auto diagnostic = system.diagnostic();
  require(diagnostic.find(paired ? "source-services=2 physical-masters=7" :
                                  "source-services=4 physical-masters=9") != std::string::npos,
          "source topology has the wrong service or physical-master count");
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto begin = diagnostic.find("\nworker=" + std::to_string(worker) + " ");
    const auto line = diagnostic.substr(begin, diagnostic.find('\n', begin + 1) - begin);
    require(line.find("source-service=source" + std::to_string(paired ? worker % 2 : worker) + " ") !=
                std::string::npos,
            "source topology does not pair workers 0/2 and 1/3");
  }
  system.register_components(reverse);
  for (std::uint64_t cycle = 0; cycle < 20000000 && !system.done(); ++cycle) {
    scheduler.step();
    system.advance_if_complete();
  }
  if (!system.done()) {
    std::cerr << "vertices=" << f.vertices << " reverse=" << reverse << " stop=" << stop
              << " pressure=" << pressure << '\n' << system.diagnostic() << '\n';
    throw std::runtime_error("whole routed system timed out");
  }
  const auto expected_rounds = std::min(expected.size(), limit);
  require(system.failed() == (expected.size() > limit), "superstep completion/failure boundary differs");
  require(system.rounds().size() == expected_rounds, "whole routed convergence round count differs");
  require(system.encoded_state() == expected[expected_rounds - 1], "whole routed full state or padding differs");
  auto expected_distances = expected[expected_rounds - 1];
  expected_distances.resize(f.vertices);
  for (auto &word : expected_distances) word = (word & 0x7fffffffU) == kWireInf ? kInf : word & 0x7fffffffU;
  require(system.distances() == expected_distances, "whole routed decoded distances differ");
  for (std::size_t buffer = 0; buffer < 2; ++buffer) {
    std::vector<std::uint32_t> source(expected.back().size(), 0);
    if (buffer == 0) {
      const std::set<std::uint32_t> active(f.initial.active_vertices.begin(), f.initial.active_vertices.end());
      for (std::size_t v = 0; v < f.vertices; ++v)
        source[v] = (f.initial.primary[v] == kInf ? kWireInf : f.initial.primary[v]) | (active.contains(v) ? kActive : 0);
    }
    for (std::size_t round = 1; round <= expected_rounds; ++round)
      if ((round & 1U) == buffer) source = expected[round - 1];
    for (std::size_t copy = 0; copy < 2; ++copy)
      require(system.source_state(copy, buffer) == source, "whole routed double-buffered source replicas differ");
  }
  const auto c = system.counters();
  const auto partitions = (f.vertices + 65535) / 65536;
  const auto padded = partitions * 65536;
  const auto expected_beats = c.extent_reads + c.row_reads + c.segment_reads + c.source_blocks * 256 +
      c.apply_reads + c.apply_writes + c.source_writes + c.status_writes;
  require(c.extent_reads == expected_rounds * partitions && c.status_writes == expected_rounds &&
          c.packets == c.segment_reads * 2 && c.packets * 8 == c.live_edges + c.dummy_edges &&
          c.source_lines == c.source_blocks * 256 && c.source_terminators == expected_rounds * partitions &&
          c.gather_rows == expected_rounds * padded / 2 && c.mux_rows == c.gather_rows &&
          c.apply_reads == expected_rounds * padded / 16 && c.apply_writes == c.apply_reads &&
          c.source_writes == c.apply_reads * 2 && c.axi_requests == c.axi_completions &&
          c.axi_beats == c.axi_completed_beats && c.axi_beats == expected_beats &&
          backend.stats().accepted == expected_beats &&
          backend.traffic_stats().reads.requests ==
              c.extent_reads + c.row_reads + c.segment_reads + c.source_blocks * 256 + c.apply_reads &&
          backend.traffic_stats().writes.requests == c.apply_writes + c.source_writes + c.status_writes &&
          c.axi_requests == c.extent_reads + c.row_reads + c.segment_reads + c.source_blocks +
              c.apply_reads + c.apply_writes + c.source_writes + c.status_writes && backend.outstanding() == 0,
          "whole routed exact transaction, packet or padding conservation failed");
  require(c.live_edges == expected_rounds * f.edges.size(), "each live edge was not scanned exactly once per round");
  require(system.invocations().size() == expected_rounds * partitions * 2, "kernel invocation ledger differs");
  for (const auto &invocation : system.invocations()) {
    require(invocation.worker == invocation.partition % 4 && invocation.end > invocation.start &&
            invocation.start >= system.rounds()[invocation.round - 1].start &&
            invocation.end <= system.rounds()[invocation.round - 1].end,
            "routed host worker mapping or kernel interval differs");
    for (const auto &previous : system.invocations())
      if (previous.round == invocation.round && previous.adapter == invocation.adapter &&
          previous.partition + 4 == invocation.partition)
        require(previous.end == invocation.start, "independent same-worker task chain is not preserved");
  }
  for (const auto &round : system.rounds())
    require(round.start < round.apply_done && round.apply_done < round.status_done &&
            round.writeback_done <= round.end && round.status_done <= round.end,
            "routed status/writeback completion boundary differs");
  Result result{c, system.invocations(), system.rounds(), system.encoded_state()};
  std::cout << "case vertices=" << f.vertices << " reverse=" << reverse << " stop=" << stop
            << " pressure=" << pressure << " fixed=" << fixed << " limit=" << limit
            << " independent=" << independent
            << " stream_depth=" << stream_depth
            << " rounds=" << expected_rounds << " failed=" << system.failed()
            << " cycles=" << c.end_cycle - c.start_cycle
            << " parents=" << c.axi_requests << " beats=" << c.axi_beats;
  if (row_line_reads) std::cout << " row_line_reads=1";
  if (paired) std::cout << " source_topology=two_pairwise";
  std::cout << '\n';
  system.unregister_components();
  scheduler.remove_component(backend);
  require(scheduler.component_count() == 0, "whole routed system leaked scheduler components");
  return result;
}

Fixture fixture(std::size_t vertices, bool warm) {
  Fixture f{vertices, {{0, 1, 2, false}, {1, 32, 3, false}, {32, 64, 4, false}}, {}};
  if (vertices > 65536) f.edges.push_back({32, 65537, 5, false});
  if (vertices > 262144) f.edges.push_back({65537, 262145, 6, false});
  f.initial.primary.assign(vertices, kInf);
  f.initial.primary[0] = 0;
  f.initial.active_vertices = {0};
  if (warm) {
    f.initial.primary[1] = 20;
    f.initial.primary[32] = 23;
    f.initial.primary[64] = 27;
    if (vertices > 65536) f.initial.primary[65537] = 28;
    if (vertices > 262144) f.initial.primary[262145] = 34;
  }
  return f;
}

void rejection_tests() {
  auto check = [](Fixture f, auto mutate) {
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("core", 150);
    MockMemoryBackend backend("memory", clock, {32, 1, 1, 4, 4, true});
    auto layout = GraSuPartitionedPmaLayout::build(f.vertices, 65536, f.edges, {}, GraSuPmaWordAbi::kWeightedFullWord);
    RoutedReGraphConfig config;
    mutate(layout, f.initial, config);
    bool rejected = false;
    try { RoutedReGraphSystem system(scheduler, clock, backend, layout, f.initial, config); }
    catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "invalid whole routed input was admitted");
    require(backend.traffic_stats().reads.requests == 0, "rejected input issued memory requests");
  };
  check(fixture(129, false), [](auto &, auto &s, auto &) { s.active_vertices.push_back(0); });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.compute.source_state_channel = 22; });
  check(fixture(129, false), [](auto &l, auto &, auto &) { l.partitions[0].row_slot_bounds[1].first = 17; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.status_address = c.compute.vertex_state_base; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.compute.source_state_buffer_stride = 64; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.fixed_rounds = c.compute.max_supersteps + 1; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.compute.runtime_channel_capacity_bytes *= 2; });
  check(fixture(129, false), [](auto &, auto &s, auto &) { s.primary[1] = 0x7ffffffdU; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.adapter_stream_depth = 0; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.gather_stream_depth = 0; });
  check(fixture(129, false), [](auto &, auto &, auto &c) { c.mux_stream_depth = 0; });
  for (auto tiles : {0U, 2U, 3U})
    check(fixture(129, false), [tiles](auto &, auto &, auto &c) {
      c.experimental_directory_tiles = tiles;
    });
  check(fixture(129, false), [](auto &, auto &, auto &c) {
    c.experimental_full_burst_refill = true;
  });
  check(fixture(129, false), [](auto &, auto &, auto &c) {
    c.experimental_prefetch_bank_lines = 512;
  });
  for (auto lines : {0U, 257U, 513U})
    check(fixture(129, false), [lines](auto &, auto &, auto &c) {
      c.input_path = RoutedInputPath::kPrefetchCompactedExperimental;
      c.experimental_prefetch_bank_lines = lines;
    });
  check(fixture(129, false), [](auto &, auto &, auto &c) {
    c.apply_topology = static_cast<RoutedApplyTopology>(-1);
  });
  check(fixture(129, false), [](auto &, auto &, auto &c) {
    c.apply_topology = RoutedApplyTopology::kSplitMastersExperimental;
    c.first_initiator_id = std::numeric_limits<std::uint32_t>::max() - 9;
  });
  auto edge_at_end = fixture(65536, false);
  edge_at_end.edges.push_back({65535, 2, 1, false});
  check(edge_at_end, [](auto &, auto &, auto &) {});
}

void pairwise_tests() {
  std::cout << "BEGIN: two-pair source topology\n";
  for (const auto [vertices, pressure, depth, row_lines] : {
      std::tuple{129U, false, 16U, false}, std::tuple{65569U, true, 1U, true},
      std::tuple{262273U, false, 32U, true}}) {
    auto f = fixture(vertices, true);
    if (vertices > 262144) {
      f.edges.push_back({0, 131073, 7, false});
      f.edges.push_back({0, 196609, 8, false});
      f.edges.push_back({65537, 131074, 9, false});
    }
    const auto dedicated = run(f, false, true, pressure, 0, 128, true, depth, row_lines);
    auto paired = run(f, false, true, pressure, 0, 128, true, depth, row_lines,
                      RoutedSourceTopology::kTwoPairwise);
    require(paired == run(f, true, true, pressure, 0, 128, true, depth, row_lines,
                          RoutedSourceTopology::kTwoPairwise),
            "pairwise system depends on component registration order");
    auto expected_counts = dedicated.counters;
    expected_counts.start_cycle = paired.counters.start_cycle;
    expected_counts.end_cycle = paired.counters.end_cycle;
    require(paired.state == dedicated.state && paired.rounds.size() == dedicated.rounds.size() &&
            paired.counters == expected_counts,
            "pairwise topology changed state, convergence or conserved traffic");
    for (std::size_t round = 0; round < paired.rounds.size(); ++round)
      require(paired.rounds[round].active_vertices == dedicated.rounds[round].active_vertices,
              "pairwise topology changed intermediate active counts");
  }
  auto empty = fixture(129, false);
  empty.edges.clear();
  run(empty, false, true, true, 0, 128, true, 1, true, RoutedSourceTopology::kTwoPairwise);
  run(fixture(129, false), false, true, false, 2, 128, true, 16, false, RoutedSourceTopology::kTwoPairwise);
  run(fixture(129, false), false, true, false, 0, 1, true, 16, false, RoutedSourceTopology::kTwoPairwise);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, 1, 1, 4, 4, true});
  const auto f = fixture(129, false);
  auto layout = GraSuPartitionedPmaLayout::build(f.vertices, 65536, f.edges, {}, GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphConfig config;
  config.source_topology = static_cast<RoutedSourceTopology>(-1);
  bool rejected = false;
  try { RoutedReGraphSystem system(scheduler, clock, backend, layout, f.initial, config); }
  catch (const std::invalid_argument &) { rejected = true; }
  require(rejected && backend.traffic_stats().reads.requests == 0,
          "invalid source topology was admitted or issued traffic");
  std::cout << "PASS: 12 pairwise/reference executions and invalid-topology rejection\n";
}
}

int main() {
  try {
    std::size_t cases = 0;
    for (auto [vertices, warm, pressure] : {
        std::tuple{129U, false, false}, std::tuple{65569U, true, false},
        std::tuple{262273U, true, false}, std::tuple{129U, false, true}}) {
      const auto f = fixture(vertices, warm);
      require(run(f, false, true, pressure) == run(f, true, true, pressure),
              "whole routed result/cycle/ledger depends on registration order");
      cases += 2;
    }
    auto f = fixture(129, false);
    require(run(f, false, false, false) == run(f, true, false, false), "unoptimized adapter order dependence");
    cases += 2;
    f.edges.clear();
    run(f, false, true, false);
    run(fixture(129, false), false, true, false, 2);
    run(fixture(129, false), false, true, false, 0, 1);
    for (auto [vertices, pressure] : {std::pair{129U, true}, std::pair{262273U, false}}) {
      const auto independent_fixture = fixture(vertices, true);
      require(run(independent_fixture, false, true, pressure, 0, 128, true) ==
              run(independent_fixture, true, true, pressure, 0, 128, true),
              "independent-channel whole-system registration order differs");
      cases += 2;
    }
    rejection_tests();
    for (const auto depth : {1U, 32U}) {
      const auto routed = fixture(65569, true);
      const auto forward = run(routed, false, true, true, 0, 128, true, depth);
      require(forward == run(routed, true, true, true, 0, 128, true, depth),
              "per-path stream depth changed registration-order independence");
      cases += 2;
    }
    std::cout << "PASS: " << cases + 3 << " whole routed SSSP cases; full state, source replicas, padding, scheduling and traffic; 14 admission rejections PASS\n";
    for (auto [vertices, pressure] : {std::pair{129U, true}, std::pair{65569U, false}, std::pair{262273U, false}}) {
      const auto f = fixture(vertices, true);
      const auto narrow = run(f, false, true, pressure, 0, 128, true, 32);
      const auto wide = run(f, false, true, pressure, 0, 128, true, 32, true);
      require(wide == run(f, true, true, pressure, 0, 128, true, 32, true),
              "whole-line whole-system registration order differs");
      require(wide.state == narrow.state && wide.rounds.size() == narrow.rounds.size() &&
              wide.counters.row_reads < narrow.counters.row_reads &&
              wide.counters.segment_reads == narrow.counters.segment_reads &&
              wide.counters.live_edges == narrow.counters.live_edges,
              "whole-line model changed full state, convergence or edge traffic");
    }
    std::cout << "PASS: 9 whole-line/reference executions; complete oracle, replicas and traffic checks\n";
    pairwise_tests();
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
