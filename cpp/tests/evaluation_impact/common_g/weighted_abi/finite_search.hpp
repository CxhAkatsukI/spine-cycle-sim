#pragma once

#include "search.hpp"
#include <chrono>

namespace weighted_control {
inline std::vector<pipe_type_96> finite_search(const host::WeightedPmaShard& shard) {
  using namespace search_pipeline;
  const std::vector<unsigned long> edges(shard.physical_updates.begin(),
                                         shard.physical_updates.end());
  const std::vector<Raw> binary(shard.binary_heads.begin(), shard.binary_heads.end());
  const std::vector<Raw> rows(shard.row_bounds.begin(), shard.row_bounds.end());
  FiniteQueue<Packet> queue(2);
  hls::stream<Packet> output;
  output.set_delegate(&queue);
  std::vector<pipe_type_96> packets;
  std::thread consumer([&] {
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
    for (unsigned i = 0; i < edges.size(); ++i) packets.push_back(output.read());
  });
  bin_search_pipeline(edges.data(), binary.data(), rows.data(), edges.size(), output);
  consumer.join();
  output.set_delegate(nullptr);
  unsigned long probes = 0;
  for (unsigned i = 0; i < packets.size(); ++i) {
    const auto reference = search(shard, edges[i], &probes);
    const auto& packet = packets[i];
    require(packet.data == reference.data && packet.keep == reference.keep &&
            packet.strb == reference.strb && packet.last == reference.last,
            "finite vs pristine ordered weighted search packet");
  }
  require(packets.size() == edges.size(), "finite weighted result count");
  const auto& channels = last_host_report().channels;
  require(channels.size() == 339, "finite weighted search topology");
  const auto& requests = channels.at(337);
  const auto& responses = channels.at(338);
  require(requests.capacity == 32 && responses.capacity == 32 &&
          requests.writes == edges.size() + probes + 1 && responses.writes == requests.writes,
          "finite weighted metadata request/response conservation");
  const auto stats = queue.stats();
  require(stats.writes == edges.size() && stats.reads == edges.size() && queue.size() == 0,
          "finite weighted output drain");
  return packets;
}

inline Fixture wraparound_fixture() {
  Fixture fixture{"pipeline_wraparound", 8, 4, {{0, 1, 1}}, {}};
  for (unsigned weight = 2; weight <= 131; ++weight)
    fixture.updates.push_back({0, 1, std::uint16_t(weight)});
  return fixture;
}
}  // namespace weighted_control
