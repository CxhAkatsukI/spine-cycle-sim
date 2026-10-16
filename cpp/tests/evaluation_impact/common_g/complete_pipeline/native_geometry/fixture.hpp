#pragma once

#include "host_prepared/handoff.hpp"

namespace native_g {
namespace host = grasu::integration;
using prepared_g::Edge;
using prepared_g::State;
constexpr unsigned kVertices = 262148;
constexpr unsigned kPartitionVertices = 65536;
constexpr unsigned kReservedOperations = 4 * kVertices;
constexpr std::array<unsigned, 10> kSources{
    0, 1, 2, 3, 262142, 262143, 262144, 262145, 262146, 262147};

struct Fixture {
  host::WeightedPartitionedPmaGraph graph;
  host::WeightedPmaRuntimePlan plan;
  std::vector<host::WeightedPmaPackedShardBuffers> packed;
  std::array<std::vector<Edge>, 3> batches;

  Fixture() {
    complete_g::require(MAX_CACHE_SEGMENT == 131072, "native test requires complete routed cache capacity");
    std::vector<Edge> initial, reservation;
    initial.reserve(2 * kVertices);
    reservation.reserve(kReservedOperations);
    // Equal reservation/update density keeps the production mapping at identity.
    // Only the declared sparse schedule below is executed, not this future trace.
    for (unsigned source = 0; source < kVertices; ++source)
      for (unsigned destination : {0u, kVertices - 1}) {
        initial.push_back({source, destination, 7, false});
        reservation.push_back({source, destination, 7, true});
        reservation.push_back({source, destination, 3, false});
      }
    graph = host::build_weighted_partitioned_pma_graph(
        kVertices, kPartitionVertices, initial, reservation);
    complete_g::require(graph.shards.size() == 5 && graph.physical_internal.size() == kReservedOperations,
                        "native reservation geometry changed");
    for (unsigned vertex = 0; vertex < kVertices; ++vertex)
      complete_g::require(graph.external_to_internal.at(vertex) == vertex &&
                          graph.internal_to_external.at(vertex) == vertex,
                          "native reservation did not retain expected production permutation");
    plan = host::build_weighted_pma_runtime_plan(graph, MAX_CACHE_SEGMENT, 23,
        host::kU55cHbmPseudoChannelBytes, host::WeightedPmaChannelPolicy::lane_aware_u55c, true);
    packed = host::pack_weighted_pma_runtime_buffers(graph, plan);
    for (unsigned shard = 0; shard < graph.shards.size(); ++shard) {
      const bool populated = shard == 0 || shard == 4;
      complete_g::require(graph.shards[shard].binary_heads.size() == (populated ? kVertices : 1) &&
                          graph.shards[shard].physical_updates.size() == (populated ? 2 * kVertices : 0),
                          "native populated/empty shard geometry changed");
    }
    for (unsigned source : kSources)
      for (unsigned destination : {0u, kVertices - 1}) {
        batches[1].push_back({source, destination, 7, true});
        batches[2].push_back({source, destination, 3, false});
      }
  }

  std::vector<std::vector<unsigned long>> lower(unsigned batch) const {
    std::vector<std::vector<unsigned long>> result(graph.shards.size());
    for (const auto& edge : batches.at(batch)) {
      const unsigned source = graph.external_to_internal.at(edge.source);
      const unsigned destination = graph.external_to_internal.at(edge.destination);
      const unsigned shard = destination / kPartitionVertices;
      const auto raw = host::pack_weighted_update(source,
          host::encode_weighted_pma_word(destination % kPartitionVertices, edge.weight), edge.delete_op);
      complete_g::require(graph.shards.at(shard).physical_updates.at(2 * source + !edge.delete_op) == raw,
                          "selected update is absent from production reservation trace");
      result.at(shard).push_back(raw);
    }
    return result;
  }
};
}  // namespace native_g
