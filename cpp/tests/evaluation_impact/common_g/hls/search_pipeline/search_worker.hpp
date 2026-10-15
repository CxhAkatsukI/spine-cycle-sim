#pragma once

#include "types.hpp"

namespace search_pipeline {
enum class SearchPhase : unsigned char {
  input, row_request, row_response, row_decode, binary_request,
  binary_response, binary_compare, midpoint, choose, emit, end
};

inline void search(hls::stream<Raw>& edges, hls::stream<Request>& requests,
                   hls::stream<Raw>& responses, hls::stream<Result>& results) {
#pragma HLS INLINE off
  SearchPhase phase = SearchPhase::input;
  Raw raw = 0, key = 0, metadata = 0;
  ap_uint<32> begin = 0, end = 0, mid = 0;
  // Overlapping loop iterations can let an empty response FIFO stall the
  // preceding request write. Context-level parallelism is provided by 64 workers.
  while (true) {
#pragma HLS PIPELINE off
    switch (phase) {
    case SearchPhase::input:
      raw = edges.read();
      key = raw;
      key[63] = 0;
      phase = raw == ~Raw(0) ? SearchPhase::end : SearchPhase::row_request;
      break;
    case SearchPhase::row_request:
      requests.write(Request(key.range(63, 32)));
      phase = SearchPhase::row_response;
      break;
    case SearchPhase::row_response:
      metadata = responses.read();
      phase = SearchPhase::row_decode;
      break;
    case SearchPhase::row_decode: {
      begin = ap_uint<32>(metadata.range(63, 32)) >> 4;
      end = ap_uint<32>(metadata.range(31, 0)) >> 4;
      phase = SearchPhase::midpoint;
      break;
    }
    case SearchPhase::binary_request: {
      Request request = mid;
      request[32] = 1;
      requests.write(request);
      phase = SearchPhase::binary_response;
      break;
    }
    case SearchPhase::binary_response:
      metadata = responses.read();
      phase = SearchPhase::binary_compare;
      break;
    case SearchPhase::binary_compare:
      if (metadata <= key) begin = mid;
      else end = mid;
      phase = SearchPhase::midpoint;
      break;
    case SearchPhase::midpoint:
      mid = (begin + end) >> 1;
      phase = SearchPhase::choose;
      break;
    case SearchPhase::choose:
      phase = begin == mid ? SearchPhase::emit : SearchPhase::binary_request;
      break;
    case SearchPhase::emit: {
      Result result = raw;
      result <<= 32;
      Result head = begin;
      head <<= 4;
      results.write(result | head);
      phase = SearchPhase::input;
      break;
    }
    case SearchPhase::end:
      requests.write(end_request());
      return;
    }
  }
}
}  // namespace search_pipeline
