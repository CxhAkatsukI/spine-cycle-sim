#pragma once

#include "../candidate.hpp"
#include "../real_fixture.hpp"
#include "replicas.hpp"

namespace sharded_g_test {
struct MetadataLayout {
  GraSuReGraphRuntimePlan plan;
  GraSuNativeConfig config;
  std::vector<Snapshot> snapshots;
  std::size_t extra_metadata_bytes{};
  std::size_t row_bytes{}, binary_bytes{};

  MetadataLayout(MemoryBackend &backend, const RealFixture &f, const std::string &arm) {
    require(f.by_shard.size() == 1, "metadata layout diagnostic requires one shard");
    plan = build_grasu_regraph_runtime_plan(f.initial, {f.updates.size()}, kCache);
    row_bytes = find_grasu_regraph_runtime_region(plan, 0, "row").allocated_bytes;
    binary_bytes = find_grasu_regraph_runtime_region(plan, 0, "binary").allocated_bytes;
    config = runtime_config(plan, 0);
    config.initiator_base = 10000;
    config.initialize_degree_payload = false;
    for (std::size_t cu = 0; cu < 4; ++cu) {
      const auto region = find_grasu_regraph_runtime_region(plan, 0, "update" + std::to_string(cu));
      config.update_channels[cu] = region.channel;
      config.update_bases[cu] = region.channel_offset_bytes;
    }
    config.pma_base = config.pma_bases[0];
    for (const auto &region : plan.regions) {
      if (region.name.starts_with("update")) continue;
      backend.initialize_payload(region.channel, region.channel_offset_bytes,
          region.name.starts_with("pma") ? blank(region.allocated_bytes)
                                        : std::vector<std::uint8_t>(region.allocated_bytes, 0xa5));
    }
    initialize_grasu_pma_layout_payloads(backend, f.initial.partitions[0], config);
    if (arm == "runtime-row-copies" || arm == "runtime-both-copies") replicate(backend, "row");
    if (arm == "runtime-binary-copies" || arm == "runtime-both-copies") replicate(backend, "binary");
    for (const auto &region : plan.regions) {
      if (!region.name.starts_with("update"))
        snapshots.push_back({region, backend.inspect_payload(region.channel, region.channel_offset_bytes,
                                                             region.allocated_bytes)});
    }
  }

  void replicate(MemoryBackend &backend, const std::string &name) {
    const auto source = find_grasu_regraph_runtime_region(plan, 0, name);
    const auto bytes = backend.inspect_payload(source.channel, source.channel_offset_bytes, source.allocated_bytes);
    const auto copies = append_metadata_replicas(plan, 0, name);
    for (const auto &copy : copies) {
      extra_metadata_bytes += copy.allocated_bytes;
      backend.initialize_payload(copy.channel, copy.channel_offset_bytes, bytes);
    }
    if (name == "row") { config.row_channels = kMetadataChannels; config.row_offset_base = copies[0].channel_offset_bytes; }
    else { config.binary_channels = kMetadataChannels; config.binary_base = copies[0].channel_offset_bytes; }
  }

  void verify(MemoryBackend &backend, const RealFixture &f) {
    for (auto &snapshot : snapshots) {
      const auto &region = snapshot.region;
      if (region.name.starts_with("pma")) {
        const auto bank = std::stoul(region.name.substr(3));
        const auto &part = f.expected.partitions[0];
        for (std::size_t s = 0; s < part.segments.size(); ++s)
          if (s % 2 * 2 + (s / 2 >= kCache) == bank) segment_bytes(snapshot.bytes, s / 2, part.segments[s]);
      }
      require(backend.inspect_payload(region.channel, region.channel_offset_bytes, region.allocated_bytes) == snapshot.bytes,
              "metadata diagnostic full payload, replicas, untouched copies or padding differs");
    }
  }
};
} // namespace sharded_g_test
