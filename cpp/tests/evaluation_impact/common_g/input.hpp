#pragma once

#include "../../original_grasu/fixture.hpp"
#include "spine_sim/grasu.hpp"

namespace common_g {
using namespace grasu_test;
inline constexpr unsigned vertices = 524288;

inline GraSuPmaLayout layout(const Fixture& fixture) {
  GraSuPmaLayout result;
  result.vertices = result.destination_vertices = vertices;
  result.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  result.row_slot_bounds.resize(vertices, {kSegments * 16, kSegments * 16});
  result.row_slot_bounds[0] = {0, g::kHotSegments * 2 * 16};
  result.row_slot_bounds[1] = {g::kHotSegments * 2 * 16, kSegments * 16};
  for (unsigned index = 0; index < kSegments; ++index) {
    const auto words = g::decode_segment(std::span<const std::uint8_t>(fixture.initial).subspan(index * 64ull, 64));
    result.segments.push_back(words);
    auto reserved = words;
    reserved[1] = words[0] + 1;
    result.reserved_segments.push_back(reserved);
    result.binary_heads.push_back(g::little_word(std::span<const std::uint8_t>(fixture.binary).subspan(index * 8ull, 8)));
  }
  return result;
}

inline std::vector<GraSuEdge> updates(const Batch& batch) {
  std::vector<GraSuEdge> result;
  for (auto value : batch.updates) {
    const auto word = static_cast<std::uint32_t>(value);
    result.push_back({static_cast<std::uint32_t>((value >> 32) & 0x7fffffff),
        decode_grasu_pma_destination(word), decode_grasu_pma_weight(word), static_cast<bool>(value >> 63)});
  }
  return result;
}

inline std::vector<std::uint8_t> expected(const Fixture& fixture) {
  auto result = fixture.initial;
  for (const auto& [segment, words] : fixture.batches.at(0).expected) {
    const auto bytes = g::encode_segments(std::span(&words, 1));
    std::copy(bytes.begin(), bytes.end(), result.begin() + segment * 64ull);
  }
  return result;
}
}  // namespace common_g
