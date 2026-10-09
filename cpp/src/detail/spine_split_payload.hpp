#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace spine::sim::detail::split_payload {

constexpr std::uint64_t kActiveOutputBytes = 8;
constexpr std::uint32_t kTileVertices = 65'536;
constexpr std::size_t kActiveWordBits = 64;
constexpr std::uint32_t kRangeTaskPathFallback = 2;

inline std::vector<std::uint8_t> encode_u32(std::uint32_t value) {
  return {
      static_cast<std::uint8_t>(value & 0xffU),
      static_cast<std::uint8_t>((value >> 8) & 0xffU),
      static_cast<std::uint8_t>((value >> 16) & 0xffU),
      static_cast<std::uint8_t>((value >> 24) & 0xffU),
  };
}

inline std::vector<std::uint8_t> encode_u64(std::uint64_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] = static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

inline std::uint32_t decode_u32(const std::vector<std::uint8_t> &data,
                                std::size_t offset = 0) {
  if (offset + sizeof(std::uint32_t) > data.size()) {
    throw std::invalid_argument("uint32 payload is truncated");
  }
  return static_cast<std::uint32_t>(data[offset]) |
         (static_cast<std::uint32_t>(data[offset + 1]) << 8) |
         (static_cast<std::uint32_t>(data[offset + 2]) << 16) |
         (static_cast<std::uint32_t>(data[offset + 3]) << 24);
}

inline std::uint64_t decode_u64(const std::vector<std::uint8_t> &data,
                                std::size_t offset = 0) {
  if (offset + sizeof(std::uint64_t) > data.size()) {
    throw std::invalid_argument("uint64 payload is truncated");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(std::uint64_t); ++byte) {
    value |= static_cast<std::uint64_t>(data[offset + byte]) << (byte * 8);
  }
  return value;
}

inline std::vector<std::uint8_t>
encode_u32_words(const std::vector<std::uint32_t> &values) {
  std::vector<std::uint8_t> data(values.size() * sizeof(std::uint32_t));
  for (std::size_t index = 0; index < values.size(); ++index) {
    const std::vector<std::uint8_t> word = encode_u32(values[index]);
    std::copy(word.begin(), word.end(),
              data.begin() + static_cast<std::ptrdiff_t>(index * word.size()));
  }
  return data;
}

} // namespace spine::sim::detail::split_payload
