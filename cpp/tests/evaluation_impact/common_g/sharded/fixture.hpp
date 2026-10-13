#pragma once

#include "spine_sim/grasu_regraph.hpp"

#include <algorithm>
#include <fstream>
#include <stdexcept>
#include <string>

namespace sharded_g_test {
using namespace spine::sim;
constexpr std::size_t kCache = 131072;
constexpr std::uint64_t kLimit = 20000000;

inline void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

inline void put(std::vector<std::uint8_t> &bytes, std::size_t offset, std::uint64_t word,
                std::size_t width) {
  require(offset + width <= bytes.size(), "fixture byte write out of bounds");
  for (std::size_t b = 0; b < width; ++b) bytes[offset + b] = word >> (8 * b);
}

inline std::vector<std::uint8_t> blank(std::size_t bytes) {
  require(bytes % 4 == 0, "PMA byte length is not word aligned");
  std::vector<std::uint8_t> result(bytes);
  for (std::size_t b = 3; b < bytes; b += 4) result[b] = 0x80;
  return result;
}

inline void segment_bytes(std::vector<std::uint8_t> &bytes, std::size_t local,
                          const std::array<std::uint32_t, 16> &segment) {
  for (std::size_t slot = 0; slot < segment.size(); ++slot)
    put(bytes, local * 64 + slot * 4, segment[slot], 4);
}

struct Fixture {
  std::size_t vertices{}, logical_updates{}, live_edges{};
  GraSuPartitionedPmaLayout initial, expected;
  std::vector<GraSuEdge> updates;
  std::vector<std::vector<GraSuEdge>> by_shard;

  explicit Fixture(const std::string &name) {
    require(name == "one-shard-64" || name == "three-shard-4096" ||
                name == "five-shard-mixed-512" || name == "empty", "unknown fixture");
    const bool mixed = name == "five-shard-mixed-512";
    vertices = mixed ? 262177 : 131105;
    const auto shards = (vertices + 65535) / 65536;
    logical_updates = name == "empty" ? 0 : mixed ? 512 : name == "one-shard-64" ? 64 : 4096;
    const auto edge_for = [&](std::size_t source, std::size_t shard) {
      const auto base = shard * 65536;
      return GraSuEdge{static_cast<std::uint32_t>(source),
          static_cast<std::uint32_t>(base + (source * 17 + shard) % std::min<std::size_t>(65536, vertices - base)), 3};
    };
    std::vector<GraSuEdge> before;
    before.reserve(vertices * shards);
    for (std::size_t shard = 0; shard < shards; ++shard)
      for (std::size_t source = 0; source < vertices; ++source) before.push_back(edge_for(source, shard));
    live_edges = before.size();
    for (std::size_t i = 0; i < logical_updates; ++i) {
      const bool cold = mixed && i >= 402;
      const auto source = cold ? 262144 + (i - 402) % 33 : i;
      const auto shard = name == "one-shard-64" ? 0 : cold ? (i - 402) / 33 : i % shards;
      auto edge = edge_for(source, shard);
      edge.delete_op = true;
      updates.push_back(edge);
      edge.delete_op = false;
      edge.weight = 1;
      updates.push_back(edge);
    }
    initial = GraSuPartitionedPmaLayout::build(vertices, 65536, before, updates,
                                               GraSuPmaWordAbi::kWeightedFullWord);
    // The candidate explicitly requires a complete two-half cache footprint.
    // Empty tail reservations belong to the last (never updated here) row.
    for (auto &part : initial.partitions) {
      const auto extent = std::max(vertices, 2 * kCache);
      std::array<std::uint32_t, 16> empty;
      empty.fill(kGraSuPmaEmpty);
      part.segments.resize(extent, empty);
      part.reserved_segments.resize(extent, empty);
      part.binary_heads.resize(extent, (static_cast<std::uint64_t>(vertices - 1) << 32) | kGraSuPmaEmpty);
      part.row_slot_bounds.back().second = extent * 16;
    }
    expected = initial;
    by_shard.resize(shards);
    for (const auto &update : updates) {
      const auto shard = initial.partition_for_destination(update.destination);
      by_shard[shard].push_back(update);
      auto &part = expected.partitions[shard];
      auto &segment = part.segments.at(part.segment_for(update));
      const auto word = encode_grasu_pma_edge(part.local_destination(update.destination), update.weight);
      const auto position = std::lower_bound(segment.begin(), segment.end(), word);
      if (update.delete_op) {
        require(position != segment.end() && *position == word, "oracle delete is not live");
        std::move(position + 1, segment.end(), position);
        segment.back() = kGraSuPmaEmpty;
      } else {
        require(position != segment.end() && *position != word && segment.back() == kGraSuPmaEmpty,
                "oracle insert has no distinct free slot");
        std::move_backward(position, segment.end() - 1, segment.end());
        *position = word;
      }
    }
    for (const auto &part : initial.partitions) {
      require(part.segments.size() == std::max(vertices, 2 * kCache), "fixture cache footprint changed");
      for (std::size_t source = 0; source < vertices; ++source)
        require(part.row_slot_bounds[source] == std::pair{static_cast<std::uint32_t>(source * 16),
                    static_cast<std::uint32_t>((source + 1 == vertices ? part.segments.size() : source + 1) * 16)},
                "fixture row geometry changed");
    }
  }

  std::size_t touched() const {
    return std::count_if(by_shard.begin(), by_shard.end(), [](const auto &u) { return !u.empty(); });
  }
};

struct Observation {
  std::uint64_t cycles{}, reads{}, writes{}, cache{}, ddr{}, rows{}, probes{};
  std::uint64_t pma_reads{}, pma_writes{};
};

inline GraSuNativeConfig candidate_config() {
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.memory_channels = 4;
  config.compact_parallel_search = true;
  config.compact_finite_search = true;
  config.compact_search_contexts = 64;
  config.compact_metadata_credits = 32;
  config.compact_cached_hot = true;
  return config;
}

inline void save_state(const std::string &path, const GraSuPartitionedPmaLayout &state) {
  std::ofstream stream(path, std::ios::binary);
  for (const auto &part : state.partitions) {
    std::vector<std::uint8_t> bytes(part.segments.size() * 64);
    for (std::size_t s = 0; s < part.segments.size(); ++s) segment_bytes(bytes, s, part.segments[s]);
    stream.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
  }
  require(stream.good(), "failed to save complete canonical PMA state");
}
} // namespace sharded_g_test
