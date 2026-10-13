#include "../../input.hpp"
#include "control.hpp"
#ifdef SEARCH_PIPELINE_SOURCE_TOP
#include "top.cpp"
#endif

int main(int argc, char** argv) {
  try {
    if (argc != 3) throw std::runtime_error("expected fixture path and stalled flag");
    search_pipeline::configure_host_threads();
    search_pipeline::check_selector();
    const common_g::Fixture fixture(argv[1]);
    const auto& batch = fixture.batches.at(0).updates;
    std::vector<search_pipeline::Raw> rows, binary;
    for (unsigned i = 0; i < fixture.rows.size(); i += 8)
      rows.emplace_back(common_g::g::little_word(std::span(fixture.rows).subspan(i, 8)));
    for (unsigned i = 0; i < fixture.binary.size(); i += 8)
      binary.emplace_back(common_g::g::little_word(std::span(fixture.binary).subspan(i, 8)));
    unsigned long probes = 0;
    for (unsigned cu = 0; cu < 4; ++cu) {
      std::vector<unsigned long> edges;
      for (unsigned i = cu; i < batch.size(); i += 4) edges.push_back(batch[i]);
      probes += search_pipeline::check(edges, binary, rows, std::string(argv[2]) == "1");
    }
    std::cout << "SEARCH_PIPELINE_FIXTURE_PASS updates=" << batch.size()
              << " probes=" << probes << '\n';
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
