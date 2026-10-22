#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>

namespace evaluation_impact {
struct Control {
  std::string arm;
  bool original{}, candidate{}, bank_stream{}, prefetch_compact{}, independent_source{};
  bool dual_elastic{};
  std::size_t a4_input_parents{2}, a4_state_parents{2};
  std::size_t k4_parents{16}, k4_apply_window{16};
};

inline Control control(const std::string& arm) {
  Control result{.arm = arm};
  if (arm == "a4" || arm == "a4_io16") {
    result.original = true;
    if (arm == "a4_io16") result.a4_input_parents = result.a4_state_parents = 16;
  } else if (arm == "bank_stream" || arm == "prefetch_compact" || arm == "prefetch_source" ||
             arm == "prefetch_dual_elastic") {
    result.candidate = result.bank_stream = true;
    result.prefetch_compact = arm != "bank_stream";
    result.dual_elastic = arm == "prefetch_dual_elastic";
    result.independent_source = arm == "prefetch_source" || result.dual_elastic;
  } else if (arm == "cross_row" || arm == "candidate" || arm == "candidate_apply2" ||
             arm == "candidate_parents2" || arm == "candidate_both2") {
    result.candidate = arm != "cross_row";
    if (arm == "candidate_apply2" || arm == "candidate_both2") result.k4_apply_window = 2;
    if (arm == "candidate_parents2" || arm == "candidate_both2") result.k4_parents = 2;
  } else {
    throw std::invalid_argument("unknown demo arm");
  }
  return result;
}
}  // namespace evaluation_impact
