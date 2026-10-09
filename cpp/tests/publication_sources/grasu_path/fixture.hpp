#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace grasu_control {
constexpr unsigned hot_segments = 131072;
constexpr unsigned half_segments = hot_segments + 32;
constexpr unsigned segments = half_segments * 2;
constexpr std::uint32_t empty_slot = 0x80000000u;
using Slots = std::array<std::uint32_t, 16>;
struct Update { unsigned segment, delta; bool deletion; };

inline unsigned source(unsigned segment) { return segment >= hot_segments * 2; }
inline unsigned local_segment(unsigned segment) { return source(segment) ? segment - hot_segments * 2 : segment; }
inline unsigned base(unsigned segment) { return local_segment(segment) * 128; }
inline std::uint64_t edge(Update item) {
  return (std::uint64_t(item.deletion) << 63) | (std::uint64_t(source(item.segment)) << 32) | (base(item.segment) + item.delta);
}
inline Slots initial(unsigned segment) {
  Slots slots; slots.fill(empty_slot);
  slots[0] = base(segment) + 10; slots[1] = base(segment) + 40; slots[2] = base(segment) + 70;
  return slots;
}
inline std::vector<unsigned> targets() {
  std::vector<unsigned> result;
  for (unsigned row : {0u, hot_segments - 16, hot_segments, hot_segments + 16})
    for (unsigned bank = 0; bank < 16; ++bank)
      for (unsigned half = 0; half < 2; ++half) result.push_back((row + bank) * 2 + half);
  return result;
}
inline std::vector<std::vector<Update>> fixture(unsigned id) {
  require(id < 8, "unknown G fixture");
  const auto all = targets();
  std::vector<std::vector<Update>> batches(id == 7 ? 3 : 1);
  if (id < 4) {
    const unsigned count[] = {0, 1, 3, 65};
    for (unsigned i = 0; i < count[id]; ++i) batches[0].push_back({all[i], 20, false});
  } else if (id == 4) {
    for (unsigned delta : {20u, 60u}) for (auto segment : all) batches[0].push_back({segment, delta, false});
    batches[0].push_back({all.front(), 40, true});
  } else {
    for (auto segment : all) {
      if (id == 5 && segment / 2 >= hot_segments || id == 6 && segment / 2 < hot_segments) continue;
      for (auto item : {Update{segment, 20, false}, Update{segment, 60, false}, Update{segment, 40, true}}) batches[0].push_back(item);
      if (id == 7) {
        batches[1].push_back({segment, 20, true}); batches[1].push_back({segment, 50, false});
        batches[2].push_back({segment, 60, true}); batches[2].push_back({segment, 60, false});
      }
    }
  }
  return batches;
}
inline unsigned route(unsigned segment) { return (segment & 1) * 2 + unsigned(segment / 2 >= hot_segments); }
inline ap_uint<512> packed(const Slots& slots) {
  ap_uint<512> result = 0;
  for (unsigned i = 0; i < 16; ++i) result.range(i * 32 + 31, i * 32) = slots[i];
  return result;
}
inline void word(std::ostream& output, std::uint32_t value) {
  for (unsigned byte = 0; byte < 4; ++byte) output.put(static_cast<char>(value >> (8 * byte)));
}
}  // namespace grasu_control
