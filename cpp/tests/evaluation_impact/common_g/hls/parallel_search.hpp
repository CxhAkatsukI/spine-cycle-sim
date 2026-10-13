#pragma once

#include <ap_int.h>
#include <ap_axi_sdata.h>
#include <hls_stream.h>

namespace compact_g {
constexpr unsigned lanes = 16;
using Packet = ap_axiu<96, 0, 0, 0>;
using Request = ap_uint<34>;

inline void read_updates(const unsigned long* edges, unsigned count,
                         hls::stream<ap_uint<64>>& output) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    output.write(edges[i]);
  }
}

inline void distribute(unsigned count, hls::stream<ap_uint<64>>& input,
                       hls::stream<ap_uint<64>> edges[lanes],
                       hls::stream<bool> credits[lanes]) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    const unsigned lane = i & (lanes - 1);
    if (i >= lanes) credits[lane].read();
    edges[lane].write(input.read());
  }
  for (unsigned lane = 0; lane < lanes; ++lane) {
#pragma HLS PIPELINE II=1
    edges[lane].write(~ap_uint<64>(0));
  }
}

inline void search(hls::stream<ap_uint<64>>& edges,
                   hls::stream<Request>& requests,
                   hls::stream<ap_uint<64>>& responses,
                   hls::stream<ap_uint<96>>& results) {
#pragma HLS INLINE off
  while (true) {
    const ap_uint<64> raw = edges.read();
    if (raw == ~ap_uint<64>(0)) break;
    ap_uint<64> key = raw;
    key[63] = 0;
    Request request = key.range(63, 32);
    requests.write(request);
    ap_uint<64> row = responses.read();
    ap_uint<32> begin = row.range(63, 32);
    ap_uint<32> end = row.range(31, 0);
    begin >>= 4; end >>= 4;
    ap_uint<32> mid = (begin + end) >> 1;
    while (begin != mid) {
      request = mid;
      request[32] = 1;
      requests.write(request);
      const ap_uint<64> value = responses.read();
      if (value <= key) begin = mid;
      else end = mid;
      mid = (begin + end) >> 1;
    }
    ap_uint<96> result = raw;
    result <<= 32;
    ap_uint<96> head = begin;
    head <<= 4;
    results.write(result | head);
  }
  Request end = 0;
  end[33] = 1;
  requests.write(end);
}

inline ap_uint<4> select_ready(ap_uint<lanes> ready, ap_uint<4> lane) {
#pragma HLS INLINE
  const ap_uint<lanes> rotated = (ready >> lane) | (ready << (lanes - lane));
  ap_uint<16> candidates = rotated;
  ap_uint<4> offset = 0;
  if (candidates.range(7, 0) == 0) { offset[3] = 1; candidates >>= 8; }
  if (candidates.range(3, 0) == 0) { offset[2] = 1; candidates >>= 4; }
  if (candidates.range(1, 0) == 0) { offset[1] = 1; candidates >>= 2; }
  offset[0] = !candidates[0];
  return lane + offset;
}

inline void service(const ap_uint<64>* rows, const ap_uint<64>* binary,
                    hls::stream<Request> requests[lanes],
                    hls::stream<ap_uint<64>> responses[lanes]) {
  ap_uint<lanes> finished = 0;
  ap_uint<4> lane = 0;
  while (finished != ~ap_uint<lanes>(0)) {
#pragma HLS PIPELINE II=1
    ap_uint<lanes> ready = 0;
    for (unsigned index = 0; index < lanes; ++index) {
#pragma HLS UNROLL
      ready[index] = !requests[index].empty();
    }
    if (ready != 0) {
      const ap_uint<4> selected = select_ready(ready, lane);
      const Request request = requests[selected].read();
      if (request[33]) finished[selected] = 1;
      else {
        ap_uint<32> address = request.range(31, 0);
        const ap_uint<64> value = request[32] ? binary[address] : rows[address];
        responses[selected].write(value);
      }
      lane = selected + 1;
    }
  }
}

inline void merge(unsigned count, hls::stream<ap_uint<96>> results[lanes],
                  hls::stream<Packet>& output, hls::stream<bool> credits[lanes]) {
  for (unsigned i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
    const unsigned lane = i & (lanes - 1);
    Packet packet;
    packet.data = results[lane].read();
    packet.keep = -1; packet.strb = -1; packet.last = 0;
    output.write(packet);
    if (i + lanes < count) credits[lane].write(true);
  }
}
}  // namespace compact_g
