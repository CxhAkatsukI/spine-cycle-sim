#include "sssp/round_wiring.hpp"

#include <iostream>

int main() {
  try {
    using namespace original_regraph_sssp_test;
    for (const auto [warm, inactive] : {std::pair{false, false}, std::pair{true, false},
                                      std::pair{true, true}}) {
      const auto f = fixture(warm, inactive);
      const auto normal = run_a4(f, false, false);
      require(run_a4(f, true, false) == normal, "A4 weighted round registration order dependence");
      const auto pressured = run_a4(f, false, true);
      require(pressured.state == normal.state && pressured.cycles > normal.cycles,
              "A4 weighted full-round pressure changed values or failed to slow execution");
      require(run_routed(f) == normal.state, "compact A4 and routed K4 full states disagree");
      std::cout << "SSSP_ROUND {\"warm\":" << warm << ",\"inactive\":" << inactive
                << ",\"checked_words_per_replica\":65536,\"a4_replicas\":4,\"routed_replicas\":2,"
                << "\"a4_cycles_diagnostic_only\":" << normal.cycles
                << ",\"pressure_cycles\":" << pressured.cycles
                << ",\"a4_read_bytes\":" << normal.reads << ",\"a4_write_bytes\":" << normal.writes
                << ",\"active_vertices\":" << normal.active
                << ",\"timing_ratio_admitted\":false}\n";
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
