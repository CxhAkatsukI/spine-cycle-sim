#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <vector>

#include "spine_sim/axi.hpp"

namespace spine::sim::original_grasu {

inline constexpr std::uint32_t kEmpty = 0x80000000u;
inline constexpr std::uint32_t kHotSegments = 131072;
inline constexpr std::size_t kSearchLanes = 64;
inline constexpr std::size_t kPeLanes = 16;
using Segment = std::array<std::uint32_t, 16>;

struct Update {
  std::uint64_t edge{};
  std::uint32_t slot{};
  bool end{};
  bool operator==(const Update&) const = default;
};

struct Port {
  Fifo<AxiRequest>& requests;
  Fifo<AxiResponse>& responses;
};
struct StreamPort {
  Port parent;
  Fifo<AxiReadBeatResponse>& beats;
};

// Schedule-informed predictions, not measured FPGA timing parameters.
struct Timing {
  std::uint64_t search_control{1};
  std::uint64_t cache_interval{3};
  std::uint64_t cache_latency{7};
  std::uint64_t ddr_compute{18};
  std::uint64_t ddr_sweep_minimum{161};
  std::uint64_t ddr_restart{4};
};

struct Counters {
  std::uint64_t updates{}, ends{}, reads{}, writes{}, acknowledgements{};
  std::uint64_t input_stalls{}, output_stalls{}, dependency_stalls{};
};

std::uint64_t little_word(std::span<const std::uint8_t> bytes);
Segment decode_segment(std::span<const std::uint8_t> bytes);
std::vector<std::uint8_t> encode_segments(std::span<const Segment> segments);
Segment apply_update(Segment segment, const Update& update);
void require_ack(const AxiResponse& response, std::uint64_t transaction,
                 MemoryOperation operation, std::uint64_t bytes);

}  // namespace spine::sim::original_grasu
