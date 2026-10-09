#include "state_execution.hpp"

#include <fstream>

namespace {
using namespace original_regraph_state_test;

void compare(const char* filename, unsigned replicas) {
  std::ifstream input(filename, std::ios::binary);
  require(input.good(), "cannot open original Apply capture");
  StateWiring network(4096, {.replicas = replicas});
  for (unsigned index = 0; index < 3; ++index) {
    const auto observed = network.run("source_comparison", index);
    for (const auto actual : observed.values) {
      std::array<unsigned char, 4> bytes;
      input.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
      require(input.gcount() == 4, "truncated original Apply capture");
      std::uint32_t expected = 0;
      for (unsigned byte = 0; byte < 4; ++byte) expected |= std::uint32_t{bytes[byte]} << (byte * 8);
      require(actual == expected, "finite state path differs from original Apply/writer source");
    }
  }
  char excess;
  require(!input.get(excess) && input.eof(), "excess original Apply capture words");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    emit_configuration();
    require(argc == 3, "state comparison requires A4 and 14-replica source captures");
    compare(argv[1], 4);
    compare(argv[2], 14);
    std::cout << "All 393216 source Apply words match finite state paths and replica oracles\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
