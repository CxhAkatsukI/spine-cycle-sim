// Exercise the pinned Spine host's graph parser and CPU reference without programming a card.
#include <functional>
#include <numeric>

#define main spine_algorithm_smoke_main
#include "host_partitioned_algorithms_smoke.cpp"
#undef main

int main(int argc, char **argv) {
    static_assert(SPINE_ALGORITHM_KIND == kResidualPagerank,
                  "compile with the residual PageRank host configuration");
    if (argc != 2) return 2;
    try {
        const auto input = load_dynamic_workload(argv[1]);
        const auto reference = prepare_resident_benchmark_reference(
            input.baseline, input.final_graph, 0, 256);
        const auto seed = resident_pagerank_seed(reference.initial_state,
                                                  input.final_graph);
        const auto vertices = static_cast<size_t>(input.final_graph.num_vertices);
        const auto changed = std::inner_product(
            reference.initial_state.begin(), reference.initial_state.begin() + vertices,
            reference.expected_state.begin(), size_t{0}, std::plus<size_t>{},
            std::not_equal_to<uint32_t>{});
        require(seed.active.empty() == (changed == 0),
                "unexpected relation between active seed and changed rank");
        std::cout << "SPINE_RESPR_CPU_PREFLIGHT status=PASS"
                  << " vertices=" << vertices
                  << " logical_updates=" << input.logical_updates
                  << " physical_updates=" << input.physical_updates.size()
                  << " active_seed=" << seed.active.size()
                  << " changed_ranks=" << changed << " converged=1\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
