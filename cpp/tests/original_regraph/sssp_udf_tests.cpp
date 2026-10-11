#include "network.hpp"

#include <iostream>

namespace {
using namespace original_regraph_test;

void arithmetic() {
  require(rg::scatter_sssp_property(12, 3) == 0, "inactive source scattered");
  require(rg::scatter_sssp_property(rg::kSsspActive, 0) == rg::kSsspActive,
          "active zero-distance/weight disappeared");
  require(rg::scatter_sssp_property(rg::kSsspInfinity | rg::kSsspActive, 3) == 0,
          "infinite source scattered");
  require(rg::scatter_sssp_property((rg::kSsspInfinity - 2) | rg::kSsspActive, 4095) ==
          (rg::kSsspInfinity | rg::kSsspActive), "distance saturation differs from HLS");
  require(rg::reduce_property(rg::Udf::kWeightedSssp, rg::kSsspActive | 8, 0) ==
          (rg::kSsspActive | 8), "inactive update changed minimum");
  require(rg::reduce_property(rg::Udf::kFixedPointPr, 0xffffffffu, 2) == 1,
          "legacy unsigned addition changed");
  require(rg::apply_sssp_property(rg::kSsspActive | 3, rg::kSsspActive | 5) ==
          (rg::kSsspActive | 3), "strict improvement lost");
  for (const auto update : {0u, 3u, rg::kSsspActive | 5, rg::kSsspActive | 7})
    require(rg::apply_sssp_property(update, rg::kSsspActive | 5) == 5,
            "Apply did not clear stale active bit");
}

std::vector<std::uint32_t> minimum_oracle(
    const std::vector<std::vector<rg::UpdateBurst>>& input) {
  std::vector<std::uint32_t> values(rg::kLittleVertices);
  for (const auto& path : input) for (const auto& burst : path) for (const auto update : burst) {
    if ((update.destination & rg::kDummyDestination) || !(update.value >> 31)) continue;
    auto& value = values[update.destination & 65535u];
    if (!(value >> 31) || (update.value & 0x7fffffffu) < (value & 0x7fffffffu))
      value = update.value;
  }
  return values;
}

void gather_paths() {
  auto input = stress_fixture(4, 513);
  for (std::size_t path = 0; path < input.size(); ++path)
    for (std::size_t burst = 0; burst < input[path].size(); ++burst)
      for (std::size_t lane = 0; lane < 8; ++lane)
        input[path][burst][lane].value = (burst + lane) % 5 == 0 ? 0 :
            rg::kSsspActive | static_cast<std::uint32_t>((path * 7 + burst + lane) % 113);
  const auto expected = minimum_oracle(input);
  Network normal(4, 8, {}, false, rg::Udf::kWeightedSssp);
  const auto first = normal.run(input);
  require(first.values == expected, "SSSP full minimum output mismatch");
  Network reverse(4, 8, {}, true, rg::Udf::kWeightedSssp);
  const auto reversed = reverse.run(input);
  require(reversed.values == first.values && reversed.cycles == first.cycles &&
          reversed.output_stalls == first.output_stalls &&
          reversed.capacity_stalls == first.capacity_stalls, "SSSP registration-order dependence");
  Network narrow(4, 1, {}, false, rg::Udf::kWeightedSssp);
  const auto stalled = narrow.run(input, {.source_interval = 3, .pipeline_start_skew = 97,
      .sink_interval = 19, .sink_start = 50000});
  require(stalled.values == expected && stalled.output_stalls > 0 &&
          stalled.cycles > first.cycles, "SSSP backpressure not conserved");
  const auto empty = normal.run(std::vector<std::vector<rg::UpdateBurst>>(4));
  require(std::all_of(empty.values.begin(), empty.values.end(), [](auto word) { return word == 0; }),
          "SSSP neutral state leaked across restart");
  const auto repeated = normal.run(input);
  require(repeated.values == first.values && repeated.cycles == first.cycles,
          "SSSP repeated partition differs");
  for (unsigned path = 0; path < 4; ++path) {
    const auto& counters = normal.gather(path).counters();
    require(counters.forwarded_reads > 0 && counters.valid_updates == counters.uram_writes &&
            counters.valid_updates + counters.dummy_updates == 2 * 513 * 8 &&
            counters.partitions == 3, "SSSP gather work conservation");
  }
  std::cout << "SSSP_GATHER {\"checked_words\":65536,\"paths\":4,\"cycles\":" << first.cycles
            << ",\"stalled_cycles\":" << stalled.cycles << ",\"restart_passed\":true}\n";
}
}  // namespace

int main() {
  try {
    arithmetic();
    gather_paths();
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
