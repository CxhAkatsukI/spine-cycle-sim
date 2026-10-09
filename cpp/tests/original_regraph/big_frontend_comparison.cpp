#include "big_frontend_execution.hpp"

#include <fstream>

namespace {
using namespace original_regraph_big_frontend_test;
std::uint32_t word(std::istream& stream) {
  std::uint32_t value = 0;
  for (unsigned byte = 0; byte < 4; ++byte) {
    const auto part = stream.get(); require(part != std::char_traits<char>::eof(), "truncated Big frontend capture");
    value |= static_cast<std::uint32_t>(part) << (byte * 8);
  }
  return value;
}
void compare(std::istream& stream) {
  require(word(stream) == 0x42534631 && word(stream) == 1 && word(stream) == 6 && word(stream) == 0,
          "Big frontend capture header mismatch");
  std::uint64_t request_count = 0, response_words = 0, tuple_words = 0;
  for (unsigned id = 0; id < 6; ++id) {
    const unsigned offset = id == 5 ? 65536 : 0;
    Network model({.destination_offset=offset});
    const auto row = execute(model, id);
    require(word(stream) == id && word(stream) == offset && word(stream) == row.updates.size() &&
            word(stream) == row.requests.size() && word(stream) == row.responses.size(), "Big frontend capture case geometry");
    for (const auto request : row.requests) {
      require(word(stream) == request.line && word(stream) == request.lane && word(stream) == request.end,
              "Big request differs from original generator/sender");
      ++request_count;
    }
    for (const auto& response : row.responses) {
      require(word(stream) == response.lane && word(stream) == response.end, "Big wrapper response lane/end mismatch");
      for (const auto value : response.data) {
        require(word(stream) == value, "Big source memory differs from original wrapper data");
        ++response_words;
      }
    }
    for (const auto& burst : row.updates) for (const auto update : burst) {
      require(word(stream) == update.destination && word(stream) == update.value,
              "Big Scatter differs from original output");
      tuple_words += 2;
    }
    report(("source_case" + std::to_string(id)).c_str(), row);
  }
  require(stream.get() == std::char_traits<char>::eof(), "excess Big frontend capture");
  std::cout << "BIG_FRONTEND_COMPARISON {\"cases\":6,\"requests\":" << request_count
            << ",\"response_words\":" << response_words << ",\"tuple_words\":" << tuple_words << "}\n";
}
}  // namespace
int main(int argc, char** argv) {
  try { require(argc == 2, "expected original Big frontend capture"); std::ifstream stream(argv[1], std::ios::binary);
        require(stream.is_open(), "cannot open Big frontend capture"); compare(stream); return 0; }
  catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
