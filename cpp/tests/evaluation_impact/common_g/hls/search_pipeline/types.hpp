#pragma once

#include <ap_axi_sdata.h>
#include <ap_int.h>
#include <hls_stream.h>

namespace search_pipeline {
constexpr unsigned groups = 8;
constexpr unsigned width = 8;
constexpr unsigned lanes = groups * width;
constexpr unsigned metadata_credits = 32;
using Raw = ap_uint<64>;
using Request = ap_uint<34>;
using TaggedRequest = ap_uint<40>;
using TaggedResponse = ap_uint<71>;
using Result = ap_uint<96>;
using Packet = ap_axiu<96, 0, 0, 0>;

inline Request end_request() {
  Request request = 0;
  request[33] = 1;
  return request;
}

inline ap_uint<3> first_ready(ap_uint<8> ready) {
#pragma HLS INLINE
  ap_uint<3> lane = 0;
  lane[2] = ready.range(3, 0) == 0;
  const ap_uint<4> nibble = lane[2] ? ap_uint<4>(ready.range(7, 4))
                                     : ap_uint<4>(ready.range(3, 0));
  lane[1] = nibble.range(1, 0) == 0;
  const ap_uint<2> pair = lane[1] ? ap_uint<2>(nibble.range(3, 2))
                                   : ap_uint<2>(nibble.range(1, 0));
  lane[0] = !pair[0];
  return lane;
}

inline ap_uint<3> select_ready(ap_uint<8> ready, ap_uint<3> cursor) {
#pragma HLS INLINE
  ap_uint<8> suffix = 0;
  for (unsigned lane = 0; lane < width; ++lane) {
#pragma HLS UNROLL
    suffix[lane] = ready[lane] && cursor <= lane;
  }
  // Encode absolute lanes in parallel, avoiding rotation and a cursor adder.
  const ap_uint<3> wrap = first_ready(ready);
  const ap_uint<3> forward = first_ready(suffix);
  return suffix == 0 ? wrap : forward;
}
}  // namespace search_pipeline
