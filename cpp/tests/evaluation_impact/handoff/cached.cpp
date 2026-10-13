#include "cached_fixture.hpp"
#include "execution.hpp"

namespace ht = handoff_test;
using namespace spine::sim;

namespace {
ht::Observation run(const ht::Fixture &f, bool cold, bool empty, bool cached, bool reverse) {
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = ht::kFullCache;
  if (cached) {
    config.compact_parallel_search = true;
    config.compact_finite_search = true;
    config.compact_search_contexts = 64;
    config.compact_metadata_credits = 32;
    config.compact_cached_hot = true;
  }
  const auto observation = ht::execute(f, config, reverse);
  const auto &g = observation.update;
  const auto &r = observation.timing;
  const auto expected_ddr = !empty && cold ? 4U : 0U;
  const auto expected_hot = f.updates.size() - expected_ddr;
  const auto bytes = cached && !empty ? 2 * 2 * ht::kFullCache * kGraSuSegmentBytes : 0;
  const auto expected_bytes = bytes + (cached ? expected_ddr : f.updates.size()) * kGraSuSegmentBytes;
  ht::require(g.cache_updates == expected_hot && g.ddr_updates == expected_ddr,
              "full-cache hot/DDR update counts differ");
  ht::require(g.pma_read_bytes == expected_bytes && g.pma_write_bytes == expected_bytes,
              "full-cache preload/writeback or cold update traffic omitted");
  std::cout << "CACHED_HANDOFF_RESULT {\"vertices\":" << f.vertices << ",\"high_source\":"
            << (f.vertices - 1) / 65536 * 65536 << ",\"cold_high_source\":" << (cold ? "true" : "false")
            << ",\"empty\":" << (empty ? "true" : "false") << ",\"cached\":" << (cached ? "true" : "false")
            << ",\"reverse\":" << (reverse ? "true" : "false") << ",\"g_cycles\":" << r.g_cycles
            << ",\"r_cycles\":" << r.r_cycles << ",\"rounds\":" << r.rounds
            << ",\"r_read_bytes\":" << r.reads << ",\"r_write_bytes\":" << r.writes
            << ",\"cache_updates\":" << g.cache_updates << ",\"ddr_updates\":" << g.ddr_updates
            << ",\"pma_read_bytes\":" << g.pma_read_bytes << ",\"pma_write_bytes\":" << g.pma_write_bytes
            << ",\"physical_handoff_pass\":true,\"performance_admitted\":false}" << std::endl;
  return observation;
}
} // namespace

int main() {
  try {
    for (auto [vertices, cold, empty] : {std::tuple{65569U, false, false},
        std::tuple{65569U, true, false}, std::tuple{131105U, true, false}, std::tuple{65569U, true, true}}) {
      const auto f = ht::cached_fixture(vertices, cold, empty);
      const auto direct = run(f, cold, empty, false, false);
      const auto cached = run(f, cold, empty, true, false);
      const auto reverse = run(f, cold, empty, true, true);
      ht::require(cached.timing == reverse.timing, "cached handoff registration order changed timing");
      ht::require(std::tie(direct.timing.r_cycles, direct.timing.reads, direct.timing.writes, direct.timing.rounds) ==
                      std::tie(cached.timing.r_cycles, cached.timing.reads, cached.timing.writes, cached.timing.rounds),
                  "cached G changed R convergence or traffic");
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
