#include "frontend_wiring.hpp"
#include "state_support.hpp"

namespace {
namespace ft = original_regraph_frontend_test;
namespace st = original_regraph_state_test;
namespace rg = spine::sim::original_regraph;

struct Observation {
  std::vector<std::uint64_t> cycles;
  std::vector<std::uint32_t> final_values;
  std::uint64_t read_bytes{};
  std::uint64_t write_bytes{};
  std::uint64_t contended_cycles{};
  bool operator==(const Observation&) const = default;
};

Observation run(const char* id, bool reverse = false) {
  ft::Wiring frontend({.little = 4, .gather = true, .reverse_registration = reverse});
  st::StatePath state(frontend.memory, *frontend.merged_output, 4096);
  frontend.memory.register_components(reverse);
  std::vector<std::vector<rg::EdgeBurst>> edges;
  for (unsigned pipeline = 0; pipeline < 4; ++pipeline) edges.push_back(ft::fixture({0, 1, 2}, pipeline));
  std::vector<std::uint32_t> degrees(65536, 0), properties(65536);
  for (std::uint32_t vertex = 0; vertex < properties.size(); ++vertex) properties[vertex] = 17 + vertex % 31;
  std::uint64_t physical_edges = 0;
  for (const auto& path : edges) {
    for (const auto& burst : path) {
      for (const auto edge : burst) {
        ++physical_edges;
        if (!(edge.destination & rg::kDummyDestination)) ++degrees[edge.source & 0x7fffffffu];
      }
    }
  }
  Observation observed;
  std::uint64_t source_address = 0, output_address = st::kNewPropertyAddress;
  for (unsigned iteration = 0; iteration < 3; ++iteration) {
    std::vector<std::uint32_t> sums(65536, 0), expected(65536);
    for (const auto& path : edges) for (const auto& burst : path) for (const auto edge : burst) {
      if (!(edge.destination & rg::kDummyDestination)) sums[edge.destination] += properties[edge.source & 0x7fffffffu];
    }
    for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
      expected[vertex] = st::oracle(sums[vertex], degrees[vertex], 3);
    }
    const auto before = frontend.backend->traffic_stats();
    state.begin(3, output_address, degrees);
    frontend.begin(edges, iteration == 0, source_address);
    bool completed = false;
    for (std::uint64_t cycle = 0; cycle < 1000000; ++cycle) {
      frontend.scheduler.step();
      if (state.finished() && frontend.drained()) {
        observed.cycles.push_back(cycle + 1);
        completed = true;
        break;
      }
    }
    st::require(completed, "complete original A4 iteration timed out");
    properties = state.inspect_and_check(expected);
    const auto traffic = spine::sim::subtract_memory_traffic(frontend.backend->traffic_stats(), before);
    st::require(traffic.reads.bytes == 262144 + 65536 * 4 + physical_edges * 8 &&
                traffic.writes.bytes == 65536 * 4 * 4, "full A4 iteration traffic differs from component work");
    observed.read_bytes += traffic.reads.bytes;
    observed.write_bytes += traffic.writes.bytes;
    std::swap(source_address, output_address);
  }
  observed.final_values = properties;
  observed.contended_cycles = frontend.backend->arbitration_stats()->contended_cycles;
  st::require(observed.contended_cycles > 0, "source reads and property writes did not share HBM arbitration");
  st::require(state.apply->counters().degree_responses == 4096 * 3 &&
              state.writer->counters().acknowledgements == 4096 * 4 * 3 &&
              state.writer->counters().input_terminators == 3, "full A4 round/state conservation failed");
  std::cout << "ITERATION_CASE {\"id\":\"" << id << "\",\"iterations\":3,\"little\":4,\"big\":0,"
            << "\"checked_words\":196608,\"read_bytes\":" << observed.read_bytes
            << ",\"write_bytes\":" << observed.write_bytes
            << ",\"shared_channel_contended_cycles\":" << observed.contended_cycles << ",\"cycles\":[";
  for (unsigned index = 0; index < observed.cycles.size(); ++index) {
    if (index) std::cout << ',';
    std::cout << observed.cycles[index];
  }
  std::cout << "]}\n";
  return observed;
}
}  // namespace

int main() {
  try {
    st::emit_configuration();
    const auto forward = run("a4_complete_rounds");
    st::require(run("a4_complete_rounds_reverse", true) == forward,
                "registration order changed complete A4 states/cycles/traffic/contention");
    std::cout << "Three complete original A4 rounds pass, with resident ping-pong state and shared channels\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
