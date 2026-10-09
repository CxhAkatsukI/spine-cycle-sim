#include "config.h"
#include <CL/cl_ext_xilinx.h>
#include "probe_support.hpp"
#define main unused_author_device_main
#include "host.cpp"
#undef main
#include <ap_utils.h>

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
#include "grasu_host/input.hpp"
#include "grasu_host/layout.hpp"
#include "grasu_host/search.hpp"
#include "grasu_host/device.hpp"

int main(int argc, char** argv) {
  using namespace grasu_host_control;
  try {
    static_assert(sizeof(unsigned long) == 8 && sizeof(unsigned) == 4);
    require(argc == 3, "usage: G_HOST INPUT OUTPUT_DIRECTORY"); const std::string directory = argv[2];
    const auto input = inspect(argv[1]); unsigned long *initial = nullptr, *updates = nullptr;
    read_dataset(argv[1], initial, updates);
    require(node_size == input.vertices && static_edge_size == input.initial.size() && update_edge_size == input.updates.size(), "G original loader extent");
    require(std::equal(input.initial.begin(), input.initial.end(), initial) && std::equal(input.updates.begin(), input.updates.end(), updates), "G original loader value/order");
    pma_dynamic_graph graph(input.vertices, initial, static_edge_size, updates, update_edge_size);
    const auto counts = verify_layout(input, graph, initial, updates);
    const std::vector<unsigned long> mapped_initial(initial, initial + static_edge_size), mapped_updates(updates, updates + update_edge_size);
    free(initial); free(updates);
    capture(directory, "mapping.u32le", graph.node_map, 4); capture(directory, "row_offsets.u64le", graph.row_offset, 8);
    capture(directory, "binary.u64le", graph.binary_search, 8); capture(directory, "prepared.u64le", graph.data, 8);
    capture(directory, "mapped_initial.u64le", mapped_initial, 8); capture(directory, "mapped_updates.u64le", mapped_updates, 8);
    Flat expected; auto memory = initialize(graph, expected);
    const auto max_occupancy = std::max(counts.max_occupancy, oracle(expected, graph, mapped_updates));
    std::vector<grasu_control::Request> requests; const auto packets = search(graph, mapped_updates, requests);
    const auto routes = grasu_host_control::apply(memory, packets); auto observed = verify(memory, expected);
    unsigned* buffers[4] = {observed[0].data(), observed[1].data(), observed[2].data(), observed[3].data()};
    merge_data(graph, buffers); verify_merged(input, graph, expected); capture(directory, "updated.u64le", graph.data, 8);
    std::ofstream protocol(directory + "/protocol.u32le", std::ios::binary); require(protocol.is_open(), "G host protocol open");
    for (auto value : {0x47485031u, 1u, unsigned(packets.size()), unsigned(requests.size())}) grasu_control::word(protocol, value);
    for (unsigned i = 0; i < packets.size(); ++i) {
      word64(protocol, mapped_updates[i]); for (unsigned part = 0; part < 3; ++part) grasu_control::word(protocol, packets[i].data.range(part * 32 + 31, part * 32).to_uint());
      grasu_control::word(protocol, grasu_control::route(locate(graph, mapped_updates[i])));
    }
    for (auto item : requests) for (auto value : {item.kernel, item.lane, item.kind, item.address, unsigned(item.data), unsigned(item.data >> 32)}) grasu_control::word(protocol, value);
    protocol.close(); require(protocol.good(), "G host protocol write");
    std::uint64_t checked = 0; for (const auto& buffer : expected) checked += buffer.size();
    std::cout << "GRASU_HOST {\"vertices\":" << input.vertices << ",\"initial_edges\":" << input.initial.size()
              << ",\"updates\":" << input.updates.size() << ",\"final_edges\":" << input.final_edges.size()
              << ",\"segments\":" << graph.binary_search.size() << ",\"memory_requests\":" << requests.size()
              << ",\"route_updates\":[" << routes[0] << ',' << routes[1] << ',' << routes[2] << ',' << routes[3]
              << "],\"empty_initial_segments\":" << counts.empty_segments << ",\"full_initial_segments\":" << counts.full_segments
              << ",\"max_occupancy\":" << max_occupancy << ",\"checked_device_slots\":" << checked
              << ",\"defined_padding_bytes\":" << (checked - graph.data.size() * 2) * 4 << "}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
