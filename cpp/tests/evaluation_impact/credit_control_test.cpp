#include <iostream>

#include "control.hpp"
#include "k4_config.hpp"
#include "../original_regraph/memory_fixture.hpp"

int main() {
  using namespace evaluation_impact;
  const auto a4 = control("a4"), a4_io = control("a4_io16");
  const auto candidate = control("candidate"), apply = control("candidate_apply2");
  const auto parents = control("candidate_parents2"), both = control("candidate_both2");
  auto require = [](bool value) { if (!value) throw std::runtime_error("credit control mismatch"); };
  require(a4.original && !a4.candidate && a4.a4_input_parents == 2 && a4.a4_state_parents == 2);
  require(a4_io.original && a4_io.a4_input_parents == 16 && a4_io.a4_state_parents == 16);
  require(!control("cross_row").candidate && !control("cross_row").original);
  require(candidate.candidate && candidate.k4_parents == 16 && candidate.k4_apply_window == 16);
  require(apply.candidate && apply.k4_parents == 16 && apply.k4_apply_window == 2);
  require(parents.candidate && parents.k4_parents == 2 && parents.k4_apply_window == 16);
  require(both.candidate && both.k4_parents == 2 && both.k4_apply_window == 2);
  const auto bank = control("bank_stream");
  const auto bank_config = k4_configuration(bank);
  const auto old_config = k4_configuration(candidate);
  require(bank.candidate && bank.bank_stream && !bank.original);
  require(bank_config.source_topology == spine::sim::RoutedSourceTopology::kTwoPairwise);
  require(old_config.source_topology != bank_config.source_topology && !candidate.bank_stream);
  require(bank_config.adapter.cross_row.bank_stream && bank_config.adapter.cross_row.bank_read_beats &&
          bank_config.adapter.cross_row.directory_cache_rows == 1024 &&
          bank_config.adapter.cross_row.bank_fifo_lines == 256 &&
          bank_config.adapter.cross_row.reader_pipeline_capacity == 2 &&
          bank_config.adapter.cross_row.block_drain_cycles == 2 &&
          bank_config.compute.max_pending_requests == 16 && bank_config.compute.apply_request_window == 16);
  require(original_regraph_memory_test::axi_config(1, 0).max_pending_requests == 2);
  require(bank_config.source_loading == spine::sim::RoutedSourceLoading::kEdgeCoupled);
  const auto compact = control("prefetch_compact"), independent = control("prefetch_source");
  require(compact.prefetch_compact && !compact.independent_source && independent.prefetch_compact &&
          independent.independent_source && independent.bank_stream && !independent.original);
  require(k4_configuration(compact).source_loading == spine::sim::RoutedSourceLoading::kEdgeCoupled &&
          k4_configuration(independent).source_loading == spine::sim::RoutedSourceLoading::kIndependentExperimental);
  const auto elastic = control("prefetch_dual_elastic");
  require(elastic.dual_elastic && elastic.prefetch_compact && elastic.independent_source &&
          k4_configuration(elastic).input_path == spine::sim::RoutedInputPath::kDualPrefetchElasticExperimental &&
          k4_configuration(elastic).compute.max_pending_requests == 16);
  const auto triple = control("prefetch_triple_elastic");
  require(triple.triple_elastic && !triple.dual_elastic && triple.prefetch_compact && triple.independent_source &&
          k4_configuration(triple).input_path == spine::sim::RoutedInputPath::kTriplePrefetchElasticExperimental &&
          k4_configuration(triple).compute.max_pending_requests == 16);
  const auto split = control("prefetch_triple_split_apply");
  require(split.split_apply && split.triple_elastic && split.independent_source &&
          k4_configuration(split).apply_topology == spine::sim::RoutedApplyTopology::kSplitMastersExperimental &&
          k4_configuration(split).input_path == spine::sim::RoutedInputPath::kTriplePrefetchElasticExperimental &&
          k4_configuration(split).compute.apply_request_window == 16);
  require(!triple.split_apply &&
          k4_configuration(triple).apply_topology == spine::sim::RoutedApplyTopology::kSharedMaster &&
          spine::sim::RoutedReGraphConfig{}.apply_topology == spine::sim::RoutedApplyTopology::kSharedMaster);
  const auto directory = control("prefetch_directory_lookahead");
  const auto ready = control("prefetch_ready_bursts");
  const auto refill = control("prefetch_ready_fullburst");
  require(refill.full_burst_refill && refill.ready_bursts && refill.directory_lookahead &&
          refill.split_apply && refill.triple_elastic &&
          k4_configuration(refill).experimental_full_burst_refill &&
          !k4_configuration(ready).experimental_full_burst_refill &&
          !spine::sim::RoutedReGraphConfig{}.experimental_full_burst_refill);
  require(ready.ready_bursts && ready.directory_lookahead && ready.triple_elastic && ready.split_apply &&
          k4_configuration(ready).gather_schedule == spine::sim::RoutedGatherSchedule::kReadyBurstsExperimental &&
          k4_configuration(directory).gather_schedule == spine::sim::RoutedGatherSchedule::kPartitionOrder &&
          spine::sim::RoutedReGraphConfig{}.gather_schedule == spine::sim::RoutedGatherSchedule::kPartitionOrder);
  require(directory.directory_lookahead && directory.split_apply && directory.triple_elastic &&
          k4_configuration(directory).experimental_directory_tiles == 2 &&
          k4_configuration(split).experimental_directory_tiles == 1 &&
          spine::sim::RoutedReGraphConfig{}.experimental_directory_tiles == 1);
  for (const auto& [arm, masters] : {
      std::pair{"candidate", 9U}, std::pair{"bank_stream", 7U},
      std::pair{"prefetch_dual_elastic", 11U}, std::pair{"prefetch_triple_elastic", 15U},
      std::pair{"prefetch_triple_split_apply", 16U}, std::pair{"prefetch_directory_lookahead", 16U},
      std::pair{"prefetch_ready_bursts", 16U}, std::pair{"prefetch_ready_fullburst", 16U}}) {
    using namespace spine::sim;
    const auto selected = control(arm);
    require(k4_physical_masters(selected) == masters);
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("core", 150);
    MockMemoryBackend backend("memory", clock, {32, 64, 1, 32, 32, true});
    auto layout = GraSuPartitionedPmaLayout::build(2, 65536, {{0, 1, 1, false}}, {},
                                                GraSuPmaWordAbi::kWeightedFullWord);
    AlgorithmInitialState initial;
    initial.primary = {0, GraphAlgorithmPolicy::kSsspInfinity};
    initial.active_vertices = {0};
    RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), initial,
                              k4_configuration(selected));
    require(backend.traffic_stats_by_initiator().size() == masters);
  }
  try { control("unknown"); return 1; } catch (const std::invalid_argument&) {}
  std::cout << "CREDIT_CONTROL_PASS sixteen explicit arms; old source topology and A4 credits unchanged\n";
}
