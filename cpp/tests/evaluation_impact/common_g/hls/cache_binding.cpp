#include "cache_pipeline.hpp"

#ifndef GRASU_ENABLE_COMPLETION_TOKEN
#error "Production cache binding requires the existing completion-token ABI"
#endif
#ifndef CACHE_BANK_REGISTERED
#error "Production cache binding requires the registered lane implementation"
#endif

extern "C" void process_cache(ap_uint<512>* pma_cache,
                               hls::stream<pipe_type_96>& update_stream,
                               hls::stream<grasu_done_pkt_t>& completion_token) {
#pragma HLS INTERFACE m_axi port=pma_cache offset=slave bundle=gmem0 depth=131072
#pragma HLS INTERFACE s_axilite port=pma_cache bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=update_stream
#pragma HLS INTERFACE axis port=completion_token
  cache_registered::candidate(pma_cache, update_stream);
  write_grasu_completion_token(completion_token, 1);
}
