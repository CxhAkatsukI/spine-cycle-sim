#include "probe_support.hpp"

#include "acc_apply.h"
#include "acc_data_types.h"
#include "acc_gather.h"
#include "acc_scatter.h"
#include "kernel_little_gs_merger.cpp"
#include "little_merger_call.hpp"

#include <algorithm>

namespace {
constexpr unsigned vertex_count = LITTLE_KERNEL_DST_BUFFER_SIZE;
constexpr unsigned logical_edges = 257;

struct Edge {
  unsigned source;
  unsigned destination;
};

std::vector<Edge> fixture(unsigned source_base) {
  std::vector<Edge> edges;
  for (unsigned i = 0; i < logical_edges; ++i) {
    const unsigned source = source_base + (i * 13 % SRC_BUFFER_SIZE);
    const unsigned destination = i % 3 == 0 ? vertex_count - 1 : i % 19;
    edges.push_back({source, destination});
  }
  return edges;
}

ap_uint<512> property_line(const std::vector<std::uint32_t> &properties,
                           unsigned line) {
  ap_uint<512> value = 0;
  for (unsigned offset = 0; offset < 16; ++offset) {
    const unsigned vertex = line * 16 + offset;
    if (vertex < properties.size()) {
      value.range(offset * 32 + 31, offset * 32) = properties[vertex];
    }
  }
  return value;
}

unsigned run_little(const std::vector<Edge> &edges, unsigned source_base,
                    const std::vector<std::uint32_t> &properties,
                    hls::stream<l_tmp_prop_pkt> &result) {
  hls::stream<edge_burst_dt> edge_stream;
  hls::stream<ppb_request_dt> requests;
  hls::stream<ppb_response_dt> responses;
  hls::stream<update_set_dt> updates;
  hls::stream<ap_uint<64>> gathered[GATHER_PE_NUM];
  const unsigned bursts =
      std::max(1u, static_cast<unsigned>((edges.size() + 7) / 8));
  for (unsigned burst = 0; burst < bursts; ++burst) {
    edge_burst_dt value{};
    for (unsigned lane = 0; lane < 8; ++lane) {
      const unsigned index = burst * 8 + lane;
      value.edges[lane].src =
          index < edges.size() ? edges[index].source : source_base;
      value.edges[lane].dst =
          index < edges.size() ? edges[index].destination : 1u << 19;
    }
    edge_stream.write(value);
  }
  // Feed complete source rounds plus one lookahead round, as requested by the
  // original ping-pong protocol. C simulation streams are deliberately
  // unbounded.
  const unsigned rounds = source_base / SRC_BUFFER_SIZE + 2;
  for (unsigned line = 0; line < rounds * SRC_BUFFER_SIZE / 16; ++line) {
    ppb_response_dt response{};
    response.addr = line;
    response.data = property_line(properties, line);
    responses.write(response);
  }
  ppb_response_dt end{};
  end.end_flag = true;
  responses.write(end);
  accScatter(requests, responses, edge_stream, updates, bursts * 8);
  unsigned end_requests = 0;
  while (!requests.empty()) {
    end_requests += requests.read().end_flag;
  }
  require(end_requests == 1,
          "Little scatter missing/duplicate request terminator");
  require(edge_stream.empty() && responses.empty(),
          "Little scatter input conservation");
  require(updates.size() == bursts, "Little scatter output burst count");
  accGather(bursts * 8, updates, gathered);
  require(updates.empty(), "Little gather input conservation");
  mergeWriteResults(gathered, 0, result);
  for (auto &lane : gathered) {
    require(lane.empty(), "Little local merge input conservation");
  }
  require(result.size() == vertex_count / 2,
          "Little full-partition output count");
  return bursts * 8;
}

void check_apply(const std::vector<write_burst_pkt> &merged,
                 const std::vector<std::uint32_t> &expected,
                 const std::vector<std::uint32_t> &degree,
                 std::vector<std::uint32_t> &properties) {
  hls::stream<write_burst_pkt> merge_stream;
  hls::stream<write_burst_dt> apply_in;
  hls::stream<write_burst_dt> unused_out;
  hls::stream<write_burst_pkt> apply_out;
  std::vector<ap_uint<512>> degree_lines(vertex_count / 16);
  for (unsigned line = 0; line < degree_lines.size(); ++line) {
    degree_lines[line] = property_line(degree, line);
    merge_stream.write(merged[line]);
  }
#if BIG_KERNEL_NUM
  hls::stream<write_burst_pkt> no_sparse_partitions;
  merge_big_little_writes(merge_stream, no_sparse_partitions, apply_in, 1, 0);
#else
  merge_big_little_writes(merge_stream, apply_in, 1, 0);
#endif
  Apply(degree_lines.data(), 100, apply_in, unused_out, apply_out);
  unsigned checked = 0;
  bool terminated = false;
  while (!apply_out.empty()) {
    const auto packet = apply_out.read();
    if (packet.last) {
      require(checked == vertex_count, "early PR apply terminator");
      terminated = true;
      break;
    }
    require(checked + 16 <= vertex_count, "excess PR apply data");
    require(packet.dest == checked / 16, "PR apply address mismatch");
    for (unsigned offset = 0; offset < 16; ++offset, ++checked) {
      const auto observed =
          packet.data.range(offset * 32 + 31, offset * 32).to_uint();
      require(observed == oracle_pr(expected[checked], degree[checked], 100),
              "PR apply differs from independent integer oracle");
      properties[checked] = observed;
    }
  }
  require(terminated && checked == vertex_count && apply_out.empty() &&
              apply_in.empty() && merge_stream.empty(),
          "PR apply stream conservation");
  require(unused_out.size() == 1 && unused_out.read().end_flag,
          "original PR no-vertex-property output terminator");
}
} // namespace

