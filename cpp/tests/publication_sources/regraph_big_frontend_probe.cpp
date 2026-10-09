#include "probe_support.hpp"
#include "acc_data_types.h"
#include "acc_scatter.h"
#include "hbm_wrapper.h"

#include <fstream>

namespace {
void word(std::ostream& output, std::uint32_t value) {
  for (unsigned byte = 0; byte < 4; ++byte) output.put(static_cast<char>((value >> (8 * byte)) & 255u));
}
void run_case(unsigned id, std::ostream& capture) {
  const unsigned bursts = id == 4 ? 1 : (id == 0 ? 8 : 64);
  const unsigned offset = id == 5 ? 65536 : 0;
  std::vector<edge_burst_dt> input(bursts);
  for (unsigned burst = 0; burst < bursts; ++burst) for (unsigned lane = 0; lane < 8; ++lane) {
    const auto index = burst * 8 + lane;
    unsigned source = 0;
    if (id == 0) source = index / 8;
    else if (id == 1) source = index * 13;
    else if (id == 2) source = (17 + burst / 2) * 16 + (burst % 2) * 4 + lane / 2;
    else if (id == 3) source = (burst / 4) * 8192 + (burst % 4) * 64 + lane * 3;
    else if (id == 5) source = 4096 + (index / 2) * 17;
    const unsigned destination = id == 4 ? 0xffffffffu : static_cast<unsigned>((index * 7919ull) % 524288) + offset;
    input[burst].edges[lane].src = id == 4 ? 0x80000000u : source;
    input[burst].edges[lane].dst = destination;
  }
  if (id != 4) for (unsigned lane = 4; lane < 8; ++lane) {
    input.back().edges[lane].src = input.back().edges[3].src | 0x80000000u;
    input.back().edges[lane].dst = 0xffffffffu;
  }
  hls::stream<src_burst_dt> sources;
  hls::stream<edge_burst_dt> edges;
  for (auto burst : input) {
    src_burst_dt src{};
    for (unsigned lane = 0; lane < 8; ++lane) {
      src.src[lane] = burst.edges[lane].src;
      ap_uint<20> local = burst.edges[lane].dst.range(30, 0) - offset;
      local.range(19, 19) = burst.edges[lane].dst.range(31, 31);
      burst.edges[lane].dst = local;
    }
    sources.write(src); edges.write(burst);
  }
  hls::stream<mem_request_burst_dt> batches;
  hls::stream<cacheline_dt> requests;
  genMemRequest(sources, batches, bursts * 8);
  sendCachelineRequest(batches, requests);
  std::vector<cacheline_dt> observed_requests;
  hls::stream<b_cacheline_request_pkt> wrapper_requests;
  while (!requests.empty()) {
    auto request = requests.read();
    // The first lane and the end address are unused/uninitialized in source.
    if (observed_requests.empty()) request.dst = 0;
    if (request.end_flag) request.idx = 0;
    observed_requests.push_back(request);
    b_cacheline_request_pkt packet{};
    packet.data = request.idx; packet.dest = request.dst; packet.last = request.end_flag;
    wrapper_requests.write(packet);
  }
  std::vector<ap_uint<512>> properties(131072 / 16);
  for (unsigned line = 0; line < properties.size(); ++line) for (unsigned index = 0; index < 16; ++index) {
    properties[line].range(index * 32 + 31, index * 32) = 17 + line * 16 + index;
  }
  hls::stream<b_cacheline_response_pkt> wrapper_responses;
  bigKernelReadMemory<0>(0, properties.data(), 1, wrapper_requests, wrapper_responses);
  std::vector<b_cacheline_response_pkt> observed_responses;
  hls::stream<cacheline_response_dt> responses;
  while (!wrapper_responses.empty()) {
    auto response = wrapper_responses.read(); observed_responses.push_back(response);
    cacheline_response_dt value{};
    value.data = response.data; value.dst = response.dest; value.end_flag = response.last;
    responses.write(value);
  }
  hls::stream<ap_uint<512>> lanes[8];
  hls::stream<update_set_dt> output;
  receiveResponses(responses, lanes);
  accScatter(lanes, edges, output, bursts * 8);
  require(sources.empty() && batches.empty() && edges.empty() && responses.empty() && wrapper_requests.empty(),
          "Big source protocol stream conservation");
  for (auto& lane : lanes) require(lane.empty(), "Big lane response conservation");
  require(output.size() == bursts && observed_requests.size() == observed_responses.size(), "Big source output extent");
  word(capture, id); word(capture, offset); word(capture, bursts);
  word(capture, observed_requests.size()); word(capture, observed_responses.size());
  for (const auto request : observed_requests) {
    word(capture, request.idx.to_uint()); word(capture, request.dst.to_uint()); word(capture, request.end_flag);
  }
  for (const auto response : observed_responses) {
    word(capture, response.dest.to_uint()); word(capture, response.last.to_uint());
    for (unsigned index = 0; index < 16; ++index) word(capture, response.data.range(index * 32 + 31, index * 32).to_uint());
  }
  while (!output.empty()) {
    const auto value = output.read();
    for (unsigned lane = 0; lane < 8; ++lane) {
      word(capture, value.tuples[lane].dst.to_uint()); word(capture, value.tuples[lane].update.to_uint());
    }
  }
  std::cout << "BIG_FRONTEND_SOURCE {\"case\":" << id << ",\"bursts\":" << bursts
            << ",\"requests_including_end\":" << observed_requests.size() << "}\n";
}
}  // namespace
int main(int argc, char** argv) {
  try {
    require(argc == 2, "expected Big source capture path");
    std::ofstream capture(argv[1], std::ios::binary); require(capture.is_open(), "cannot create Big source capture");
    word(capture, 0x42534631); word(capture, 1); word(capture, 6); word(capture, 0);
    for (unsigned id = 0; id < 6; ++id) run_case(id, capture);
    capture.close(); require(capture.good(), "Big source capture write failed"); return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
