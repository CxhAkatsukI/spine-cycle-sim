#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "kernel_process_ddr.cpp"

namespace {
std::vector<std::uint32_t> words(const char* name) {
  std::ifstream input(name, std::ios::binary);
  if (!input) throw std::runtime_error("missing G DDR fixture");
  std::vector<std::uint32_t> result;
  char bytes[4];
  while (input.read(bytes, 4)) {
    std::uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= std::uint32_t(static_cast<unsigned char>(bytes[i])) << (i * 8);
    result.push_back(value);
  }
  if (input.gcount()) throw std::runtime_error("truncated G DDR fixture");
  return result;
}
}

int main(int argc, char** argv) {
  try {
    if (argc != 4) throw std::runtime_error("usage: source_probe INITIAL UPDATES OUTPUT");
    const auto initial = words(argv[1]), updates = words(argv[2]);
    if (initial.size() != 32 * 16 || updates.size() % 3) throw std::runtime_error("invalid G DDR fixture extent");
    std::vector<ap_uint<512>> memory(MAX_CACHE_SEGMENT + 33);
    const ap_uint<512> guard = ~ap_uint<512>(0);
    std::fill(memory.begin(), memory.end(), guard);
    for (unsigned line = 0; line < 32; ++line) for (unsigned lane = 0; lane < 16; ++lane)
      memory[MAX_CACHE_SEGMENT + line].range(lane * 32 + 31, lane * 32) = initial[line * 16 + lane];
    hls::stream<pipe_type_96> stream;
    for (unsigned i = 0; i < updates.size(); i += 3) {
      pipe_type_96 packet{};
      for (unsigned word = 0; word < 3; ++word) packet.data.range(word * 32 + 31, word * 32) = updates[i + word];
      stream.write(packet);
    }
    pipe_type_96 end{}; end.data = END_EDGE; stream.write(end);
    process_ddr(memory.data(), memory.data(), memory.data(), memory.data(), stream);
    if (!stream.empty()) throw std::runtime_error("G DDR source stream not drained");
    for (unsigned line = 0; line < MAX_CACHE_SEGMENT; ++line)
      if (memory[line] != guard) throw std::runtime_error("G DDR source changed an untouched prefix line");
    if (memory.back() != guard) throw std::runtime_error("G DDR source changed the end guard");
    std::ofstream output(argv[3], std::ios::binary);
    if (!output) throw std::runtime_error("G DDR capture output missing");
    for (unsigned line = MAX_CACHE_SEGMENT; line < MAX_CACHE_SEGMENT + 32; ++line)
      for (unsigned lane = 0; lane < 16; ++lane) {
        const auto value = memory[line].range(lane * 32 + 31, lane * 32).to_uint();
        for (unsigned byte = 0; byte < 4; ++byte) output.put(static_cast<char>(value >> (byte * 8)));
      }
    if (!output) throw std::runtime_error("G DDR capture write failed");
    std::cout << "G_DDR_SOURCE {\"passed\":true,\"updates\":" << updates.size() / 3 << ",\"all_prefix_and_end_guards_unchanged\":true}\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
