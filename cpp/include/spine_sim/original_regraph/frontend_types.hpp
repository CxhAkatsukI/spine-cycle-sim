#pragma once

#include "spine_sim/axi.hpp"
#include "spine_sim/original_regraph/types.hpp"

namespace spine::sim::original_regraph {

inline constexpr std::size_t kSourceWindowVertices = 4096;
inline constexpr std::size_t kSourceWindowLines = kSourceWindowVertices / 16;
inline constexpr PipelineTiming kEdgeReaderTiming{3, 1, 4};
inline constexpr PipelineTiming kScatterTiming{4, 1, 5};

struct Edge {
  std::uint32_t source{};
  std::uint32_t destination{};
};
using EdgeBurst = std::array<Edge, 8>;

struct SourceRequest {
  std::uint32_t round{};
  bool end{};
  bool operator==(const SourceRequest&) const = default;
};

struct SourceResponse {
  PropertyLine data{};
  std::uint32_t line{};
  bool end{};
};

struct ReadPort {
  Fifo<AxiRequest>& requests;
  Fifo<AxiResponse>& responses;
  Fifo<AxiReadBeatResponse>& beats;
};

}  // namespace spine::sim::original_regraph
