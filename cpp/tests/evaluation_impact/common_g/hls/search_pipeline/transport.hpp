#pragma once

#include "types.hpp"

namespace search_pipeline {
inline void gather_group(unsigned group, hls::stream<Request> requests[width],
                         hls::stream<TaggedRequest>& output) {
#pragma HLS INLINE off
  ap_uint<8> finished = 0;
  ap_uint<3> cursor = 0;
  ap_uint<3> selected = 0;
  bool pending = false;
  bool done = false;
  while (!done) {
#pragma HLS PIPELINE off
    if (!pending) {
      ap_uint<8> ready = 0;
      for (unsigned lane = 0; lane < width; ++lane) {
#pragma HLS UNROLL
        ready[lane] = !requests[lane].empty();
      }
      if (ready != 0) {
        selected = select_ready(ready, cursor);
        pending = true;
      }
    } else {
      // This is the sole reader: a selected nonempty FIFO stays readable.
      const Request request = requests[selected].read();
      if (request[33]) {
        finished[selected] = 1;
        done = finished == ap_uint<8>(255);
      }
      else {
        TaggedRequest tagged = request;
        tagged.range(39, 34) = group * width + selected;
        output.write(tagged);
      }
      cursor = selected + 1;
      pending = false;
    }
  }
  output.write(TaggedRequest(end_request()));
}

inline void gather(hls::stream<TaggedRequest> input[groups],
                   hls::stream<TaggedRequest>& output) {
#pragma HLS INLINE off
  ap_uint<8> finished = 0;
  ap_uint<3> cursor = 0;
  ap_uint<3> selected = 0;
  bool pending = false;
  bool done = false;
  while (!done) {
#pragma HLS PIPELINE off
    if (!pending) {
      ap_uint<8> ready = 0;
      for (unsigned group = 0; group < groups; ++group) {
#pragma HLS UNROLL
        ready[group] = !input[group].empty();
      }
      if (ready != 0) {
        selected = select_ready(ready, cursor);
        pending = true;
      }
    } else {
      const TaggedRequest request = input[selected].read();
      if (request[33]) {
        finished[selected] = 1;
        done = finished == ap_uint<8>(255);
      }
      else output.write(request);
      cursor = selected + 1;
      pending = false;
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
    // Empty input must insert a bubble, not stall an in-flight AXI response.
    TaggedRequest request;
    if (!input.read_nb(request)) continue;
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
    TaggedResponse response;
    if (!input.read_nb(response)) continue;
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
    TaggedResponse response;
    if (!input.read_nb(response)) continue;
    if (response[70]) break;
    const ap_uint<3> lane = response.range(66, 64);
    output[lane].write(Raw(response.range(63, 0)));
  }
}
}  // namespace search_pipeline
