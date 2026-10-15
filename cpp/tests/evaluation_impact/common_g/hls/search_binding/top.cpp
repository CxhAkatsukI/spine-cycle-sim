#include "top.hpp"
#include "../search_pipeline/network.hpp"

extern "C" void bin_search(
    const unsigned long* edges,
    const search_pipeline::Raw* binary_0, const search_pipeline::Raw* binary_1,
    const search_pipeline::Raw* binary_2, const search_pipeline::Raw* binary_3,
    const search_pipeline::Raw* row_offset_0, const search_pipeline::Raw* row_offset_1,
    const search_pipeline::Raw* row_offset_2, const search_pipeline::Raw* row_offset_3,
    unsigned edge_size, hls::stream<search_pipeline::Packet>& segment_head_stream_out) {
// Match the production compact-HBM interface; depths bound only the RTL bench.
#pragma HLS INTERFACE m_axi port=edges offset=slave bundle=gmem_edges num_read_outstanding=16 depth=257
#pragma HLS INTERFACE m_axi port=binary_0 offset=slave bundle=gmem_binary num_read_outstanding=32 depth=255
#pragma HLS INTERFACE m_axi port=row_offset_0 offset=slave bundle=gmem_binary num_read_outstanding=32 depth=8
#pragma HLS INTERFACE s_axilite port=edges bundle=control
#pragma HLS INTERFACE s_axilite port=binary_0 bundle=control
#pragma HLS INTERFACE s_axilite port=binary_1 bundle=control
#pragma HLS INTERFACE s_axilite port=binary_2 bundle=control
#pragma HLS INTERFACE s_axilite port=binary_3 bundle=control
#pragma HLS INTERFACE s_axilite port=row_offset_0 bundle=control
#pragma HLS INTERFACE s_axilite port=row_offset_1 bundle=control
#pragma HLS INTERFACE s_axilite port=row_offset_2 bundle=control
#pragma HLS INTERFACE s_axilite port=row_offset_3 bundle=control
#pragma HLS INTERFACE s_axilite port=edge_size bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=segment_head_stream_out
  search_pipeline::network(edges, binary_0, row_offset_0, edge_size, segment_head_stream_out);
}
