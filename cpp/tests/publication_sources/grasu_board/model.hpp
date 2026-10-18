#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace original_g_board {
using Words = std::vector<std::uint32_t>;
using Longs = std::vector<std::uint64_t>;
constexpr std::uint64_t empty_edge = 1ull << 63;
constexpr std::uint32_t empty_slot = 1u << 31;
constexpr unsigned hot_segments = 131072, guard_words = 32;

inline void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}

inline std::uint64_t word(std::istream& stream, unsigned bytes) {
  std::uint64_t value = 0;
  for (unsigned i = 0; i < bytes; ++i) {
    const int byte = stream.get(); require(byte != EOF, "truncated original G packet");
    value |= std::uint64_t(static_cast<unsigned char>(byte)) << (i * 8);
  }
  return value;
}

inline Longs longs(std::istream& stream, std::size_t count) {
  Longs result(count);
  for (auto& value : result) value = word(stream, 8);
  return result;
}

struct Input {
  unsigned vertices{}, segments{};
  Longs offsets, binary, prepared, updates, final_state;
};

inline Input load(const std::filesystem::path& path) {
  require(!std::filesystem::is_symlink(path) && std::filesystem::is_regular_file(path), "regular G input required");
  const auto bytes = std::filesystem::file_size(path);
  require(bytes >= 20 && bytes <= 256ull * 1024 * 1024, "bounded original G packet required");
  std::ifstream stream(path, std::ios::binary);
  require(word(stream, 4) == 0x3142474f && word(stream, 4) == 1, "original G packet header");
  Input result; result.vertices = word(stream, 4); result.segments = word(stream, 4);
  const auto count = word(stream, 4);
  require(result.vertices > 0 && result.vertices <= 262208 && result.segments <= 524416 && count <= 524416,
          "original G packet extent");
  require(bytes == 20 + 8 * (std::uint64_t(result.vertices) + 1 + 33ull * result.segments + count),
          "original G packet byte count");
  result.offsets = longs(stream, result.vertices + 1); result.binary = longs(stream, result.segments);
  result.prepared = longs(stream, 16ull * result.segments); result.updates = longs(stream, count);
  result.final_state = longs(stream, 16ull * result.segments);
  require(stream.peek() == EOF && !stream.bad(), "original G packet trailing data");
  return result;
}

inline unsigned route(unsigned segment) { return (segment & 1) * 2 + unsigned(segment / 2 >= hot_segments); }

struct Model {
  std::array<Words, 4> initial, expected;
  std::array<Longs, 4> edges;
  Longs rows, binary;
  std::array<unsigned, 4> route_updates{};
  std::uint64_t checked_slots{};

  explicit Model(const Input& input) {
    require(input.offsets.size() == input.vertices + 1ull && input.binary.size() == input.segments &&
            input.prepared.size() == input.segments * 16ull && input.final_state.size() == input.prepared.size(),
            "original G table extent");
    require(input.offsets.front() == 0 && input.offsets.back() == input.prepared.size(), "original G row endpoints");
    require(std::is_sorted(input.offsets.begin(), input.offsets.end()), "original G row order");
    rows.reserve(input.vertices + 1);
    for (unsigned source = 0; source < input.vertices; ++source) {
      const auto begin = input.offsets[source], end = input.offsets[source + 1];
      require(begin % 16 == 0 && end % 16 == 0 && end <= input.prepared.size(), "original G row alignment");
      rows.push_back((begin << 32) | end);
      const auto first = input.binary.begin() + begin / 16, last = input.binary.begin() + end / 16;
      require(std::is_sorted(first, last) && std::adjacent_find(first, last) == last, "original G search head order");
      for (auto item = first; item != last; ++item)
        require((*item >> 32) == source && (*item & 0xffffffffu) < input.vertices, "original G search head source");
      for (auto slot = begin; slot < end; ++slot)
        for (auto value : {input.prepared[slot], input.final_state[slot]})
          require(value == empty_edge || ((value >> 32) == source &&
                  (value & 0xffffffffu) < input.vertices), "original G state edge domain");
    }
    rows.push_back(0); binary = input.binary; binary.push_back(0);
    for (unsigned buffer = 0; buffer < 4; ++buffer) {
      const auto segments = std::max(hot_segments, (input.segments + unsigned(buffer < 2)) / 2);
      initial[buffer].assign(segments * 16ull + guard_words, empty_slot);
      checked_slots += initial[buffer].size();
    }
    for (unsigned slot = 0; slot < input.prepared.size(); ++slot) {
      const unsigned segment = slot / 16, base = segment / 2 * 16 + slot % 16, half = (segment & 1) * 2;
      const auto value = input.prepared[slot] == empty_edge ? empty_slot : std::uint32_t(input.prepared[slot]);
      initial[half][base] = initial[half + 1][base] = value;
    }
    expected = initial;
    for (unsigned i = 0; i < input.updates.size(); ++i) {
      const auto encoded = input.updates[i], edge = encoded & ~empty_edge;
      const auto source = edge >> 32, target = edge & 0xffffffffu;
      require(source < input.vertices && target < input.vertices, "original G update domain");
      const auto first = input.binary.begin() + input.offsets[source] / 16;
      const auto last = input.binary.begin() + input.offsets[source + 1] / 16;
      const auto found = std::upper_bound(first, last, edge);
      require(found != first, "original G update below search head");
      const unsigned segment = (found - input.binary.begin()) - 1, buffer = route(segment), base = segment / 2 * 16;
      Words live;
      for (unsigned j = 0; j < 16; ++j) if (expected[buffer][base + j] != empty_slot) live.push_back(expected[buffer][base + j]);
      require(std::is_sorted(live.begin(), live.end()) && std::adjacent_find(live.begin(), live.end()) == live.end(),
              "original G initial segment order/uniqueness");
      const auto position = std::lower_bound(live.begin(), live.end(), target);
      if (encoded & empty_edge) {
        require(position != live.end() && *position == target, "original G absent deletion"); live.erase(position);
      } else {
        require(live.size() < 16 && (position == live.end() || *position != target), "original G invalid insertion");
        live.insert(position, target);
      }
      for (unsigned j = 0; j < 16; ++j) expected[buffer][base + j] = j < live.size() ? live[j] : empty_slot;
      edges[i % 4].push_back(encoded); ++route_updates[buffer];
    }
    for (unsigned slot = 0; slot < input.prepared.size(); ++slot) {
      const unsigned segment = slot / 16, value = expected[route(segment)][segment / 2 * 16 + slot % 16];
      require(value == (input.final_state[slot] == empty_edge ? empty_slot : std::uint32_t(input.final_state[slot])),
              "original G independent final-state disagreement");
    }
  }
};
}  // namespace original_g_board
