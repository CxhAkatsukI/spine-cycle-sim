#pragma once

#include "fixture.hpp"

namespace handoff_test {
inline GraSuNativeConfig shard_config(const GraSuReGraphRuntimePlan &plan, std::size_t shard,
                                      std::size_t cache) {
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = cache;
  config.explicit_runtime_regions = true;
  const auto row = find_grasu_regraph_runtime_region(plan, shard, "row");
  const auto binary = find_grasu_regraph_runtime_region(plan, shard, "binary");
  config.row_channels.fill(row.channel);
  config.row_offset_base = row.channel_offset_bytes;
  config.binary_channels.fill(binary.channel);
  config.binary_base = binary.channel_offset_bytes;
  for (std::size_t bank = 0; bank < 4; ++bank) {
    const auto pma = find_grasu_regraph_runtime_region(plan, shard, "pma" + std::to_string(bank));
    config.pma_channels[bank] = pma.channel;
    config.pma_bases[bank] = pma.channel_offset_bytes;
  }
  return config;
}

// Test-only inspection, never a transfer or a device-time replacement.
inline std::vector<std::uint8_t> graph_bytes(MemoryBackend &backend,
                                            const GraSuPartitionedPmaLayout &layout,
                                            const GraSuReGraphRuntimePlan &plan) {
  std::vector<std::uint8_t> result;
  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard) {
    const auto config = shard_config(plan, shard, plan.max_cache_segments);
    const auto rows = backend.inspect_payload(config.row_channels[0], config.row_offset_base,
                                               (layout.vertices + 1) * 8);
    result.insert(result.end(), rows.begin(), rows.end());
    for (std::size_t segment = 0; segment < layout.partitions[shard].segments.size(); ++segment) {
      const auto local = segment / 2;
      const auto bank = segment % 2 * 2 + (local < plan.max_cache_segments ? 0 : 1);
      const auto bytes = backend.inspect_payload(config.pma_channels[bank], config.pma_bases[bank] + local * 64, 64);
      result.insert(result.end(), bytes.begin(), bytes.end());
    }
  }
  return result;
}

inline bool same_placement(const GraSuReGraphRuntimePlan &a, const GraSuReGraphRuntimePlan &b) {
  if (a.regions.size() != b.regions.size() || a.total_allocated_bytes != b.total_allocated_bytes) return false;
  for (std::size_t index = 0; index < a.regions.size(); ++index) {
    const auto &x = a.regions[index], &y = b.regions[index];
    if (std::tie(x.shard, x.name, x.channel, x.channel_offset_bytes, x.logical_bytes, x.allocated_bytes) !=
        std::tie(y.shard, y.name, y.channel, y.channel_offset_bytes, y.logical_bytes, y.allocated_bytes)) return false;
  }
  return true;
}
} // namespace handoff_test
