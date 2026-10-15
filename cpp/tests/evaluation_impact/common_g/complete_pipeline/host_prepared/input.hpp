#pragma once

#include "host/weighted_pma_runtime_plan.hpp"
#include <fstream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>

namespace prepared_g {
namespace host = grasu::integration;
using Edge = host::WeightedEdgeRecord;
using State = std::map<std::pair<unsigned, unsigned>, unsigned>;

inline void check_input(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

struct Input {
  unsigned vertices{}, partition_vertices{};
  std::vector<Edge> initial, updates;
  explicit Input(const char* path) {
    std::ifstream stream(path);
    unsigned initial_count{}, update_count{};
    check_input(bool(stream >> vertices >> initial_count >> update_count >> partition_vertices),
            "host-prepared input header");
    check_input(vertices && vertices < 65536 && initial_count == 8192 &&
            (update_count == 512 || update_count == 8192) &&
            (partition_vertices == 65536 || partition_vertices == 1024), "input scope");
    for (unsigned i = 0; i < initial_count + update_count; ++i) {
      unsigned source{}, destination{}, weight{};
      int diff{};
      check_input(bool(stream >> source >> destination >> weight >> diff) &&
              source < vertices && destination < vertices && weight && weight < 4096 &&
              (diff == 1 || diff == -1) && (i >= initial_count || diff == 1), "input edge");
      (i < initial_count ? initial : updates).push_back(
          {source, destination, static_cast<std::uint16_t>(weight), diff == -1});
    }
    std::string extra;
    check_input(!(stream >> extra), "extra host-prepared input records");
  }
};

inline void mutate(State& state, const Edge& edge) {
  const auto key = std::make_pair(edge.source, edge.destination);
  if (edge.delete_op) {
    const auto found = state.find(key);
    check_input(found != state.end() && found->second == edge.weight, "logical deletion absent/wrong weight");
    state.erase(found);
  } else {
    check_input(state.emplace(key, edge.weight).second, "logical insertion duplicate");
  }
}

inline std::vector<std::vector<unsigned long>> batches(
    const Input& input, const host::WeightedPartitionedPmaGraph& graph,
    unsigned begin, unsigned end) {
  std::vector<std::vector<unsigned long>> result(graph.shards.size());
  for (unsigned i = begin; i < end; ++i) {
    const auto& edge = input.updates.at(i);
    const unsigned source = graph.external_to_internal.at(edge.source);
    const unsigned destination = graph.external_to_internal.at(edge.destination);
    const auto shard = destination / input.partition_vertices;
    const unsigned word = (edge.weight << 19) | (destination % input.partition_vertices);
    result.at(shard).push_back((static_cast<unsigned long>(edge.delete_op) << 63) |
                              (static_cast<unsigned long>(source) << 32) | word);
  }
  return result;
}

inline void check_host_mapping(const Input& input, const host::WeightedPartitionedPmaGraph& graph) {
  check_input(graph.vertices == input.vertices && graph.physical_internal.size() == input.updates.size(),
          "host changed vertex/update count");
  std::set<unsigned> permutation;
  for (unsigned external = 0; external < input.vertices; ++external) {
    const auto internal = graph.external_to_internal.at(external);
    check_input(internal < input.vertices && permutation.insert(internal).second &&
            graph.internal_to_external.at(internal) == external, "host mapping is not bijective");
  }
  const auto expected = batches(input, graph, 0, input.updates.size());
  for (unsigned shard = 0; shard < graph.shards.size(); ++shard) {
    const auto& actual = graph.shards[shard].physical_updates;
    check_input(actual.size() == expected[shard].size() &&
            std::equal(actual.begin(), actual.end(), expected[shard].begin()),
            "host physical update order/routing changed");
  }
}
}  // namespace prepared_g
