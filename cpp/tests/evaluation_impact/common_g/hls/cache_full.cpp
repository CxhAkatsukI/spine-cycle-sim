#include "upstream/kernel_process_cache.cpp"
#include "cache_lane.hpp"

namespace {
void update_banks(CacheWord cache[16][cache_bank_depth],
                  hls::stream<CacheUpdate> updates[16]) {
#pragma HLS INLINE off
#pragma HLS DATAFLOW
  for (unsigned bank = 0; bank < 16; ++bank) {
#pragma HLS UNROLL
    cache_probe_detail::lane_update(cache[bank], updates[bank]);
  }
}

void cached_process(CacheWord* memory, hls::stream<CacheUpdate> updates[16]) {
#pragma HLS INLINE off
  CacheWord cache[16][cache_bank_depth];
#pragma HLS ARRAY_PARTITION variable=cache complete dim=1
#pragma HLS BIND_STORAGE variable=cache type=RAM_1P impl=URAM
  preload_all:
  for (unsigned row = 0; row < cache_bank_depth; ++row) {
#pragma HLS PIPELINE II=16
    for (unsigned bank = 0; bank < 16; ++bank) {
#pragma HLS UNROLL
      cache[bank][row] = memory[row * 16 + bank];
    }
  }
  update_banks(cache, updates);
  writeback_all:
  for (unsigned row = 0; row < cache_bank_depth; ++row) {
#pragma HLS PIPELINE II=16
    for (unsigned bank = 0; bank < 16; ++bank) {
#pragma HLS UNROLL
      memory[row * 16 + bank] = cache[bank][row];
    }
  }
}

void candidate(CacheWord* memory, hls::stream<pipe_type_96>& updates) {
#pragma HLS INLINE off
  hls::stream<CacheUpdate> bank_updates[16];
#pragma HLS STREAM variable=bank_updates depth=2
#pragma HLS DATAFLOW
  dispatch_update(updates, bank_updates);
  cached_process(memory, bank_updates);
}
}  // namespace

// The upstream top omits the external array depth required by RTL cosimulation.
// Keep its body and directives unchanged; only the test top supplies that depth.
extern "C" void cache_full_probe(ap_uint<512>* memory,
                                  hls::stream<pipe_type_96>& updates) {
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=gmem0 depth=131072
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=updates
#ifdef CACHE_BANK_REGISTERED
  candidate(memory, updates);
#else
  process_cache(memory, updates);
#endif
}
