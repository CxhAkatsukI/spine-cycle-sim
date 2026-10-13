#pragma once

#include "types.hpp"

namespace search_pipeline {
inline void read_updates(const unsigned long* edges, unsigned count,
                         hls::stream<Raw>& output) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    output.write(edges[i]);
  }
}

inline void distribute(unsigned count, hls::stream<Raw>& input,
                       hls::stream<Raw> edges[lanes],
                       hls::stream<bool> credits[lanes]) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    const ap_uint<6> lane = i;
    if (i >= lanes) credits[lane].read();
    edges[lane].write(input.read());
  }
  for (unsigned lane = 0; lane < lanes; ++lane) {
#pragma HLS PIPELINE II=1
    edges[lane].write(~Raw(0));
  }
}

inline void search(hls::stream<Raw>& edges, hls::stream<Request>& requests,
                   hls::stream<Raw>& responses, hls::stream<Result>& results) {
#pragma HLS INLINE off
  while (true) {
    const Raw raw = edges.read();
    if (raw == ~Raw(0)) break;
    Raw key = raw;
    key[63] = 0;
    Request request = key.range(63, 32);
    requests.write(request);
    const Raw row = responses.read();
    ap_uint<32> begin = row.range(63, 32);
    ap_uint<32> end = row.range(31, 0);
    begin >>= 4; end >>= 4;
    ap_uint<32> mid = (begin + end) >> 1;
    while (begin != mid) {
      request = mid;
      request[32] = 1;
      requests.write(request);
      const Raw value = responses.read();
      if (value <= key) begin = mid;
      else end = mid;
      mid = (begin + end) >> 1;
    }
    Result result = raw;
    result <<= 32;
    Result head = begin;
    head <<= 4;
    results.write(result | head);
  }
  requests.write(end_request());
}

inline void merge(unsigned count, hls::stream<Result> results[lanes],
                  hls::stream<Packet>& output, hls::stream<bool> credits[lanes]) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    const ap_uint<6> lane = i;
    Packet packet;
    packet.data = results[lane].read();
    packet.keep = -1; packet.strb = -1; packet.last = 0;
    output.write(packet);
    if (i + lanes < count) credits[lane].write(true);
  }
}
}  // namespace search_pipeline
