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
#include <iostream>

int main() {
  using namespace complete_g;
  try {
    search_pipeline::configure_host_threads();
    check_report_isolation();
    Fixture fixture;
    const auto* binary_storage = fixture.binary.data();
    const auto* row_storage = fixture.rows.data();
    for (bool registered : {false, true}) {
      for (unsigned generation = 0; generation < 2; ++generation) {
        fixture.metadata(generation);
        require(fixture.binary.data() == binary_storage && fixture.rows.data() == row_storage,
                "metadata pointer storage not reused");
        Memory memory;
        for (unsigned batch = 0; batch < counts.size(); ++batch) {
          const auto updates = fixture.batch(batch);
          const auto ports = run_g(fixture, memory, updates, registered);
          const auto edges = check_adapter(fixture, memory);
          std::cout << "COMPLETE_G_ROW {\"registered\":" << int(registered)
                    << ",\"generation\":" << generation << ",\"batch\":" << batch
                    << ",\"updates\":" << updates.size() << ",\"edges\":" << edges
                    << ",\"hot_even\":" << ports[0] << ",\"cold_even\":" << ports[1]
                    << ",\"hot_odd\":" << ports[2] << ",\"cold_odd\":" << ports[3]
                    << "}" << std::endl;
        }
      }
    }
    std::cout << "COMPLETE_G_SOURCE_PASS four_search_cus=4 hot_half_segments=131072 "
                 "cold_segments=4 metadata_generations=2 internal_cache_ddr_fifos=unbounded "
                 "timing_admitted=false" << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
