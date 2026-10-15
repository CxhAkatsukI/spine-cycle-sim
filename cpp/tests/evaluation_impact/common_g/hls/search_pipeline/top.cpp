#include "network.hpp"

extern "C" void bin_search_pipeline(
    const unsigned long* edges, const search_pipeline::Raw* binary_nodes,
    const search_pipeline::Raw* rows, unsigned count,
    hls::stream<search_pipeline::Packet>& output) {
// Depths describe this isolated RTL testbench, not a production graph limit.
#pragma HLS INTERFACE m_axi port=edges offset=slave bundle=updates num_read_outstanding=16 depth=257
#pragma HLS INTERFACE m_axi port=binary_nodes offset=slave bundle=metadata num_read_outstanding=32 depth=255
#pragma HLS INTERFACE m_axi port=rows offset=slave bundle=metadata num_read_outstanding=32 depth=8
#pragma HLS INTERFACE s_axilite port=edges bundle=control
#pragma HLS INTERFACE s_axilite port=binary_nodes bundle=control
#pragma HLS INTERFACE s_axilite port=rows bundle=control
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=output
  search_pipeline::network(edges, binary_nodes, rows, count, output);
}
