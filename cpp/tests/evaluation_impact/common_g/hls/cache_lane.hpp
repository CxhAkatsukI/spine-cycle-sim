#pragma once

#include "cache_bank.hpp"
#include "upstream/kernel_config.h"

namespace cache_probe_detail {
inline CacheWord edit_segment(CacheWord before, ap_uint<32> key, bool erase) {
#ifdef CACHE_BANK_REGISTERED
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=3 max=3
#else
#pragma HLS INLINE
#endif
  ap_uint<32> words[16];
  ap_uint<1> less[16];
#pragma HLS ARRAY_PARTITION variable=words complete
#pragma HLS ARRAY_PARTITION variable=less complete
  for (unsigned i = 0; i < 16; ++i) {
#pragma HLS UNROLL
    words[i] = before.range(i * 32 + 31, i * 32);
    less[i] = words[i] < key;
  }
  // Sorted inputs make the insertion boundary local. Static lane wiring
  // avoids the original data-dependent 512-bit shifts and prefix sum.
  CacheWord after = 0;
  for (unsigned i = 0; i < 16; ++i) {
#pragma HLS UNROLL
    const ap_uint<32> next = i == 15 ? ap_uint<32>(0x80000000u) : words[i + 1];
    const ap_uint<32> previous = i == 0 ? ap_uint<32>(0) : words[i - 1];
    const bool boundary = !less[i] && (i == 0 || less[i - 1]);
    const ap_uint<32> value = erase ? (less[i] ? words[i] : next)
        : (less[i] ? words[i] : boundary ? key : previous);
    after.range(i * 32 + 31, i * 32) = value;
  }
  return after;
}

inline void lane_update(CacheWord* cache, hls::stream<CacheUpdate>& updates) {
#pragma HLS INLINE off
  candidate_updates:
  while (true) {
#pragma HLS PIPELINE II=1
    const CacheUpdate info = updates.read();
    if (info == END_EDGE) break;
    const ap_uint<23> address = info.range(31, 9);
    const ap_uint<32> key = info.range(63, 32);
    const bool erase = info[95];
    const CacheWord before = cache[address];
    cache[address] = edit_segment(before, key, erase);
  }
}
}  // namespace cache_probe_detail
