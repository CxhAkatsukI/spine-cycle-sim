#include "cache_bank.hpp"
#include "upstream/kernel_process_cache.cpp"
#include "cache_lane.hpp"

extern "C" void cache_bank_probe(CacheWord* memory,
                                  hls::stream<CacheUpdate>& updates) {
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=gmem0 depth=8192 num_read_outstanding=16 num_write_outstanding=16 max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=updates
  CacheWord cache[cache_bank_depth];
#pragma HLS BIND_STORAGE variable=cache type=RAM_1P impl=URAM
  preload:
  for (unsigned i = 0; i < cache_bank_depth; ++i) {
#pragma HLS PIPELINE II=1
    cache[i] = memory[i];
  }
#if defined(CACHE_BANK_CANDIDATE) || defined(CACHE_BANK_REGISTERED)
  cache_probe_detail::lane_update(cache, updates);
#else
  process_1(cache, updates);
#endif
  writeback:
  for (unsigned i = 0; i < cache_bank_depth; ++i) {
#pragma HLS PIPELINE II=1
    memory[i] = cache[i];
  }
}
