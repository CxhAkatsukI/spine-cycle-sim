#include "probe_support.hpp"
#include "acc_data_types.h"
#include "kernel_apply.cpp"
#include "hbm_wrapper.h"
#include "property_writer_call.hpp"

#include <array>
#include <fstream>

namespace {
constexpr unsigned vertices = 65536;
constexpr unsigned lines = vertices / 16;
constexpr std::array<unsigned, 3> arguments{0, 3, 17};
constexpr std::array<unsigned, 8> degrees{0, 1, 2, 3, 7, 31, 65536, 65537};

void capture_word(std::ofstream& output, std::uint32_t value) {
  if (!output.is_open()) return;
  for (unsigned byte = 0; byte < 4; ++byte) output.put(static_cast<char>((value >> (byte * 8)) & 255u));
  require(output.good(), "Apply capture write failed");
}

void run_case(unsigned index, std::ofstream& capture) {
  std::vector<ap_uint<512>> degree(lines);
  hls::stream<write_burst_pkt> little;
#if BIG_KERNEL_NUM
  hls::stream<write_burst_pkt> big;
#endif
  hls::stream<write_burst_pkt> applied;
  std::vector<unsigned> expected(vertices);
  for (unsigned line = 0; line < lines; ++line) {
    write_burst_pkt packet{};
    for (unsigned word = 0; word < 16; ++word) {
      const auto vertex = line * 16 + word;
      const auto sum = (vertex * 37 + index * 101) % 4096;
      const auto outdegree = degrees[vertex % degrees.size()];
      packet.data.range(word * 32 + 31, word * 32) = sum;
      degree[line].range(word * 32 + 31, word * 32) = outdegree;
      expected[vertex] = oracle_pr(sum, outdegree, arguments[index]);
    }
    little.write(packet);
  }
  kernelApply(degree.data(), 1, 0, arguments[index], little,
#if BIG_KERNEL_NUM
              big,
#endif
              applied);
  require(little.empty() && applied.size() == lines + 1, "Apply input/output extent mismatch");
#if BIG_KERNEL_NUM
  require(big.empty(), "unused Big component produced input");
#endif
  hls::stream<write_burst_pkt> writer_input;
  for (unsigned line = 0; line < lines; ++line) {
    auto packet = applied.read();
    require(!packet.last && packet.dest == line, "Apply write index/terminator mismatch");
    for (unsigned word = 0; word < 16; ++word) {
      const auto observed = packet.data.range(word * 32 + 31, word * 32).to_uint();
      require(observed == expected[line * 16 + word], "original Apply differs from independent PR oracle");
      capture_word(capture, observed);
    }
    writer_input.write(packet);
  }
  const auto end = applied.read();
  require(end.last && applied.empty(), "Apply missing or duplicate terminator");
  writer_input.write(end);
  std::vector<std::vector<ap_uint<512>>> replicas(LITTLE_KERNEL_NUM + BIG_KERNEL_NUM,
      std::vector<ap_uint<512>>(lines + 2, ap_uint<512>{-1}));
  call_property_writer(replicas, writer_input);
  require(writer_input.empty(), "original property writer left input");
  for (const auto& replica : replicas) {
    for (unsigned line = 0; line < lines; ++line) {
      for (unsigned word = 0; word < 16; ++word) {
        require(replica[line].range(word * 32 + 31, word * 32).to_uint() == expected[line * 16 + word],
                "original writer replica value mismatch");
      }
    }
    require(replica[lines] == ap_uint<512>{-1} && replica[lines + 1] == ap_uint<512>{-1},
            "original writer overwrote allocation guard");
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    std::ofstream capture;
    if (argc == 3 && std::string(argv[1]) == "--capture-applied") capture.open(argv[2], std::ios::binary);
    else require(argc == 1, "usage: probe [--capture-applied FILE]");
    require(argc == 1 || capture.good(), "cannot open Apply capture");
    for (unsigned index = 0; index < arguments.size(); ++index) run_case(index, capture);
    if (capture.is_open()) { capture.close(); require(capture.good(), "Apply capture close failed"); }
    std::cout << "PUBLICATION_PROBE {\"kind\":\"regraph_apply\",\"passed\":true,\"little\":"
              << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
              << ",\"cases\":3,\"checked_vertices\":" << vertices * arguments.size()
              << ",\"replica_words_checked\":" << vertices * arguments.size() * (LITTLE_KERNEL_NUM + BIG_KERNEL_NUM)
              << ",\"degree_zero_words\":" << vertices / 8 * arguments.size()
              << ",\"write_terminators\":3}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
