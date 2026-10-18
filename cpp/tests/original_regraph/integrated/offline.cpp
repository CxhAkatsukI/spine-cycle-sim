#include "model.hpp"
#include <iostream>

int main(int argc, char** argv) {
  try {
    original_r_k4::require(argc == 5 && std::string_view(argv[1]) == "control",
                          "usage: original_r_k4_model control INPUT author_initial|csr_degree OUTPUT");
    const auto selected = original_r_board::binding(argv[3]);
    const std::filesystem::path output(argv[4]);
    original_r_k4::require(!std::filesystem::exists(output) && !std::filesystem::is_symlink(output),
                          "fresh output directory required");
    const auto model = original_r_k4::Model::load(argv[2], selected);
    original_r_k4::require(std::filesystem::create_directory(output), "could not create fresh output directory");
    const auto write = [&](const char* name, const auto& words) {
      original_r_board::wt::write_words(output / name, words);
    };
    write("gathered_external.u32le", model.gathered_external);
    write("payload_external.u32le", model.payload_external);
    write("external_to_internal.u32le", model.preparation.graph.external_to_internal);
    std::ofstream json(output / "result.json");
    json << "{\n  \"schema_version\": 1,\n"
         << "  \"status\": \"OFFLINE_MATCHED_K4_A4_MODEL_PASS_NOT_FPGA\",\n"
         << "  \"binding\": \"" << argv[3] << "\",\n"
         << "  \"vertices\": " << model.original.vertices << ",\n"
         << "  \"logical_edges\": " << model.original.logical_edges << ",\n"
         << "  \"a4_published_vertices\": " << model.original.published << ",\n"
         << "  \"capacity_vertices\": " << model.original.aligned << ",\n"
         << "  \"partitions\": " << model.preparation.graph.shards.size() << ",\n"
         << "  \"graph_channels\": 23,\n  \"cache_segments\": 131072,\n"
         << "  \"partition_vertices\": 65536,\n  \"row_line_read\": true,\n"
         << "  \"iterations\": 1,\n  \"damping_numerator\": 108,\n  \"damping_denominator\": 128,\n"
         << "  \"base\": 0,\n  \"dangling_share\": 0,\n  \"rank_initial\": 0,\n"
         << "  \"updates\": 0,\n  \"g_skipped\": true,\n  \"source_prepare_skipped\": true,\n"
         << "  \"external_binary_encoding\": \"logical-V-u32le-binary32-bits\",\n"
         << "  \"permutation_encoding\": \"logical-V-u32le-external-to-internal\",\n"
         << "  \"assertions\": {\"csr_task_edges_equal\": true, \"permutation_bijection\": true, "
         << "\"pma_conservation\": true, \"packed_gather_equal\": true, "
         << "\"full_capacity_and_trailing_guards\": true, \"guarded_bank_capacity\": true},\n"
         << "  \"board_programmed\": false,\n  \"hardware_timing_measured\": false,\n"
         << "  \"publication_match\": false,\n  \"default_profile_equivalence\": false\n}\n";
    json.close();
    original_r_k4::require(json.good(), "could not write result.json");
    std::cout << "OFFLINE_MATCHED_K4_A4_MODEL_PASS_NOT_FPGA\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
