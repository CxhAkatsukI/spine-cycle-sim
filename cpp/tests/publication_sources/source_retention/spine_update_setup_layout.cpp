// Compile against the pinned Spine weighted host. No XRT device is opened.
#define main spine_board_main
#include "host_partitioned_algorithms_smoke.cpp"
#undef main

static uint64_t fingerprint_words(
    uint64_t hash,
    const std::vector<uint64_t> &words
) {
    hash = (hash ^ words.size()) * 1099511628211ULL;
    for (uint64_t word : words) {
        hash = (hash ^ word) * 1099511628211ULL;
    }
    return hash;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " graph [graph ...]\n";
        return 2;
    }
    bool failed = false;
    for (int i = 1; i < argc; ++i) {
        try {
            auto batch = read_setup_insertion_batch(argv[i]);
            const auto start = std::chrono::steady_clock::now();
            const auto image = serialize_partitioned_hot_cold_graph_reference(
                build_compacted_hot_cold_reference(setup_baseline_workload(batch), nullptr),
                PartitionedActiveBinFlat{});
            const auto elapsed_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - start).count();
            const size_t updates = batch.inserts.size();
            batch.inserts.clear();
            const size_t checked = check_setup_updated_graph(image.graph_words, image.meta_words, batch);
            size_t max_bank_words = 0;
            uint64_t graph_hash = 14695981039346656037ULL;
            for (const auto &bank : image.graph_words) {
                max_bank_words = std::max(max_bank_words, bank.size());
                graph_hash = fingerprint_words(graph_hash, bank);
            }
            const uint64_t meta_hash =
                fingerprint_words(14695981039346656037ULL, image.meta_words);
            std::cout << "SPINE_UPDATE_SETUP_LAYOUT_PASS path=" << argv[i]
                      << " vertices=" << batch.vertices << " checked_old_edges=" << checked
                      << " parsed_updates=" << updates << " max_bank_words=" << max_bank_words
                      << " graph_hash=" << std::hex << graph_hash
                      << " meta_hash=" << meta_hash << std::dec
                      << " layout_ms=" << elapsed_ms
                      << std::endl;
        } catch (const std::exception &error) {
            failed = true;
            std::cerr << "SPINE_UPDATE_SETUP_LAYOUT_FAIL path=" << argv[i]
                      << " reason=" << error.what() << std::endl;
        }
    }
    return failed ? 1 : 0;
}
