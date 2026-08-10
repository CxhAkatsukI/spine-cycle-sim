#include <algorithm>
#include <array>
#include <chrono>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

#include "spine_sim/grasu.hpp"
#include "spine_sim/spine_l0.hpp"

namespace {

using spine::sim::GraSuEdge;
using spine::sim::GraSuNativeReorderedGraph;
using spine::sim::GraSuPartitionedPmaLayout;
using spine::sim::SpineEdgeRecord;
using spine::sim::SpineEdgeSlice;
using spine::sim::SpineL0Config;

std::uint64_t parse_u64(std::string_view text) {
  std::uint64_t value = 0;
  const auto [end, error] =
      std::from_chars(text.data(), text.data() + text.size(), value);
  if (error != std::errc{} || end != text.data() + text.size()) {
    throw std::invalid_argument("invalid unsigned integer: " +
                                std::string(text));
  }
  return value;
}

SpineEdgeSlice load_slice(const std::string &path, bool updates) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open slice: " + path);
  }
  SpineEdgeSlice result;
  result.case_name = path;
  std::string line;
  while (std::getline(input, line)) {
    if (line.empty()) {
      continue;
    }
    if (line[0] == '#') {
      constexpr std::string_view prefix = "# vertices=";
      if (line.starts_with(prefix)) {
        result.vertices = parse_u64(std::string_view(line).substr(prefix.size()));
      }
      continue;
    }
    std::array<std::int64_t, 4> fields{};
    std::size_t field = 0;
    std::size_t begin = 0;
    while (begin < line.size() && field < fields.size()) {
      while (begin < line.size() && line[begin] == ' ') {
        ++begin;
      }
      const std::size_t end = line.find(' ', begin);
      const std::string_view token(
          line.data() + begin,
          (end == std::string::npos ? line.size() : end) - begin);
      const auto [parsed, error] = std::from_chars(
          token.data(), token.data() + token.size(), fields[field]);
      if (error != std::errc{} || parsed != token.data() + token.size()) {
        throw std::invalid_argument("invalid edge row in " + path);
      }
      ++field;
      begin = end == std::string::npos ? line.size() : end + 1;
    }
    if (field != 4 || fields[0] < 0 || fields[1] < 0 || fields[2] <= 0 ||
        fields[2] > std::numeric_limits<std::uint16_t>::max() ||
        (updates ? std::abs(fields[3]) != 1 : fields[3] != 1)) {
      throw std::invalid_argument("invalid edge row in " + path);
    }
    result.edges.push_back(SpineEdgeRecord{
        .src = static_cast<std::uint32_t>(fields[0]),
        .dst = static_cast<std::uint32_t>(fields[1]),
        .weight = static_cast<std::uint16_t>(fields[2]),
        .diff = static_cast<std::int16_t>(fields[3]),
    });
  }
  if (result.vertices == 0) {
    throw std::invalid_argument("slice has no vertices metadata: " + path);
  }
  return result;
}

std::uint64_t median(std::vector<std::uint64_t> samples) {
  std::sort(samples.begin(), samples.end());
  return samples[samples.size() / 2];
}

std::vector<GraSuEdge> convert_edges(const SpineEdgeSlice &slice) {
  std::vector<GraSuEdge> result;
  result.reserve(slice.edges.size());
  for (const SpineEdgeRecord &edge : slice.edges) {
    result.push_back(GraSuEdge{
        .source = edge.src,
        .destination = edge.dst,
        .weight = edge.weight,
        .delete_op = edge.diff < 0,
    });
  }
  return result;
}

