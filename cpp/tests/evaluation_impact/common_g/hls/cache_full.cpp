#include "upstream/kernel_process_cache.cpp"
#include "cache_pipeline.hpp"

// The upstream top omits the external array depth required by RTL cosimulation.
// Keep its body and directives unchanged; only the test top supplies that depth.
extern "C" void cache_full_probe(ap_uint<512>* memory,
                                  hls::stream<pipe_type_96>& updates) {
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=gmem0 depth=131072
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=updates
#ifdef CACHE_BANK_REGISTERED
  cache_registered::candidate(memory, updates);
#else
  process_cache(memory, updates);
#endif
}
