#pragma once

#include "fixture.hpp"

namespace weighted_control {
class Responses final : public hls::stream_delegate<sizeof(ap_uint<32>)> {
 public:
  Responses(const std::vector<std::uint64_t>& memory, hls::stream<ap_uint<64>>& output)
      : memory_(memory), output_(output) {}
  bool read(void*) override { throw std::runtime_error("request is write-only"); }
  bool read_nb(void*) override { throw std::runtime_error("request is write-only"); }
  std::size_t size() override { return 0; }
  void write(const void* pointer) override {
    const auto address = static_cast<const ap_uint<32>*>(pointer)->to_uint();
    require(!ended, "request after end");
    if (address == END_INDEX) ended = true;
    else { output_.write(memory_.at(address)); addresses.push_back(address); }
  }
  bool ended = false;
  std::vector<unsigned> addresses;
 private:
  const std::vector<std::uint64_t>& memory_;
  hls::stream<ap_uint<64>>& output_;
};
inline pipe_type_96 search(const host::WeightedPmaShard& shard, std::uint64_t raw) {
  hls::stream<ap_uint<32>> binary_requests, row_requests;
  hls::stream<ap_uint<64>> binary_responses, row_responses, edges;
  hls::stream<ap_uint<96>> results;
  Responses binary(shard.binary_heads, binary_responses), rows(shard.row_bounds, row_responses);
  binary_requests.set_delegate(&binary); row_requests.set_delegate(&rows);
  edges.write(raw); edges.write(END_EDGE);
  author_search::binary_search(binary_requests, binary_responses, row_requests,
                               row_responses, edges, results);
  require(binary.ended && rows.ended && binary_responses.empty() && row_responses.empty()
          && edges.empty() && results.size() == 1, "search stream conservation");
  const auto key = raw & ~(std::uint64_t{1} << 63);
  const auto source = key >> 32;
  require(rows.addresses == std::vector<unsigned>{unsigned(source)}, "search row address");
  const auto row = shard.row_bounds.at(source);
  auto first = shard.binary_heads.begin() + (row >> 32) / 16;
  auto last = shard.binary_heads.begin() + unsigned(row) / 16;
  const auto found = std::upper_bound(first, last, key);
  require(found != first, "search key below first reserved head");
  const auto segment = unsigned(found - shard.binary_heads.begin() - 1);
  pipe_type_96 packet;
  packet.data = results.read(); packet.keep = -1; packet.strb = -1; packet.last = 0;
  require(packet.data.range(95, 32).to_uint64() == raw &&
          packet.data.range(31, 0).to_uint() == segment * 16, "weighted search head/payload");
  return packet;
}
inline void check_dispatch_boundary() {
  hls::stream<pipe_type_96> input[4], output[4];
  const std::array<unsigned, 4> segments{0, 1, MAX_CACHE_SEGMENT * 2,
                                       MAX_CACHE_SEGMENT * 2 + 1};
  for (unsigned i = 0; i < 4; ++i) {
    pipe_type_96 packet; packet.data = segments[i] * 16;
    packet.data.range(95, 32) = std::uint64_t{0x8123456700080001};
    input[i].write(packet);
  }
  current_dispatch::dispatch(4, input[0], input[1], input[2], input[3],
                            output[0], output[2], output[1], output[3]);
  for (unsigned buffer = 0; buffer < 4; ++buffer) {
    const unsigned original = buffer == 1 ? 2 : buffer == 2 ? 1 : buffer;
    auto packet = output[buffer].read();
    require(packet.data.range(31, 0).to_uint() == segments[original] * 16 &&
            packet.data.range(95, 32).to_uint64() == 0x8123456700080001ULL,
            "dispatch cache/DDR or even/odd boundary");
    require(output[buffer].read().data == END_EDGE && output[buffer].empty()
            && input[buffer].empty(), "dispatch boundary drain");
  }
}
}  // namespace weighted_control
