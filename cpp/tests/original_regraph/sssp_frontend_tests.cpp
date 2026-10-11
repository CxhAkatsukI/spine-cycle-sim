#include "frontend_wiring.hpp"
#include "whole_graph/compact_source.hpp"
#include "whole_graph/compute_wiring.hpp"

#include <iostream>

namespace {
using namespace original_regraph_frontend_test;

std::uint32_t property(std::uint32_t vertex) {
  return (vertex % 3 == 0 ? 0u : 0x80000000u) | (vertex * 17 % 100003);
}

std::vector<std::vector<rg::EdgeBurst>> edges(bool gaps, bool unflagged_dummy = false) {
  std::vector<std::vector<rg::EdgeBurst>> paths(4);
  const std::array<unsigned, 4> rounds = gaps ? std::array<unsigned, 4>{0, 1, 3, 7}
                                           : std::array<unsigned, 4>{0, 1, 2, 3};
  for (unsigned path = 0; path < 4; ++path) for (const auto round : rounds)
    for (unsigned index = 0; index < 5; ++index) {
      rg::EdgeBurst burst;
      for (unsigned lane = 0; lane < 8; ++lane) {
        const auto source = round * 4096 + index * 17 + lane;
        const auto destination = index % 2 ? 65535u : lane % 3;
        const auto weight = (path + index + lane) % 3 == 0 ? 4095u : index + lane;
        burst[lane] = {source, destination | (weight << 19)};
        if (index == 4 && lane > 5) {
          if (unflagged_dummy) burst[lane].destination = 0xffffffffu;
          else {
            burst[lane].source |= 0x80000000u;
            burst[lane].destination |= 0x80000000u;
          }
        }
      }
      paths[path].push_back(burst);
    }
  return paths;
}

std::vector<std::uint32_t> oracle_min(const std::vector<std::vector<rg::EdgeBurst>>& input) {
  std::vector<std::uint32_t> result(65536);
  for (const auto& path : input) for (const auto& burst : path) for (const auto edge : burst) {
    if (edge.destination >> 31) continue;
    const auto value = property(edge.source);
    if (!(value >> 31)) continue;
    const auto candidate = (value & 0x7fffffffu) + ((edge.destination >> 19) & 4095u);
    auto& best = result[edge.destination & 0x7ffffu];
    if (!(best >> 31) || candidate < (best & 0x7fffffffu)) best = candidate | 0x80000000u;
  }
  return result;
}

std::uint64_t execute(Wiring& wiring, bool gaps = true, bool unflagged_dummy = false) {
  const auto input = edges(gaps, unflagged_dummy);
  const auto expected = oracle_min(input);
  std::vector<std::uint8_t> properties;
  for (std::uint32_t vertex = 0; vertex < 65536; ++vertex) append_word(properties, property(vertex));
  for (unsigned path = 0; path < 4; ++path)
    wiring.backend->initialize_payload(path * 2 + 1, 0, properties);
  const auto reads_before = wiring.backend->traffic_stats().reads.bytes;
  wiring.begin(input, false);
  std::vector<std::uint32_t> observed;
  for (std::uint64_t cycle = 0; cycle < 1000000; ++cycle) {
    if (cycle >= wiring.options.sink_start && cycle % wiring.options.sink_interval == 0 &&
        !wiring.merged_output->empty()) {
      rg::PropertyLine line;
      require(wiring.merged_output->try_pop(line), "SSSP output ownership");
      observed.insert(observed.end(), line.begin(), line.end());
      require(observed.size() <= expected.size(), "SSSP excess output");
    }
    wiring.scheduler.step();
    if (!wiring.drained()) continue;
    require(observed == expected, "weighted reader/cache/scatter/gather full output mismatch");
    std::uint64_t read_bytes = 0;
    for (const auto& path : wiring.paths) {
      for (const auto* master : {path.edge_port.master, path.source_port.master}) {
        require(master->stats().requests_accepted == master->stats().requests_completed &&
                master->stats().beats_issued == master->stats().beats_completed,
                "SSSP AXI request conservation");
      }
      const auto& source = path.source->counters();
      const auto& scatter = path.scatter->counters();
      require(source.rounds == source.acknowledgements &&
              source.response_lines == scatter.source_lines_loaded + scatter.source_lines_discarded &&
              source.partition_terminators == scatter.end_responses &&
              scatter.end_requests == scatter.end_responses, "SSSP source terminal conservation");
      read_bytes += path.reader->counters().read_bytes + source.read_bytes;
    }
    require(wiring.backend->traffic_stats().reads.bytes == read_bytes &&
            wiring.backend->traffic_stats().writes.bytes == 0 &&
            wiring.backend->traffic_stats().reads.bytes > reads_before, "SSSP traffic conservation");
    return cycle + 1;
  }
  std::cerr << "SSSP frontend timeout: observed=" << observed.size()
            << " backend_pending=" << wiring.backend->outstanding() << '\n';
  for (const auto& path : wiring.paths)
    std::cerr << "reader=" << path.reader->finished() << " source=" << path.source->finished()
              << " scatter=" << path.scatter->finished() << " gather=" << path.gather->finished()
              << " bursts=" << path.scatter->counters().bursts
              << " loaded=" << path.scatter->counters().source_lines_loaded
              << " requests=" << path.scatter->counters().source_round_requests
              << " source_lines=" << path.source->counters().response_lines << '\n';
  throw std::runtime_error("weighted frontend exceeded cycle budget");
}

namespace wt = original_regraph_whole_test;

wt::Input compact_input() {
  wt::Input input;
  input.vertices = input.aligned_vertices = input.published_vertices = 131072;
  input.partitions = 2;
  input.initial.assign(input.aligned_vertices, rg::kSsspInfinity);
  input.degrees.assign(input.aligned_vertices, 1);
  input.initial[0] = rg::kSsspActive | 10;
  input.initial[1] = rg::kSsspActive | 3;
  input.initial[2] = 1;  // Inactive sources must not contribute.
  input.initial[7] = rg::kSsspActive | 9;
  input.initial[9] = rg::kSsspActive | 5;
  input.initial[65536 + 7] = rg::kSsspActive | 15;
  for (unsigned partition = 0; partition < 2; ++partition) {
    for (unsigned subpartition = 0; subpartition < 4; ++subpartition) {
      const auto kernel = partition ? 3 - subpartition : subpartition;
      input.tasks.push_back({partition, subpartition, kernel, partition * 65536, 65536,
          static_cast<std::uint32_t>(input.edge_words.size()), 16, partition * 64ull});
      const std::array<rg::Edge, 8> packed{{
          {0, 7 | (9u << 19)}, {1, 7 | (5u << 19)}, {2, 9}, {0, 9 | (1u << 19)},
          {1, 0xffffffffu}, {1, 0xffffffffu}, {1, 0xffffffffu}, {0x80000001u, 0xffffffffu}}};
      for (const auto edge : packed) {
        input.edge_words.push_back(edge.source); input.edge_words.push_back(edge.destination);
      }
    }
  }
  return input;
}

std::vector<std::uint64_t> test_compact_compute(bool reverse, bool anchored) {
  const auto input = compact_input();
  wt::ComputeOptions options;
  options.udf = rg::Udf::kWeightedSssp;
  options.memory = original_regraph_memory_test::kMatchedMockService;
  if (anchored) {
    options.apply_timing = rg::kSsspSchedulePostReadTiming;
    options.sssp_response_anchored = true;
  }
  wt::ComputeWiring<wt::CompactSource, rg::SsspApply> path(
      wt::CompactSource(input, options.udf), 2, 4, reverse, 2, options);
  require(path.memory.scheduler.clock(path.memory.clock).period_fs == 6666667,
          "shared compute ignored the optional service clock");
  path.initialize(); path.begin();
  std::uint64_t cycles = 0;
  for (; cycles < 200000 && !path.finished(); ++cycles) {
    path.memory.scheduler.step(); path.advance(cycles + 1);
  }
  require(path.finished(), "weighted compact shared-wiring round timed out");
  auto expected = input.initial;
  for (auto& word : expected) word &= rg::kSsspValueMask;
  expected[7] = expected[65536 + 7] = rg::kSsspActive | 8;
  expected[65536 + 9] = rg::kSsspActive | 11;
  const auto encoded = wt::bytes(expected);
  for (unsigned replica = 0; replica < 4; ++replica) {
    const auto channel = replica * 2 + 1;
    require(path.memory.backend->inspect_payload(channel, wt::kOutputAddress, encoded.size()) == encoded,
            "weighted compact round differs from full-state min/old-state oracle");
    require(path.memory.backend->inspect_payload(channel, wt::kOutputAddress + encoded.size(), 64) ==
            std::vector<std::uint8_t>(64, 0xa5), "weighted compact round changed output guard");
  }
  const auto old = wt::bytes(input.initial);
  require(path.memory.backend->inspect_payload(30, 0, old.size()) == old,
          "weighted compact round did not preserve channel-30 old state");
  require(path.apply->counters().active_vertices == 3 &&
          path.apply->counters().old_state_bytes == old.size() &&
          path.writer->counters().write_bytes == old.size() * 4 &&
          path.writer->counters().acknowledgements == old.size() / 64 * 4,
          "weighted compact round did not conserve active/read/write/replica work");
  return {cycles, path.apply->counters().active_vertices, path.apply->counters().old_state_bytes,
          path.writer->counters().write_bytes, path.writer->counters().acknowledgements};
}

void test_shared_options() {
  using original_regraph_memory_test::MemoryFixture;
  const original_regraph_memory_test::MemoryServiceConfig defaults;
  require(defaults.clock_mhz == 210 && defaults.max_outstanding_per_channel == 512 &&
          defaults.response_queue_depth == 64, "legacy memory service defaults changed");
  MemoryFixture legacy;
  require(legacy.scheduler.clock(legacy.clock).period_fs == 4761905, "legacy fixture clock changed");
  auto input = compact_input();
  require(wt::CompactSource(input).udf() == rg::Udf::kFixedPointPr, "compact source default changed");
  const auto rejects = [](auto action, const std::string& diagnostic) {
    try { action(); }
    catch (const std::runtime_error& error) {
      require(std::string{error.what()}.find(diagnostic) != std::string::npos,
              "unexpected shared-wiring rejection");
      return;
    }
    throw std::runtime_error("missing shared-wiring rejection: " + diagnostic);
  };
  wt::ComputeOptions options;
  options.udf = rg::Udf::kWeightedSssp;
  rejects([&] {
    wt::ComputeWiring<wt::CompactSource> path(wt::CompactSource(input, options.udf), 2, 4, false, 2, options);
  }, "Apply type disagree");
  rejects([&] {
    wt::ComputeWiring<wt::CompactSource, rg::SsspApply> path(wt::CompactSource(input), 2, 4, false, 2, options);
  }, "source UDF disagree");
  options.udf = rg::Udf::kFixedPointPr; options.sssp_response_anchored = true;
  rejects([&] {
    wt::ComputeWiring<wt::CompactSource> path(wt::CompactSource(input), 2, 4, false, 2, options);
  }, "anchor requires SSSP");
  options.udf = rg::Udf::kWeightedSssp;
  input.published_vertices = 65536;
  rejects([&] {
    wt::ComputeWiring<wt::CompactSource, rg::SsspApply> path(
        wt::CompactSource(input, options.udf), 2, 4, false, 2, options);
  }, "complete aligned state");
  input.edge_words[1] = 65536;
  rejects([&] { wt::CompactSource source(input, rg::Udf::kWeightedSssp); }, "packed and prelocalized");
}
}  // namespace

