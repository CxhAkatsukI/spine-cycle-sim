#pragma once

#include "../candidate.hpp"

namespace sharded_g_test {
inline constexpr std::array<std::size_t, 4> kMetadataChannels{3, 9, 15, 20};

inline std::vector<GraSuReGraphBufferRegion> append_metadata_replicas(
    GraSuReGraphRuntimePlan &plan, std::size_t shard, const std::string &name) {
  require(name == "row" || name == "binary", "unknown metadata table");
  const auto source = find_grasu_regraph_runtime_region(plan, shard, name);
  for (const auto &region : plan.regions)
    require(region.shard != shard || !region.name.starts_with(name + "-cu"),
            "metadata table already replicated");
  const auto maximum = *std::max_element(plan.channel_load_bytes.begin(), plan.channel_load_bytes.end());
  require(maximum <= plan.channel_capacity_bytes, "invalid existing bank span");
  const auto padding = (4096 - maximum % 4096) % 4096;
  require(padding <= plan.channel_capacity_bytes - maximum, "metadata alignment exceeds capacity");
  const auto base = maximum + padding;
  require(source.allocated_bytes <= plan.channel_capacity_bytes - base,
          "metadata replicas exceed physical bank capacity");
  std::vector<GraSuReGraphBufferRegion> copies;
  for (std::size_t cu = 0; cu < kMetadataChannels.size(); ++cu) {
    auto copy = source;
    copy.name = name + "-cu" + std::to_string(cu);
    copy.channel = kMetadataChannels[cu];
    copy.channel_offset_bytes = base;
    require(copy.channel < plan.channel_load_bytes.size() && copy.channel >= copy.channel_first &&
                copy.channel < copy.channel_last, "metadata copy escapes connected bank range");
    copies.push_back(copy);
  }
  // Validate the complete addition before mutating the plan; all four CUs use
  // a common base, so per-bank gaps are charged in the span ledger.
  for (const auto &copy : copies) {
    plan.regions.push_back(copy);
    plan.channel_load_bytes[copy.channel] = base + copy.allocated_bytes;
    plan.total_allocated_bytes += copy.allocated_bytes;
  }
  return copies;
}
} // namespace sharded_g_test
