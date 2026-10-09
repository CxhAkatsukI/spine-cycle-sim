#include "probe_support.hpp"

#include "kernel_big_gs_merger.cpp"
#include "kernel_scatter_gather.cpp"

#include "big_merger_call.hpp"

#include <algorithm>

namespace {
constexpr unsigned logical_edges = 257;
constexpr unsigned vertex_count = BIG_KERNEL_DST_BUFFER_SIZE;

struct Edge {
  unsigned source;
  unsigned destination;
};

struct Request {
  unsigned line;
  unsigned lane;
};

unsigned property(unsigned vertex) { return 17 + vertex % 31; }

ap_uint<512> property_line(unsigned line) {
  ap_uint<512> value = 0;
  for (unsigned offset = 0; offset < 16; ++offset) {
    value.range(offset * 32 + 31, offset * 32) = property(line * 16 + offset);
  }
  return value;
}

unsigned run_big(const std::vector<Edge> &edges, unsigned destination_offset,
                 hls::stream<b_tmp_prop_pkt> &result) {
  const unsigned bursts = static_cast<unsigned>((edges.size() + 7) / 8);
  std::vector<edge_burst_dt> packed(bursts);
  std::vector<Request> expected_requests{{0, 0}};
  unsigned previous_last_line = 0;
  for (unsigned burst = 0; burst < bursts; ++burst) {
    unsigned lines[8];
    for (unsigned lane = 0; lane < 8; ++lane) {
      const unsigned index = burst * 8 + lane;
      const unsigned source =
          index < edges.size() ? edges[index].source : edges.back().source;
      packed[burst].edges[lane].src = source;
      packed[burst].edges[lane].dst =
          index < edges.size() ? edges[index].destination + destination_offset
                               : 0x80000000u;
      lines[lane] = source / 16;
    }
    // The source-sorted format makes reused last-line lanes a prefix.
    if (lines[7] != previous_last_line) {
      for (unsigned lane = 0; lane < 8; ++lane) {
        if (lines[lane] != previous_last_line) {
          expected_requests.push_back({lines[lane], lane});
        }
      }
    }
    previous_last_line = lines[7];
  }

  hls::stream<b_cacheline_request_pkt> requests;
  hls::stream<b_cacheline_response_pkt> responses;
  for (const auto &request : expected_requests) {
    b_cacheline_response_pkt response{};
    response.data = property_line(request.line);
    response.dest = request.lane;
    response.last = false;
    responses.write(response);
  }
  b_cacheline_response_pkt end{};
  end.last = true;
  responses.write(end);
  bigKernelScatterGather(packed.data(), bursts * 8, destination_offset,
                         requests, responses, result);
  for (unsigned index = 0; index < expected_requests.size(); ++index) {
    require(!requests.empty(), "Big missing cacheline request");
    const auto observed = requests.read();
    require(!observed.last && observed.data == expected_requests[index].line,
            "Big source-cache request address mismatch");
    // The first response is broadcast; the upstream initial request's dest is
    // unused.
    if (index) {
      require(observed.dest == expected_requests[index].lane,
              "Big source-cache request lane mismatch");
    }
  }
  require(requests.size() == 1 && requests.read().last,
          "Big missing/duplicate request terminator");
  require(responses.empty(), "Big response conservation");
  require(result.size() == vertex_count / 16,
          "Big full-partition output count");
  return bursts * 8;
}
} // namespace

int main() {
  try {
    unsigned physical_edges = 0;
    for (unsigned destination_offset : {0u, 65536u}) {
      std::vector<std::uint32_t> expected(vertex_count, 0);
      std::vector<Edge> per_pipeline[BIG_KERNEL_NUM];
      for (unsigned index = 0; index < logical_edges; ++index) {
        const unsigned source = index * 13;
        const unsigned destination =
            index % 3 == 0 ? vertex_count - 1 : index % 19;
        expected[destination] += property(source);
        per_pipeline[index % BIG_KERNEL_NUM].push_back({source, destination});
      }
      hls::stream<b_tmp_prop_pkt> partials[BIG_KERNEL_NUM];
      for (unsigned pipeline = 0; pipeline < BIG_KERNEL_NUM; ++pipeline) {
        physical_edges += run_big(per_pipeline[pipeline], destination_offset,
                                  partials[pipeline]);
      }
      PartitionOutput<write_burst_pkt> observer(vertex_count / 16);
      hls::stream<write_burst_pkt> merged;
      merged.set_delegate(&observer);
      bool cut = false;
      try {
        call_big_merger(partials, merged);
      } catch (const PrefixComplete &) {
        cut = true;
      }
      require(cut && observer.values.size() == vertex_count / 16,
              "Big merger did not emit one complete partition");
      for (auto &partial : partials) {
        require(partial.empty(), "Big merger input conservation");
      }
      for (unsigned vertex = 0; vertex < vertex_count; ++vertex) {
        require(observer.values[vertex / 16]
                        .data.range((vertex % 16) * 32 + 31, (vertex % 16) * 32)
                        .to_uint() == expected[vertex],
                "Big cache/scatter/omega/gather/merger differs from per-edge "
                "oracle");
      }
    }
    std::cout
        << "PUBLICATION_PROBE {\"kind\":\"regraph_big\",\"passed\":true,"
           "\"destination_offsets\":2,\"logical_edges_per_iteration\":257,"
           "\"checked_vertices\":1048576,\"little\":"
        << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
        << ",\"physical_edges\":" << physical_edges
        << ",\"merger_observation\":\"one_partition_prefix\"}\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