int main() {
  try {
    unsigned physical_edges = 0;
    for (unsigned source_base : {0u, static_cast<unsigned>(SRC_BUFFER_SIZE)}) {
      const auto edges = fixture(source_base);
      std::vector<std::uint32_t> degree(vertex_count, 0);
      std::vector<std::uint32_t> properties(vertex_count);
      for (unsigned vertex = 0; vertex < vertex_count; ++vertex) {
        properties[vertex] = 17 + vertex % 31;
      }
      for (const auto &edge : edges) {
        ++degree[edge.source];
      }
      for (unsigned iteration = 0; iteration < 3; ++iteration) {
        std::vector<std::uint32_t> expected(vertex_count, 0);
        std::vector<Edge> per_pipeline[LITTLE_KERNEL_NUM];
        for (unsigned index = 0; index < edges.size(); ++index) {
          expected[edges[index].destination] += properties[edges[index].source];
          per_pipeline[index % LITTLE_KERNEL_NUM].push_back(edges[index]);
        }
        hls::stream<l_tmp_prop_pkt> partials[LITTLE_KERNEL_NUM];
        for (unsigned pipeline = 0; pipeline < LITTLE_KERNEL_NUM; ++pipeline) {
          physical_edges += run_little(per_pipeline[pipeline], source_base,
                                       properties, partials[pipeline]);
        }
        PartitionOutput<write_burst_pkt> observer(vertex_count / 16);
        hls::stream<write_burst_pkt> merged;
        merged.set_delegate(&observer);
        bool cut = false;
        try {
          call_little_merger(partials, merged);
        } catch (const PrefixComplete &) {
          cut = true;
        }
        require(
            cut && observer.values.size() == vertex_count / 16,
            "free-running Little merger did not emit one complete partition");
        for (auto &partial : partials) {
          require(partial.empty(), "Little global merger input conservation");
        }
        for (unsigned vertex = 0; vertex < vertex_count; ++vertex) {
          require(
              observer.values[vertex / 16]
                      .data.range((vertex % 16) * 32 + 31, (vertex % 16) * 32)
                      .to_uint() == expected[vertex],
              "Little scatter/gather/merger differs from per-edge oracle");
        }
        check_apply(observer.values, expected, degree, properties);
      }
    }
    std::cout
        << "PUBLICATION_PROBE {\"kind\":\"regraph_little\",\"passed\":true,"
           "\"source_windows\":2,\"iterations_per_window\":3,"
           "\"logical_edges_per_iteration\":257,\"checked_vertices\":393216,"
           "\"little\":"
        << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
        << ",\"physical_edges\":" << physical_edges
        << ",\"merger_observation\":\"one_partition_prefix\"}\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
