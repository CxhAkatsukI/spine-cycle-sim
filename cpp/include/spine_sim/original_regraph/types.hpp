#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace spine::sim::original_regraph {

inline constexpr std::size_t kGatherLanes = 8;
inline constexpr std::size_t kLittleVertices = 65536;
inline constexpr std::size_t kLittleRows = kLittleVertices / 2;
inline constexpr std::uint32_t kDummyDestination = 1u << 19;
inline constexpr std::size_t kForwardingEntries = 4;
inline constexpr std::uint64_t kUramWriteLatency = 3;

struct Update {
  std::uint32_t destination{};
  std::uint32_t value{};
};
using UpdateBurst = std::array<Update, kGatherLanes>;

struct VertexPair {
  std::uint32_t low{};
  std::uint32_t high{};
  bool operator==(const VertexPair&) const = default;
};
using LanePairs = std::array<VertexPair, kGatherLanes>;
using PropertyLine = std::array<std::uint32_t, 16>;

struct PipelineTiming {
  std::uint64_t latency{};
  std::uint64_t initiation_interval{1};
  std::size_t capacity{};
};

struct PipelineCounters {
  std::uint64_t accepted{};
  std::uint64_t completed{};
  std::uint64_t capacity_stalls{};
  std::uint64_t interval_stalls{};
  std::uint64_t output_stalls{};
  std::size_t max_inflight{};
};

// These are HLS-schedule-informed model assumptions, not measured RTL cycles.
struct LittleTiming {
  PipelineTiming gather{6, 1, 7};
  PipelineTiming drain{3, 1, 4};
  PipelineTiming local_merge{3, 1, 4};
  PipelineTiming global_merge{4, 1, 5};
};

}  // namespace spine::sim::original_regraph
