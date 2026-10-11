#pragma once

#include <cstdint>

namespace spine::sim::original_regraph {

// Weighted SSSP is a local UDF extension, not an author-publication workload.
enum class Udf { kFixedPointPr, kWeightedSssp };

inline constexpr std::uint32_t kSsspActive = 0x80000000u;
inline constexpr std::uint32_t kSsspValueMask = 0x7fffffffu;
inline constexpr std::uint32_t kSsspInfinity = 0x7ffffffeu;

inline std::uint32_t scatter_sssp_property(std::uint32_t source,
                                         std::uint32_t weight) {
  const auto distance = source & kSsspValueMask;
  if (!(source & kSsspActive) || distance >= kSsspInfinity) return 0;
  const auto next = static_cast<std::uint64_t>(distance) + weight;
  return static_cast<std::uint32_t>(next < kSsspInfinity ? next : kSsspInfinity) |
         kSsspActive;
}

inline std::uint32_t reduce_property(Udf udf, std::uint32_t current,
                                     std::uint32_t update) {
  if (udf == Udf::kFixedPointPr) return current + update;
  if (!(update & kSsspActive)) return current;
  if (!(current & kSsspActive)) return update;
  return (update & kSsspValueMask) < (current & kSsspValueMask) ? update : current;
}

inline std::uint32_t apply_sssp_property(std::uint32_t update,
                                        std::uint32_t old) {
  const auto distance = old & kSsspValueMask;
  return (update & kSsspActive) && (update & kSsspValueMask) < distance
             ? update : distance;
}

}  // namespace spine::sim::original_regraph
