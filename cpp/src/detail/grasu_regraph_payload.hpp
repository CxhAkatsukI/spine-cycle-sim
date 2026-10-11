#pragma once

#include <algorithm>

#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

#include "spine_sim/algorithm.hpp"

namespace spine::sim::detail {

constexpr std::uint32_t kReGraphActive = 0x8000'0000U;
constexpr std::uint32_t kReGraphValueMask = 0x7fff'ffffU;
constexpr std::uint32_t kReGraphInfinity = 0x7fff'fffeU;
constexpr std::size_t kStateWordsPerBurst = 16;

inline std::uint32_t decode_u32(const std::vector<std::uint8_t> &bytes,
                         std::size_t offset = 0) {
  if (offset + 4 > bytes.size()) {
    throw std::invalid_argument("ReGraph 32-bit payload has invalid size");
  }
  std::uint32_t value = 0;
  for (std::size_t index = 0; index < 4; ++index) {
    value |= static_cast<std::uint32_t>(bytes[offset + index]) << (index * 8);
  }
  return value;
}

inline std::uint64_t decode_u64(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != 8) {
    throw std::invalid_argument("ReGraph 64-bit payload has invalid size");
  }
  std::uint64_t value = 0;
  for (std::size_t index = 0; index < 8; ++index) {
    value |= static_cast<std::uint64_t>(bytes[index]) << (index * 8);
  }
  return value;
}

inline std::vector<std::uint8_t>
encode_words(const std::array<std::uint32_t, kStateWordsPerBurst> &words) {
  std::vector<std::uint8_t> bytes(kStateWordsPerBurst * 4);
  for (std::size_t word = 0; word < words.size(); ++word) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[word * 4 + byte] =
          static_cast<std::uint8_t>(words[word] >> (byte * 8));
    }
  }
  return bytes;
}

inline std::uint32_t policy_distance(std::uint32_t encoded) {
  const std::uint32_t value = encoded & kReGraphValueMask;
  return value == kReGraphInfinity ? GraphAlgorithmPolicy::kSsspInfinity
                                   : value;
}

inline std::uint32_t encode_distance(std::uint32_t distance, bool active) {
  const std::uint32_t value = distance == GraphAlgorithmPolicy::kSsspInfinity
                                  ? kReGraphInfinity
                                  : std::min(distance, kReGraphInfinity - 1);
  return value | (active ? kReGraphActive : 0U);
}

inline std::uint32_t decode_policy_value(const GraphAlgorithmPolicy &policy,
                                  std::uint32_t encoded) {
  if (policy.config().kind == GraphAlgorithmKind::kWeightedSssp) {
    return policy_distance(encoded);
  }
  if (policy.config().kind == GraphAlgorithmKind::kFullPageRank ||
      policy.config().kind == GraphAlgorithmKind::kConnectedComponents) {
    return encoded & kReGraphValueMask;
  }
  return encoded;
}

inline std::uint32_t encode_policy_value(const GraphAlgorithmPolicy &policy,
                                  std::uint32_t value, bool active) {
  if (policy.config().kind == GraphAlgorithmKind::kWeightedSssp) {
    return encode_distance(value, active);
  }
  if (policy.config().kind == GraphAlgorithmKind::kConnectedComponents) {
    return (value & kReGraphValueMask) | (active ? kReGraphActive : 0U);
  }
  if (policy.config().kind == GraphAlgorithmKind::kResidualPageRank) {
    return value;
  }
  (void)active;
  return value;
}

inline bool uses_auxiliary_state(const GraphAlgorithmPolicy &policy) {
  return policy.config().kind == GraphAlgorithmKind::kResidualPageRank;
}

inline std::size_t state_bytes_per_vertex(const GraphAlgorithmPolicy &policy) {
  return uses_auxiliary_state(policy) ? 8 : 4;
}

inline std::size_t state_vertices_per_beat(const GraphAlgorithmPolicy &policy) {
  return 64 / state_bytes_per_vertex(policy);
}

inline std::vector<std::uint8_t> encode_state_words(
    const GraphAlgorithmPolicy &policy,
    const std::array<std::uint32_t, kStateWordsPerBurst> &primary,
    const std::array<std::uint32_t, kStateWordsPerBurst> &auxiliary) {
  if (!uses_auxiliary_state(policy)) {
    return encode_words(primary);
  }
  std::vector<std::uint8_t> bytes(kStateWordsPerBurst * 8);
  for (std::size_t word = 0; word < primary.size(); ++word) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[word * 8 + byte] =
          static_cast<std::uint8_t>(primary[word] >> (byte * 8));
      bytes[word * 8 + 4 + byte] =
          static_cast<std::uint8_t>(auxiliary[word] >> (byte * 8));
    }
  }
  return bytes;
}

} // namespace spine::sim::detail
