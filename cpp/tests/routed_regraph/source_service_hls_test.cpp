#include <iostream>
#include <stdexcept>
#include <vector>

#include GRASU_HBM_WRAPPER_SOURCE

namespace {
void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

void check(unsigned left, unsigned right) {
  hls::stream<l_ppb_request_pkt> requests[2];
  hls::stream<l_ppb_response_pkt> responses[2];
  std::vector<ap_uint<512>> memory[2];
  const unsigned counts[2] = {left, right};
  for (unsigned worker = 0; worker < 2; ++worker) {
    memory[worker].resize(1024);
    for (unsigned line = 0; line < 1024; ++line)
      for (unsigned word = 0; word < 16; ++word)
        memory[worker][line].range(word * 32 + 31, word * 32) =
            0x80000000u | (worker << 24) | (line * 16 + word);
    for (unsigned invocation = 0; invocation < counts[worker]; ++invocation) {
      for (unsigned block = 0; block < 2; ++block) {
        l_ppb_request_pkt request{};
        request.data = invocation * 2 + block;
        requests[worker].write(request);
      }
      l_ppb_request_pkt end{};
      end.last = 1;
      requests[worker].write(end);
    }
  }
#if GRASU_SOURCE_PAIRWISE
  sharedLittleKernelReadMemory<0>(memory[0].data(), memory[1].data(), left, right,
                                 requests[0], requests[1], responses[0], responses[1]);
#else
  littleKernelReadMemory<0>(0, memory[0].data(), left, requests[0], responses[0]);
  littleKernelReadMemory<1>(1, memory[1].data(), right, requests[1], responses[1]);
#endif
  for (unsigned worker = 0; worker < 2; ++worker) {
    require(requests[worker].empty(), "HLS left an invocation request unread");
    for (unsigned invocation = 0; invocation < counts[worker]; ++invocation) {
      for (unsigned block = 0; block < 2; ++block)
        for (unsigned line = 0; line < 256; ++line) {
          require(!responses[worker].empty(), "HLS lost a source line");
          const auto response = responses[worker].read();
          const auto address = (invocation * 2 + block) * 256 + line;
          require(!response.last && response.dest == address && response.data == memory[worker][address],
                  "HLS source address, data or sidebands differ");
#if GRASU_SOURCE_PAIRWISE
          require(response.keep == ap_uint<64>(-1) && response.strb == ap_uint<64>(-1), "pairwise sidebands differ");
#endif
        }
      require(!responses[worker].empty(), "HLS lost a source terminator");
      const auto end = responses[worker].read();
      require(end.last, "HLS source terminator differs");
#if GRASU_SOURCE_PAIRWISE
      require(end.data == 0 && end.dest == 0, "pairwise source terminator payload differs");
#endif
    }
    require(responses[worker].empty(), "HLS produced extra source responses");
  }
}
} // namespace

int main() {
  try {
    for (unsigned left = 0; left < 3; ++left)
      for (unsigned right = 0; right < 3; ++right) check(left, right);
#if GRASU_SOURCE_PAIRWISE
    std::cout << "PASS: 9 worktree HLS pairwise source payload/count cases\n";
#else
    std::cout << "PASS: 9 routed SSSP HLS dedicated source payload/count cases\n";
#endif
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
