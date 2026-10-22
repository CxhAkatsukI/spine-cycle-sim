#include "../../src/detail/routed_regraph_transport.hpp"
#include "../evaluation_impact/k4_config.hpp"

#include <iostream>
#include <set>

namespace {
using namespace spine::sim;
void check(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

struct Result {
  RoutedReGraphCounters counters;
  std::vector<RoutedReGraphRound> rounds;
  RoutedReGraphObservation observation;
  bool operator==(const Result&) const = default;
};

void check_observation(const RoutedReGraphObservation& a, const RoutedReGraphObservation& b) {
  const auto compare = [](auto x, auto y, const std::string& field) {
    if (x != y)
      throw std::runtime_error(field + " registration-order mismatch: " +
                               std::to_string(x) + " vs " + std::to_string(y));
  };
#define CHECK_FIELD(field) compare(x.field, y.field, owner + "." #field)
  for (std::size_t i = 0; i < a.frontends.size(); ++i) {
    const auto& x = a.frontends[i]; const auto& y = b.frontends[i];
    const auto owner = "frontend[" + std::to_string(i) + "]";
    CHECK_FIELD(packets); CHECK_FIELD(emitted); CHECK_FIELD(source_waits);
    CHECK_FIELD(edge_waits); CHECK_FIELD(output_stalls); CHECK_FIELD(pipeline_stalls);
    CHECK_FIELD(request_stalls); CHECK_FIELD(source_lines); CHECK_FIELD(gather_reset);
    CHECK_FIELD(gather_merge); CHECK_FIELD(gather_drain); CHECK_FIELD(gather_output_stalls);
    CHECK_FIELD(gather_conflicts); CHECK_FIELD(gather_rows);
  }
  compare(a.sources.size(), b.sources.size(), "source services");
  for (std::size_t i = 0; i < a.sources.size(); ++i) {
    const auto& x = a.sources[i]; const auto& y = b.sources[i];
    const auto owner = "source[" + std::to_string(i) + "]";
    CHECK_FIELD(blocks); CHECK_FIELD(lines); CHECK_FIELD(terminators); CHECK_FIELD(parents);
    CHECK_FIELD(completions); CHECK_FIELD(output_stalls); CHECK_FIELD(issue_stalls);
    CHECK_FIELD(max_pending);
  }
  const auto& x = a.backend; const auto& y = b.backend;
  const std::string owner = "backend";
  CHECK_FIELD(merger_output_stalls); CHECK_FIELD(apply_output_stalls);
  CHECK_FIELD(apply_read_stalls); CHECK_FIELD(apply_pipeline_stalls);
  CHECK_FIELD(apply_write_stalls); CHECK_FIELD(writeback_pipeline_stalls);
  CHECK_FIELD(writeback_write_stalls); CHECK_FIELD(apply_max_reads);
  CHECK_FIELD(apply_max_pipeline); CHECK_FIELD(apply_max_writes);
  CHECK_FIELD(writeback_max_pipeline); CHECK_FIELD(writeback_max_writes);
#undef CHECK_FIELD
}

Result execute(std::size_t vertices, bool empty, bool reverse, bool throttled,
               const std::string& arm) {
  const auto inf = GraphAlgorithmPolicy::kSsspInfinity;
  std::vector<GraSuEdge> edges{{0, 1, 2, false}};
  if (vertices > 8192) {
    edges = {{0, 4095, 2, false}, {4095, 4096, 3, false}, {4096, 8192, 4, false}};
    if (vertices > 262144) {
      edges.push_back({8192, 65537, 5, false});
      edges.push_back({65537, 262145, 6, false});
    }
  }
  if (empty) edges.clear();
  AlgorithmInitialState initial;
  initial.primary.assign(vertices, inf);
  initial.primary[0] = 0;
  initial.active_vertices = {0};
  auto state = initial.primary;
  std::set<std::uint32_t> active{0};
  std::vector<std::vector<std::uint32_t>> expected;
  std::vector<std::size_t> active_counts;
  do {
    auto next = state;
    for (const auto& edge : edges)
      if (active.contains(edge.source) && state[edge.source] != inf)
        next[edge.destination] = std::min(next[edge.destination], state[edge.source] + edge.weight);
    active.clear();
    std::vector<std::uint32_t> encoded(((vertices + 65535) / 65536) * 65536, 0);
    for (std::size_t v = 0; v < vertices; ++v) {
      if (next[v] < state[v]) active.insert(v);
      encoded[v] = (next[v] == inf ? 0x7ffffffeU : next[v]) |
                   (active.contains(v) ? 0x80000000U : 0U);
    }
    state = std::move(next);
    active_counts.push_back(active.size());
    expected.push_back(std::move(encoded));
  } while (!active.empty());
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, 64, 1, throttled ? 2U : 32U,
                                              throttled ? 2U : 32U, true});
  scheduler.add_component(backend);
  auto config = evaluation_impact::k4_configuration(evaluation_impact::control(arm));
  config.compute.cache_segments_per_half = 1;
  if (throttled) {
    config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 1;
    config.compute.apply_request_window = config.shared_master_capacity = 2;
  }
  auto layout = GraSuPartitionedPmaLayout::build(vertices, 65536, edges, {},
                                                GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), initial, config);
  system.register_components(reverse);
  for (std::uint64_t cycle = 0; cycle < 20000000 && !system.done(); ++cycle) {
    scheduler.step(); system.advance_if_complete();
    if (cycle % 4096 == 0) {
      const auto counters = system.counters();
      const auto observation = system.observation();
      check(observation == system.observation() && counters == system.counters(),
            "read-only observation changes live component state");
    }
  }
  check(system.done() && !system.failed(), "compact convergence timed out or failed");
  check(system.encoded_state() == expected.back() && system.rounds().size() == expected.size(),
        "compact final full state or round count differs from independent oracle");
  for (std::size_t r = 0; r < expected.size(); ++r)
    check(system.rounds()[r].active_vertices == active_counts[r], "compact active trajectory differs");
  for (unsigned copy = 0; copy < 2; ++copy)
    check(system.source_state(copy, expected.size() & 1U) == expected.back(), "compact source replica differs");
  const auto c = system.counters();
  const auto traffic = backend.traffic_stats();
  check(c.live_edges == edges.size() * expected.size() && c.packets * 8 == c.live_edges + c.dummy_edges &&
        c.packets <= c.segment_reads * 2 && c.axi_requests == c.axi_completions &&
        c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0 &&
        traffic.reads.bytes == (c.extent_reads + c.row_reads + c.segment_reads + c.source_lines + c.apply_reads) * 64 &&
        traffic.writes.bytes == (expected.back().size() * 12ULL + 4) * expected.size(),
        "compact physical request, beat, dummy or byte conservation failed");
  check(system.invocations().size() == expected.size() * ((vertices + 65535) / 65536) * 2,
        "compact invocation/restart ledger differs");
  const auto observation = system.observation();
  check(observation.backend.apply_read_stalls <= c.end_cycle - c.start_cycle,
        "sampled Apply read-window waits exceed execution cycles");
  std::uint64_t packets = 0, rows = 0, lines = 0, parents = 0, completions = 0;
  for (const auto& f : observation.frontends) {
    packets += f.packets; rows += f.gather_rows;
    check(f.packets == f.emitted, "observation lost scatter packet completion");
  }
  for (const auto& s : observation.sources) {
    lines += s.lines; parents += s.parents; completions += s.completions;
  }
  check(packets == c.packets && rows == c.gather_rows && lines == c.source_lines &&
        parents == completions && observation.sources.size() == 2,
        "read-only observation disagrees with aggregate conservation");
  Result result{c, system.rounds(), observation};
  system.unregister_components(); scheduler.remove_component(backend);
  check(scheduler.component_count() == 0, "compact components leaked");
  std::cout << arm << " vertices=" << vertices << " empty=" << empty << " reverse=" << reverse
            << " throttled=" << throttled << " rounds=" << expected.size()
            << " cycles=" << c.end_cycle - c.start_cycle << '\n';
  return result;
}

