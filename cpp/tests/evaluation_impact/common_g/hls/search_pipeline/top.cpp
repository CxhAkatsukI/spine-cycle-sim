#include "transport.hpp"
#include "workers.hpp"
#ifndef __SYNTHESIS__
#include "finite_host.hpp"
#endif

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
  using namespace search_pipeline;
  hls::stream<Raw> input, updates[lanes], responses[lanes];
  hls::stream<Request> requests[lanes];
  hls::stream<Result> results[lanes];
  hls::stream<bool> credits[lanes];
  hls::stream<TaggedRequest> group_requests[groups], memory_requests;
  hls::stream<TaggedResponse> group_responses[groups], memory_responses;
#pragma HLS STREAM variable=input depth=2
#pragma HLS STREAM variable=updates depth=2
#pragma HLS STREAM variable=responses depth=2
#pragma HLS STREAM variable=requests depth=2
#pragma HLS STREAM variable=results depth=2
#pragma HLS STREAM variable=credits depth=2
#pragma HLS STREAM variable=group_requests depth=2
#pragma HLS STREAM variable=group_responses depth=2
#pragma HLS STREAM variable=memory_requests depth=32
#pragma HLS STREAM variable=memory_responses depth=32

#ifndef __SYNTHESIS__
  HostNetwork host;
  host.bind(input);
  for (unsigned lane = 0; lane < lanes; ++lane) {
    host.bind(updates[lane]); host.bind(responses[lane]); host.bind(requests[lane]);
    host.bind(results[lane]); host.bind(credits[lane]);
  }
  for (unsigned group = 0; group < groups; ++group) {
    host.bind(group_requests[group]); host.bind(group_responses[group]);
  }
  host.bind(memory_requests, metadata_credits);
  host.bind(memory_responses, metadata_credits);
  host.launch([&] { read_updates(edges, count, input); });
  host.launch([&] { distribute(count, input, updates, credits); });
  for (unsigned lane = 0; lane < lanes; ++lane)
    host.launch([&, lane] { search(updates[lane], requests[lane], responses[lane], results[lane]); });
  for (unsigned group = 0; group < groups; ++group) {
    host.launch([&, group] { gather_group(group, &requests[group * width], group_requests[group]); });
    host.launch([&, group] { scatter_group(group_responses[group], &responses[group * width]); });
  }
  host.launch([&] { gather(group_requests, memory_requests); });
  host.launch([&] { memory(rows, binary_nodes, memory_requests, memory_responses); });
  host.launch([&] { scatter(memory_responses, group_responses); });
  host.launch([&] { merge(count, results, output, credits); });
  host.join();
#else
#pragma HLS DATAFLOW
  read_updates(edges, count, input);
  distribute(count, input, updates, credits);
  for (unsigned lane = 0; lane < lanes; ++lane) {
#pragma HLS UNROLL
    search(updates[lane], requests[lane], responses[lane], results[lane]);
  }
  for (unsigned group = 0; group < groups; ++group) {
#pragma HLS UNROLL
    gather_group(group, &requests[group * width], group_requests[group]);
    scatter_group(group_responses[group], &responses[group * width]);
  }
  gather(group_requests, memory_requests);
  memory(rows, binary_nodes, memory_requests, memory_responses);
  scatter(memory_responses, group_responses);
  merge(count, results, output, credits);
#endif
}
