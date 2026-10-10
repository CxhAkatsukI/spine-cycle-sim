#include "spine_sim/original_grasu/types.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_grasu {

std::uint64_t little_word(std::span<const std::uint8_t> bytes) {
  if (bytes.empty() || bytes.size() > 8) throw std::logic_error("invalid G word extent");
  std::uint64_t value = 0;
  for (std::size_t i = 0; i < bytes.size(); ++i) value |= std::uint64_t{bytes[i]} << (i * 8);
  return value;
}

Segment decode_segment(std::span<const std::uint8_t> bytes) {
  if (bytes.size() != 64) throw std::logic_error("invalid G segment extent");
  Segment result;
  for (std::size_t i = 0; i < result.size(); ++i) result[i] = little_word(bytes.subspan(i * 4, 4));
  return result;
}

std::vector<std::uint8_t> encode_segments(std::span<const Segment> segments) {
  std::vector<std::uint8_t> result;
  result.reserve(segments.size() * 64);
  for (const auto& segment : segments) for (auto word : segment)
    for (unsigned i = 0; i < 4; ++i) result.push_back(word >> (i * 8));
  return result;
}

Segment apply_update(Segment segment, const Update& update) {
  const auto destination = static_cast<std::uint32_t>(update.edge);
  if (update.end || destination >= kEmpty || !std::is_sorted(segment.begin(), segment.end()))
    throw std::logic_error("G update requires valid sorted source16 geometry");
  const auto position = std::lower_bound(segment.begin(), segment.end(), destination);
  if (update.edge >> 63) {
    if (position == segment.end() || *position != destination) throw std::logic_error("absent G deletion");
    std::move(position + 1, segment.end(), position); segment.back() = kEmpty;
  } else {
    if (segment.back() != kEmpty || position == segment.end() || *position == destination)
      throw std::logic_error("full or duplicate G insertion");
    std::move_backward(position, segment.end() - 1, segment.end()); *position = destination;
  }
  return segment;
}

void require_ack(const AxiResponse& response, std::uint64_t transaction,
                 MemoryOperation operation, std::uint64_t bytes) {
  if (!response.success || response.transaction_id != transaction || response.operation != operation ||
      response.read_data.size() != (operation == MemoryOperation::kRead ? bytes : 0))
    throw std::logic_error("G memory response identity/extent differs: got transaction=" +
        std::to_string(response.transaction_id) + " expected=" + std::to_string(transaction) +
        " data=" + std::to_string(response.read_data.size()) + " expected_data=" + std::to_string(bytes));
}

}  // namespace spine::sim::original_grasu
