#pragma once

#include "fixture.hpp"
#include <set>

namespace complete_g {
struct Memory {
  std::array<std::vector<Word>, 4> buffers;
  std::array<std::vector<Slots>, 4> expected;
  Memory() {
    Slots empty, canary;
    empty.fill(0x80000000u);
    canary.fill(0xd00df00du);
    for (unsigned port = 0; port < 4; ++port) {
      const unsigned size = MAX_CACHE_SEGMENT + (port & 1 ? 2 : 0);
      expected[port].assign(size, port & 1 ? canary : empty);
      buffers[port].assign(size, pack(port & 1 ? canary : empty));
    }
    for (unsigned segment = 0; segment < segments; ++segment) {
      const auto port = owner(segment);
      expected[port][segment / 2] = initial(segment);
      buffers[port][segment / 2] = pack(initial(segment));
    }
  }
  static unsigned owner(unsigned segment) {
    return (segment & 1) * 2 + unsigned(segment / 2 >= MAX_CACHE_SEGMENT);
  }
  void apply(const Fixture& fixture, const std::vector<unsigned long>& updates) {
    for (auto raw : updates) {
      unsigned long probes = 0;
      const auto segment = fixture.locate(raw, probes);
      edit(expected[owner(segment)][segment / 2], raw);
    }
  }
  void check() const {
    for (unsigned port = 0; port < buffers.size(); ++port)
      for (unsigned index = 0; index < buffers[port].size(); ++index)
        require(unpack(buffers[port][index]) == expected[port][index],
                "complete hot/cold PMA or unused DDR prefix changed");
  }
  std::set<std::pair<unsigned, unsigned>> logical(unsigned source) const {
    std::set<std::pair<unsigned, unsigned>> result;
    std::set<unsigned> destinations;
    for (unsigned segment = 0; segment < segments; ++segment)
      for (auto word : expected[owner(segment)][segment / 2]) {
        if (word >> 31) continue;
        require((word >> 19) != 0 && destinations.insert(word & 0x7ffffu).second,
                "fixture weight zero or duplicate logical destination");
        require(result.emplace(source, word).second, "duplicate fixture edge");
      }
    return result;
  }
};
}  // namespace complete_g
