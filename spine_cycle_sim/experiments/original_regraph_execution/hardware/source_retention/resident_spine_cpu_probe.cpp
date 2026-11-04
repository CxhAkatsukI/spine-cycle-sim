// Exercise the pinned Spine host's graph parser and CPU reference without programming a card.
#include <functional>
#include <fstream>
#include <iomanip>
#include <numeric>

#define main spine_algorithm_smoke_main
#include "host_partitioned_algorithms_smoke.cpp"
#undef main

int main(int argc, char **argv) {
    static_assert(SPINE_ALGORITHM_KIND == kResidualPagerank,
                  "compile with the residual PageRank host configuration");
    if (argc != 2 && argc != 3) return 2;
    try {
        const auto input = load_dynamic_workload(argv[1]);
        const auto reference = prepare_resident_benchmark_reference(
            input.baseline, input.final_graph, 0, 256);
        {
            const auto old_seed = resident_pagerank_seed(reference.initial_state, input.baseline);
            const size_t old_span = state_span(input.baseline.num_vertices);
            float old_max_residual = 0.0F;
            for (int vertex = 0; vertex < input.baseline.num_vertices; ++vertex) {
                const float value = bits_float(old_seed.state[old_span + vertex]);
                require(std::isfinite(value), "nonfinite old-graph residual");
                old_max_residual = std::max(old_max_residual, std::fabs(value));
            }
            std::cout << "SPINE_RESPR_WARM_CHECK active=" << old_seed.active.size()
                      << " max_abs_residual=" << old_max_residual << '\n';
            require(old_seed.active.empty(), "Spine CPU warm rank did not converge on the old graph");
        }
        const auto seed = resident_pagerank_seed(reference.initial_state,
                                                  input.final_graph);
        const auto vertices = static_cast<size_t>(input.final_graph.num_vertices);
        const auto changed = std::inner_product(
            reference.initial_state.begin(), reference.initial_state.begin() + vertices,
            reference.expected_state.begin(), size_t{0}, std::plus<size_t>{},
            std::not_equal_to<uint32_t>{});
        require(seed.active.empty() == (changed == 0),
                "unexpected relation between active seed and changed rank");
        if (argc == 3) {
            const size_t span = state_span(input.final_graph.num_vertices);
            std::ofstream out(argv[2]);
            out << std::setprecision(std::numeric_limits<float>::max_digits10);
            for (size_t v = 0; v < vertices; ++v) {
                out << input.baseline.adjacency[v].size() << '\t'
                    << input.final_graph.adjacency[v].size() << '\t'
                    << bits_float(reference.initial_state[v]) << '\t'
                    << bits_float(seed.state[span + v]) << '\t'
                    << bits_float(reference.expected_state[v]) << '\t'
                    << bits_float(reference.expected_state[span + v]) << '\t'
                    << (std::fabs(bits_float(seed.state[span + v])) > 1.0e-6f) << '\n';
            }
            out.close();
            require(out.good(), "failed to write Spine oracle state");
        }
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
