#include "network.hpp"

#include <fstream>
#include <iostream>
#include <limits>

namespace {
using namespace original_regraph_test;

std::uint32_t read_word(std::istream& stream) {
  std::uint32_t value = 0;
  for (unsigned byte = 0; byte < 4; ++byte) {
    const auto part = stream.get();
    require(part != std::char_traits<char>::eof(), "truncated original-source capture");
    value |= static_cast<std::uint32_t>(part) << (byte * 8);
  }
  return value;
}

void compare(std::size_t pipelines, const char* path) {
  std::ifstream stream(path, std::ios::binary);
  require(stream.is_open(), "cannot open original-source capture");
  Network model(pipelines);
  std::uint64_t checked = 0;
  for (const unsigned source_base : {0u, 4096u}) {
    std::vector<std::uint32_t> properties(rg::kLittleVertices);
    std::vector<std::uint32_t> degree(rg::kLittleVertices, 0);
    for (std::size_t vertex = 0; vertex < properties.size(); ++vertex) {
      properties[vertex] = 17 + vertex % 31;
    }
    for (unsigned edge = 0; edge < 257; ++edge) {
      ++degree[source_base + (edge * 13 % 4096)];
    }
    for (unsigned iteration = 0; iteration < 3; ++iteration) {
      std::vector<std::vector<rg::Update>> updates(pipelines);
      std::vector<std::uint32_t> expected(rg::kLittleVertices, 0);
      for (unsigned edge = 0; edge < 257; ++edge) {
        const auto source = source_base + (edge * 13 % 4096);
        const unsigned destination = edge % 3 == 0 ? rg::kLittleVertices - 1 : edge % 19;
        updates[edge % pipelines].push_back({destination, properties[source]});
        expected[destination] += properties[source];
      }
      std::vector<std::vector<rg::UpdateBurst>> input(pipelines);
      for (std::size_t pipeline = 0; pipeline < pipelines; ++pipeline) {
        input[pipeline].resize(std::max<std::size_t>(1, (updates[pipeline].size() + 7) / 8));
        for (std::size_t edge = 0; edge < input[pipeline].size() * 8; ++edge) {
          input[pipeline][edge / 8][edge % 8] = edge < updates[pipeline].size()
              ? updates[pipeline][edge] : rg::Update{rg::kDummyDestination, 0};
        }
      }
      const auto row = model.run(input, {.pipeline_start_skew = 13});
      require(row.values == expected, "cycle model differs from direct per-edge sum");
      for (std::size_t vertex = 0; vertex < row.values.size(); ++vertex) {
        require(row.values[vertex] == read_word(stream),
                "cycle model differs from original source at word " + std::to_string(checked));
        ++checked;
        // Keep this fixture inside the original signed-int arithmetic domain.
        const std::uint64_t damped = 108ull * expected[vertex];
        const std::uint64_t score = 100 + (damped >> 7);
        const std::uint64_t inverse = degree[vertex] ? 65536 / degree[vertex] : 0;
        require(damped <= std::numeric_limits<std::int32_t>::max() &&
                score * inverse <= std::numeric_limits<std::int32_t>::max(),
                "fixture exceeds admitted original signed PR arithmetic domain");
        properties[vertex] = (score * inverse) >> 16;
      }
      std::cout << "SOURCE_COMPARISON {\"little\":" << pipelines
                << ",\"source_base\":" << source_base << ",\"iteration\":" << iteration
                << ",\"cycles\":" << row.cycles << ",\"checked_words\":" << row.values.size()
                << ",\"output_stalls\":" << row.output_stalls
                << ",\"capacity_stalls\":" << row.capacity_stalls << "}\n";
    }
  }
  require(stream.get() == std::char_traits<char>::eof(), "excess original-source capture words");
  require(checked == 393216, "incomplete original-source comparison");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    std::cout << configuration_record() << '\n';
    require(argc == 3, "expected A4.u32le A11.u32le original-source captures");
    compare(4, argv[1]);
    compare(11, argv[2]);
    std::cout << "Original ReGraph source comparison passed: 786432 words\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
