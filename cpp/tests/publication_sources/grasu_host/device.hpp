#pragma once

namespace grasu_host_control {
using Memories = std::array<std::vector<ap_uint<512>>, 4>;
using Flat = std::array<std::vector<unsigned>, 4>;
inline Memories initialize(const pma_dynamic_graph& graph, Flat& expected) {
  Memories memory;
  std::array<unsigned, 16> padding; padding.fill(grasu_control::empty_slot);
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    const auto count = std::max<unsigned>(MAX_CACHE_SEGMENT, (graph.data.size() / 16 + (buffer / 2 == 0)) / 2);
    memory[buffer].assign(count, grasu_control::packed(padding)); expected[buffer].assign(count * 16, grasu_control::empty_slot);
  }
  for (unsigned i = 0; i < graph.data.size(); ++i) {
    const auto segment = i / 16, half = segment % 2, index = segment / 2 * 16 + i % 16;
    const unsigned value = graph.data[i] == EMPTY ? grasu_control::empty_slot : unsigned(graph.data[i]);
    for (unsigned copy = 0; copy < 2; ++copy) {
      const auto buffer = half * 2 + copy; expected[buffer][index] = value;
      memory[buffer][index / 16].range((index % 16) * 32 + 31, (index % 16) * 32) = value;
    }
  }
  return memory;
}
inline unsigned oracle(Flat& expected, const pma_dynamic_graph& graph, const std::vector<unsigned long>& updates) {
  unsigned maximum = 0;
  for (auto edge : updates) {
    const auto segment = locate(graph, edge), buffer = grasu_control::route(segment), index = segment / 2 * 16;
    std::vector<unsigned> values;
    for (unsigned i = 0; i < 16; ++i) if (expected[buffer][index + i] != grasu_control::empty_slot) values.push_back(expected[buffer][index + i]);
    const unsigned target = edge;
    const auto position = std::lower_bound(values.begin(), values.end(), target);
    if (edge & EMPTY) { require(position != values.end() && *position == target, "G mapped absent deletion"); values.erase(position); }
    else { require(values.size() < 16 && (position == values.end() || *position != target), "G mapped invalid insertion"); values.insert(position, target); }
    maximum = std::max(maximum, unsigned(values.size()));
    for (unsigned i = 0; i < 16; ++i) expected[buffer][index + i] = i < values.size() ? values[i] : grasu_control::empty_slot;
  }
  return maximum;
}
inline std::array<unsigned, 4> apply(Memories& memory, const std::vector<pipe_type_96>& packets) {
  hls::stream<pipe_type_96> input[4], output[4]; std::array<std::vector<ap_uint<96>>, 4> buckets;
  for (unsigned i = 0; i < packets.size(); ++i) {
    input[i % 4].write(packets[i]); buckets[grasu_control::route(packets[i].data.range(31, 0).to_uint() / 16)].push_back(packets[i].data);
  }
  author_dispatch::dispatch(packets.size(), input[0], input[1], input[2], input[3], output[0], output[2], output[1], output[3]);
  std::array<unsigned, 4> counts{};
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    require(input[buffer].empty(), "G host dispatch input drain"); hls::stream<pipe_type_96> checked;
    for (auto expected : buckets[buffer]) {
      const auto packet = output[buffer].read(); require(packet.data == expected, "G host dispatch route/order"); checked.write(packet); ++counts[buffer];
    }
    const auto end = output[buffer].read(); require(end.data == END_EDGE && output[buffer].empty(), "G host dispatch end"); checked.write(end);
    if (buffer % 2 == 0) author_cache::process_cache(memory[buffer].data(), checked);
    else author_ddr::process_ddr(memory[buffer].data(), memory[buffer].data(), memory[buffer].data(), memory[buffer].data(), checked);
    require(checked.empty(), "G host update drain");
  }
  return counts;
}
inline Flat verify(const Memories& memory, const Flat& expected) {
  Flat observed;
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    observed[buffer].resize(expected[buffer].size());
    for (unsigned i = 0; i < expected[buffer].size(); ++i) {
      const auto value = memory[buffer][i / 16].range((i % 16) * 32 + 31, (i % 16) * 32).to_uint();
      require(value == expected[buffer][i], "G host full device-buffer state mismatch"); observed[buffer][i] = value;
    }
  }
  return observed;
}
inline void verify_merged(const Input& input, const pma_dynamic_graph& graph, const Flat& expected) {
  std::vector<unsigned> inverse(input.vertices);
  for (unsigned i = 0; i < input.vertices; ++i) inverse[graph.node_map[i]] = i;
  std::set<unsigned long> restored;
  for (unsigned vertex = 0; vertex < input.vertices; ++vertex) for (unsigned i = graph.row_offset[vertex]; i < graph.row_offset[vertex + 1]; ++i) {
    const auto segment = i / 16, buffer = grasu_control::route(segment);
    const auto value = expected[buffer][segment / 2 * 16 + i % 16];
    const auto reference = value == grasu_control::empty_slot ? EMPTY : (std::uint64_t(vertex) << 32) | value;
    require(graph.data[i] == reference, "G original merge slot mismatch");
    if (reference != EMPTY) require(restored.insert((std::uint64_t(inverse[vertex]) << 32) | inverse.at(value)).second, "G restored duplicate edge");
  }
  require(restored == input.final_edges, "G complete external graph mismatch");
}
}  // namespace grasu_host_control
