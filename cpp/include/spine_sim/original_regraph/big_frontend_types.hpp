#pragma once

#include "spine_sim/original_regraph/frontend_types.hpp"

namespace spine::sim::original_regraph {

struct CachelineRequest {
  std::uint32_t line{};
  unsigned lane{};
  bool end{};
  bool operator==(const CachelineRequest&) const = default;
};
struct CachelineResponse {
  PropertyLine data{};
  std::uint32_t line{};  // Model metadata; the original response carries lane only.
  unsigned lane{};
  bool end{};
};
struct CachelineBatch {
  std::array<std::uint32_t, 8> lines{};
  unsigned first{};
  bool end{};
};
struct LaneProperty {
  PropertyLine data{};
  std::uint32_t line{};
};
using LanePropertyPorts = std::array<Fifo<LaneProperty>*, 8>;

}  // namespace spine::sim::original_regraph
