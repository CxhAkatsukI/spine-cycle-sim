#include "integrated.hpp"
#include "spine.hpp"
#include "../../routed_regraph/round_execution.hpp"

int main(int argc, char** argv) {
  using namespace warm_comparison;
  try {
    require(argc == 7, "usage: warm_demo INPUT|smoke OUTPUT LATENCY REVERSE MAX_CYCLES ARM");
    const auto input = load(argv[1]);
    const std::filesystem::path output(argv[2]);
    const auto latency = routed_regraph_round_test::number(argv[3]);
    const auto reverse = routed_regraph_round_test::number(argv[4]);
    const auto maximum = routed_regraph_round_test::number(argv[5]);
    require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output) &&
        latency > 0 && reverse <= 1 && maximum > 0, "invalid output or finite run bounds");
    ei::wt::write_words(output / "old_state.u32le", input.after.initial.primary);
    ei::wt::write_words(output / "expected.u32le", dijkstra(input.after.compact.vertices, input.after.edges, input.root));
    std::cout << "WARM_INPUT {\"vertices\":" << input.after.compact.vertices
        << ",\"old_edges\":" << input.before.size() << ",\"root\":" << input.root
        << ",\"oracle_rounds\":" << input.oracle.states.size() << ",\"updates\":[";
    for (std::size_t i = 0; i < input.updates.size(); ++i) {
      const auto& edge = input.updates[i];
      if (i) std::cout << ',';
      std::cout << '[' << edge.source << ',' << edge.destination << ',' << edge.weight << ']';
    }
    std::cout << "]}" << std::endl;
    const std::string arm(argv[6]);
    if (arm == "gr") integrated(input, output, latency, reverse, maximum);
    else if (arm == "spine") {
      require(reverse == 0, "Spine uses its fixed public registration order");
      warm_comparison::spine(input, output, latency, maximum);
    } else throw std::invalid_argument("unknown warm comparison arm");
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
