#include "../input.hpp"
#include "parallel_search.hpp"

#include <iostream>

namespace {
void check_arbiter() {
  for (unsigned ready = 1; ready < (1u << compact_g::lanes); ++ready) {
    for (unsigned lane = 0; lane < compact_g::lanes; ++lane) {
      unsigned expected = lane;
      while (!(ready & (1u << expected))) expected = (expected + 1) % compact_g::lanes;
      if (compact_g::select_ready(ready, lane).to_uint() != expected)
        throw std::runtime_error("HLS arbiter differs from work-conserving round robin");
    }
  }
  ap_uint<64> rows[16], binary[16];
  hls::stream<compact_g::Request> requests[compact_g::lanes];
  hls::stream<ap_uint<64>> responses[compact_g::lanes];
  for (unsigned lane = 0; lane < compact_g::lanes; ++lane) {
    rows[lane] = lane + 100; binary[lane] = lane + 200;
    requests[lane].write(lane);
    requests[lane].write((std::uint64_t{1} << 32) | lane);
    requests[lane].write(std::uint64_t{1} << 33);
  }
  compact_g::service(rows, binary, requests, responses);
  for (unsigned lane = 0; lane < compact_g::lanes; ++lane)
    if (responses[lane].read() != rows[lane] || responses[lane].read() != binary[lane] ||
        !responses[lane].empty() || !requests[lane].empty())
      throw std::runtime_error("HLS metadata service did not conserve responses");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("expected common G input path");
    const common_g::Fixture fixture(argv[1]);
    const auto& batch = fixture.batches.at(0).updates;
    if (batch.empty()) check_arbiter();
    std::uint64_t rows = 0, probes = 0;
    // Preload only oracle responses, then check every HLS request in order.
    for (unsigned cu = 0; cu < 4; ++cu) {
      hls::stream<ap_uint<96>> results[compact_g::lanes];
      hls::stream<bool> credits[compact_g::lanes];
      for (unsigned lane = 0; lane < compact_g::lanes; ++lane) {
        hls::stream<ap_uint<64>> edges, responses;
        hls::stream<compact_g::Request> requests;
        std::vector<std::uint64_t> expected_requests;
        for (std::size_t local = lane; cu + local * 4 < batch.size(); local += compact_g::lanes) {
          const auto raw = batch[cu + local * 4];
          const auto key = raw & ~(std::uint64_t{1} << 63);
          const auto source = key >> 32;
          const auto row = common_g::g::little_word(std::span(fixture.rows).subspan(source * 8, 8));
          edges.write(raw); responses.write(row); expected_requests.push_back(source); ++rows;
          auto begin = static_cast<std::uint32_t>(row >> 32) >> 4;
          auto end = static_cast<std::uint32_t>(row) >> 4;
          for (auto mid = (begin + end) >> 1; begin != mid; mid = (begin + end) >> 1) {
            const auto value = common_g::g::little_word(std::span(fixture.binary).subspan(mid * 8, 8));
            responses.write(value); expected_requests.push_back((std::uint64_t{1} << 32) | mid); ++probes;
            if (value <= key) begin = mid;
            else end = mid;
          }
        }
        edges.write(~ap_uint<64>(0));
        compact_g::search(edges, requests, responses, results[lane]);
        for (const auto expected : expected_requests)
          if (requests.empty() || requests.read().to_uint64() != expected)
            throw std::runtime_error("HLS source search request mismatch");
        if (requests.read().to_uint64() != (std::uint64_t{1} << 33) ||
            !requests.empty() || !responses.empty() || !edges.empty())
          throw std::runtime_error("HLS source lane did not drain");
      }
      hls::stream<compact_g::Packet> output;
      const unsigned count = (batch.size() + 3 - cu) / 4;
      compact_g::merge(count, results, output, credits);
      for (unsigned local = 0; local < count; ++local) {
        const auto raw = batch[cu + local * 4];
        const auto key = raw & ~(std::uint64_t{1} << 63);
        const auto row = common_g::g::little_word(std::span(fixture.rows).subspan((key >> 32) * 8, 8));
        auto begin = static_cast<std::uint32_t>(row >> 32) >> 4;
        auto end = static_cast<std::uint32_t>(row) >> 4;
        for (auto mid = (begin + end) >> 1; begin != mid; mid = (begin + end) >> 1) {
          const auto value = common_g::g::little_word(std::span(fixture.binary).subspan(mid * 8, 8));
          if (value <= key) begin = mid; else end = mid;
        }
        const auto packet = output.read();
        if (packet.data.range(95, 32).to_uint64() != raw ||
            packet.data.range(31, 0).to_uint() != begin * 16 ||
            packet.keep != decltype(packet.keep)(-1) || packet.strb != decltype(packet.strb)(-1) || packet.last)
          throw std::runtime_error("HLS source ordered packet mismatch cu=" + std::to_string(cu) +
              " local=" + std::to_string(local) + " raw=" + std::to_string(raw) +
              " actual_raw=" + std::to_string(packet.data.range(95, 32).to_uint64()) +
              " head=" + std::to_string(begin * 16) +
              " actual_head=" + std::to_string(packet.data.range(31, 0).to_uint()) +
              " keep=" + std::to_string(packet.keep.to_uint()) +
              " strb=" + std::to_string(packet.strb.to_uint()) +
              " last=" + std::to_string(packet.last.to_uint()));
      }
      for (unsigned lane = 0; lane < compact_g::lanes; ++lane) {
        if (!results[lane].empty()) throw std::runtime_error("HLS results left over");
        unsigned returned = 0;
        while (!credits[lane].empty()) {
          if (!credits[lane].read()) throw std::runtime_error("false HLS credit");
          ++returned;
        }
        const unsigned assigned = count > lane ? (count - lane + compact_g::lanes - 1) / compact_g::lanes : 0;
        if (returned != (assigned ? assigned - 1 : 0))
          throw std::runtime_error("HLS credit count mismatch");
      }
      if (!output.empty()) throw std::runtime_error("HLS output left over");
    }
    std::cout << "G_SEARCH_SOURCE_PASS rows=" << rows << " probes=" << probes
              << " host_vendor_keep_bits=" << compact_g::Packet::width_keep << '\n';
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
