#include <ap_int.h>
#include <ap_utils.h>
#include <hls_stream.h>
#include "integration/kernel_config.h"
#include "hls/search_binding/top.cpp"
#include "hls/cache_full.cpp"
namespace production_dispatch {
#include "integration/kernel_dispatch.cpp"
}
namespace production_ddr {
#include "integration/kernel_process_ddr.cpp"
}
#define GRASU_REGRAPH_WEIGHTED_PMA 1
#define GRASU_REGRAPH_SHARDED_PMA 1
#include "adapter/pma_to_regraph_adapter.cpp"
#include "execution.hpp"
#include "host_prepared/handoff.hpp"
#include <iostream>
#include <memory>

int main(int argc, char** argv) {
  using namespace prepared_g;
  try {
    require(argc == 3, "usage: host-prepared-control case-id input");
    search_pipeline::configure_host_threads();
    check_report_isolation();
    const Input input(argv[2]);
    const auto graph = host::build_weighted_partitioned_pma_graph(
        input.vertices, input.partition_vertices, input.initial, input.updates);
    check_host_mapping(input, graph);
    const auto plan = host::build_weighted_pma_runtime_plan(graph, MAX_CACHE_SEGMENT,
        23, host::kU55cHbmPseudoChannelBytes, host::WeightedPmaChannelPolicy::lane_aware_u55c, true);
    const auto packed = host::pack_weighted_pma_runtime_buffers(graph, plan);
    const std::array<unsigned, 4> ends{0, 0, unsigned(input.updates.size() / 2), unsigned(input.updates.size())};
    for (bool registered : {false, true}) {
      State state;
      for (const auto& edge : input.initial) mutate(state, edge);
      std::vector<PreparedFixture> fixtures;
      std::vector<PreparedMemory> memories;
      for (const auto& buffers : packed) {
        fixtures.emplace_back(buffers);
        memories.emplace_back(buffers);
      }
      for (unsigned batch = 0; batch < 3; ++batch) {
        const auto updates = batches(input, graph, ends[batch], ends[batch + 1]);
        for (unsigned i = ends[batch]; i < ends[batch + 1]; ++i) mutate(state, input.updates[i]);
        std::vector<State> expected(graph.shards.size());
        for (const auto& [key, weight] : state)
          expected.at(graph.external_to_internal.at(key.second) / input.partition_vertices).emplace(key, weight);
        std::array<unsigned, 4> ports{};
        unsigned packets = 0, physical = 0;
        for (unsigned shard = 0; shard < graph.shards.size(); ++shard) {
          const auto row_pin = fixtures[shard].rows;
          const auto binary_pin = fixtures[shard].binary;
          const auto dispatched = run_g(fixtures[shard], memories[shard], updates[shard], registered);
          require(fixtures[shard].rows == row_pin && fixtures[shard].binary == binary_pin,
                  "host metadata mutated during G execution");
          packets += handoff(graph, shard, fixtures[shard], memories[shard], expected[shard]);
          physical += updates[shard].size();
          for (unsigned port = 0; port < 4; ++port) ports[port] += dispatched[port];
        }
        require(physical == ends[batch + 1] - ends[batch], "batch physical update conservation");
        std::cout << "HOST_G_ROW {\"case\":\"" << argv[1] << "\",\"registered\":" << int(registered)
                  << ",\"batch\":" << batch << ",\"vertices\":" << input.vertices
                  << ",\"shards\":" << graph.shards.size() << ",\"updates\":" << physical
                  << ",\"edges\":" << state.size() << ",\"packets\":" << packets
                  << ",\"hot_even\":" << ports[0] << ",\"cold_even\":" << ports[1]
                  << ",\"hot_odd\":" << ports[2] << ",\"cold_odd\":" << ports[3]
                  << ",\"complete_state_pass\":true,\"direct_handoff_pass\":true}" << std::endl;
      }
    }
    std::cout << "HOST_G_SOURCE_PASS internal_cache_ddr_fifos=unbounded timing_admitted=false" << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
