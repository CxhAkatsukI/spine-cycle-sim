#include <ap_int.h>
#include <ap_utils.h>
#include <hls_stream.h>
#include "upstream/kernel_config.h"
namespace author_search {
#include "upstream/kernel_bin_search.cpp"
}
namespace author_cache {
#include "upstream/kernel_process_cache.cpp"
}
// The pristine configuration lacks the integration-only debug-print macro.
#define GRASU_KDEBUG(...)
namespace current_dispatch {
#include "integration/kernel_dispatch.cpp"
}
#define GRASU_REGRAPH_WEIGHTED_PMA 1
#define GRASU_REGRAPH_SHARDED_PMA 1
#include "adapter/pma_to_regraph_adapter.cpp"
#include "cache_lane.hpp"
#include "search.hpp"
#ifdef WEIGHTED_FINITE_SEARCH
#include "search_pipeline/top.cpp"
#include "finite_search.hpp"
#endif

namespace weighted_control {
using Banks = std::array<std::vector<Segment>, 32>;
inline Segment& locate(Banks& banks, unsigned segment) {
  return banks.at(segment % 32).at(segment / 32);
}
void check_adapter(const host::WeightedPartitionedPmaGraph& graph,
                   const host::WeightedPmaShard& shard, Banks& banks, EdgeMap& edges) {
  const unsigned segments = shard.initial_pma_words.size() / 16;
  std::array<std::vector<Segment>, 4> buffers;
  for (auto& buffer : buffers) buffer.resize(std::max(1u, (segments + 1) / 2));
  for (unsigned segment = 0; segment < segments; ++segment)
    buffers[(segment & 1) * 2][segment / 2] = locate(banks, segment);
#if GRASU_REGRAPH_ROW_LINE_READ
  std::vector<ap_uint<512>> rows((shard.row_bounds.size() + 7) / 8);
  for (unsigned i = 0; i < shard.row_bounds.size(); ++i)
    rows[i / 8].range((i % 8) * 64 + 63, (i % 8) * 64) = shard.row_bounds[i];
#else
  std::vector<ap_uint<64>> rows(shard.row_bounds.begin(), shard.row_bounds.end());
#endif
  hls::stream<edge_burst_pkt_t> stream;
  pma_to_regraph_adapter(buffers[0].data(), buffers[1].data(), buffers[2].data(),
      buffers[3].data(), rows.data(), graph.vertices, segments * 16,
      MAX_CACHE_SEGMENT, shard.destination_base, shard.destination_vertices, stream);
  require(stream.size() == segments * 2, "adapter physical packet count");
  unsigned lasts = 0;
  for (unsigned burst = 0; burst < segments * 2; ++burst) {
    const auto packet = stream.read();
    require(bool(packet.last) == (burst + 1 == segments * 2), "adapter terminal position");
    lasts += bool(packet.last);
    require(packet.keep == decltype(packet.keep)(-1) && packet.strb == decltype(packet.strb)(-1),
            "adapter byte enables");
    for (unsigned lane = 0; lane < 8; ++lane) {
      const unsigned source = packet.data.range(lane * 64 + 31, lane * 64).to_uint();
      const unsigned word = packet.data.range(lane * 64 + 63, lane * 64 + 32).to_uint();
      require(bool(source >> 31) == bool(word >> 31), "adapter dummy consistency");
      if (word >> 31) continue;
      const unsigned dst = shard.destination_base + (word & 0x7ffffu);
      require(source < graph.vertices && dst < graph.vertices && (word >> 19) != 0,
              "adapter source/destination/weight range");
      const auto external = std::pair{graph.internal_to_external.at(source),
                                      graph.internal_to_external.at(dst)};
      require(edges.emplace(external, word >> 19).second, "duplicate adapter edge");
    }
  }
  require(stream.empty() && lasts == 1, "adapter stream closure");
}
void run(const Fixture& fixture, bool candidate) {
  const auto graph = host::build_weighted_partitioned_pma_graph(
      fixture.vertices, fixture.partition, fixture.initial, fixture.updates);
  EdgeMap emitted;
  unsigned operations = 0, segments_seen = 0;
  for (const auto& shard : graph.shards) {
    const unsigned segments = shard.initial_pma_words.size() / 16;
    require(segments > 0 && segments <= MAX_CACHE_SEGMENT * 2, "probe hot-region bound");
    Banks banks;
    for (auto& bank : banks) bank.resize((segments + 31) / 32);
    std::vector<Slots> expected(segments);
    for (unsigned segment = 0; segment < segments; ++segment) {
      std::copy_n(shard.initial_pma_words.begin() + segment * 16, 16, expected[segment].begin());
      locate(banks, segment) = pack(expected[segment]);
    }
#ifdef WEIGHTED_FINITE_SEARCH
    const auto packets = finite_search(shard);
#endif
    for (unsigned operation = 0; operation < shard.physical_updates.size(); ++operation) {
      const auto raw = shard.physical_updates[operation];
#ifdef WEIGHTED_FINITE_SEARCH
      const auto packet = packets[operation];
#else
      const auto packet = search(shard, raw);
#endif
      const unsigned segment = packet.data.range(31, 0).to_uint() / 16;
      hls::stream<pipe_type_96> inputs[4], outputs[4];
      inputs[0].write(packet);
      current_dispatch::dispatch(1, inputs[0], inputs[1], inputs[2], inputs[3],
                                outputs[0], outputs[2], outputs[1], outputs[3]);
      for (unsigned buffer = 0; buffer < 4; ++buffer) {
        if (buffer == (segment & 1) * 2) {
          const auto actual = outputs[buffer].read();
          require(actual.data == packet.data, "dispatch weighted payload");
          hls::stream<ap_uint<96>> updates;
          updates.write(actual.data); updates.write(END_EDGE);
          if (candidate) cache_probe_detail::lane_update(banks[segment % 32].data(), updates);
          else author_cache::process_1(banks[segment % 32].data(), updates);
          require(updates.empty(), "cache update drain");
        }
        require(outputs[buffer].read().data == END_EDGE && outputs[buffer].empty(), "dispatch drain");
        require(inputs[buffer].empty(), "dispatch input drain");
      }
      edit_oracle(expected[segment], raw);
      for (unsigned index = 0; index < segments; ++index)
        require(unpack(locate(banks, index)) == expected[index], "complete intermediate PMA mismatch");
      ++operations;
    }
    check_adapter(graph, shard, banks, emitted);
    segments_seen += segments;
  }
  require(emitted == external_oracle(fixture), "adapter vs independent logical graph mismatch");
  std::cout << "WEIGHTED_ABI_PASS case=" << fixture.name << " arm="
            << (candidate ? "registered_cache" : "original_cache")
            << " operations=" << operations << " segments=" << segments_seen
            << " shards=" << graph.shards.size() << " edges=" << emitted.size() << '\n';
}
}  // namespace weighted_control

int main() {
  try {
    weighted_control::check_dispatch_boundary();
#ifdef WEIGHTED_FINITE_SEARCH
    search_pipeline::configure_host_threads();
#endif
    for (const auto& fixture : weighted_control::fixtures())
      for (bool candidate : {false, true}) weighted_control::run(fixture, candidate);
#ifdef WEIGHTED_FINITE_SEARCH
    for (bool candidate : {false, true})
      weighted_control::run(weighted_control::wraparound_fixture(), candidate);
    std::cout << "WEIGHTED_SEARCH_COMPLETE mode=finite_pipeline channels=339\n";
#endif
    std::cout << "WEIGHTED_ABI_COMPLETE scope=source_functional timing_admitted=false\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
