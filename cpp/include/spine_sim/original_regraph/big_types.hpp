#pragma once

#include "spine_sim/original_regraph/types.hpp"

namespace spine::sim::original_regraph {

inline constexpr std::size_t kBigVertices = 524288;
inline constexpr std::size_t kBigBankRows = kBigVertices / 16;

struct RoutedUpdate {
  Update update{};
  bool end{};
};

// Pipeline depths are model assumptions informed by HLS, not measured RTL.
struct BigTiming {
  PipelineTiming gather{6, 1, 7};
  PipelineTiming drain{3, 1, 4};
  PipelineTiming pack{1, 1, 2};
  PipelineTiming merge{4, 1, 5};
};

}  // namespace spine::sim::original_regraph
