#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

#include "spine_sim/regraph_pma_adapter.hpp"

namespace routed_adapter_test {
using namespace spine::sim;

inline std::vector<std::uint8_t> bytes(const std::vector<std::uint32_t> &words) {
  std::vector<std::uint8_t> result;
  for (auto word : words)
    for (unsigned shift = 0; shift < 32; shift += 8)
      result.push_back(static_cast<std::uint8_t>(word >> shift));
  return result;
}

struct Data {
  ReGraphPmaPartition partition;
  std::vector<std::uint32_t> rows;
  std::array<std::vector<std::uint32_t>, 4> pma;
  std::vector<ReGraphPmaPacket> expected;
  std::size_t last_source{};

  Data(std::size_t vertices, bool at_end, bool empty, ReGraphPmaFormat format,
       std::size_t cache = 1) {
    partition.vertices = vertices;
    partition.cache_segments_per_half = cache;
    partition.destination_base = 65536;
    partition.destination_vertices = 128;
    partition.row_channel = 4;
    partition.pma_base = {4096, 8192, 12288, 16384};
    partition.pma_channel = {0, 1, 2, 3};
    rows.resize(std::max<std::size_t>(16, (vertices + 7) / 8 * 16), 0);
    for (auto &words : pma) words.resize(128, 0xdeadbeefU);
    if (vertices && !empty) last_source = at_end ? vertices - 1 : std::min<std::size_t>(2, vertices - 1);
    std::size_t cursor = 0;
    for (std::size_t source = 0; source < vertices; ++source) {
      const auto count = !empty && (source == 0 || source == last_source) ? 48U : 0U;
      rows[source * 2] = cursor + count;
      rows[source * 2 + 1] = cursor;
      for (std::size_t local_slot = 0; local_slot < count; local_slot += 8) {
        ReGraphPmaPacket packet;
        for (std::size_t lane = 0; lane < 8; ++lane) {
          const auto slot = cursor + local_slot + lane;
          const auto segment = slot / 16;
          const auto bank = (segment % 2) * 2 + (segment / 2 < cache ? 0 : 1);
          const auto destination = slot % 11 == 0 ? 256U : static_cast<unsigned>((slot * 3) % 128);
          const auto weight = static_cast<unsigned>((slot * 17) % 4096);
          const auto deleted = slot % 7 == 0 ? 0x80000000U : 0U;
          pma[bank][segment / 2 * 16 + slot % 16] = destination | (weight << 19) | deleted;
          const auto dummy = deleted || destination >= 128 ? 0x80000000U : 0U;
          packet.sources[lane] = static_cast<std::uint32_t>(source) | dummy;
          packet.destinations[lane] = (format == ReGraphPmaFormat::kWeighted ? destination | (weight << 19)
              : format == ReGraphPmaFormat::kDestination ? 65536U + destination
              : destination | (1U << 19)) | dummy;
        }
        expected.push_back(packet);
      }
      cursor += count;
    }
    partition.slots = cursor;
    if (!expected.empty()) expected.back().last = true;
  }
};
} // namespace routed_adapter_test
