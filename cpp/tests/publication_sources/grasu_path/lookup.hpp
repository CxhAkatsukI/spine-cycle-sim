#pragma once

#include <algorithm>

namespace grasu_control {
struct Request { unsigned kernel, lane, kind, address; std::uint64_t data; };
class MemoryRequests final : public hls::stream_delegate<sizeof(ap_uint<32>)> {
 public:
  MemoryRequests(unsigned kernel, unsigned lane, unsigned kind, const std::vector<ap_uint<64>>& memory,
                 hls::stream<ap_uint<64>>& responses, std::vector<Request>& log)
      : kernel_(kernel), lane_(lane), kind_(kind), memory_(memory), responses_(responses), log_(log) {}
  bool read(void*) override { throw std::runtime_error("G memory request is write-only"); }
  bool read_nb(void*) override { throw std::runtime_error("G memory request is write-only"); }
  std::size_t size() override { return 0; }
  void write(const void* pointer) override {
    const auto address = static_cast<const ap_uint<32>*>(pointer)->to_uint();
    require(!ended, "G request after end");
    if (address == END_INDEX) { ended = true; return; }
    require(address < memory_.size(), "G search memory address outside table");
    const auto value = memory_[address]; responses_.write(value);
    log_.push_back({kernel_, lane_, kind_, address, value.to_uint64()});
  }
  bool ended = false;
 private:
  unsigned kernel_, lane_, kind_;
  const std::vector<ap_uint<64>>& memory_;
  hls::stream<ap_uint<64>>& responses_;
  std::vector<Request>& log_;
};

inline void check_bipa(const std::vector<Request>& log, unsigned kernel, unsigned group, unsigned kind,
                       const std::vector<ap_uint<64>>& memory) {
  hls::stream<ap_uint<32>> addresses[16]; hls::stream<ap_uint<64>> responses[16];
  std::array<std::vector<std::uint64_t>, 16> expected;
  for (auto item : log) if (item.kernel == kernel && item.lane / 16 == group && item.kind == kind) {
    addresses[item.lane % 16].write(item.address); expected[item.lane % 16].push_back(item.data);
  }
  for (auto& stream : addresses) stream.write(END_INDEX);
  author_search::bipa(memory.data(), addresses, responses);
  for (unsigned lane = 0; lane < 16; ++lane) {
    require(addresses[lane].empty(), "G BIPA input conservation");
    for (auto value : expected[lane]) require(responses[lane].read().to_uint64() == value, "G BIPA response mismatch");
    require(responses[lane].empty(), "G BIPA output conservation");
  }
}

inline std::vector<pipe_type_96> search(const std::vector<Update>& updates, std::vector<Request>& log) {
  std::vector<ap_uint<64>> binary(segments), offsets(2);
  for (unsigned i = 0; i < segments; ++i) binary[i] = (std::uint64_t(source(i)) << 32) + base(i) + 10;
  offsets[0] = hot_segments * 2 * 16;
  offsets[1] = (std::uint64_t(hot_segments * 2 * 16) << 32) + segments * 16;
  std::array<std::vector<pipe_type_96>, 4> output;
  for (unsigned kernel = 0; kernel < 4; ++kernel) {
    std::vector<unsigned long> input;
    for (unsigned i = kernel; i < updates.size(); i += 4) input.push_back(edge(updates[i]));
    hls::stream<ap_uint<64>> edges[64]; hls::stream<ap_uint<96>> results[64];
    author_search::read_edges(input.data(), input.size(), edges);
    for (unsigned lane = 0; lane < 64; ++lane) {
      hls::stream<ap_uint<32>> ba, oa; hls::stream<ap_uint<64>> bd, od;
      MemoryRequests binary_requests(kernel, lane, 1, binary, bd, log), offset_requests(kernel, lane, 0, offsets, od, log);
      ba.set_delegate(&binary_requests); oa.set_delegate(&offset_requests);
      author_search::binary_search(ba, bd, oa, od, edges[lane], results[lane]);
      require(edges[lane].empty() && bd.empty() && od.empty() && binary_requests.ended && offset_requests.ended,
              "G binary-search stream conservation/end mismatch");
    }
    hls::stream<pipe_type_96> merged;
    author_search::merge_updates(input.size(), results, merged);
    for (auto& stream : results) require(stream.empty(), "G search merge input not drained");
    while (!merged.empty()) output[kernel].push_back(merged.read());
    for (unsigned group = 0; group < 4; ++group) for (unsigned kind = 0; kind < 2; ++kind)
      check_bipa(log, kernel, group, kind, kind ? binary : offsets);
  }
  std::vector<pipe_type_96> result;
  for (unsigned i = 0; i < updates.size(); ++i) {
    const auto packet = output[i % 4].at(i / 4);
    // Search-table upper_bound is independent of the author's iterative binary search.
    const auto item = updates[i]; const auto first = source(item.segment) ? hot_segments * 2 : 0;
    const auto last = source(item.segment) ? segments : hot_segments * 2;
    const auto key = edge(item) & ~(std::uint64_t{1} << 63);
    const auto found = std::upper_bound(binary.begin() + first, binary.begin() + last, ap_uint<64>(key));
    require(found != binary.begin() + first && unsigned(found - binary.begin() - 1) == item.segment, "G fixture search admission");
    require(packet.data.range(31, 0).to_uint() == item.segment * 16 &&
            packet.data.range(95, 32).to_uint64() == edge(item), "G search packet mismatch");
    result.push_back(packet);
  }
  return result;
}
}  // namespace grasu_control
