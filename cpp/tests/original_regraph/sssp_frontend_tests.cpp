#include "frontend_wiring.hpp"

#include <iostream>

namespace {
using namespace original_regraph_frontend_test;

std::uint32_t property(std::uint32_t vertex) {
  return (vertex % 3 == 0 ? 0u : 0x80000000u) | (vertex * 17 % 100003);
}

std::vector<std::vector<rg::EdgeBurst>> edges(bool gaps) {
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
          burst[lane].source |= 0x80000000u;
          burst[lane].destination |= 0x80000000u;
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

std::uint64_t execute(Wiring& wiring, bool gaps = true) {
  const auto input = edges(gaps);
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
}  // namespace

int main() {
  try {
    Options options;
    options.little = 4; options.gather = true; options.udf = rg::Udf::kWeightedSssp;
    Wiring normal(options);
    const auto first = execute(normal);
    require(execute(normal) == first, "weighted frontend restart changed cycle count");
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
    std::cout << "SSSP_FRONTEND {\"checked_words\":65536,\"paths\":4,\"cycles\":" << first
              << ",\"stalled_cycles\":" << slow << ",\"restart_passed\":true}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
