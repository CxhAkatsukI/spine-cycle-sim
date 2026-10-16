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
#include "native_geometry/fixture.hpp"
#include <iostream>

int main(int argc, char**) {
  using namespace prepared_g;
  try {
    require(argc == 1, "native-geometry-control accepts no reduced-size arguments");
    search_pipeline::configure_host_threads();
    check_report_isolation();
    const native_g::Fixture fixture;
    std::cout << "NATIVE_G_SETUP {\"vertices\":" << fixture.graph.vertices
              << ",\"shards\":" << fixture.graph.shards.size()
              << ",\"partition_vertices\":" << native_g::kPartitionVertices
              << ",\"cache_segments_per_half\":" << MAX_CACHE_SEGMENT
              << ",\"reserved_operations\":" << native_g::kReservedOperations
              << ",\"executed_operations\":40,\"hbm_bytes\":" << fixture.plan.total_allocated_bytes
              << ",\"board\":false}" << std::endl;
    for (bool registered : {false, true}) {
      State state;
      for (const auto& edge : fixture.graph.initial_internal) mutate(state, edge);
      std::vector<PreparedFixture> metadata;
      std::vector<PreparedMemory> memories;
      for (const auto& buffers : fixture.packed) {
        metadata.emplace_back(buffers);
        memories.emplace_back(buffers);
      }
      for (unsigned batch = 0; batch < 3; ++batch) {
        const auto physical = fixture.lower(batch);
        for (const auto& edge : fixture.batches[batch]) mutate(state, edge);
        std::vector<State> expected(fixture.graph.shards.size());
        for (const auto& [key, weight] : state)
          expected.at(key.second / native_g::kPartitionVertices).emplace(key, weight);
        std::array<unsigned, 4> ports{};
        unsigned packets = 0;
        for (unsigned shard = 0; shard < fixture.graph.shards.size(); ++shard) {
          const auto rows = metadata[shard].rows, binary = metadata[shard].binary;
          const auto dispatched = run_g(metadata[shard], memories[shard], physical[shard], registered);
          require(metadata[shard].rows == rows && metadata[shard].binary == binary,
                  "native metadata changed between resident batches");
          packets += handoff(fixture.graph, shard, metadata[shard], memories[shard], expected[shard]);
          for (unsigned port = 0; port < 4; ++port) ports[port] += dispatched[port];
        }
        std::cout << "NATIVE_G_ROW {\"registered\":" << int(registered) << ",\"batch\":" << batch
                  << ",\"updates\":" << fixture.batches[batch].size() << ",\"edges\":" << state.size()
                  << ",\"packets\":" << packets << ",\"hot_even\":" << ports[0]
                  << ",\"cold_even\":" << ports[1] << ",\"hot_odd\":" << ports[2]
                  << ",\"cold_odd\":" << ports[3]
                  << ",\"complete_state_pass\":true,\"direct_handoff_pass\":true,\"metadata_pass\":true,"
                     "\"restored_pma\":false,\"board\":false}" << std::endl;
      }
    }
    std::cout << "NATIVE_G_SOURCE_PASS_NOT_RTL_OR_BOARD" << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
