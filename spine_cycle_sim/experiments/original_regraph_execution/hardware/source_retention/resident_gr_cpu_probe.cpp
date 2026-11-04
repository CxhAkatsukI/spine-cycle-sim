// Exercise the same graph parser and CPU oracles as the pinned G+R ResPR host.
#include <iomanip>

#define main grasu_respr_main
#include "sharded_k4_pagerank_native_host.cpp"
#undef main

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    try {
        const auto input = read_dataset(argv[1]);
        const auto old_edges = build_static_external_edges(input);
        const auto new_edges = build_final_external_edges(input);
        const auto warm = run_full_pagerank_oracle(
            input.node_size, old_edges, 128, kPageRankDamping);
        {
            const auto warm_check = run_residual_pagerank_oracle(
                input.node_size, old_edges, warm.rank, 0, kPageRankDamping, kPageRankEpsilon);
            float old_max_residual = 0.0F;
            for (float value : warm_check.residual) {
                if (!std::isfinite(value)) fail("nonfinite old-graph residual");
                old_max_residual = std::max(old_max_residual, std::abs(value));
            }
            std::cout << "GR_RESPR_WARM_CHECK active=" << warm_check.correction_active_vertices
                      << " max_abs_residual=" << old_max_residual << '\n';
            if (!warm_check.converged) fail("G+R CPU warm rank did not converge on the old graph");
        }
        // Zero rounds returns the unconsumed correction without changing the warm rank.
        const auto seed = run_residual_pagerank_oracle(
            input.node_size, new_edges, warm.rank, 0, kPageRankDamping, kPageRankEpsilon);
        const auto final = run_residual_pagerank_oracle(
            input.node_size, new_edges, warm.rank, kResidualPageRankMaxRounds,
            kPageRankDamping, kPageRankEpsilon);
        if (!final.converged) fail("G+R CPU PageRank reference did not converge");
        std::ofstream out(argv[2]);
        out << std::setprecision(std::numeric_limits<float>::max_digits10);
        for (size_t v = 0; v < warm.rank.size(); ++v) {
            out << warm.out_degree[v] << '\t' << final.out_degree[v] << '\t'
                << warm.rank[v] << '\t' << seed.residual[v] << '\t'
                << final.rank[v] << '\t' << final.residual[v] << '\t'
                << (std::abs(seed.residual[v]) > kPageRankEpsilon) << '\n';
        }
        out.close();
        if (!out.good()) fail("failed to write G+R oracle state");
        std::cout << "GR_RESPR_CPU_PREFLIGHT status=PASS vertices=" << warm.rank.size()
                  << " active_seed=" << seed.correction_active_vertices
                  << " propagation_rounds=" << final.propagation_rounds << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
