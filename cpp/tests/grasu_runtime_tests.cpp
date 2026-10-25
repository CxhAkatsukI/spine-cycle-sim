#include "spine_sim/grasu_regraph.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <tuple>
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

void test_bounded_cache_short_layout_preserves_state_and_traffic() {
  using namespace spine::sim;
  for (const unsigned rows : {0U, 1U, 31U, 32U, 33U}) {
    for (const bool degree : {false, true}) {
      std::vector<GraSuEdge> initial, updates, expected;
      for (unsigned source = 0; source < rows; ++source)
        initial.push_back({.source = source, .destination = 1, .weight = 3});
      expected = initial;
      if (rows) {
        updates.push_back({.source = rows - 1, .destination = 2, .weight = 5});
        expected.push_back(updates.back());
        updates.push_back({.source = 0, .destination = 1, .weight = 3, .delete_op = true});
        expected.erase(expected.begin());
      }
      auto layout = GraSuPmaLayout::build(64, initial, updates, GraSuPmaWordAbi::kWeightedFullWord);
      require(layout.segments.size() == rows, "short-cache fixture changed its parity geometry");
      Scheduler scheduler;
      const auto clock = scheduler.add_clock_mhz("G", 150);
      MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 64, true});
      GraSuNativeConfig config;
      config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
      config.compact_parallel_search = true;
      config.compact_search_contexts = 64;
      config.compact_cached_hot = true;
      config.compact_cache_valid_extent = true;
      config.maintain_out_degree = degree;
      GraSuPmaUpdateSystem system(scheduler, clock, backend, std::move(layout), updates, config);
      system.register_components();
      scheduler.add_component(backend);
      scheduler.run_until([&] { return system.done() || system.failed(); }, 100000);
      require(system.done() && !system.failed(), "bounded short-layout update failed: " + system.failure());
      auto keys = [](const std::vector<GraSuEdge> &edges) {
        std::vector<std::tuple<unsigned, unsigned, unsigned>> result;
        for (const auto &edge : edges) result.emplace_back(edge.source, edge.destination, edge.weight);
        std::sort(result.begin(), result.end());
        return result;
      };
      require(keys(system.live_edges()) == keys(expected), "bounded cache changed the logical graph");
      const auto counters = system.counters();
      const auto aligned = [](unsigned count) { return (count + 15) / 16 * 16; };
      const auto transferred = aligned((rows + 1) / 2) + aligned(rows / 2);
      require(counters.pma_reads == transferred && counters.pma_writes == transferred &&
                  counters.pma_read_bytes == transferred * 64 && counters.pma_write_bytes == transferred * 64 &&
                  counters.updates == updates.size() && counters.cache_updates == updates.size() &&
                  counters.ddr_updates == 0 && backend.outstanding() == 0,
              "bounded cache parity, padding, update or drain ledger differs from HLS");
      system.unregister_components();
      scheduler.remove_component(backend);
    }
  }
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
      {"bounded_cache_short_layout", test_bounded_cache_short_layout_preserves_state_and_traffic},
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
