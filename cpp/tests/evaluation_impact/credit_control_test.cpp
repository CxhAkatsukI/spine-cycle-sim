#include <iostream>

#include "control.hpp"
#include "../original_regraph/memory_fixture.hpp"

int main() {
  using namespace evaluation_impact;
  const auto a4 = control("a4"), a4_io = control("a4_io16");
  const auto candidate = control("candidate"), apply = control("candidate_apply2");
  const auto parents = control("candidate_parents2"), both = control("candidate_both2");
  auto require = [](bool value) { if (!value) throw std::runtime_error("credit control mismatch"); };
  require(a4.original && !a4.candidate && a4.a4_input_parents == 2 && a4.a4_state_parents == 2);
  require(a4_io.original && a4_io.a4_input_parents == 16 && a4_io.a4_state_parents == 16);
  require(!control("cross_row").candidate && !control("cross_row").original);
  require(candidate.candidate && candidate.k4_parents == 16 && candidate.k4_apply_window == 16);
  require(apply.candidate && apply.k4_parents == 16 && apply.k4_apply_window == 2);
  require(parents.candidate && parents.k4_parents == 2 && parents.k4_apply_window == 16);
  require(both.candidate && both.k4_parents == 2 && both.k4_apply_window == 2);
  require(original_regraph_memory_test::axi_config(1, 0).max_pending_requests == 2);
  try { control("unknown"); return 1; } catch (const std::invalid_argument&) {}
  std::cout << "CREDIT_CONTROL_PASS seven explicit arms; source A4 remains two\n";
}
