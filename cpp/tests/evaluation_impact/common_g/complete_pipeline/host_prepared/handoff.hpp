#pragma once

#include "memory.hpp"

namespace prepared_g {
inline unsigned handoff(const host::WeightedPartitionedPmaGraph& graph, unsigned index,
                        const PreparedFixture& fixture, PreparedMemory& memory,
                        const State& expected) {
  const auto& shard = graph.shards.at(index);
  const auto slots = shard.initial_pma_words.size();
  std::vector<Word> rows((fixture.rows.size() + 7) / 8);
  for (unsigned source = 0; source < fixture.rows.size(); ++source)
    rows[source / 8].range((source % 8) * 64 + 63, (source % 8) * 64) = fixture.rows[source];
  State actual;
  hls::stream<edge_burst_pkt_t> output;
  search_pipeline::FiniteQueue<edge_burst_pkt_t> queue(2);
  output.set_delegate(&queue);
  unsigned packets = 0;
  std::exception_ptr error;
  std::thread consumer([&] {
    try {
      while (true) {
        const auto packet = output.read();
        require(++packets <= slots / 8, "host adapter excess physical packets");
        require(packet.keep == decltype(packet.keep)(-1) && packet.strb == decltype(packet.strb)(-1),
                "host adapter byte enables");
        for (unsigned lane = 0; lane < 8; ++lane) {
          const unsigned source = packet.data.range(lane * 64 + 31, lane * 64).to_uint();
          const unsigned word = packet.data.range(lane * 64 + 63, lane * 64 + 32).to_uint();
          require(bool(source >> 31) == bool(word >> 31), "host adapter dummy sidebands");
          if (word >> 31) continue;
          const unsigned local = word & 0x7ffffu, weight = word >> 19;
          require(source < graph.vertices && local < shard.destination_vertices && weight > 0,
                  "host adapter source/local destination/weight");
          const auto key = std::make_pair(graph.internal_to_external.at(source),
              graph.internal_to_external.at(shard.destination_base + local));
          require(actual.emplace(key, weight).second, "host adapter duplicate logical pair");
        }
        if (packet.last) break;
      }
    } catch (...) { error = std::current_exception(); }
  });
  pma_to_regraph_adapter(memory.buffers[0].data(), memory.buffers[1].data(),
      memory.buffers[2].data(), memory.buffers[3].data(), rows.data(), graph.vertices, slots,
      MAX_CACHE_SEGMENT, shard.destination_base, shard.destination_vertices, output);
  consumer.join();
  if (error) std::rethrow_exception(error);
  const auto stats = queue.stats();
  require(packets == slots / 8 && queue.size() == 0 && stats.writes == stats.reads &&
          stats.high_water <= stats.capacity && actual == expected, "host PMA direct handoff edge set");
  output.set_delegate(nullptr);
  return packets;
}
}  // namespace prepared_g
