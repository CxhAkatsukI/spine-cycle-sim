#include "parallel_search.hpp"

extern "C" void bin_search_parallel(
    const unsigned long* edges, const ap_uint<64>* binary,
    const ap_uint<64>* rows, unsigned count,
    hls::stream<compact_g::Packet>& output) {
#pragma HLS INTERFACE m_axi port=edges offset=slave bundle=updates num_read_outstanding=16
#pragma HLS INTERFACE m_axi port=binary offset=slave bundle=metadata num_read_outstanding=16
#pragma HLS INTERFACE m_axi port=rows offset=slave bundle=metadata num_read_outstanding=16
#pragma HLS INTERFACE s_axilite port=edges bundle=control
#pragma HLS INTERFACE s_axilite port=binary bundle=control
#pragma HLS INTERFACE s_axilite port=rows bundle=control
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=output
  hls::stream<ap_uint<64>> input;
  hls::stream<ap_uint<64>> updates[compact_g::lanes], responses[compact_g::lanes];
  hls::stream<ap_uint<96>> results[compact_g::lanes];
  hls::stream<compact_g::Request> requests[compact_g::lanes];
  hls::stream<bool> credits[compact_g::lanes];
#pragma HLS STREAM variable=input depth=2
#pragma HLS STREAM variable=updates depth=2
#pragma HLS STREAM variable=responses depth=2
#pragma HLS STREAM variable=results depth=2
#pragma HLS STREAM variable=requests depth=2
#pragma HLS STREAM variable=credits depth=2
#pragma HLS DATAFLOW
  compact_g::read_updates(edges, count, input);
  compact_g::distribute(count, input, updates, credits);
  for (unsigned lane = 0; lane < compact_g::lanes; ++lane) {
#pragma HLS UNROLL
    compact_g::search(updates[lane], requests[lane], responses[lane], results[lane]);
  }
  compact_g::service(rows, binary, requests, responses);
  compact_g::merge(count, results, output, credits);
}
