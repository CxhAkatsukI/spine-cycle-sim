#include "a4_input.hpp"
#include "../a4.hpp"
#include "../../routed_regraph/round_execution.hpp"

int main(int argc, char** argv) {
  using namespace warm_comparison;
  try {
    require(argc == 4 || argc == 8, "usage: a4 INPUT OUTPUT export|LAYOUT [LATENCY REVERSE MAX_CYCLES run]");
    auto input = load(argv[1]);
    const std::filesystem::path output(argv[2]);
    require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output), "fresh output required");
    capture_input(input, output);
    if (argc == 4) {
      require(std::string(argv[3]) == "export", "unknown export mode");
      std::ofstream graph(output / "graph.txt");
      for (const auto& edge : input.after.edges) graph << edge.source << ' ' << edge.destination << '\n';
      graph.close(); require(graph.good(), "graph export failed");
    } else {
      require(std::string(argv[7]) == "run", "unknown execution mode");
      const auto latency = routed_regraph_round_test::number(argv[4]);
      const auto reverse = routed_regraph_round_test::number(argv[5]);
      const auto maximum = routed_regraph_round_test::number(argv[6]);
      require(latency > 0 && reverse <= 1 && maximum > 0, "finite execution bounds required");
      attach_author_layout(input, argv[3]);
      ei::a4(input.after, input.oracle, output, latency, reverse, maximum, ei::control("a4_io16"));
      auto state = ei::wt::read_words(output / "replica0.u32le", input.after.compact.aligned_vertices);
      state.resize(input.after.compact.vertices);
      for (auto& value : state) {
        require(!(value & ei::rg::kSsspActive), "nonconverged final state");
        value &= ei::rg::kSsspValueMask;
        if (value == ei::rg::kSsspInfinity) value = GraphAlgorithmPolicy::kSsspInfinity;
      }
      ei::wt::write_words(output / "final.u32le", state);
    }
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
