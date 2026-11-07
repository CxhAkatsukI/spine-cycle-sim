#pragma once

namespace {

// The static base occupies the highest level; lower levels absorb updates.
constexpr int kPersistentBootstrapLevel = HOST_PARTITIONED_RATIO2_LEVELS - 1;

static PartitionedHotColdReferenceGraph build_persistent_reference(
    const SetupInsertionBatch &trace
) {
    std::vector<uint64_t> indegree((size_t)trace.vertices, 0);
    for (const auto &edge : trace.old_edges) ++indegree.at(edge.dst);
    uint64_t capacity = 0;
    for (int level = kPersistentBootstrapLevel;
         level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
        capacity += partitioned_ratio2_level_partition_capacity(level);
    }
    PartitionedHotColdClassifierConfig config;
    config.num_vertices = (size_t)trace.vertices;
    config.family_edge_cap = capacity;
    config.cold_partition_target = capacity;
    config.hot_shard_edge_cap = capacity;
    const auto classification = partitioned_classify_hot_cold_from_indegree(indegree, config);
    const auto family_of = [&](uint32_t dst) {
        const int family = partitioned_dispatch_family_host(
            dst, classification.hot_bitmap_words, !classification.empty_hot_set);
        require(family >= 0 && family < HOST_PARTITIONED_CSR_FAMILY_COUNT,
                "persistent classifier produced an invalid family");
        return (size_t)family;
    };
    std::array<size_t, HOST_PARTITIONED_CSR_FAMILY_COUNT> counts{};
    for (size_t dst = 0; dst < indegree.size(); ++dst) {
        if (indegree[dst]) counts[family_of((uint32_t)dst)] += indegree[dst];
    }
    std::array<PartitionedCompactedBaselinePlan, HOST_PARTITIONED_CSR_FAMILY_COUNT> plans{};
    for (size_t family = 0; family < plans.size(); ++family) {
        plans[family] = plan_partitioned_compacted_baseline(
            counts[family], kPersistentBootstrapLevel);
        require(plans[family].fits, "persistent initial family exceeds Spine capacity");
    }
    std::vector<std::vector<PartitionedCsrEdgeRef>> levels(HOST_PARTITIONED_RATIO2_LEVELS);
    std::array<int, HOST_PARTITIONED_CSR_FAMILY_COUNT> current{};
    std::array<size_t, HOST_PARTITIONED_CSR_FAMILY_COUNT> used{};
    current.fill(HOST_PARTITIONED_RATIO2_LEVELS - 1);
    // Initial placement depends only on the old graph, never future endpoints.
    for (const auto &edge : trace.old_edges) {
        const size_t family = family_of(edge.dst);
        int &level = current[family];
        while (level >= kPersistentBootstrapLevel &&
               used[family] >= plans[family].edge_counts[(size_t)level]) {
            --level;
            used[family] = 0;
        }
        require(level >= kPersistentBootstrapLevel,
                "persistent initial planner lost an edge");
        levels[(size_t)level].push_back({edge.src, edge.dst, edge.weight, 1});
        ++used[family];
    }
    return build_partitioned_hot_cold_reference(levels, classification, trace.vertices);
}

}  // namespace
