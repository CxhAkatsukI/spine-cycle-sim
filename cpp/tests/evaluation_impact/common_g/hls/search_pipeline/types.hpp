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

inline ap_uint<3> select_ready(ap_uint<8> ready, ap_uint<3> cursor) {
#pragma HLS INLINE
  const ap_uint<8> rotated = (ready >> cursor) | (ready << (8 - cursor));
  ap_uint<8> candidates = rotated;
  ap_uint<3> offset = 0;
  if (candidates.range(3, 0) == 0) { offset[2] = 1; candidates >>= 4; }
  if (candidates.range(1, 0) == 0) { offset[1] = 1; candidates >>= 2; }
  offset[0] = !candidates[0];
  return cursor + offset;
}
}  // namespace search_pipeline
