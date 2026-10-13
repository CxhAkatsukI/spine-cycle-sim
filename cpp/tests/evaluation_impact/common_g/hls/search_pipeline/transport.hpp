#pragma once

#include "types.hpp"

namespace search_pipeline {
inline void gather_group(unsigned group, hls::stream<Request> requests[width],
                         hls::stream<TaggedRequest>& output) {
#pragma HLS INLINE off
  ap_uint<8> finished = 0;
  ap_uint<3> cursor = 0;
  while (finished != ap_uint<8>(255)) {
#pragma HLS PIPELINE II=1
    ap_uint<8> ready = 0;
    for (unsigned lane = 0; lane < width; ++lane) {
#pragma HLS UNROLL
      ready[lane] = !requests[lane].empty();
    }
    if (ready != 0) {
      const ap_uint<3> lane = select_ready(ready, cursor);
      const Request request = requests[lane].read();
      if (request[33]) finished[lane] = 1;
      else {
        TaggedRequest tagged = request;
        tagged.range(39, 34) = group * width + lane;
        output.write(tagged);
      }
      cursor = lane + 1;
    }
  }
  output.write(TaggedRequest(end_request()));
}

inline void gather(hls::stream<TaggedRequest> input[groups],
                   hls::stream<TaggedRequest>& output) {
#pragma HLS INLINE off
  ap_uint<8> finished = 0;
  ap_uint<3> cursor = 0;
  while (finished != ap_uint<8>(255)) {
#pragma HLS PIPELINE II=1
    ap_uint<8> ready = 0;
    for (unsigned group = 0; group < groups; ++group) {
#pragma HLS UNROLL
      ready[group] = !input[group].empty();
    }
    if (ready != 0) {
      const ap_uint<3> group = select_ready(ready, cursor);
      const TaggedRequest request = input[group].read();
      if (request[33]) finished[group] = 1;
      else output.write(request);
      cursor = group + 1;
    }
  }
  output.write(TaggedRequest(end_request()));
}

inline void memory(const Raw* rows, const Raw* binary,
                   hls::stream<TaggedRequest>& input,
                   hls::stream<TaggedResponse>& output) {
#pragma HLS INLINE off
  while (true) {
#pragma HLS PIPELINE II=1
    const TaggedRequest request = input.read();
    if (request[33]) break;
    const ap_uint<32> address = request.range(31, 0);
    TaggedResponse response = request[32] ? binary[address] : rows[address];
    response.range(69, 64) = request.range(39, 34);
    output.write(response);
  }
  TaggedResponse end = 0;
  end[70] = 1;
  output.write(end);
}

inline void scatter(hls::stream<TaggedResponse>& input,
                    hls::stream<TaggedResponse> output[groups]) {
#pragma HLS INLINE off
  while (true) {
#pragma HLS PIPELINE II=1
    const TaggedResponse response = input.read();
    if (response[70]) {
      for (unsigned group = 0; group < groups; ++group) {
#pragma HLS UNROLL
        output[group].write(response);
      }
      break;
    }
    const ap_uint<3> group = response.range(69, 67);
    output[group].write(response);
  }
}

inline void scatter_group(hls::stream<TaggedResponse>& input,
                          hls::stream<Raw> output[width]) {
#pragma HLS INLINE off
  while (true) {
#pragma HLS PIPELINE II=1
    const TaggedResponse response = input.read();
    if (response[70]) break;
    const ap_uint<3> lane = response.range(66, 64);
    output[lane].write(Raw(response.range(63, 0)));
  }
}
}  // namespace search_pipeline
