#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace complete_g {
using Word = ap_uint<512>;
using Raw = search_pipeline::Raw;
using Packet = search_pipeline::Packet;
using Slots = std::array<unsigned, 16>;
constexpr unsigned vertices = 524288;
constexpr unsigned segments = 2 * MAX_CACHE_SEGMENT + 4;
constexpr std::array<unsigned, 3> counts{0, 257, 129};
constexpr std::array<unsigned, 10> active_segments{
    256, 257, 1024, 1025, 2 * MAX_CACHE_SEGMENT - 2, 2 * MAX_CACHE_SEGMENT - 1,
    2 * MAX_CACHE_SEGMENT, 2 * MAX_CACHE_SEGMENT + 1,
    2 * MAX_CACHE_SEGMENT + 2, 2 * MAX_CACHE_SEGMENT + 3};

inline void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
inline Word pack(const Slots& slots) {
  Word result = 0;
  for (unsigned i = 0; i < slots.size(); ++i)
    result.range(i * 32 + 31, i * 32) = slots[i];
  return result;
}
inline Slots unpack(const Word& word) {
  Slots result;
  for (unsigned i = 0; i < result.size(); ++i)
    result[i] = word.range(i * 32 + 31, i * 32).to_uint();
  return result;
}
inline unsigned base_key(unsigned ordinal) {
  return active_segments.at(ordinal) * 4096 + ordinal * 16;
}
inline Slots initial(unsigned segment) {
  Slots result;
  result.fill(0x80000000u);
  const auto found = std::find(active_segments.begin(), active_segments.end(), segment);
  if (found != active_segments.end()) {
    const unsigned base = base_key(found - active_segments.begin());
    for (unsigned i = 0; i < 4; ++i) result[i] = base + i + 1;
  }
  return result;
}
inline void edit(Slots& slots, unsigned long raw) {
  const unsigned key = raw;
  std::vector<unsigned> live;
  for (auto word : slots) if (!(word >> 31)) live.push_back(word);
  const auto found = std::lower_bound(live.begin(), live.end(), key);
  if (raw >> 63) {
    require(found != live.end() && *found == key, "oracle deletion absent");
    live.erase(found);
  } else {
    require(live.size() < 16 && (found == live.end() || *found != key),
            "oracle insertion duplicate/full");
    live.insert(found, key);
  }
  slots.fill(0x80000000u);
  std::copy(live.begin(), live.end(), slots.begin());
}

struct Fixture {
  std::vector<Raw> binary = std::vector<Raw>(segments);
  std::vector<Raw> rows = std::vector<Raw>(vertices);
  unsigned source{};
  void metadata(unsigned generation) {
    source = generation ? 3 : 0;
    for (unsigned segment = 0; segment < segments; ++segment)
      binary[segment] = (static_cast<unsigned long>(source) << 32) | segment * 4096;
    for (unsigned vertex = 0; vertex < vertices; ++vertex) {
      const unsigned begin = vertex <= source ? 0 : segments * 16;
      const unsigned end = vertex < source ? 0 : segments * 16;
      rows[vertex] = (static_cast<unsigned long>(begin) << 32) | end;
    }
  }
  std::vector<unsigned long> batch(unsigned batch_index) const {
    unsigned preceding = 0;
    for (unsigned i = 0; i < batch_index; ++i) preceding += counts[i];
    std::vector<unsigned long> result;
    for (unsigned i = preceding; i < preceding + counts.at(batch_index); ++i) {
      const auto key = base_key(i % active_segments.size()) + 8;
      const bool erase = (i / active_segments.size()) & 1;
      result.push_back((static_cast<unsigned long>(erase) << 63) |
                       (static_cast<unsigned long>(source) << 32) | key);
    }
    return result;
  }
  unsigned locate(unsigned long raw, unsigned long& probes) const {
    const auto key = raw & ~(1ul << 63);
    const auto row = rows.at(key >> 32).to_uint64();
    const unsigned begin = static_cast<unsigned>(row >> 32) / 16;
    const unsigned end = static_cast<unsigned>(row) / 16;
    unsigned lower = begin, upper = end;
    for (unsigned mid = (lower + upper) / 2; lower != mid; mid = (lower + upper) / 2) {
      ++probes;
      if (binary.at(mid).to_uint64() <= key) lower = mid;
      else upper = mid;
    }
    // A second, standard-library oracle checks the scalar search as well.
    const auto found = std::upper_bound(binary.begin() + begin, binary.begin() + end,
        key, [](unsigned long value, const Raw& node) { return value < node.to_uint64(); });
    require(found != binary.begin() + begin && unsigned(found - binary.begin() - 1) == lower,
            "scalar search disagrees with upper_bound");
    return lower;
  }
};
}  // namespace complete_g
