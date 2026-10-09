#include <iostream>

#include "fixture.hpp"

namespace {
using namespace pma_adapter_test;

void geometry_rejections() {
  original_regraph_memory_test::MemoryFixture memory;
  const auto port = memory.port("axi", 1, 0);
  auto* output = memory.queue<rg::EdgeBurst>("output");
  auto* reader = memory.make<pa::Reader>("adapter", memory.clock, port.ports(), *output);
  pa::Partition valid{{4096, 8192, 12288, 16384}, 0, 11, 96, 1, 65536, 256};
  for (unsigned index = 0; index < 6; ++index) {
    auto bad = valid;
    if (index == 0) bad.vertices = 0;
    if (index == 1) bad.slots = 17;
    if (index == 2) bad.row_address = 8;
    if (index == 3) bad.pma_addresses[0] = 4;
    if (index == 4) bad.destination_vertices = 65537;
    if (index == 5) bad.destination_offset = 0xffff0000u;
    bool rejected = false;
    try { reader->begin_partition(bad); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "PMA adapter accepted invalid geometry");
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 1 || argc == 2, "usage: pma_adapter_tests [CAPTURE_DIR]");
    const auto baseline = run(Data{});
    const auto reversed = run(Data{}, {.reverse = true});
    require(baseline.cycles == reversed.cycles && baseline.global == reversed.global &&
            baseline.counters.read_bytes == reversed.counters.read_bytes &&
            baseline.counters.request_stalls == reversed.counters.request_stalls &&
            baseline.counters.output_stalls == reversed.counters.output_stalls,
            "registration order changed the finite PMA producer");
    const auto pressured = run(Data{}, {.depth = 1, .sink_start = 1500, .sink_interval = 113});
    require(pressured.cycles > baseline.cycles && pressured.counters.output_stalls,
            "finite PMA output pressure did not affect timing");
    const auto limited = run(Data{}, {.parents = 1});
    const auto delayed = run(Data{}, {.latency = 128});
    auto options = Options{}; options.timing.segment_capacity = 1;
    const auto capacity = run(Data{}, options);
    require(limited.cycles > baseline.cycles && delayed.cycles > baseline.cycles &&
            capacity.cycles > baseline.cycles && capacity.counters.capacity_stalls,
            "PMA AXI, memory latency or finite segment capacity was bypassed");
    bool rejected = false;
    try { run(Data{}, {.bad_rows = true}); } catch (const std::logic_error&) { rejected = true; }
    require(rejected, "PMA malformed row was not rejected");
    geometry_rejections();
    for (unsigned cache : {0u, 1u, 3u}) {
      const auto result = run(Data{cache});
      const auto& c = result.counters;
      const std::array<std::uint64_t, 4> expected = cache == 0 ? std::array<std::uint64_t, 4>{0, 3, 0, 3}
          : cache == 1 ? std::array<std::uint64_t, 4>{1, 2, 1, 2} : std::array<std::uint64_t, 4>{3, 0, 3, 0};
      require(c.segment_reads == expected, "PMA hot/cold even/odd routing mismatch");
      if (argc == 2) original_regraph_whole_test::write_words(
          std::filesystem::path(argv[1]) / ("cache" + std::to_string(cache) + ".u32le"), result.global);
      std::cout << "PMA_ADAPTER {\"cache_segments\":" << cache << ",\"passed\":true,\"cycles\":" << result.cycles
                << ",\"physical_edges\":" << c.physical_edges << ",\"valid_edges\":" << c.valid_edges
                << ",\"dummy_edges\":" << c.dummy_edges << ",\"row_word_reads\":" << c.row_word_reads
                << ",\"row_bus_bytes\":" << c.row_bus_bytes << ",\"pma_bus_bytes\":" << c.pma_bus_bytes
                << ",\"requests\":" << c.parent_requests << ",\"acknowledgements\":" << c.acknowledgements
                << ",\"queues_and_requests_conserved\":true}\n";
    }
    std::cout << "PMA adapter finite producer, pressure, routing and rejection tests passed\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
