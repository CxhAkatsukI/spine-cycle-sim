// Compile against the frozen CC repair host headers and its image's defines.
#define CL_HPP_ENABLE_EXCEPTIONS
#include "host_split.hpp"

#include <fstream>
#include <iostream>

static_assert(SPINE_ENABLE_CC_REPAIR == 1 && SPINE_ENABLE_SSSP_REPAIR == 0 &&
              SPINE_ALGORITHM_KIND == 1 && HOST_PARTITIONED_CSR_DST_PARTITIONS == 16);

static void measure(const char *path) {
    std::ifstream input(path);
    uint64_t vertices, edges, updates;
    if (!(input >> vertices >> edges >> updates) || !vertices || vertices > MAX_N ||
        !edges || !updates || updates > SPINE_CC_BATCH_CAPACITY ||
        edges > std::numeric_limits<uint64_t>::max() - updates) {
        throw std::runtime_error("invalid CC workload header");
    }
    std::array<uint64_t, 32> cold{}, hot{};
    std::vector<uint64_t> indegree(vertices, 0);
    for (uint64_t row = 0; row < edges + updates; ++row) {
        unsigned u, v, weight;
        if (!(input >> u >> v >> weight) || u >= vertices || v >= vertices ||
            u == v || weight > 65535) {
            throw std::runtime_error("invalid CC edge");
        }
        if (row >= edges) {
            int diff;
            if (!(input >> diff) || (diff != 1 && diff != -1)) {
                throw std::runtime_error("invalid CC update");
            }
            continue;
        }
        const auto partition = partitioned_csr_dst_partition(v);
        ++cold[partition];
        ++hot[v % 3 == 0 ? 16 + partitioned_hot_shard_host(v, 16) : partition];
        ++indegree[v];
    }
    std::string extra;
    if (input >> extra || !input.eof()) throw std::runtime_error("trailing CC records");

    const auto capacity = partitioned_ratio2_level_partition_capacity(10);
    const auto cold_max = *std::max_element(cold.begin(), cold.end());
    const auto hot_max = *std::max_element(hot.begin(), hot.end());
    std::cout << path << '\t' << vertices << '\t' << edges << '\t' << updates
              << '\t' << capacity << '\t' << cold_max << '\t' << hot_max
              << '\t' << (cold_max <= capacity ? "FIT" : "OVER")
              << '\t' << (hot_max <= capacity ? "FIT" : "OVER");

    // This existing classifier is an offline alternative, not the current CC loader.
    PartitionedHotColdClassifierConfig config;
    config.num_vertices = vertices;
    config.family_edge_cap = capacity - updates;
    try {
        const auto balanced = partitioned_classify_hot_cold_from_indegree(indegree, config);
        const auto max_cold = *std::max_element(balanced.cold_partition_edges.begin(),
                                                balanced.cold_partition_edges.end());
        const auto max_hot = *std::max_element(balanced.hot_shard_edges.begin(),
                                               balanced.hot_shard_edges.end());
        if (balanced.total_edges != edges || std::max(max_cold, max_hot) > config.family_edge_cap)
            throw std::logic_error("classifier result violates input totals or reserved capacity");
        std::cout << '\t' << max_cold << '\t' << max_hot << '\t' << balanced.hot_vertex_count
                  << "\tFIT" << std::endl;
    } catch (const std::runtime_error &error) {
        std::cerr << path << ": " << error.what() << '\n';
        std::cout << "\tNA\tNA\tNA\tOVER" << std::endl;
    }
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    try {
        std::cout << "input\tvertices\tedges\tupdates\tL10_capacity\tcold_max\thot_max"
                     "\tcold_fit\thot_fit\tbalanced_cold_max\tbalanced_hot_max"
                     "\tbalanced_hot_vertices\tbalanced_fit" << std::endl;
        for (int i = 1; i < argc; ++i) measure(argv[i]);
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
