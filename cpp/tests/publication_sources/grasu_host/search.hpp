#pragma once

namespace grasu_host_control {
inline std::vector<pipe_type_96> search(const pma_dynamic_graph& graph, const std::vector<unsigned long>& updates,
                                      std::vector<grasu_control::Request>& log) {
  std::vector<ap_uint<64>> binary(graph.binary_search.begin(), graph.binary_search.end()), offsets(graph.node_size);
  for (unsigned i = 0; i < graph.node_size; ++i) {
    require(graph.row_offset[i + 1] < (std::uint64_t{1} << 32), "G search row ABI overflow");
    offsets[i] = (graph.row_offset[i] << 32) | graph.row_offset[i + 1];
  }
  std::array<std::vector<pipe_type_96>, 4> output;
  for (unsigned kernel = 0; kernel < 4; ++kernel) {
    std::vector<unsigned long> input;
    for (unsigned i = kernel; i < updates.size(); i += 4) input.push_back(updates[i]);
    hls::stream<ap_uint<64>> edges[64]; hls::stream<ap_uint<96>> results[64];
    author_search::read_edges(input.data(), input.size(), edges);
    for (unsigned lane = 0; lane < 64; ++lane) {
      hls::stream<ap_uint<32>> ba, oa; hls::stream<ap_uint<64>> bd, od;
      grasu_control::MemoryRequests b(kernel, lane, 1, binary, bd, log), o(kernel, lane, 0, offsets, od, log);
      ba.set_delegate(&b); oa.set_delegate(&o);
      author_search::binary_search(ba, bd, oa, od, edges[lane], results[lane]);
      require(edges[lane].empty() && bd.empty() && od.empty() && b.ended && o.ended, "G host search conservation/end");
    }
    hls::stream<pipe_type_96> merged;
    author_search::merge_updates(input.size(), results, merged);
    for (auto& stream : results) require(stream.empty(), "G host search merge drain");
    while (!merged.empty()) output[kernel].push_back(merged.read());
    for (unsigned group = 0; group < 4; ++group) for (unsigned kind = 0; kind < 2; ++kind)
      grasu_control::check_bipa(log, kernel, group, kind, kind ? binary : offsets);
  }
  std::vector<pipe_type_96> result;
  for (unsigned i = 0; i < updates.size(); ++i) {
    const auto packet = output[i % 4].at(i / 4);
    require(packet.data.range(95, 32).to_uint64() == updates[i] && packet.data.range(31, 0).to_uint() == locate(graph, updates[i]) * 16,
            "G host searched packet mismatch");
    result.push_back(packet);
  }
  return result;
}
}  // namespace grasu_host_control
