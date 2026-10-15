#pragma once

#include "types.hpp"
#include "search_worker.hpp"

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