int main() {
  try {
    Options options;
    options.little = 4; options.gather = true; options.udf = rg::Udf::kWeightedSssp;
    Wiring normal(options);
    const auto first = execute(normal);
    require(execute(normal) == first, "weighted frontend restart changed cycle count");
    require(execute(normal, true, true) == first, "unflagged-source padding changed frontend output/timing");
    options.reverse_registration = true;
    Wiring reversed(options);
    require(execute(reversed) == first, "weighted frontend registration-order dependence");
    options.fifo_depth = 1; options.sink_start = 50000; options.sink_interval = 19;
    Wiring narrow(options);
    // The inherited source protocol needs room for lookahead requests across gaps.
    // Exercise depth-one backpressure separately with sequential source windows.
    const auto slow = execute(narrow, false);
    require(slow > first && narrow.global_merge->counters().output_stalls > 0,
            "weighted frontend backpressure was not exercised");
    test_shared_options();
    for (const bool anchored : {false, true}) {
      require(test_compact_compute(false, anchored) == test_compact_compute(true, anchored),
              "weighted shared-wiring round depends on registration order");
    }
    std::cout << "SSSP_FRONTEND {\"checked_words\":65536,\"paths\":4,\"cycles\":" << first
              << ",\"stalled_cycles\":" << slow << ",\"restart_passed\":true}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
