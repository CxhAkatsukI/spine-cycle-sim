#pragma once

#include <span>
#include <stdexcept>

#include "spine_sim/original_regraph/frontend_types.hpp"

namespace spine::sim::original_regraph::detail {

inline std::uint32_t word(std::span<const std::uint8_t> bytes, std::size_t index) {
  if (bytes.size() != 64 || index >= 16) {
    throw std::invalid_argument("original ReGraph requires complete 512-bit lines");
  }
  std::uint32_t value = 0;
  for (unsigned byte = 0; byte < 4; ++byte) {
    value |= static_cast<std::uint32_t>(bytes[index * 4 + byte]) << (byte * 8);
  }
  return value;
}

inline PropertyLine property_line(std::span<const std::uint8_t> bytes) {
  PropertyLine result;
  for (std::size_t index = 0; index < result.size(); ++index) result[index] = word(bytes, index);
  return result;
}

inline void validate_port(const ReadPort& port, ClockId clock) {
  if (port.requests.clock_id() != clock || port.responses.clock_id() != clock ||
      port.beats.clock_id() != clock) {
    throw std::invalid_argument("original ReGraph read port clock mismatch");
  }
}

inline void require_read_ack(const AxiResponse& response, std::uint64_t transaction,
                             std::uint64_t bytes) {
  if (response.transaction_id != transaction || !response.success ||
      response.operation != MemoryOperation::kRead || response.read_data.size() != bytes) {
    throw std::logic_error("original ReGraph read parent acknowledgement mismatch");
  }
}

}  // namespace spine::sim::original_regraph::detail
