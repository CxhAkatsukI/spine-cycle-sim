#pragma once

#include "model.hpp"
#include "weighted_pma_runtime_plan.hpp"
#include <cmath>
#include <iostream>

namespace source_retention {
namespace rb = original_r_board;
namespace gp = grasu::integration;

struct Input {
    rb::Model reference;
    gp::WeightedPartitionedPmaGraph graph;
    gp::WeightedPmaRuntimePlan plan;
    std::vector<gp::WeightedPmaPackedShardBuffers> packed;
    std::vector<float> source, sums, payload;
    std::vector<std::uint32_t> degree;

    explicit Input(const std::filesystem::path& directory)
        : reference(rb::Model::load(directory, "a4", rb::Binding::csr_degree)) {
        const auto offsets = rb::wt::read_words(directory / "csr_offsets.u32le", reference.vertices + 1);
        const auto destinations = rb::wt::read_words(directory / "csr_destinations.u32le", reference.logical_edges);
        std::vector<gp::WeightedEdgeRecord> edges;
        edges.reserve(destinations.size());
        for (unsigned src = 0; src < reference.vertices; ++src)
            for (unsigned i = offsets[src]; i < offsets[src + 1]; ++i)
                edges.push_back({src, destinations[i], 1, false});
        graph = gp::build_weighted_partitioned_pma_graph(reference.vertices, 65536, edges, {});
        rb::require(graph.initial_internal.size() == reference.logical_edges,
                    "PMA input must preserve every logical edge, without deduplication");
        plan = gp::build_weighted_pma_runtime_plan(graph, 131072, 23, 512ull << 20,
                                                  gp::WeightedPmaChannelPolicy::lane_aware_u55c, true);
        packed = gp::pack_weighted_pma_runtime_buffers(graph, plan);
        const auto capacity = graph.shards.size() * 65536;
        source.resize(capacity); degree.resize(capacity); sums.resize(capacity); payload.resize(capacity);
        for (unsigned external = 0; external < reference.vertices; ++external) {
            const auto internal = graph.external_to_internal.at(external);
            rb::require(reference.initial[external] <= (1u << 24) && reference.sums[external] <= (1u << 24),
                        "common gather exceeds exact binary32 integer domain");
            source[internal] = static_cast<float>(reference.initial[external]);
            degree[internal] = reference.degrees[external];
            sums[internal] = static_cast<float>(reference.sums[external]);
            payload[internal] = degree[internal] ? (108.0F / 128.0F) * sums[internal] / degree[internal] : 0;
        }
        std::cout << "RETENTION_CONFIG {\"vertices\":" << reference.vertices
                  << ",\"edges\":" << reference.logical_edges << ",\"shards\":" << graph.shards.size()
                  << ",\"pma_slots\":";
        std::size_t slots = 0;
        for (const auto& shard : graph.shards) slots += shard.initial_pma_words.size();
        std::cout << slots << ",\"graph_bytes\":" << plan.total_allocated_bytes << "}\n" << std::flush;
    }
};
}  // namespace source_retention
