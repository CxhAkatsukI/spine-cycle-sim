#include "control.hpp"
#ifdef SEARCH_PIPELINE_SOURCE_TOP
#include "top.cpp"
#endif

int main() {
  search_pipeline::configure_host_threads();
  search_pipeline::check_selector();
  std::vector<search_pipeline::Raw> rows, binary;
  for (unsigned source = 0; source < 8; ++source) {
    const unsigned begin = binary.size();
    const unsigned segments = 1u << source;
    for (unsigned i = 0; i < segments; ++i)
      binary.emplace_back((static_cast<unsigned long>(source) << 32) | i * 128u);
    rows.emplace_back((static_cast<unsigned long>(begin * 16) << 32) | binary.size() * 16);
  }
  for (const unsigned count : {0u, 1u, 63u, 64u, 65u, 127u, 128u, 129u, 257u}) {
    for (const bool same_key : {false, true}) {
      std::vector<unsigned long> edges;
      for (unsigned i = 0; i < count; ++i) {
        const unsigned source = same_key ? 7 : i % 8;
        const unsigned destination = same_key ? 256 : (i * 31) % ((1u << source) * 128);
        edges.push_back((static_cast<unsigned long>(i & 1) << 63) |
                        (static_cast<unsigned long>(source) << 32) | destination);
      }
      // The co-simulation instrumenter must see a direct top-function call.
      const auto invoke = [](const unsigned long* updates, const search_pipeline::Raw* nodes,
                             const search_pipeline::Raw* offsets, unsigned size,
                             hls::stream<search_pipeline::Packet>& output) {
        bin_search_pipeline(updates, nodes, offsets, size, output);
      };
      search_pipeline::check(edges, binary, rows, false, false, invoke);
    }
  }
}
