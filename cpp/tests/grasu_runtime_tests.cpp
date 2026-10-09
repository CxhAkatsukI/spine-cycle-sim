#include "spine_sim/grasu_regraph.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using spine::sim::GraSuEdge;
using spine::sim::GraSuPartitionedPmaLayout;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void test_sharded_k4_runtime_plan_matches_u55c_contract() {
  constexpr std::size_t kVertices = 6 * 64;
  std::vector<GraSuEdge> initial;
  std::vector<GraSuEdge> updates;
  for (std::uint32_t destination = 0; destination < kVertices; ++destination) {
    initial.push_back(
        {.source = destination % 17,
         .destination = destination,
         .weight = static_cast<std::uint16_t>(destination % 7 + 1)});
    if (destination % 3 == 0) {
      updates.push_back(
          {.source = static_cast<std::uint32_t>((destination + 1) % kVertices),
           .destination = destination,
           .weight = 2});
    }
  }
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, 64, initial, updates,
      spine::sim::GraSuPmaWordAbi::kWeightedFullWord);
  const std::vector<std::size_t> update_counts(layout.partitions.size(), 21);
  const auto plan =
      spine::sim::build_grasu_regraph_runtime_plan(layout, update_counts, 8);
  require(plan.shards.size() == 6 && plan.channel_load_bytes.size() == 23,
          "sharded-K4 runtime plan has the wrong U55C geometry");
  require(plan.regions.size() == 6 * 10,
          "sharded-K4 runtime plan omitted a shard buffer role");
  std::size_t allocated_sum = 0;
  std::array<std::vector<std::pair<std::size_t, std::size_t>>, 23>
      channel_intervals;
  for (const auto &region : plan.regions) {
    require(region.channel >= region.channel_first &&
                region.channel < region.channel_last,
            "sharded-K4 runtime region escaped its routed channel range");
    require(region.allocated_bytes %
                    spine::sim::kGraSuReGraphRuntimeAlignmentBytes ==
                0,
            "sharded-K4 runtime region is not page aligned");
    require(region.channel_offset_bytes + region.allocated_bytes <=
                plan.channel_capacity_bytes,
            "sharded-K4 runtime region exceeds its channel");
    channel_intervals[region.channel].push_back(
        {region.channel_offset_bytes,
         region.channel_offset_bytes + region.allocated_bytes});
    allocated_sum += region.allocated_bytes;
  }
  require(allocated_sum == plan.total_allocated_bytes,
          "sharded-K4 runtime allocated-byte ledger is not conserved");
  for (std::size_t channel = 0; channel < channel_intervals.size(); ++channel) {
    auto &intervals = channel_intervals[channel];
    std::sort(intervals.begin(), intervals.end());
    std::size_t cursor = 0;
    for (const auto &[begin, end] : intervals) {
      require(begin == cursor && end > begin,
              "sharded-K4 runtime regions overlap or leave an offset hole");
      cursor = end;
    }
    require(cursor == plan.channel_load_bytes[channel],
            "sharded-K4 runtime channel-offset ledger is not conserved");
  }
  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard) {
    for (std::size_t lane = 0; lane < 4; ++lane) {
      const std::string region_name = "pma" + std::to_string(lane);
      const auto &pma = spine::sim::find_grasu_regraph_runtime_region(
          plan, shard, region_name);
      const std::array<std::pair<std::size_t, std::size_t>, 4> ranges{
          {{0, 6}, {6, 12}, {12, 18}, {18, 23}}};
      require(pma.channel >= ranges[lane].first &&
                  pma.channel < ranges[lane].second,
              "sharded-K4 PMA lane placement differs from routed HLS");
    }
  }
  require(spine::sim::find_grasu_regraph_runtime_region(plan, 0, "row")
                  .logical_bytes == (kVertices + 1) * sizeof(std::uint64_t),
          "sharded-K4 row buffer omitted the HLS sentinel word");
}

void test_sharded_k4_runtime_plan_rejects_channel_overflow() {
  constexpr std::size_t kVertices = 128;
  const std::vector<GraSuEdge> initial = {
      {.source = 0, .destination = 1},
      {.source = 0, .destination = 65},
  };
  const GraSuPartitionedPmaLayout layout =
      GraSuPartitionedPmaLayout::build(kVertices, 64, initial, {});
  bool rejected = false;
  try {
    (void)spine::sim::build_grasu_regraph_runtime_plan(
        layout, std::vector<std::size_t>(layout.partitions.size(), 1), 8, 23,
        4095);
  } catch (const std::overflow_error &) {
    rejected = true;
  }
  require(rejected,
          "sharded-K4 runtime plan silently exceeded pseudo-channel capacity");
}

void test_sharded_k4_runtime_plan_accepts_empty_destination_shard() {
  constexpr std::size_t kVertices = 128;
  const GraSuPartitionedPmaLayout layout = GraSuPartitionedPmaLayout::build(
      kVertices, 64, {{.source = 0, .destination = 1}}, {});
  require(layout.partitions.size() == 2 &&
              layout.partitions[1].segments.empty(),
          "empty-shard fixture unexpectedly materialized PMA segments");
  const auto plan = spine::sim::build_grasu_regraph_runtime_plan(
      layout, std::vector<std::size_t>{0, 0}, 8);
  require(plan.shards.size() == 2 && plan.shards[1].pma_slot_count == 0,
          "empty destination shard did not preserve a zero logical PMA span");
  require(spine::sim::find_grasu_regraph_runtime_region(plan, 1, "binary")
                  .allocated_bytes >=
              spine::sim::kGraSuReGraphRuntimeAlignmentBytes &&
              spine::sim::find_grasu_regraph_runtime_region(plan, 1, "pma0")
                  .allocated_bytes >=
              spine::sim::kGraSuReGraphRuntimeAlignmentBytes,
          "empty destination shard omitted its routed minimum buffers");
}

} // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"sharded_k4_runtime_plan",
       test_sharded_k4_runtime_plan_matches_u55c_contract},
      {"sharded_k4_runtime_capacity_guard",
       test_sharded_k4_runtime_plan_rejects_channel_overflow},
      {"sharded_k4_runtime_empty_shard",
       test_sharded_k4_runtime_plan_accepts_empty_destination_shard},
  };
  std::size_t failures = 0;
  for (const auto &[name, test] : tests) {
    try {
      test();
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception &error) {
      ++failures;
      std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    }
  }
  if (failures != 0) {
    std::cerr << failures << " GraSU runtime test(s) failed\n";
    return 1;
  }
  std::cout << tests.size() << " GraSU runtime test(s) passed\n";
  return 0;
}