std::uint64_t grasu_layout_bytes(const GraSuPartitionedPmaLayout &layout) {
  std::uint64_t bytes = 0;
  for (const auto &partition : layout.partitions) {
    bytes += partition.row_slot_bounds.size() * 8ULL;
    bytes += partition.binary_heads.size() * 8ULL;
    bytes += partition.segments.size() * spine::sim::kGraSuSegmentBytes;
  }
  return bytes;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 6) {
    std::cerr << "usage: persistent_update_host_benchmark GRAPH UPDATE "
                 "BATCH_COUNT PARTITION_VERTICES REPEATS\n";
    return 2;
  }
  const SpineEdgeSlice initial = load_slice(argv[1], false);
  const SpineEdgeSlice trace = load_slice(argv[2], true);
  const std::size_t batch_count = parse_u64(argv[3]);
  const std::size_t partition_vertices = parse_u64(argv[4]);
  const std::size_t repeats = parse_u64(argv[5]);
  if (trace.vertices != initial.vertices || batch_count == 0 || repeats == 0 ||
      batch_count > trace.edges.size()) {
    throw std::invalid_argument("invalid persistent host benchmark shape");
  }

  std::vector<std::uint64_t> spine_samples;
  std::vector<std::uint64_t> grasu_samples;
  std::uint64_t spine_layout_bytes = 0;
  std::uint64_t grasu_bytes = 0;
  for (std::size_t repeat = 0; repeat < repeats; ++repeat) {
    auto start = std::chrono::steady_clock::now();
    SpineL0Config config;
    auto state = spine::sim::preload_spine_resident_snapshot(initial, config);
    auto sorted = trace.edges;
    const auto edge_order = [](const SpineEdgeRecord &left,
                               const SpineEdgeRecord &right) {
      return std::tie(left.src, left.dst, left.weight, left.diff) <
             std::tie(right.src, right.dst, right.weight, right.diff);
    };
    for (std::size_t batch = 0; batch < batch_count; ++batch) {
      const std::size_t begin = batch * sorted.size() / batch_count;
      const std::size_t end = (batch + 1) * sorted.size() / batch_count;
      std::stable_sort(sorted.begin() + static_cast<std::ptrdiff_t>(begin),
                       sorted.begin() + static_cast<std::ptrdiff_t>(end),
                       edge_order);
    }
    const auto spine_end = std::chrono::steady_clock::now();
    spine_samples.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                spine_end - start)
                                .count());
    spine_layout_bytes = 0;
    for (const auto &families : {&state.cold_levels, &state.hot_levels}) {
      for (const auto &levels : *families) {
        for (const auto &edges : levels) {
          spine_layout_bytes += edges.size() * 8ULL;
        }
      }
    }

    start = std::chrono::steady_clock::now();
    auto initial_edges = convert_edges(initial);
    auto updates = convert_edges(trace);
    GraSuNativeReorderedGraph reordered = spine::sim::reorder_grasu_native_graph(
        initial.vertices, initial_edges, updates);
    std::vector<GraSuEdge> reserved;
    reserved.reserve(reordered.updates.size());
    for (const GraSuEdge &edge : reordered.updates) {
      if (!edge.delete_op) {
        reserved.push_back(edge);
      }
    }
    GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
        initial.vertices, partition_vertices, reordered.initial_edges, reserved);
    const auto grasu_end = std::chrono::steady_clock::now();
    grasu_samples.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                grasu_end - start)
                                .count());
    grasu_bytes = grasu_layout_bytes(layout);
  }

  std::cout << "{\n"
            << "  \"graph_edges\": " << initial.edges.size() << ",\n"
            << "  \"updates\": " << trace.edges.size() << ",\n"
            << "  \"batch_count\": " << batch_count << ",\n"
            << "  \"spine_host_preprocess_ns\": " << median(spine_samples)
            << ",\n"
            << "  \"grasu_host_preprocess_ns\": " << median(grasu_samples)
            << ",\n"
            << "  \"spine_initial_h2d_bytes\": " << spine_layout_bytes
            << ",\n"
            << "  \"grasu_initial_h2d_bytes\": " << grasu_bytes << ",\n"
            << "  \"spine_update_h2d_bytes\": "
            << trace.edges.size() * 16ULL << ",\n"
            << "  \"grasu_update_h2d_bytes\": "
            << trace.edges.size() * 16ULL << "\n"
            << "}\n";
  return 0;
}
