#pragma once

#include "fixture.hpp"
#include "../replicas.hpp"

namespace sharded_g_test::lifecycle {
class Residency {
public:
  GraSuReGraphRuntimePlan plan;
  std::size_t extra_bytes{}, metadata_upload_bytes{};

  template <class Input>
  Residency(MemoryBackend &backend, const Input &fixture, bool replicated)
      : plan(build_grasu_regraph_runtime_plan(fixture.batches[0].initial, fixture.maximum_updates, kCache)) {
    const auto original = plan.regions;
    for (const auto &region : original) {
      if (region.name.starts_with("update")) continue;
      backend.initialize_payload(region.channel, region.channel_offset_bytes,
          region.name.starts_with("pma") ? blank(region.allocated_bytes)
                                        : std::vector<std::uint8_t>(region.allocated_bytes, 0xa5));
      if (region.name == "row" || region.name == "binary") metadata_upload_bytes += region.logical_bytes;
    }
    for (std::size_t shard = 0; shard < plan.shards.size(); ++shard)
      initialize_grasu_pma_layout_payloads(backend, fixture.batches[0].initial.partitions[shard], config(shard));
    if (replicated) {
      for (std::size_t shard = 0; shard < plan.shards.size(); ++shard) {
        for (const std::string name : {"row", "binary"}) {
          const auto source = find_grasu_regraph_runtime_region(plan, shard, name);
          const auto bytes = backend.inspect_payload(source.channel, source.channel_offset_bytes, source.allocated_bytes);
          for (const auto &copy : append_metadata_replicas(plan, shard, name)) {
            backend.initialize_payload(copy.channel, copy.channel_offset_bytes, bytes);
            extra_bytes += copy.allocated_bytes;
            metadata_upload_bytes += copy.logical_bytes;
          }
        }
      }
    }
    check_intervals();
    for (const auto &region : plan.regions) {
      if (!region.name.starts_with("update"))
        snapshots_.push_back({region, backend.inspect_payload(region.channel, region.channel_offset_bytes,
                                                              region.allocated_bytes)});
    }
  }

  GraSuNativeConfig config(std::size_t shard) const {
    auto result = runtime_config(plan, shard);
    result.initiator_base = 10000 + shard * 32;
    result.initialize_degree_payload = false;
    for (std::size_t cu = 0; cu < 4; ++cu) {
      const auto update = find_grasu_regraph_runtime_region(plan, shard, "update" + std::to_string(cu));
      result.update_channels[cu] = update.channel;
      result.update_bases[cu] = update.channel_offset_bytes;
    }
    for (const auto &region : plan.regions) {
      if (region.shard != shard || (region.name != "row-cu0" && region.name != "binary-cu0")) continue;
      if (region.name == "row-cu0") {
        result.row_channels = kMetadataChannels;
        result.row_offset_base = region.channel_offset_bytes;
      } else {
        result.binary_channels = kMetadataChannels;
        result.binary_base = region.channel_offset_bytes;
      }
    }
    result.pma_base = result.pma_bases[0];
    return result;
  }

  void verify(MemoryBackend &backend, const GraSuPartitionedPmaLayout &expected) {
    for (auto &snapshot : snapshots_) {
      const auto &region = snapshot.region;
      if (region.name.starts_with("pma")) {
        const auto bank = std::stoul(region.name.substr(3));
        const auto &part = expected.partitions[region.shard];
        for (std::size_t segment = 0; segment < part.segments.size(); ++segment)
          if (segment % 2 * 2 + (segment / 2 >= kCache) == bank)
            segment_bytes(snapshot.bytes, segment / 2, part.segments[segment]);
      }
      require(backend.inspect_payload(region.channel, region.channel_offset_bytes, region.allocated_bytes) == snapshot.bytes,
              "resident batch changed full PMA, untouched data, metadata, copy or padding");
    }
  }

private:
  std::vector<Snapshot> snapshots_;

  void check_intervals() const {
    std::vector<std::vector<std::pair<std::size_t, std::size_t>>> intervals(23);
    std::size_t total = 0;
    for (const auto &region : plan.regions) {
      require(region.channel < 23 && region.channel >= region.channel_first && region.channel < region.channel_last &&
                  region.channel_offset_bytes % 4096 == 0 && region.allocated_bytes % 4096 == 0 &&
                  region.channel_offset_bytes <= plan.channel_capacity_bytes &&
                  region.allocated_bytes <= plan.channel_capacity_bytes - region.channel_offset_bytes,
              "resident region exceeds capacity, alignment or connectivity");
      intervals[region.channel].emplace_back(region.channel_offset_bytes,
                                           region.channel_offset_bytes + region.allocated_bytes);
      total += region.allocated_bytes;
    }
    require(total == plan.total_allocated_bytes, "resident allocated-byte ledger differs");
    for (std::size_t bank = 0; bank < intervals.size(); ++bank) {
      auto &items = intervals[bank];
      std::sort(items.begin(), items.end());
      std::size_t end = 0;
      for (const auto &item : items) {
        require(item.first >= end && item.second > item.first, "resident regions overlap");
        end = item.second;
      }
      require(end == plan.channel_load_bytes[bank], "resident channel-span ledger differs");
    }
  }
};
} // namespace sharded_g_test::lifecycle
