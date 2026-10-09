#include "probe_support.hpp"
#include "acc_gather.h"
#include "kernel_big_gs_merger.cpp"
#include "big_merger_call.hpp"

#include <fstream>

namespace {
void gather(unsigned path, unsigned case_id, hls::stream<b_tmp_prop_pkt>& output) {
  const unsigned bursts = case_id == 1 ? 0 : (case_id == 2 ? 1000 : 257);
  hls::stream<update_set_dt> sets;
  for (unsigned burst = 0; burst < bursts; ++burst) {
    update_set_dt set{};
    for (unsigned lane = 0; lane < 8; ++lane) {
      const unsigned index = burst * 8 + lane;
      unsigned destination = case_id == 2 ? (index % 2 ? 8u : 0u)
          : static_cast<unsigned>((index * 7919ull + path * 17) % BIG_KERNEL_DST_BUFFER_SIZE);
      if (case_id != 2 && index % 29 == 0) destination = BIG_KERNEL_DST_BUFFER_SIZE - 1;
      if (index % 31 == 0) destination = (1u << 19) | (index & 7u);
      set.tuples[lane].dst = destination;
      set.tuples[lane].update = index % 17 ? 17 + (index + path) % 31 : 0;
    }
    sets.write(set);
  }
  hls::stream<update_tuple_dt> layers[4][8];
  dispatchUpdateTuples(sets, layers[0], bursts * 8);
  for (unsigned stage = 0; stage < 3; ++stage) {
    for (unsigned pair = 0; pair < 4; ++pair) {
      // The template parameter is unused by the original C functions.
      switch2x2<0>(2 - stage, layers[stage][pair], layers[stage][pair + 4],
                    layers[stage + 1][pair * 2], layers[stage + 1][pair * 2 + 1]);
    }
  }
  hls::stream<ap_uint<64>> rows[8];
  for (unsigned bank = 0; bank < 8; ++bank) accGather(layers[3][bank], rows[bank], 0);
  writeResults(rows, 0, output);
  require(sets.empty(), "Big dispatch input conservation");
  for (auto& layer : layers) for (auto& queue : layer) require(queue.empty(), "Big omega conservation");
  for (auto& queue : rows) require(queue.empty(), "Big bank-row conservation");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 2 && BIG_KERNEL_NUM == 3, "expected capture path and three Big pipelines");
    std::ofstream capture(argv[1], std::ios::binary);
    require(capture.is_open(), "cannot create Big capture");
    for (unsigned case_id : {0u, 1u, 2u, 0u}) {
      hls::stream<b_tmp_prop_pkt> inputs[BIG_KERNEL_NUM];
      for (unsigned path = 0; path < BIG_KERNEL_NUM; ++path) gather(path, case_id, inputs[path]);
      PartitionOutput<write_burst_pkt> observer(BIG_KERNEL_DST_BUFFER_SIZE / 16);
      hls::stream<write_burst_pkt> merged;
      merged.set_delegate(&observer);
      bool cut = false;
      try { call_big_merger(inputs, merged); } catch (const PrefixComplete&) { cut = true; }
      require(cut && observer.values.size() == BIG_KERNEL_DST_BUFFER_SIZE / 16, "Big merger partition prefix");
      for (auto& input : inputs) require(input.empty(), "Big global merger conservation");
      for (const auto& line : observer.values) for (unsigned word = 0; word < 16; ++word) {
        const auto value = line.data.range(word * 32 + 31, word * 32).to_uint();
        for (unsigned byte = 0; byte < 4; ++byte) capture.put(static_cast<char>((value >> (8 * byte)) & 255u));
      }
    }
    capture.close();
    require(capture.good(), "Big source capture failed");
    std::cout << "BIG_SOURCE {\"cases\":4,\"checked_words\":2097152,\"big\":3,\"boundary\":\"dispatch_to_global_merger\"}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
