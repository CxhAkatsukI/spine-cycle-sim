#include <climits>
#include <iostream>
#include <stdexcept>

#include "spine_sim/original_regraph/udf.hpp"

namespace reference {
#include SPINE_SSSP_UDF_REFERENCE
}
#undef prop_t
#undef SSSP_INF
#undef VERTEX_ACTIVE_BIT_MASK
#undef PROP_VALUE_MASK
#undef IS_ACTIVE_VERTEX

int main() {
  namespace rg = spine::sim::original_regraph;
  try {
    std::uint32_t random = 0x193ac405u;
    auto next = [&] { random = random * 1664525u + 1013904223u; return random; };
    for (unsigned index = 0; index < 100000; ++index) {
      const auto source = next(), update = next(), weight = next() & 4095u;
      if (rg::scatter_sssp_property(source, weight) != reference::scatterFunc(source, weight) ||
          rg::reduce_property(rg::Udf::kWeightedSssp, source, update) != reference::gatherFunc(source, update) ||
          rg::apply_sssp_property(update, source) != reference::applyFunc(update, source, 0, 0))
        throw std::runtime_error("local SSSP UDF differs from admitted HLS source");
    }
    for (const auto source : {0u, rg::kSsspActive, rg::kSsspInfinity,
                             rg::kSsspActive | (rg::kSsspInfinity - 1), 0xffffffffu})
      for (const auto weight : {0u, 1u, 4095u})
        if (rg::scatter_sssp_property(source, weight) != reference::scatterFunc(source, weight))
          throw std::runtime_error("SSSP HLS infinity/active boundary mismatch");
    std::cout << "SSSP_SOURCE {\"random_cases\":100000,\"boundary_cases\":15,"
                 "\"matched_local_hls_udf\":true,\"publication_reproduction\":false}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
