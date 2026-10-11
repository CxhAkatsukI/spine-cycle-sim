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
           std::size_t limit = 128, bool independent = false) {
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
  config.compute.cache_segments_per_half = 1;
  config.compute.max_supersteps = limit;
  config.fixed_rounds = fixed;
  config.independent_read_write = independent;
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
            << " rounds=" << expected_rounds << " failed=" << system.failed()
            << " cycles=" << c.end_cycle - c.start_cycle
            << " parents=" << c.axi_requests << " beats=" << c.axi_beats << '\n';
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
  auto edge_at_end = fixture(65536, false);
  edge_at_end.edges.push_back({65535, 2, 1, false});
  check(edge_at_end, [](auto &, auto &, auto &) {});
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
    std::cout << "PASS: " << cases + 3 << " whole routed SSSP cases (15 convergence, 1 fixed-round, 1 expected limit failure); full state, source replicas, padding, scheduling and traffic; 9 admission rejections PASS\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
