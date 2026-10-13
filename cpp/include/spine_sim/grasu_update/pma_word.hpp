#pragma once

#include <limits>
#include <stdexcept>

#include "spine_sim/grasu.hpp"

namespace spine::sim::grasu_update_detail {

inline std::vector<std::uint8_t>
encode_segment(const std::array<std::uint32_t, kGraSuSegmentSlots> &segment) {
  std::vector<std::uint8_t> bytes(kGraSuSegmentBytes);
  for (std::size_t lane = 0; lane < segment.size(); ++lane) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[lane * 4 + byte] =
          static_cast<std::uint8_t>(segment[lane] >> (byte * 8));
    }
  }
  return bytes;
}

inline std::array<std::uint32_t, kGraSuSegmentSlots>
decode_segment(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != kGraSuSegmentBytes) {
    throw std::invalid_argument("GraSU PMA segment payload has invalid size");
  }
  std::array<std::uint32_t, kGraSuSegmentSlots> segment{};
  for (std::size_t lane = 0; lane < segment.size(); ++lane) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      segment[lane] |= static_cast<std::uint32_t>(bytes[lane * 4 + byte])
                       << (byte * 8);
    }
  }
  return segment;
}

inline std::uint32_t encode_pma_word(std::uint32_t destination, std::uint16_t weight,
                              GraSuPmaWordAbi abi) {
  if (abi == GraSuPmaWordAbi::kNativeRawDestination) {
    if (destination >= kGraSuPmaEmpty || weight != 1) {
      throw std::invalid_argument(
          "native GraSU PMA requires unit-weight raw dst");
    }
    return destination;
  }
  return encode_grasu_pma_edge(destination, weight);
}

inline bool uses_full_word_key(GraSuPmaWordAbi abi) noexcept {
  return abi == GraSuPmaWordAbi::kWeightedFullWord;
}

inline std::uint32_t pma_search_key(std::uint32_t destination, std::uint16_t weight,
                             GraSuPmaWordAbi abi) {
  return uses_full_word_key(abi) ? encode_pma_word(destination, weight, abi)
                                 : destination;
}

inline std::uint32_t decode_pma_destination(std::uint32_t encoded,
                                     GraSuPmaWordAbi abi) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return abi == GraSuPmaWordAbi::kNativeRawDestination
             ? encoded & ~kGraSuPmaEmpty
             : decode_grasu_pma_destination(encoded);
}

inline std::uint16_t decode_pma_weight(std::uint32_t encoded, GraSuPmaWordAbi abi) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return abi == GraSuPmaWordAbi::kNativeRawDestination
             ? std::uint16_t{1}
             : decode_grasu_pma_weight(encoded);
}

inline std::uint32_t pma_word_sort_key(std::uint32_t encoded, GraSuPmaWordAbi abi) {
  return is_grasu_pma_empty(encoded) ? std::numeric_limits<std::uint32_t>::max()
         : uses_full_word_key(abi)   ? encoded
                                     : decode_pma_destination(encoded, abi);
}


}  // namespace spine::sim::grasu_update_detail
