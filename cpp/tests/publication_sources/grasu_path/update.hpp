#pragma once

namespace grasu_control {
using Memories = std::array<std::vector<ap_uint<512>>, 4>;
using Reference = std::array<std::vector<Slots>, 4>;
inline void initialize(Memories& memory, Reference& expected) {
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    memory[buffer].resize(half_segments); expected[buffer].resize(half_segments);
    for (unsigned index = 0; index < half_segments; ++index) {
      expected[buffer][index] = initial(index * 2 + buffer / 2);
      memory[buffer][index] = packed(expected[buffer][index]);
    }
  }
}
inline void oracle(Reference& expected, const std::vector<Update>& updates) {
  for (auto item : updates) {
    auto& slots = expected[route(item.segment)][item.segment / 2];
    std::vector<unsigned> values;
    for (auto value : slots) if (value != empty_slot) values.push_back(value);
    const auto target = base(item.segment) + item.delta;
    const auto position = std::lower_bound(values.begin(), values.end(), target);
    if (item.deletion) {
      require(position != values.end() && *position == target, "G oracle rejects absent deletion"); values.erase(position);
    } else {
      require(position == values.end() || *position != target, "G oracle rejects duplicate insertion");
      require(values.size() < 16, "G oracle rejects full segment"); values.insert(position, target);
    }
    slots.fill(empty_slot); std::copy(values.begin(), values.end(), slots.begin());
  }
}
inline std::array<unsigned, 4> update(Memories& memory, const std::vector<pipe_type_96>& packets,
                                      const std::vector<Update>& updates) {
  hls::stream<pipe_type_96> inputs[4], outputs[4];
  std::array<std::vector<pipe_type_96>, 4> expected;
  for (unsigned i = 0; i < packets.size(); ++i) { inputs[i % 4].write(packets[i]); expected[route(updates[i].segment)].push_back(packets[i]); }
  author_dispatch::dispatch(packets.size(), inputs[0], inputs[1], inputs[2], inputs[3], outputs[0], outputs[2], outputs[1], outputs[3]);
  std::array<unsigned, 4> counts{};
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    require(inputs[buffer].empty(), "G dispatch input not drained");
    hls::stream<pipe_type_96> checked;
    for (auto packet : expected[buffer]) {
      const auto observed = outputs[buffer].read(); require(observed.data == packet.data, "G dispatch ordering/route mismatch");
      checked.write(observed); ++counts[buffer];
    }
    const auto end = outputs[buffer].read(); require(end.data == END_EDGE && outputs[buffer].empty(), "G dispatch end mismatch");
    checked.write(end);
    if (buffer % 2 == 0) author_cache::process_cache(memory[buffer].data(), checked);
    else author_ddr::process_ddr(memory[buffer].data(), memory[buffer].data(), memory[buffer].data(), memory[buffer].data(), checked);
    require(checked.empty(), "G update input not drained");
  }
  return counts;
}
inline void verify(const Memories& memory, const Reference& expected) {
  for (unsigned buffer = 0; buffer < 4; ++buffer) for (unsigned segment = 0; segment < half_segments; ++segment)
    for (unsigned slot = 0; slot < 16; ++slot)
      require(memory[buffer][segment].range(slot * 32 + 31, slot * 32).to_uint() == expected[buffer][segment][slot],
              "G complete device-buffer state mismatch");
}
inline void capture_state(const Memories& memory, std::ostream& output) {
  for (unsigned segment = 0; segment < segments; ++segment) {
    const auto& value = memory[route(segment)][segment / 2];
    for (unsigned slot = 0; slot < 16; ++slot) word(output, value.range(slot * 32 + 31, slot * 32).to_uint());
  }
}
}  // namespace grasu_control
