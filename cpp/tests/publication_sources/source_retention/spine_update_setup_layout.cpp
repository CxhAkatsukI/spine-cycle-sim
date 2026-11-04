// Compile against the pinned Spine weighted host. No XRT device is opened.
#define main spine_board_main
#include "host_partitioned_algorithms_smoke.cpp"
#undef main

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " graph [graph ...]\n";
        return 2;
    }
    bool failed = false;
    for (int i = 1; i < argc; ++i) {
        try {
            auto batch = read_setup_insertion_batch(argv[i]);
            const auto image = serialize_partitioned_hot_cold_graph_reference(
                build_compacted_hot_cold_reference(setup_baseline_workload(batch), nullptr),
                PartitionedActiveBinFlat{});
            const size_t updates = batch.inserts.size();
            batch.inserts.clear();
            const size_t checked = check_setup_updated_graph(image.graph_words, image.meta_words, batch);
            size_t max_bank_words = 0;
            for (const auto &bank : image.graph_words) {
                max_bank_words = std::max(max_bank_words, bank.size());
            }
            std::cout << "SPINE_UPDATE_SETUP_LAYOUT_PASS path=" << argv[i]
                      << " vertices=" << batch.vertices << " checked_old_edges=" << checked
                      << " parsed_updates=" << updates << " max_bank_words=" << max_bank_words
                      << std::endl;
        } catch (const std::exception &error) {
            failed = true;
            std::cerr << "SPINE_UPDATE_SETUP_LAYOUT_FAIL path=" << argv[i]
                      << " reason=" << error.what() << std::endl;
        }
    }
    return failed ? 1 : 0;
}