void framing() {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  Fifo<ReGraphPmaPacket> input("input", clock, 4), output("output", clock, 1);
  detail::RoutedStreamBridge<ReGraphPmaPacket> bridge("bridge", clock, input, output, true);
  for (auto* component : std::vector<Component*>{&input, &output, &bridge}) scheduler.add_component(*component);
  bridge.start_until_last(4);
  ReGraphPmaPacket last; last.last = true;
  check(input.try_push(last), "cannot stage terminal packet");
  scheduler.step();
  check(input.try_push(last), "cannot stage next invocation");
  for (int i = 0; i < 10; ++i) scheduler.step();
  check(bridge.done() && input.size() == 1 && output.size() == 1,
        "terminal bridge consumed the next invocation");
  ReGraphPmaPacket packet;
  check(output.try_pop(packet), "terminal bridge lost output");
  scheduler.step();
  bridge.start_until_last(4);
  for (int i = 0; i < 10; ++i) scheduler.step();
  check(bridge.done() && input.empty() && output.size() == 1, "terminal bridge restart failed");
  Scheduler bad_scheduler;
  const auto bad_clock = bad_scheduler.add_clock_mhz("core", 150);
  Fifo<ReGraphPmaPacket> bad_input("bad-input", bad_clock, 1), bad_output("bad-output", bad_clock, 1);
  detail::RoutedStreamBridge<ReGraphPmaPacket> bad("bad", bad_clock, bad_input, bad_output, true);
  for (auto* component : std::vector<Component*>{&bad_input, &bad_output, &bad}) bad_scheduler.add_component(*component);
  bad.start_until_last(1);
  check(bad_input.try_push({}), "cannot stage malformed packet");
  bool rejected = false;
  try { for (int i = 0; i < 4; ++i) bad_scheduler.step(); }
  catch (const std::logic_error&) { rejected = true; }
  check(rejected, "terminal bridge accepted a missing TLAST at its bound");
}
}  // namespace

int main() {
  try {
    framing();
    for (const auto& arm : {"prefetch_compact", "prefetch_source", "prefetch_dual_elastic",
                           "prefetch_triple_elastic", "prefetch_triple_split_apply"})
     for (const auto [vertices, empty, throttled] : {
        std::tuple{129U, false, false}, std::tuple{129U, true, true},
        std::tuple{8193U, false, true}, std::tuple{262273U, false, false}}) {
      const auto forward = execute(vertices, empty, false, throttled, arm);
      const auto reverse = execute(vertices, empty, true, throttled, arm);
      check_observation(forward.observation, reverse.observation);
      check(forward == reverse, "compact results depend on registration order");
    }
    std::cout << "PASS: 40 coupled/independent/dual/triple/split-Apply compact convergence executions and terminal framing/restart/rejection\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
