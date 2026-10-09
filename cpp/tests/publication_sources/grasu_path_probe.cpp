#include "probe_support.hpp"
#include "kernel_config.h"
#include <ap_utils.h>
#include <fstream>

// Namespace wrappers only avoid duplicate helper names; author bodies are unchanged.
namespace author_search {
#include "kernel_bin_search.cpp"
}
namespace author_dispatch {
#include "kernel_dispatch.cpp"
}
namespace author_cache {
#include "kernel_process_cache.cpp"
}
namespace author_ddr {
#include "kernel_process_ddr.cpp"
}
#include "grasu_path/fixture.hpp"
#include "grasu_path/lookup.hpp"
#include "grasu_path/update.hpp"

int main(int argc, char** argv) {
  try {
    require(argc == 4, "expected fixture, protocol capture, final state capture");
    const unsigned id = std::stoul(argv[1]); const auto batches = grasu_control::fixture(id);
    std::ofstream protocol(argv[2], std::ios::binary), state(argv[3], std::ios::binary);
    require(protocol.is_open() && state.is_open(), "cannot create G captures");
    for (auto value : {0x47535031u, 1u, id, unsigned(batches.size()), grasu_control::segments, grasu_control::hot_segments})
      grasu_control::word(protocol, value);
    grasu_control::Memories memory; grasu_control::Reference expected; grasu_control::initialize(memory, expected);
    unsigned update_count = 0, request_count = 0; std::array<unsigned, 4> routes{};
    for (unsigned batch = 0; batch < batches.size(); ++batch) {
      std::vector<grasu_control::Request> requests;
      const auto packets = grasu_control::search(batches[batch], requests);
      grasu_control::oracle(expected, batches[batch]);
      const auto counts = grasu_control::update(memory, packets, batches[batch]);
      grasu_control::verify(memory, expected);
      for (unsigned buffer = 0; buffer < 4; ++buffer) routes[buffer] += counts[buffer];
      for (auto value : {batch, unsigned(packets.size()), unsigned(requests.size())}) grasu_control::word(protocol, value);
      for (unsigned i = 0; i < packets.size(); ++i) {
        const auto edge = grasu_control::edge(batches[batch][i]);
        grasu_control::word(protocol, edge); grasu_control::word(protocol, edge >> 32);
        for (unsigned part = 0; part < 3; ++part) grasu_control::word(protocol, packets[i].data.range(part * 32 + 31, part * 32).to_uint());
        grasu_control::word(protocol, grasu_control::route(batches[batch][i].segment));
      }
      for (auto item : requests) for (auto value : {item.kernel, item.lane, item.kind, item.address, unsigned(item.data), unsigned(item.data >> 32)})
        grasu_control::word(protocol, value);
      update_count += packets.size(); request_count += requests.size();
    }
    grasu_control::capture_state(memory, state); protocol.close(); state.close();
    require(protocol.good() && state.good(), "G capture write failure");
    std::cout << "GRASU_PATH {\"case\":" << id << ",\"batches\":" << batches.size() << ",\"updates\":" << update_count
              << ",\"memory_requests\":" << request_count << ",\"route_updates\":[" << routes[0] << ',' << routes[1] << ',' << routes[2] << ',' << routes[3]
              << "],\"checked_buffer_slots\":" << std::uint64_t(batches.size()) * grasu_control::half_segments * 4 * 16
              << ",\"search_lane_end_checks\":" << batches.size() * 4 * 64 * 2
              << ",\"cache_invocations\":" << batches.size() * 2 << ",\"ddr_invocations\":" << batches.size() * 2 << "}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
