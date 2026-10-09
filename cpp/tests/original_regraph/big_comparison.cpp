#include "big_network.hpp"

#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  using namespace original_regraph_test;
  try {
    require(argc == 2, "expected original Big gather/merger capture");
    std::ifstream stream(argv[1], std::ios::binary);
    require(stream.is_open(), "missing Big source capture");
    BigNetwork model(3);
    for (unsigned case_id : {0u, 1u, 2u, 0u}) {
      const auto fixture = big_fixture(case_id);
      const auto row = model.run(fixture);
      require(row.values == big_oracle(fixture), "Big model per-edge oracle mismatch");
      for (const auto value : row.values) {
        std::uint32_t original = 0;
        for (unsigned byte = 0; byte < 4; ++byte) {
          const auto part = stream.get();
          require(part != std::char_traits<char>::eof(), "truncated Big source capture");
          original |= static_cast<std::uint32_t>(part) << (byte * 8);
        }
        require(value == original, "Big model differs from original output");
      }
      std::cout << "BIG_COMPARISON {\"case\":" << case_id << ",\"cycles\":" << row.cycles
                << ",\"checked_words\":" << row.values.size() << ",\"output_stalls\":" << row.output_stalls
                << ",\"capacity_stalls\":" << row.capacity_stalls << "}\n";
    }
    require(stream.get() == std::char_traits<char>::eof(), "excess Big source capture");
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
