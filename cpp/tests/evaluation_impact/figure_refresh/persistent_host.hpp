#pragma once

#include "bootstrap.hpp"
#include "update_preparation.hpp"
#include <chrono>
#include <iostream>

namespace figure_refresh {
using HostClock = std::chrono::steady_clock;

inline std::uint64_t host_ns(HostClock::time_point start) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(HostClock::now() - start).count();
}

inline void append_host_word(std::vector<std::uint8_t>& bytes, std::uint64_t word,
                             std::size_t width) {
  for (std::size_t byte = 0; byte < width; ++byte)
    bytes.push_back(static_cast<std::uint8_t>(word >> (8 * byte)));
}

struct PersistentHostWork {
  std::uint64_t initial_ns{}, total_ns{}, initial_bytes{}, update_bytes{};
  std::vector<std::uint64_t> batch_bytes;
};

inline PersistentHostWork persistent_spine_host(const wc::Input& input, std::size_t count,
                                               std::size_t preload_minimum_level = 2) {
  const auto start = HostClock::now();
  auto config = spine_config();
  auto state = preload_spine_resident_snapshot(slice(input, false), config, nullptr,
                                              preload_minimum_level);
  BootstrapCapture capture(config);
  constructor_image(state, SpineEdgeSlice{.vertices = input.after.compact.vertices, .edges = {},
      .case_name = "persistent-host-bootstrap"}, config);
  PersistentHostWork work;
  work.initial_ns = host_ns(start);
  work.initial_bytes = capture.initial_bytes();
  const auto trace = slice(input, true);
  std::vector<std::vector<std::uint8_t>> payloads;
  for (std::size_t batch = 0; batch < count; ++batch) {
    payloads.push_back(encode_spine_sort_edges(ordered_batch(trace, batch, count).edges));
    work.batch_bytes.push_back(payloads.back().size());
    work.update_bytes += payloads.back().size();
  }
  work.total_ns = host_ns(start);
  require(capture.calls > 0 && work.initial_bytes > 0 && capture.batch_bytes == 0 &&
      work.update_bytes == input.updates.size() * 16, "incomplete resident Spine host payloads");
  for (std::size_t batch = 0; batch < count; ++batch)
    require(payloads[batch] == encode_spine_sort_edges(ordered_batch(trace, batch, count).edges),
            "Spine host batch encoding changed");
  return work;
}

inline PersistentHostWork persistent_grasu_host(const wc::Input& input, std::size_t count) {
  const auto start = HostClock::now();
  const auto layout = reserved_grasu(input);
  struct Image { std::vector<std::uint8_t> rows, heads, segments; };
  std::vector<Image> images(layout.partitions.size());
  PersistentHostWork work;
  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard) {
    const auto& part = layout.partitions[shard];
    auto& image = images[shard];
    for (const auto& [begin, end] : part.row_slot_bounds)
      append_host_word(image.rows, (static_cast<std::uint64_t>(begin) << 32) | end, 8);
    const auto slots = part.row_slot_bounds.back().second;
    append_host_word(image.rows, (static_cast<std::uint64_t>(slots) << 32) | slots, 8);
    for (const auto head : part.binary_heads) append_host_word(image.heads, head, 8);
    for (const auto& segment : part.segments)
      for (const auto word : segment) append_host_word(image.segments, word, 4);
    work.initial_bytes += image.rows.size() + image.heads.size() + image.segments.size();
  }
  work.initial_ns = host_ns(start);
  using PackedShard = std::array<std::vector<std::uint8_t>, 4>;
  std::vector<std::vector<PackedShard>> payloads;
  for (std::size_t batch = 0; batch < count; ++batch) {
    std::vector<std::vector<GraSuEdge>> bins(layout.partitions.size());
    for (const auto& edge : grasu_batch(input, batch, count))
      bins.at(layout.partition_for_destination(edge.destination)).push_back(edge);
    auto& packed = payloads.emplace_back();
    std::uint64_t bytes = 0;
    for (std::size_t shard = 0; shard < bins.size(); ++shard) {
      packed.push_back(encode_grasu_compact_updates(layout.partitions[shard], bins[shard],
                                                   GraSuPmaWordAbi::kWeightedFullWord));
      for (const auto& lane : packed.back()) bytes += lane.size();
    }
    work.batch_bytes.push_back(bytes);
    work.update_bytes += bytes;
  }
  work.total_ns = host_ns(start);
  require(work.initial_bytes > 0 && work.update_bytes == input.updates.size() * 8,
          "incomplete resident G host payloads");
  // Consume all serialized buffers after timing so packing cannot disappear.
  std::uint64_t checksum = 0;
  for (const auto& image : images)
    for (const auto* bytes : {&image.rows, &image.heads, &image.segments})
      for (const auto byte : *bytes) checksum = checksum * 131 + byte;
  for (const auto& batch : payloads)
    for (const auto& shard : batch) for (const auto& lane : shard)
      for (const auto byte : lane) checksum = checksum * 131 + byte;
  std::cout << "HOST_PAYLOAD_DIGEST " << checksum << '\n';
  return work;
}

inline void persistent_host(const wc::Input& input, const std::string& arm, std::size_t count,
                            std::size_t preload_minimum_level = 2) {
  require(count > 1 && count <= input.updates.size(), "nonempty persistent host batches required");
  const auto work = arm == "spine" ? persistent_spine_host(input, count, preload_minimum_level)
                                    : persistent_grasu_host(input, count);
  std::cout << "HOST_RESULT {\"arm\":\"" << arm << "\",\"repeat\":0,\"batches\":" << count
      << ",\"updates\":" << input.updates.size() << ",\"nanoseconds\":" << work.total_ns
      << ",\"initial_nanoseconds\":" << work.initial_ns
      << ",\"batch_nanoseconds\":" << work.total_ns - work.initial_ns
      << ",\"initial_h2d_bytes\":" << work.initial_bytes
      << ",\"update_h2d_bytes\":" << work.update_bytes
      << ",\"bootstrap_complete\":true,\"batch_preparation_complete\":true,\"batch_h2d_bytes\": [";
  for (std::size_t batch = 0; batch < work.batch_bytes.size(); ++batch)
    std::cout << (batch ? "," : "") << work.batch_bytes[batch];
  std::cout << "]}" << std::endl;
}
} // namespace figure_refresh
