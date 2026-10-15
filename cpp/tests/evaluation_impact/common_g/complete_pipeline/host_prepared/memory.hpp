#pragma once

#include "input.hpp"

namespace prepared_g {
struct PreparedFixture {
  std::vector<Raw> binary, rows;
  explicit PreparedFixture(const host::WeightedPmaPackedShardBuffers& packed) {
    for (auto value : packed.binary_heads) binary.emplace_back(value);
    for (auto value : packed.row_bounds) rows.emplace_back(value);
  }
  unsigned locate(unsigned long raw, unsigned long& probes) const {
    const auto key = raw & ~(1ul << 63);
    const auto row = rows.at(key >> 32).to_uint64();
    const unsigned begin = static_cast<unsigned>(row >> 32) / 16;
    const unsigned end = static_cast<unsigned>(row) / 16;
    require(begin < end && end <= binary.size(), "host row does not contain updated source");
    unsigned lower = begin, upper = end;
    while (lower != (lower + upper) / 2) {
      ++probes;
      const auto mid = (lower + upper) / 2;
      if (binary.at(mid).to_uint64() <= key) lower = mid;
      else upper = mid;
    }
    const auto found = std::upper_bound(binary.begin() + begin, binary.begin() + end, key,
        [](unsigned long value, const Raw& node) { return value < node.to_uint64(); });
    require(found != binary.begin() + begin && unsigned(found - binary.begin() - 1) == lower,
            "host search and standard-library oracle disagree");
    return lower;
  }
};

struct PreparedMemory {
  std::array<std::vector<Word>, 4> buffers;
  std::array<std::vector<Slots>, 4> expected;
  explicit PreparedMemory(const host::WeightedPmaPackedShardBuffers& packed) {
    for (unsigned port = 0; port < 4; ++port) {
      const auto& words = packed.pma_words[port];
      require(words.size() % 16 == 0, "host segment alignment");
      for (unsigned begin = 0; begin < words.size(); begin += 16) {
        Slots slots;
        std::copy_n(words.begin() + begin, 16, slots.begin());
        expected[port].push_back(slots);
        buffers[port].push_back(pack(slots));
      }
    }
    require(buffers[0].size() == MAX_CACHE_SEGMENT && buffers[2].size() == MAX_CACHE_SEGMENT,
            "host hot-half capacity changed");
  }
  static unsigned owner(unsigned segment) { return Memory::owner(segment); }
  void apply(const PreparedFixture& fixture, const std::vector<unsigned long>& updates) {
    for (auto raw : updates) {
      unsigned long ignored = 0;
      const auto segment = fixture.locate(raw, ignored);
      edit(expected[owner(segment)].at(segment / 2), raw);
    }
  }
  void check() const {
    for (unsigned port = 0; port < 4; ++port)
      for (unsigned segment = 0; segment < buffers[port].size(); ++segment)
        require(unpack(buffers[port][segment]) == expected[port][segment],
                "host-prepared complete PMA/unused padding state mismatch");
  }
};
}  // namespace prepared_g
