#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace pma_adapter_test {

struct Data {
  unsigned vertices{11}, slots{96}, cache_segments{1}, destination{65536}, destination_vertices{256};
  std::vector<std::uint32_t> rows;
  std::array<std::vector<std::uint32_t>, 4> buffers;
  std::vector<std::uint32_t> expected_global;

  explicit Data(unsigned cache = 1) : cache_segments(cache) {
    // Explicit independent route tables exercise both sides and both parities.
    const std::array<unsigned, 6> routes = cache == 0 ? std::array<unsigned, 6>{1, 3, 1, 3, 1, 3}
        : cache == 1 ? std::array<unsigned, 6>{0, 2, 1, 3, 1, 3}
        : std::array<unsigned, 6>{0, 2, 0, 2, 0, 2};
    for (auto& buffer : buffers) buffer.assign(48, 0x12345678u);
    unsigned begin = 0;
    for (unsigned source = 0; source < vertices; ++source) {
      const unsigned count = source == 1 ? 32 : source == 3 ? 16 : source == 6 ? 48 : 0;
      rows.push_back(begin + count); rows.push_back(begin);
      for (unsigned slot = begin; slot < begin + count; ++slot) {
        const unsigned segment = slot / 16;
        const auto raw = slot % 7 == 0 ? 0x80000000u : slot == 18 ? 511u : (slot * 3) % 256;
        buffers[routes[segment]][segment / 2 * 16 + slot % 16] = raw;
        const bool dummy = raw >> 31 || (raw & 0x7ffffu) >= destination_vertices;
        expected_global.push_back(source | (dummy ? 0x80000000u : 0));
        expected_global.push_back((destination + (raw & 0x7ffffu)) | (dummy ? 0x80000000u : 0));
      }
      begin += count;
    }
  }
};

}  // namespace pma_adapter_test
