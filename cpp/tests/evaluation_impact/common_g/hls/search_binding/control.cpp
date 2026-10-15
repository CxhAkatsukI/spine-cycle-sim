#include "../search_pipeline/control.hpp"
#include "top.hpp"
#ifdef SEARCH_PIPELINE_SOURCE_TOP
#include "../search_pipeline/top.cpp"
#include "top.cpp"
#endif

int main() {
  using namespace search_pipeline;
  configure_host_threads();
  const std::vector<Raw> poison(255, Raw(-1));
  std::vector<Raw> rows, binary;
  for (unsigned generation = 0; generation < 2; ++generation) {
    rows.clear();
    binary.clear();
    const unsigned stride = generation ? 64 : 128;
    for (unsigned source = 0; source < 8; ++source) {
      const unsigned begin = binary.size();
      const unsigned segments = 1u << (generation ? 7 - source : source);
      for (unsigned i = 0; i < segments; ++i)
        binary.emplace_back((static_cast<unsigned long>(source) << 32) | i * stride);
      rows.emplace_back((static_cast<unsigned long>(begin * 16) << 32) | binary.size() * 16);
    }
    for (const unsigned count : {0u, 1u, 63u, 64u, 65u, 127u, 128u, 129u, 257u}) {
      for (const bool same_key : {false, true}) {
        std::vector<unsigned long> edges;
        for (unsigned i = 0; i < count; ++i) {
          const unsigned source = same_key ? (generation ? 0 : 7) : i % 8;
          const unsigned segments = 1u << (generation ? 7 - source : source);
          const unsigned destination = same_key ? 256 : (i * 31) % (segments * stride);
          edges.push_back((static_cast<unsigned long>(i & 1) << 63) |
                          (static_cast<unsigned long>(source) << 32) | destination);
        }
        for (unsigned alias = 0; alias < 3; ++alias) {
          for (const bool stalled : {false, true}) {
            const auto invoke = [&](const unsigned long* updates, const Raw* nodes,
                                    const Raw* offsets, unsigned size, hls::stream<Packet>& output) {
              const Raw* unused_nodes = alias == 0 ? nodes : alias == 1 ? poison.data() : nullptr;
              const Raw* unused_offsets = alias == 0 ? offsets : alias == 1 ? poison.data() : nullptr;
              bin_search(updates, nodes, unused_nodes, unused_nodes, unused_nodes,
                         offsets, unused_offsets, unused_offsets, unused_offsets, size, output);
            };
            const auto probes = check(edges, binary, rows, stalled, true, invoke);
            std::cout << "SEARCH_BINDING_ROW {\"generation\":" << generation
                      << ",\"updates\":" << count << ",\"same_key\":" << int(same_key)
                      << ",\"alias\":" << alias << ",\"stalled\":" << int(stalled)
                      << ",\"probes\":" << probes << "}\n";
          }
        }
      }
    }
  }
}
