#include "../search_pipeline/control.hpp"
#include "top.hpp"
#ifdef SEARCH_PIPELINE_SOURCE_TOP
#include "top.cpp"
#endif

int main() {
  using namespace search_pipeline;
  configure_host_threads();
  std::vector<Raw> rows(8), binary(255);
  for (const unsigned count : {0u, 1u, 63u, 64u, 65u, 127u, 128u, 129u, 257u}) {
    for (unsigned generation = 0; generation < 2; ++generation) {
      unsigned begin = 0;
      const unsigned stride = generation ? 64 : 128;
      for (unsigned source = 0; source < 8; ++source) {
        const unsigned segments = 1u << (generation ? 7 - source : source);
        const unsigned end = begin + segments;
        for (unsigned i = 0; i < segments; ++i)
          binary[begin + i] = (static_cast<unsigned long>(source) << 32) | i * stride;
        rows[source] = (static_cast<unsigned long>(begin * 16) << 32) | end * 16;
        begin = end;
      }
      std::vector<unsigned long> edges;
      for (unsigned i = 0; i < count; ++i) {
        const unsigned source = generation ? 0 : i % 8;
        const unsigned segments = 1u << (generation ? 7 - source : source);
        const unsigned destination = generation ? 256 : (i * 31) % (segments * stride);
        edges.push_back((static_cast<unsigned long>(i & 1) << 63) |
                        (static_cast<unsigned long>(source) << 32) | destination);
      }
      const auto invoke = [](const unsigned long* updates, const Raw* nodes,
                             const Raw* offsets, unsigned size, hls::stream<Packet>& output) {
        bin_search(updates, nodes, nodes, nodes, nodes, offsets, offsets, offsets, offsets, size, output);
      };
      check(edges, binary, rows, false, false, invoke);
      std::cout << "SEARCH_BINDING_RTL_ROW generation=" << generation << " updates=" << count << '\n';
    }
  }
}
