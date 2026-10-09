#include "spine_sim/grasu_regraph.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::array<std::pair<std::size_t, std::size_t>, 4>
    kU55cLaneChannelRanges{{{0, 6}, {6, 12}, {12, 18}, {18, 23}}};

std::size_t align_runtime_bytes(std::size_t value) {
  constexpr std::size_t alignment = kGraSuReGraphRuntimeAlignmentBytes;
  if (value > std::numeric_limits<std::size_t>::max() - (alignment - 1)) {
    throw std::overflow_error("GraSU-ReGraph runtime region size overflow");
  }
  return (value + alignment - 1) & ~(alignment - 1);
}

} // namespace

GraSuReGraphRuntimePlan build_grasu_regraph_runtime_plan(
    const GraSuPartitionedPmaLayout &layout,
    const std::vector<std::size_t> &physical_updates_per_shard,
    std::size_t max_cache_segments, std::size_t channels,
    std::size_t channel_capacity_bytes) {
  if (layout.vertices == 0 || layout.partitions.empty() ||
      physical_updates_per_shard.size() != layout.partitions.size() ||
      max_cache_segments == 0 || channels != kGraSuReGraphU55cGraphChannels ||
      channel_capacity_bytes == 0) {
    throw std::invalid_argument("invalid GraSU-ReGraph runtime geometry");
  }

  GraSuReGraphRuntimePlan result;
  result.max_cache_segments = max_cache_segments;
  result.channel_capacity_bytes = channel_capacity_bytes;
  result.channel_load_bytes.assign(channels, 0);
  result.shards.reserve(layout.partitions.size());

  const auto add_region = [&](std::size_t shard, std::string name,
                              std::size_t logical_bytes) {
    std::size_t channel_first = 0;
    std::size_t channel_last = channels;
    if (name.rfind("update", 0) == 0 || name.rfind("pma", 0) == 0) {
      const char lane_character = name.back();
      if (lane_character < '0' || lane_character > '3') {
        throw std::logic_error("GraSU-ReGraph lane role is malformed");
      }
      const std::size_t lane = static_cast<std::size_t>(lane_character - '0');
      channel_first = kU55cLaneChannelRanges[lane].first;
      channel_last = kU55cLaneChannelRanges[lane].second;
    }
    result.regions.push_back({
        .shard = shard,
        .name = std::move(name),
        .logical_bytes = logical_bytes,
        .allocated_bytes =
            align_runtime_bytes(std::max<std::size_t>(logical_bytes, 1)),
        .channel_first = channel_first,
        .channel_last = channel_last,
    });
  };

  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard) {
    const GraSuPmaLayout &partition = layout.partitions[shard];
    const std::size_t segments = partition.segments.size();
    if (partition.row_slot_bounds.size() != layout.vertices ||
        partition.binary_heads.size() != segments) {
      throw std::invalid_argument("invalid GraSU-ReGraph PMA shard buffers");
    }
    const std::size_t even_segments = (segments + 1) / 2;
    const std::size_t odd_segments = segments / 2;
    GraSuReGraphShardRuntimePlan shard_plan;
    shard_plan.destination_base = partition.destination_base;
    shard_plan.destination_vertices = partition.destination_vertices;
    shard_plan.pma_slot_count = segments * kGraSuSegmentSlots;
    shard_plan.pma_words = {
        max_cache_segments * kGraSuSegmentSlots,
        std::max<std::size_t>(
            even_segments > max_cache_segments ? even_segments : 1, 1) *
            kGraSuSegmentSlots,
        max_cache_segments * kGraSuSegmentSlots,
        std::max<std::size_t>(
            odd_segments > max_cache_segments ? odd_segments : 1, 1) *
            kGraSuSegmentSlots,
    };
    for (std::size_t lane = 0; lane < 4; ++lane) {
      shard_plan.update_counts[lane] =
          physical_updates_per_shard[shard] / 4 +
          (lane < physical_updates_per_shard[shard] % 4 ? 1 : 0);
      shard_plan.update_alloc_counts[lane] =
          std::max<std::size_t>(shard_plan.update_counts[lane], 1);
      add_region(shard, "update" + std::to_string(lane),
                 shard_plan.update_alloc_counts[lane] * sizeof(std::uint64_t));
      add_region(shard, "pma" + std::to_string(lane),
                 shard_plan.pma_words[lane] * sizeof(std::uint32_t));
    }
    // The routed HLS ABI stores a sentinel row at index |V|.
    shard_plan.row_words = layout.vertices + 1;
    shard_plan.binary_words = std::max<std::size_t>(segments, 1);
    add_region(shard, "row", shard_plan.row_words * sizeof(std::uint64_t));
    add_region(shard, "binary",
               shard_plan.binary_words * sizeof(std::uint64_t));
    result.shards.push_back(shard_plan);
  }

  std::vector<std::size_t> order(result.regions.size());
  for (std::size_t index = 0; index < order.size(); ++index) {
    order[index] = index;
  }
  std::sort(order.begin(), order.end(),
            [&](std::size_t left, std::size_t right) {
              const auto &a = result.regions[left];
              const auto &b = result.regions[right];
              if (a.allocated_bytes != b.allocated_bytes) {
                return a.allocated_bytes > b.allocated_bytes;
              }
              return std::pair(a.shard, a.name) < std::pair(b.shard, b.name);
            });

  for (const std::size_t region_index : order) {
    GraSuReGraphBufferRegion &region = result.regions[region_index];
    std::size_t selected = channels;
    for (std::size_t channel = region.channel_first;
         channel < region.channel_last; ++channel) {
      if (region.allocated_bytes > channel_capacity_bytes ||
          result.channel_load_bytes[channel] >
              channel_capacity_bytes - region.allocated_bytes) {
        continue;
      }
      if (selected == channels || result.channel_load_bytes[channel] <
                                      result.channel_load_bytes[selected]) {
        selected = channel;
      }
    }
    if (selected == channels) {
      throw std::overflow_error(
          "GraSU-ReGraph runtime buffers exceed HBM pseudo-channel capacity");
    }
    region.channel = selected;
    region.channel_offset_bytes = result.channel_load_bytes[selected];
    result.channel_load_bytes[selected] += region.allocated_bytes;
    result.total_allocated_bytes += region.allocated_bytes;
  }
  return result;
}

const GraSuReGraphBufferRegion &
find_grasu_regraph_runtime_region(const GraSuReGraphRuntimePlan &plan,
                                  std::size_t shard, const std::string &name) {
  const auto found =
      std::find_if(plan.regions.begin(), plan.regions.end(),
                   [&](const GraSuReGraphBufferRegion &region) {
                     return region.shard == shard && region.name == name;
                   });
  if (found == plan.regions.end()) {
    throw std::out_of_range("GraSU-ReGraph runtime region is missing");
  }
  return *found;
}

} // namespace spine::sim
