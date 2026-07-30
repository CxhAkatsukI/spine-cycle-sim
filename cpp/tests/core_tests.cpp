#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <functional>
#include <iostream>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/algorithm.hpp"
#include "spine_sim/algorithm_pipeline.hpp"
#include "spine_sim/axi.hpp"
#include "spine_sim/banked_memory.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_l0.hpp"
#include "spine_sim/spine_pagerank.hpp"
#include "spine_sim/spine_split.hpp"
#include "spine_sim/spine_system.hpp"

namespace {

using spine::sim::AxiConfig;
using spine::sim::AxiBeatTrace;
using spine::sim::AxiBurstTrace;
using spine::sim::AxiMaster;
using spine::sim::AxiPeriodicStall;
using spine::sim::AxiReadBeatResponse;
using spine::sim::AxiRequest;
using spine::sim::AxiResponse;
using spine::sim::AxiStats;
using spine::sim::AxiWriteIngressStage;
using spine::sim::AxiWriteIngressTrace;
using spine::sim::AlgorithmIterationContext;
using spine::sim::AlgorithmPipeline;
using spine::sim::AlgorithmPipelineConfig;
using spine::sim::AlgorithmPipelinePorts;
using spine::sim::AlgorithmPipelineRequest;
using spine::sim::AlgorithmPipelineResponse;
using spine::sim::AlgorithmPipelineStage;
using spine::sim::AlgorithmPolicyConfig;
using spine::sim::AlgorithmUpdateMode;
using spine::sim::AlgorithmVertexState;
using spine::sim::BankedMemory;
using spine::sim::BankedMemoryConfig;
using spine::sim::BackendRequest;
using spine::sim::ClockId;
using spine::sim::combine_memory_traffic;
using spine::sim::Component;
using spine::sim::CycleContext;
using spine::sim::decode_spine_level_edge;
using spine::sim::decode_spine_maintenance_result;
using spine::sim::decode_spine_sort_edge;
using spine::sim::encode_spine_level_edge;
using spine::sim::encode_spine_maintenance_result;
using spine::sim::encode_spine_sort_edge;
using spine::sim::Fifo;
using spine::sim::FifoStats;
using spine::sim::FixedAxiPort;
using spine::sim::FixedAxiPortConfig;
using spine::sim::GraphAlgorithmKind;
using spine::sim::GraphAlgorithmPolicy;
using spine::sim::load_spine_edge_slice;
using spine::sim::preload_spine_resident_snapshot;
using spine::sim::MemoryOperation;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::RegisteredChannelArbiter;
using spine::sim::OnChipOperation;
using spine::sim::OnChipRequest;
using spine::sim::OnChipResponse;
using spine::sim::PartConvWord;
using spine::sim::PartConvWordKind;
using spine::sim::ReadAfterWritePolicy;
using spine::sim::Scheduler;
using spine::sim::SourceValueWord;
using spine::sim::spine_hot_shard;
using spine::sim::spine_dirty_identity;
using spine::sim::spine_level_layout;
using spine::sim::spine_metadata_layout;
using spine::sim::spine_candidate10_publication_window_min_cycles;
using spine::sim::spine_candidate10_l0_writer_min_cycles;
using spine::sim::build_spine_host_active_bins;
using spine::sim::SpineActiveBins;
using spine::sim::SpineActiveRecord;
using spine::sim::SpineAxiInterfaceProfile;
using spine::sim::SpineAxiPortKind;
using spine::sim::SpineComputeCounters;
using spine::sim::SpineComputePorts;
using spine::sim::SpineDirtyIdentity;
using spine::sim::SpineDirtyStatus;
using spine::sim::SpineEdgeRecord;
using spine::sim::SpineEdgeSlice;
using spine::sim::SpineL0Config;
using spine::sim::SpineL0Counters;
using spine::sim::SpineL0Maintenance;
using spine::sim::SpineL0Ports;
using spine::sim::SpineL0State;
using spine::sim::SpineResidentClassification;
using spine::sim::SpineMaintenanceResult;
using spine::sim::SpineMaintenanceArchitecture;
using spine::sim::SpineLevelLayout;
using spine::sim::SpineMetadataLayout;
using spine::sim::SpineOnChipMemoryProfile;
using spine::sim::SpinePageRankVerticalSliceSystem;
using spine::sim::SpineSplitPageRankCompute;
using spine::sim::SpineReaderCounters;
using spine::sim::SpineReaderPorts;
using spine::sim::SpineSplitReader;
using spine::sim::SpineSplitSsspCompute;
using spine::sim::SpineSsspRunResult;
using spine::sim::SpineVerticalSliceSystem;
using spine::sim::subtract_memory_traffic;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void test_spine_edge_slice_empty_update_contract() {
  const std::filesystem::path data =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data";
  const std::filesystem::path valid = data / "empty_update_v16.slice";
  bool rejected_by_default = false;
  try {
    (void)load_spine_edge_slice(valid);
  } catch (const std::runtime_error &) {
    rejected_by_default = true;
  }
  require(rejected_by_default,
          "generic Spine workload loader silently accepted an empty graph");
  const SpineEdgeSlice update = load_spine_edge_slice(valid, true);
  require(update.vertices == 16 && update.edges.empty() &&
              update.case_name == "empty_update_v16",
          "empty update slice lost required metadata");

  bool missing_vertices_rejected = false;
  try {
    (void)load_spine_edge_slice(data / "empty_update_missing_vertices.slice",
                                true);
  } catch (const std::runtime_error &) {
    missing_vertices_rejected = true;
  }
  require(missing_vertices_rejected,
          "empty update slice without vertex metadata was accepted");
}

std::uint64_t maintenance_result_counter(const SpineMaintenanceResult &result,
                                         std::size_t base,
                                         std::size_t counter) {
  const std::uint64_t low = std::bit_cast<std::uint32_t>(
      result.words.at(base + counter * 2));
  const std::uint64_t high = std::bit_cast<std::uint32_t>(
      result.words.at(base + counter * 2 + 1));
  return low | (high << 32);
}

struct MaintenanceOnlyRun {
  SpineL0Counters counters;
  SpineL0State state;
  SpineMaintenanceResult result;
  std::vector<std::uint8_t> graph0_word7;
  std::vector<std::uint8_t> slice_epoch_word0;
  std::vector<std::uint8_t> family_directory_word0;
  std::vector<std::uint8_t> dirty_bitmap_word0;
  std::vector<std::uint8_t> dirty_list_word0;
  std::vector<std::uint8_t> family_bucket_payload;
  bool failed{};
  std::string failure;
};

std::vector<std::uint8_t> u32_payload(std::uint32_t value);

MaintenanceOnlyRun run_maintenance_only(
    SpineL0Config config, SpineL0State state, SpineEdgeSlice workload,
    const std::function<void(FixedAxiPort &, SpineL0Ports &,
                             const SpineL0Config &)> &mutate = {}) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("maintenance-only-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "maintenance-only-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(800 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "maintenance-only-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32,
          .channel = 16,
          .initiator_id = 816,
          .data_width_bytes =
              config.maintenance_architecture ==
                      SpineMaintenanceArchitecture::kCandidate10OnePass
                  ? 16U
                  : 64U,
          .stream_read_beats =
              config.maintenance_architecture ==
              SpineMaintenanceArchitecture::kCandidate10OnePass,
      },
      backend);
  FixedAxiPort metadata(
      "maintenance-only-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 820},
      backend);
  FixedAxiPort result(
      "maintenance-only-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 821},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0Maintenance maintenance("maintenance-only", core, config,
                                 std::move(workload), ports, state);
  if (mutate) {
    mutate(metadata, ports, config);
  }
  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      200'000);
  return MaintenanceOnlyRun{
      .counters = maintenance.counters(),
      .state = std::move(state),
      .result = decode_spine_maintenance_result(backend.inspect_payload(
          21, config.result_base, spine::sim::kSpineMaintenanceResultBytes)),
      .graph0_word7 = backend.inspect_payload(
          0, 7 * spine::sim::kSpineGraphWordBytes,
          spine::sim::kSpineGraphWordBytes),
      .slice_epoch_word0 = backend.inspect_payload(
          20,
          config.metadata_base +
              spine_metadata_layout(config).slice_epoch_base *
                  spine::sim::kSpineMetadataWordBytes,
          spine::sim::kSpineMetadataWordBytes),
      .family_directory_word0 = backend.inspect_payload(
          16, config.persistent_family_directory_base,
          spine::sim::kSpineSortWordBytes),
      .dirty_bitmap_word0 = backend.inspect_payload(
          16, config.persistent_dirty_bitmap_base,
          spine::sim::kSpineSortWordBytes),
      .dirty_list_word0 = backend.inspect_payload(
          16, config.persistent_dirty_list_base,
          spine::sim::kSpineSortWordBytes),
      .family_bucket_payload =
          config.maintenance_architecture ==
                  SpineMaintenanceArchitecture::kCandidate10OnePass
              ? backend.inspect_payload(
                    16, config.persistent_family_bucket_base,
                    maintenance.counters().dispatch_bucket_writes *
                        spine::sim::kSpineSortWordBytes)
              : std::vector<std::uint8_t>{},
      .failed = maintenance.failed(),
      .failure = maintenance.failure(),
  };
}

void test_spine_candidate10_publication_rtl_window_formula() {
  const SpineL0Config config;
  require(spine_candidate10_publication_window_min_cycles(
              config, 1, 1, 1, false, true) == 256 &&
              spine_candidate10_publication_window_min_cycles(
                  config, 16, 4, 16, false, true) == 421 &&
              spine_candidate10_publication_window_min_cycles(
                  config, 64, 16, 64, false, true) == 1'209 &&
              spine_candidate10_publication_window_min_cycles(
                  config, 64, 16, 64, false, false) == 1'206 &&
              spine_candidate10_publication_window_min_cycles(
                  config, 16, 1, 0, true, true) == 245 &&
              spine_candidate10_publication_window_min_cycles(
                  config, 16, 16, 0, true, true) == 376,
          "Candidate-10 grouped-pass formula diverged from the RTL oracle");
}

void test_spine_candidate10_l0_writer_rtl_formula() {
  const SpineL0Config config;
  require(spine_candidate10_l0_writer_min_cycles(config, 0, 0, 0, 0) == 0 &&
              spine_candidate10_l0_writer_min_cycles(config, 1, 1, 1, 1) ==
                  799 &&
              spine_candidate10_l0_writer_min_cycles(config, 16, 1, 1, 16) ==
                  1'085 &&
              spine_candidate10_l0_writer_min_cycles(config, 16, 16, 1, 1) ==
                  1'156 &&
              spine_candidate10_l0_writer_min_cycles(config, 17, 17, 1, 1) ==
                  1'249 &&
              spine_candidate10_l0_writer_min_cycles(config, 16, 16, 16, 1) ==
                  1'300 &&
              spine_candidate10_l0_writer_min_cycles(config, 17, 17, 17, 1) ==
                  1'462 &&
              spine_candidate10_l0_writer_min_cycles(config, 8, 4, 1, 2) ==
                  962 &&
              spine_candidate10_l0_writer_min_cycles(config, 8, 4, 4, 2) ==
                  893,
          "Candidate-10 L0 writer formula diverged from the RTL oracle");
}

void test_spine_candidate10_one_pass_publication_payloads() {
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  config.hot_vertices = {3};
  SpineEdgeSlice workload{
      .vertices = (2U << 20) + 16,
      .edges = {
          SpineEdgeRecord{.src = 0, .dst = 1, .weight = 7, .diff = 1},
          SpineEdgeRecord{.src = 0,
                          .dst = (1U << 20) + 1,
                          .weight = 6,
                          .diff = 1},
          SpineEdgeRecord{.src = 1, .dst = 2, .weight = 5, .diff = 1},
          SpineEdgeRecord{.src = 4, .dst = 3, .weight = 4, .diff = 1},
          SpineEdgeRecord{.src = 130, .dst = 4, .weight = 3, .diff = 1},
          SpineEdgeRecord{.src = 130,
                          .dst = (2U << 20) + 5,
                          .weight = 2,
                          .diff = 1},
      },
      .case_name = "candidate10_one_pass_empty_frontier",
  };
  const std::vector<SpineEdgeRecord> input = workload.edges;
  const MaintenanceOnlyRun run =
      run_maintenance_only(config, SpineL0State{}, std::move(workload));
  require(!run.failed, "candidate-10 maintenance failed: " + run.failure);

  const SpineL0Counters &counters = run.counters;
  require(counters.candidate_classify_edge_visits == input.size() &&
              counters.candidate_reduce_edge_visits == input.size() &&
              counters.candidate_classify_blocks == 1 &&
              counters.candidate_family_tag_word_writes == 1 &&
              counters.candidate_source_record_word_writes == 4 &&
              counters.candidate_prefix_iterations == 32,
          "candidate-10 classify/reduce/prefix ledger mismatch");
  require(counters.dispatch_status == 0 &&
              counters.dispatch_input_reads == input.size() &&
              counters.dispatch_bucket_writes == input.size() &&
              counters.dispatch_cursor_mismatches == 0,
          "candidate-10 dispatch ledger mismatch");
  require(counters.family_directory_word_reads == 3 &&
              counters.family_directory_word_writes == 3 &&
              counters.family_directory_bits_set == 6 &&
              counters.dirty_bitmap_reads == 0 &&
              counters.dirty_bitmap_writes == 2 &&
              counters.publication_list_word_reads == 0 &&
              counters.publication_list_word_writes == 1 &&
              counters.publication_scratch_word_reads == 0 &&
              counters.publication_scratch_word_writes == 0 &&
              counters.candidate_publication_windows == 2 &&
              counters.candidate_publication_groups == 5 &&
              counters.candidate_publication_prefetch_chunks == 2 &&
              counters.candidate_publication_new_bits_enumerated == 6 &&
              counters.candidate_publication_rtl_min_cycles == 515 &&
              counters.candidate_publication_schedule_stall_cycles != 0 &&
              counters.candidate_list_schedule_cycles == 441 &&
              counters.publication_empty_frontier_fast_path &&
              counters.publication_complete && counters.dirty_count == 4,
          "candidate-10 grouped publication ledger mismatch");
  require(counters.sorted_scan_passes == 39 &&
              counters.sorted_edge_visits == 5 * input.size() &&
              counters.candidate_l0_precount_edge_visits == input.size() &&
              counters.persisted_edges == input.size() &&
              counters.l0_writer_rtl_schedule_invocations == 4 &&
              counters.l0_writer_rtl_min_cycles == 3'241 &&
              counters.l0_writer_rtl_padding_cycles != 0 &&
              counters.l0_writer_rtl_memory_overrun_cycles == 0,
          "candidate-10 scan/bucket writer closure mismatch");

  std::vector<std::uint8_t> expected_directory(16, 0);
  expected_directory[0] = 3;
  expected_directory[4] = 1;
  require(run.family_directory_word0 == expected_directory,
          "candidate-10 directory payload did not preserve packed masks");
  std::vector<std::uint8_t> expected_bitmap(16, 0);
  expected_bitmap[0] = 0x13;
  require(run.dirty_bitmap_word0 == expected_bitmap,
          "candidate-10 bitmap payload did not publish source bits");
  std::vector<std::uint8_t> expected_list;
  for (const std::uint32_t source : {0U, 1U, 4U, 130U}) {
    const std::vector<std::uint8_t> packed = u32_payload(source);
    expected_list.insert(expected_list.end(), packed.begin(), packed.end());
  }
  require(run.dirty_list_word0 == expected_list,
          "candidate-10 dirty-list payload is not source ordered");

  std::vector<SpineEdgeRecord> expected_bucket;
  for (std::size_t family = 0; family < spine::sim::kSpineFamilyCount;
       ++family) {
    for (const SpineEdgeRecord &edge : input) {
      const bool hot = edge.dst == 3;
      const std::size_t owner =
          hot ? config.partitions + spine_hot_shard(edge.dst)
              : std::min<std::size_t>(
                    edge.dst / config.vertex_partition_size,
                    config.partitions - 1);
      if (owner == family) {
        expected_bucket.push_back(edge);
      }
    }
  }
  std::vector<SpineEdgeRecord> actual_bucket;
  for (std::size_t offset = 0; offset < run.family_bucket_payload.size();
       offset += spine::sim::kSpineSortWordBytes) {
    actual_bucket.push_back(decode_spine_sort_edge(
        std::vector<std::uint8_t>(
            run.family_bucket_payload.begin() +
                static_cast<std::ptrdiff_t>(offset),
            run.family_bucket_payload.begin() +
                static_cast<std::ptrdiff_t>(offset +
                                            spine::sim::kSpineSortWordBytes))));
  }
  require(actual_bucket == expected_bucket,
          "candidate-10 family bucket bypassed returned HBM payload");

  const std::uint32_t publication_flags = std::bit_cast<std::uint32_t>(
      run.result.words[SpineMaintenanceResult::kDirtyGenerationAdvances]);
  const std::uint32_t list_flags = std::bit_cast<std::uint32_t>(
      run.result.words[SpineMaintenanceResult::kDirtyAux]);
  require(run.result[SpineMaintenanceResult::kLayoutVersion] == 6 &&
              run.result[SpineMaintenanceResult::kMetadataFormatVersion] == 5 &&
              run.result[SpineMaintenanceResult::kDispatchInputReads] == 6 &&
              run.result[SpineMaintenanceResult::kDispatchBucketWrites] == 6 &&
              run.result[SpineMaintenanceResult::kFamilyDirectoryWordReads] ==
                  3 &&
              run.result[SpineMaintenanceResult::kFamilyDirectoryBitsSet] == 6 &&
              publication_flags == ((1U << 19) | 1U) &&
              list_flags == ((1U << 18) | 1U),
          "candidate-10 result ABI does not match frozen layout v6");
  std::cout << "EVIDENCE spine_candidate10 scans="
            << counters.sorted_scan_passes
            << " dispatch=" << counters.dispatch_bucket_writes
            << " directory_words=" << counters.family_directory_word_reads
            << " bitmap_reads=" << counters.dirty_bitmap_reads
            << " bitmap_writes=" << counters.dirty_bitmap_writes
            << " list_writes=" << counters.publication_list_word_writes
            << " cycles=" << counters.end_cycle - counters.start_cycle << '\n';
}

void test_spine_candidate10_hot_metadata_carry_retires_new_batch_request() {
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  config.hot_vertices = {7};

  SpineL0State state;
  state.hot_enabled = true;
  state.hot_vertices.insert(7);
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1},
  };
  SpineEdgeSlice workload{
      .vertices = 16,
      .edges = {
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1},
      },
      .case_name = "candidate10_hot_metadata_carry",
  };

  const MaintenanceOnlyRun run =
      run_maintenance_only(config, std::move(state), std::move(workload));
  require(!run.failed, "candidate-10 hot-metadata carry failed: " + run.failure);
  require(run.counters.target_level == 1 &&
              run.counters.carry_new_batch_reads == 1 &&
              run.counters.carry_level_payload_reads == 1 &&
              run.counters.hot_bitmap_carry_reads == 0 &&
              run.counters.carry_merge_inputs == 2 &&
              run.state.cold_levels[0][0].empty() &&
              run.state.cold_levels[0][1].size() == 2,
          "candidate-10 carry did not retire its preclassified new-batch stream");
}

std::vector<std::uint8_t> u64_payload(std::uint64_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] = static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

std::vector<std::uint8_t> u32_payload(std::uint32_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] =
        static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

void test_spine_candidate10_repeated_frontier_uses_grouped_payload_reads() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("candidate-repeat-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports;
  SpineL0Ports ports;
  for (std::size_t family = 0; family < graph_ports.size(); ++family) {
    graph_ports[family] = std::make_unique<FixedAxiPort>(
        "candidate-repeat-graph" + std::to_string(family), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = family,
            .initiator_id = static_cast<std::uint32_t>(900 + family),
        },
        backend);
    ports.graph[family] = graph_ports[family].get();
  }
  FixedAxiPort sorted(
      "candidate-repeat-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32,
          .channel = 16,
          .initiator_id = 916,
          .data_width_bytes = 16,
          .stream_read_beats = true,
      },
      backend);
  FixedAxiPort metadata(
      "candidate-repeat-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 920},
      backend);
  FixedAxiPort result(
      "candidate-repeat-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 921},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0State state;
  SpineL0Maintenance maintenance(
      "candidate-repeat-maintenance", core, config,
      SpineEdgeSlice{
          .vertices = 512,
          .edges = {
              SpineEdgeRecord{.src = 0, .dst = 10, .weight = 1, .diff = 1},
              SpineEdgeRecord{.src = 1, .dst = 11, .weight = 1, .diff = 1},
              SpineEdgeRecord{.src = 4, .dst = 12, .weight = 1, .diff = 1},
          },
          .case_name = "candidate_repeat_seed",
      },
      ports, state);
  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  const auto drained = [&] {
    return maintenance.done() && sorted.idle() && metadata.idle() &&
           result.idle() &&
           std::all_of(graph_ports.begin(), graph_ports.end(),
                       [](const auto &port) { return port->idle(); });
  };
  scheduler.run_until(drained, 200'000);
  require(!maintenance.failed() && maintenance.counters().dirty_count == 3,
          "candidate seed publication failed");

  maintenance.reset_batch(SpineEdgeSlice{
      .vertices = 512,
      .edges = {
          SpineEdgeRecord{.src = 1, .dst = 13, .weight = 1, .diff = 1},
          SpineEdgeRecord{.src = 2, .dst = 14, .weight = 1, .diff = 1},
          SpineEdgeRecord{.src = 130, .dst = 15, .weight = 1, .diff = 1},
      },
      .case_name = "candidate_repeat_mixed",
  });
  scheduler.run_until(drained, 300'000);
  require(!maintenance.failed(),
          "candidate repeated publication failed: " + maintenance.failure());
  const SpineL0Counters &counters = maintenance.counters();
  require(!counters.publication_empty_frontier_fast_path &&
              counters.family_directory_word_reads == 2 &&
              counters.family_directory_word_writes == 2 &&
              counters.family_directory_bits_set == 2 &&
              counters.dirty_bitmap_reads == 2 &&
              counters.dirty_bitmap_writes == 2 &&
              counters.dirty_list_appends == 2 &&
              counters.dirty_duplicates_suppressed == 1 &&
              counters.publication_scratch_word_writes == 1 &&
              counters.publication_scratch_word_reads == 1 &&
              counters.publication_list_word_reads == 2 &&
              counters.publication_list_word_writes == 2 &&
              counters.dirty_count == 5 && counters.dirty_generation == 2 &&
              counters.sorted_scan_passes == 3 &&
              counters.carry_new_batch_reads == 3,
          "candidate nonempty grouped publication/carry ledger mismatch");

  std::vector<std::uint8_t> expected_first_word;
  for (const std::uint32_t source : {0U, 1U, 4U, 2U}) {
    const auto packed = u32_payload(source);
    expected_first_word.insert(expected_first_word.end(), packed.begin(),
                               packed.end());
  }
  require(backend.inspect_payload(16, config.persistent_dirty_list_base, 16) ==
                  expected_first_word &&
              backend.inspect_payload(16,
                                      config.persistent_dirty_list_base + 16,
                                      4) == u32_payload(130),
          "candidate repeated list did not preserve and append packed words");
  const SpineDirtyIdentity expected_identity = spine_dirty_identity(
      2, std::vector<std::uint32_t>{0, 1, 2, 4, 130});
  require(counters.dirty_hash_sum == expected_identity.hash_sum &&
              counters.dirty_hash_xor == expected_identity.hash_xor,
          "candidate repeated publication identity diverged from payload");

  const SpineMaintenanceResult second = decode_spine_maintenance_result(
      backend.inspect_payload(21, config.result_base,
                              spine::sim::kSpineMaintenanceResultBytes));
  const std::uint32_t publication_flags = std::bit_cast<std::uint32_t>(
      second.words[SpineMaintenanceResult::kDirtyGenerationAdvances]);
  const std::uint32_t list_flags = std::bit_cast<std::uint32_t>(
      second.words[SpineMaintenanceResult::kDirtyAux]);
  require(publication_flags == 3U &&
              list_flags == ((1U << 18) | (2U << 16) | 2U),
          "candidate nonempty publication flags mismatch");
  std::cout << "EVIDENCE spine_candidate10_repeat bitmap_reads="
            << counters.dirty_bitmap_reads
            << " bitmap_writes=" << counters.dirty_bitmap_writes
            << " scratch_words="
            << counters.publication_scratch_word_writes
            << " list_reads=" << counters.publication_list_word_reads
            << " list_writes=" << counters.publication_list_word_writes
            << " target=" << counters.target_level << '\n';
}

void test_spine_candidate10_block_and_publication_window_boundaries() {
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  SpineEdgeSlice workload{
      .vertices = 256,
      .edges = {},
      .case_name = "candidate10_130_unique_sources",
  };
  for (std::uint32_t source = 0; source < 130; ++source) {
    workload.edges.push_back(
        SpineEdgeRecord{.src = source,
                        .dst = 0,
                        .weight = static_cast<std::uint16_t>(source + 1),
                        .diff = 1});
  }
  const MaintenanceOnlyRun run =
      run_maintenance_only(config, SpineL0State{}, std::move(workload));
  const SpineL0Counters &counters = run.counters;
  require(!run.failed, "candidate boundary run failed: " + run.failure);
  require(counters.candidate_classify_blocks == 2 &&
              counters.candidate_classify_edge_visits == 130 &&
              counters.candidate_reduce_edge_visits == 130 &&
              counters.candidate_family_tag_word_writes == 17 &&
              counters.candidate_source_record_word_writes == 130 &&
              counters.publication_source_record_reads == 390,
          "candidate 128-edge/source-prefetch boundaries do not close");
  require(counters.family_directory_word_reads == 33 &&
              counters.family_directory_word_writes == 33 &&
              counters.family_directory_bits_set == 130 &&
              counters.dirty_bitmap_reads == 0 &&
              counters.dirty_bitmap_writes == 2 &&
              counters.publication_list_word_reads == 1 &&
              counters.publication_list_word_writes == 33 &&
              counters.dirty_count == 130 && counters.sorted_scan_passes == 20 &&
              counters.sorted_edge_visits == 650 &&
              counters.candidate_l0_precount_edge_visits == 130,
          "candidate packed-word grouping crossed a boundary incorrectly");
  for (std::size_t index = 0; index < 130; ++index) {
    require(decode_spine_sort_edge(std::vector<std::uint8_t>(
                run.family_bucket_payload.begin() +
                    static_cast<std::ptrdiff_t>(
                        index * spine::sim::kSpineSortWordBytes),
                run.family_bucket_payload.begin() +
                    static_cast<std::ptrdiff_t>(
                        (index + 1) * spine::sim::kSpineSortWordBytes)))
                    .src == index,
            "candidate bucket lost source order across classify blocks");
  }
  std::cout << "EVIDENCE spine_candidate10_boundary blocks="
            << counters.candidate_classify_blocks
            << " source_records="
            << counters.candidate_source_record_word_writes
            << " directory_words=" << counters.family_directory_word_reads
            << " bitmap_words=" << counters.dirty_bitmap_writes
            << " list_words=" << counters.publication_list_word_writes
            << " cycles=" << counters.end_cycle - counters.start_cycle << '\n';
}

void test_spine_candidate10_zero_edge_batch() {
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  SpineEdgeSlice workload{
      .vertices = 1,
      .edges = {},
      .case_name = "candidate10_zero_edge",
  };
  const MaintenanceOnlyRun run =
      run_maintenance_only(config, SpineL0State{}, std::move(workload));
  require(!run.failed, "candidate zero-edge run failed: " + run.failure);
  require(run.result.words[SpineMaintenanceResult::kInputEdges] == 0 &&
              run.result.words[SpineMaintenanceResult::kPersistedEdges] == 0,
          "candidate zero-edge result counts mismatch");
  require(run.result.words[SpineMaintenanceResult::kDispatchStatus] == 0 &&
              run.result.words[SpineMaintenanceResult::kDispatchInputReads] == 0 &&
              run.result.words[SpineMaintenanceResult::kDispatchBucketWrites] == 0,
          "candidate zero-edge dispatch must be empty and successful");
  require(run.counters.candidate_classify_blocks == 0 &&
              run.counters.publication_source_record_reads == 0 &&
              run.counters.family_directory_word_reads == 0 &&
              run.counters.publication_complete,
          "candidate zero-edge publication counters mismatch");
  require(run.counters.end_cycle - run.counters.start_cycle == 4'490 &&
              run.counters.candidate_zero_edge_control_min_cycles == 4'490 &&
              run.counters.candidate_zero_edge_control_padding_cycles > 0 &&
              run.counters.candidate_zero_edge_control_memory_overrun_cycles ==
                  0,
          "candidate zero-edge control path finished before its RTL oracle");
  std::cout << "EVIDENCE spine_candidate10_zero_edge cycles="
            << run.counters.end_cycle - run.counters.start_cycle
            << " dispatch=" << run.counters.dispatch_input_reads
            << " publication_complete=" << run.counters.publication_complete
            << '\n';
}

std::vector<SourceValueWord> source_protocol_reply(std::uint32_t source,
                                                   std::uint32_t value) {
  return {
      SourceValueWord{.source = source, .value = value},
      SourceValueWord{.kind = SourceValueWord::Kind::kProtocolAck,
                      .value = static_cast<std::uint32_t>(
                          spine::sim::SpineSourceProtocolStatus::kOk)},
  };
}

class EdgeCounter final : public Component {
 public:
  EdgeCounter(std::string name, ClockId clock)
      : Component(std::move(name), clock) {}
  void evaluate(const CycleContext &) override { ++evaluations; }
  void commit(const CycleContext &) override { ++commits; }
  std::uint64_t evaluations{};
  std::uint64_t commits{};
};

class PhaseCounter final : public Component {
 public:
  PhaseCounter(std::string name, ClockId clock, bool prepare_phase,
               bool evaluate_phase, bool commit_phase)
      : Component(std::move(name), clock),
        prepare_phase_(prepare_phase),
        evaluate_phase_(evaluate_phase),
        commit_phase_(commit_phase) {}

  [[nodiscard]] bool has_prepare_phase() const noexcept override {
    return prepare_phase_;
  }
  [[nodiscard]] bool has_evaluate_phase() const noexcept override {
    return evaluate_phase_;
  }
  [[nodiscard]] bool has_commit_phase() const noexcept override {
    return commit_phase_;
  }
  void prepare(const CycleContext&) override { ++prepares; }
  void evaluate(const CycleContext&) override { ++evaluations; }
  void commit(const CycleContext&) override { ++commits; }

  std::uint64_t prepares{};
  std::uint64_t evaluations{};
  std::uint64_t commits{};

 private:
  bool prepare_phase_{};
  bool evaluate_phase_{};
  bool commit_phase_{};
};

class ReadyPhaseCounter final : public Component {
 public:
  ReadyPhaseCounter(std::string name, ClockId clock)
      : Component(std::move(name), clock) {}

  [[nodiscard]] bool has_prepare_phase() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_prepare_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_is_ready;
  }
  [[nodiscard]] bool prepare_ready() const noexcept override {
    return prepare_is_ready;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return commit_is_ready;
  }
  void evaluate(const CycleContext&) override { ++evaluations; }
  void prepare(const CycleContext&) override { ++prepares; }
  void commit(const CycleContext&) override { ++commits; }

  bool prepare_is_ready{};
  bool evaluate_is_ready{};
  bool commit_is_ready{};
  std::uint64_t prepares{};
  std::uint64_t evaluations{};
  std::uint64_t commits{};
};

class LatchedCommitCounter final : public Component {
 public:
  LatchedCommitCounter(std::string name, ClockId clock, std::size_t identity,
                       std::vector<std::size_t> &order)
      : Component(std::move(name), clock),
        identity_(identity),
        order_(order) {}

  [[nodiscard]] bool has_evaluate_phase() const noexcept override {
    return false;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  void arm() { set_latched_commit_ready(true); }
  void evaluate(const CycleContext &) override {}
  void commit(const CycleContext &context) override {
    order_.push_back(identity_);
    commit_cycles.push_back(context.domain_cycle);
    set_latched_commit_ready(false);
  }

  std::vector<std::uint64_t> commit_cycles;

 private:
  std::size_t identity_{};
  std::vector<std::size_t> &order_;
};

class LatchedEvaluateCounter final : public Component {
 public:
  LatchedEvaluateCounter(std::string name, ClockId clock,
                         std::size_t identity,
                         std::vector<std::size_t> &order)
      : Component(std::move(name), clock),
        identity_(identity),
        order_(order) {}

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_commit_phase() const noexcept override {
    return false;
  }
  void arm() { set_latched_evaluate_ready(true); }
  void evaluate(const CycleContext &context) override {
    order_.push_back(identity_);
    evaluate_cycles.push_back(context.domain_cycle);
    set_latched_evaluate_ready(false);
  }
  void commit(const CycleContext &) override {}

  std::vector<std::uint64_t> evaluate_cycles;

 private:
  std::size_t identity_{};
  std::vector<std::size_t> &order_;
};

template <typename T>
class SequenceProducer final : public Component {
 public:
  SequenceProducer(std::string name, ClockId clock, Fifo<T> &output,
                   std::vector<T> values)
      : Component(std::move(name), clock),
        output_(output),
        values_(std::move(values)) {}

  void evaluate(const CycleContext &) override {
    accepted_ = index_ < values_.size() && output_.try_push(values_[index_]);
  }
  void commit(const CycleContext &) override {
    if (accepted_) {
      ++index_;
      accepted_ = false;
    }
  }
  [[nodiscard]] bool done() const noexcept { return index_ == values_.size(); }

 private:
  Fifo<T> &output_;
  std::vector<T> values_;
  std::size_t index_{};
  bool accepted_{};
};

template <typename T>
class SequenceConsumer final : public Component {
 public:
  SequenceConsumer(std::string name, ClockId clock, Fifo<T> &input,
                   std::uint64_t start_cycle = 0)
      : Component(std::move(name), clock),
        input_(input),
        start_cycle_(start_cycle) {}

  void evaluate(const CycleContext &context) override {
    accepted_ = false;
    if (context.domain_cycle >= start_cycle_) {
      accepted_ = input_.try_pop(staged_);
    }
  }
  void commit(const CycleContext &) override {
    if (accepted_) {
      values.push_back(staged_);
      accepted_ = false;
    }
  }
  std::vector<T> values;

 private:
  Fifo<T> &input_;
  std::uint64_t start_cycle_{};
  T staged_{};
  bool accepted_{};
};

template <typename T>
class PeriodicSequenceConsumer final : public Component {
 public:
  PeriodicSequenceConsumer(std::string name, ClockId clock, Fifo<T> &input,
                           AxiPeriodicStall stall)
      : Component(std::move(name), clock), input_(input), stall_(stall) {
    if (!stall_.valid()) {
      throw std::invalid_argument("invalid periodic consumer stall");
    }
  }

  void evaluate(const CycleContext &context) override {
    accepted_ = false;
    if (stall_.stalled(context.domain_cycle)) {
      if (input_.front() != nullptr) {
        ++stall_cycles;
      }
      return;
    }
    accepted_ = input_.try_pop(staged_);
    if (accepted_) {
      staged_cycle_ = context.domain_cycle;
    }
  }

  void commit(const CycleContext &) override {
    if (accepted_) {
      values.push_back(staged_);
      accepted_cycles.push_back(staged_cycle_);
      accepted_ = false;
    }
  }

  std::vector<T> values;
  std::vector<std::uint64_t> accepted_cycles;
  std::uint64_t stall_cycles{};

 private:
  Fifo<T> &input_;
  AxiPeriodicStall stall_;
  T staged_{};
  std::uint64_t staged_cycle_{};
  bool accepted_{};
};

void test_multiclock_scheduler() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  const auto hbm = scheduler.add_clock_mhz("hbm", 250.0);
  EdgeCounter core_counter("core-counter", core);
  EdgeCounter hbm_counter("hbm-counter", hbm);
  scheduler.add_component(core_counter);
  scheduler.add_component(hbm_counter);

  scheduler.run_events(6);

  require(core_counter.evaluations == 2, "100 MHz edge count mismatch");
  require(hbm_counter.evaluations == 5, "250 MHz edge count mismatch");
  require(core_counter.evaluations == core_counter.commits,
          "evaluate/commit count mismatch");
  require(scheduler.now_fs() == 16'000'000, "unexpected absolute timestamp");
}

void test_scheduler_component_removal_is_exact() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  EdgeCounter retained("retained", core);
  EdgeCounter removed("removed", core);
  scheduler.add_component(retained);
  scheduler.add_component(removed);
  scheduler.run_events(3);

  require(scheduler.component_count() == 2 && removed.evaluations == 3 &&
              removed.commits == 3,
          "scheduler removal setup did not execute both components");
  scheduler.remove_component(removed);
  scheduler.run_events(4);
  require(scheduler.component_count() == 1 && retained.evaluations == 7 &&
              retained.commits == 7 && removed.evaluations == 3 &&
              removed.commits == 3,
          "removed component received cycles or retained component stopped");

  bool duplicate_removal_rejected = false;
  try {
    scheduler.remove_component(removed);
  } catch (const std::invalid_argument &) {
    duplicate_removal_rejected = true;
  }
  require(duplicate_removal_rejected,
          "scheduler silently accepted duplicate component removal");
}

void test_scheduler_dispatches_only_declared_phases() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  const auto hbm = scheduler.add_clock_mhz("hbm", 250.0);
  PhaseCounter prepare_only("prepare-only", core, true, false, false);
  PhaseCounter evaluate_only("evaluate-only", core, false, true, false);
  PhaseCounter commit_only("commit-only", hbm, false, false, true);
  PhaseCounter all_phases("all-phases", core, true, true, true);
  PhaseCounter no_phases("no-phases", core, false, false, false);
  scheduler.add_component(prepare_only);
  scheduler.add_component(evaluate_only);
  scheduler.add_component(commit_only);
  scheduler.add_component(all_phases);
  scheduler.add_component(no_phases);

  scheduler.run_events(6);

  require(prepare_only.prepares == 2 && prepare_only.evaluations == 0 &&
              prepare_only.commits == 0,
          "scheduler called an undeclared prepare-only component phase");
  require(evaluate_only.prepares == 0 && evaluate_only.evaluations == 2 &&
              evaluate_only.commits == 0,
          "scheduler called an undeclared evaluate-only component phase");
  require(commit_only.prepares == 0 && commit_only.evaluations == 0 &&
              commit_only.commits == 5,
          "scheduler called an undeclared commit-only component phase");
  require(all_phases.prepares == 2 && all_phases.evaluations == 2 &&
              all_phases.commits == 2,
          "scheduler skipped a declared component phase");
  require(no_phases.prepares == 0 && no_phases.evaluations == 0 &&
              no_phases.commits == 0,
          "scheduler called a phase-free component");

  scheduler.remove_component(all_phases);
  scheduler.run_events(5);
  require(all_phases.prepares == 2 && all_phases.evaluations == 2 &&
              all_phases.commits == 2,
          "component removal left a stale phase registration");
  require(prepare_only.prepares == 4 && evaluate_only.evaluations == 4 &&
              commit_only.commits == 9,
          "phase dispatch changed surviving multi-clock components");
}

void test_scheduler_component_sampling_profile() {
  require(setenv("SPINE_SIM_PROFILE_COMPONENT_PERIOD", "2", 1) == 0,
          "failed to configure scheduler sampling profile");
  Scheduler scheduler;
  require(unsetenv("SPINE_SIM_PROFILE_COMPONENT_PERIOD") == 0,
          "failed to clear scheduler sampling profile");
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  PhaseCounter all_phases("profiled", core, true, true, true);
  scheduler.add_component(all_phases);
  scheduler.run_events(5);

  const auto rows = scheduler.component_profile();
  require(scheduler.profiling_period() == 2 && rows.size() == 1,
          "scheduler sampling profile configuration was not retained");
  require(rows[0].name == "profiled" && rows[0].prepare_samples == 3 &&
              rows[0].evaluate_samples == 3 && rows[0].commit_samples == 3,
          "scheduler sampled the wrong component cycles or phases");
}

void test_scheduler_dynamic_phase_readiness() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  ReadyPhaseCounter component("dynamic-ready", core);
  scheduler.add_component(component);

  scheduler.run_events(3);
  require(component.prepares == 0 && component.evaluations == 0 &&
              component.commits == 0,
          "scheduler invoked a dynamically sleeping phase");
  component.prepare_is_ready = true;
  scheduler.run_events(2);
  require(component.prepares == 2 && component.evaluations == 0 &&
              component.commits == 0,
          "scheduler did not wake only the ready prepare phase");
  component.prepare_is_ready = false;
  component.evaluate_is_ready = true;
  scheduler.run_events(2);
  require(component.evaluations == 2 && component.commits == 0,
          "scheduler did not wake only the ready evaluate phase");
  component.evaluate_is_ready = false;
  component.commit_is_ready = true;
  scheduler.run_events(4);
  require(component.evaluations == 2 && component.commits == 4,
          "scheduler did not wake only the ready commit phase");
}

void test_fifo_latched_commit_readiness() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("fifo-latched-ready", 100.0);
  Fifo<std::uint32_t> fifo("fifo-latched-ready", core, 2);
  scheduler.add_component(fifo);

  require(!fifo.latched_commit_ready(),
          "new FIFO unexpectedly requested a commit");
  require(fifo.try_push(17), "FIFO rejected its first staged push");
  require(fifo.latched_commit_ready(),
          "staged FIFO push did not request a commit");
  scheduler.run_events(1);
  require(fifo.size() == 1 && !fifo.latched_commit_ready(),
          "FIFO push commit did not clear its readiness latch");

  std::uint32_t value = 0;
  require(fifo.try_pop(value) && value == 17,
          "FIFO rejected or corrupted its staged pop");
  require(fifo.latched_commit_ready(),
          "staged FIFO pop did not request a commit");
  scheduler.run_events(1);
  require(fifo.empty() && !fifo.latched_commit_ready(),
          "FIFO pop commit did not clear its readiness latch");
}

struct FifoNotifierProbe {
  std::size_t nonempty{};
  std::size_t nonfull{};

  static void on_nonempty(void *owner) noexcept {
    ++static_cast<FifoNotifierProbe *>(owner)->nonempty;
  }

  static void on_nonfull(void *owner) noexcept {
    ++static_cast<FifoNotifierProbe *>(owner)->nonfull;
  }
};

void test_fifo_transition_notifiers_and_bulk_stalls() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("fifo-transition-notifier", 100.0);
  Fifo<std::uint32_t> fifo("fifo-transition-notifier", core, 1);
  FifoNotifierProbe probe;
  fifo.bind_nonempty_notifier(&probe, &FifoNotifierProbe::on_nonempty);
  fifo.bind_nonfull_notifier(&probe, &FifoNotifierProbe::on_nonfull);
  scheduler.add_component(fifo);

  require(fifo.try_push(23), "notifier FIFO rejected staged push");
  scheduler.run_events(1);
  require(fifo.full() && probe.nonempty == 1 && probe.nonfull == 0,
          "FIFO nonempty notifier did not follow the registered edge");

  std::uint32_t value = 0;
  require(fifo.try_pop(value) && value == 23,
          "notifier FIFO rejected or corrupted staged pop");
  scheduler.run_events(1);
  require(fifo.empty() && probe.nonempty == 1 && probe.nonfull == 1,
          "FIFO nonfull notifier did not follow the full-to-nonfull edge");

  fifo.account_push_stalls(7);
  fifo.account_pop_stalls(11);
  require(fifo.stats().push_stalls == 7 && fifo.stats().pop_stalls == 11,
          "FIFO bulk stall accounting changed the exact ledger");

  fifo.unbind_nonempty_notifier(&probe);
  fifo.unbind_nonfull_notifier(&probe);
  require(fifo.try_push(29), "notifier FIFO rejected post-unbind push");
  scheduler.run_events(1);
  require(probe.nonempty == 1 && probe.nonfull == 1,
          "FIFO invoked a transition notifier after unbind");
}

void test_scheduler_latched_evaluate_bitmap_ordering() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("latched-evaluate", 100.0);
  std::vector<std::size_t> order;
  std::vector<std::unique_ptr<LatchedEvaluateCounter>> counters;
  counters.reserve(130);
  for (std::size_t identity = 0; identity < 130; ++identity) {
    counters.push_back(std::make_unique<LatchedEvaluateCounter>(
        "latched-evaluate-" + std::to_string(identity), core, identity,
        order));
    scheduler.add_component(*counters.back());
  }

  counters[129]->arm();
  counters[1]->arm();
  counters[64]->arm();
  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129}),
          "latched evaluate bitmap changed registration order");

  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129}),
          "one-shot evaluate latch ran again without a wakeup");

  counters[129]->arm();
  scheduler.remove_component(*counters[0]);
  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129, 129}) &&
              counters[129]->evaluate_cycles ==
                  std::vector<std::uint64_t>({0, 2}),
          "component removal lost a rebased latched evaluate notification");
}

void test_scheduler_latched_commit_bitmap_ordering() {
  Scheduler scheduler;
  const auto fast = scheduler.add_clock_mhz("fast", 100.0);
  const auto slow = scheduler.add_clock_mhz("slow", 50.0, 5'000'000);
  std::vector<std::size_t> order;
  std::vector<std::unique_ptr<LatchedCommitCounter>> counters;
  counters.reserve(131);
  for (std::size_t identity = 0; identity < 130; ++identity) {
    counters.push_back(std::make_unique<LatchedCommitCounter>(
        "latched-" + std::to_string(identity), fast, identity, order));
    scheduler.add_component(*counters.back());
  }
  counters.push_back(std::make_unique<LatchedCommitCounter>(
      "latched-slow", slow, 130, order));
  scheduler.add_component(*counters.back());

  counters[129]->arm();
  counters[1]->arm();
  counters[64]->arm();
  counters[130]->arm();
  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129}),
          "latched commit bitmap changed registration order or clock phase");

  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129, 130}) &&
              counters[130]->commit_cycles == std::vector<std::uint64_t>({0}),
          "latched multi-clock component committed before its own edge");

  counters[129]->arm();
  scheduler.remove_component(*counters[0]);
  scheduler.run_events(1);
  require(order == std::vector<std::size_t>({1, 64, 129, 130, 129}),
          "component removal lost a rebased latched commit notification");
}

void test_fixed_axi_port_rejects_busy_unregister() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  MockMemoryBackend backend("backend", core,
                            MockMemoryConfig{
                                .channels = 1,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 8,
                                .response_queue_depth = 16,
                            });
  FixedAxiPort port(
      "port", core,
      FixedAxiPortConfig{
          .memory_channels = 1, .channel = 0, .initiator_id = 99},
      backend);
  port.register_components(scheduler);
  scheduler.add_component(backend);
  require(port.requests().try_push(AxiRequest{
              .transaction_id = 1,
              .operation = MemoryOperation::kRead,
              .address = 0,
              .bytes = 64,
              .stream_read_beats = false,
              .write_data = {},
          }),
          "busy unregister test could not stage its request");
  scheduler.step();

  bool busy_rejected = false;
  try {
    port.unregister_components(scheduler);
  } catch (const std::logic_error &) {
    busy_rejected = true;
  }
  require(busy_rejected && scheduler.component_count() == 5,
          "busy fixed AXI port was partially or fully unregistered");
}

void test_fifo_has_no_same_cycle_fallthrough() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 1);
  SequenceProducer<int> producer("producer", core, fifo, {7});
  SequenceConsumer<int> consumer("consumer", core, fifo);
  scheduler.add_component(consumer);
  scheduler.add_component(fifo);
  scheduler.add_component(producer);

  scheduler.step();
  require(consumer.values.empty(), "FIFO allowed same-cycle fall-through");
  require(fifo.size() == 1, "producer value was not committed");
  scheduler.step();
  require(consumer.values == std::vector<int>{7},
          "consumer missed committed value");
  require(fifo.stats().pushes == 1 && fifo.stats().pops == 1,
          "FIFO activity counters mismatch");
}

std::vector<int> run_fifo_order_case(bool producer_first) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 2);
  SequenceProducer<int> producer("producer", core, fifo, {3, 5, 8});
  SequenceConsumer<int> consumer("consumer", core, fifo);
  if (producer_first) {
    scheduler.add_component(producer);
    scheduler.add_component(fifo);
    scheduler.add_component(consumer);
  } else {
    scheduler.add_component(consumer);
    scheduler.add_component(fifo);
    scheduler.add_component(producer);
  }
  scheduler.run_until([&consumer] { return consumer.values.size() == 3; }, 12);
  return consumer.values;
}

void test_fifo_is_registration_order_independent() {
  const auto forward = run_fifo_order_case(true);
  const auto reverse = run_fifo_order_case(false);
  require(forward == std::vector<int>({3, 5, 8}), "forward order lost data");
  require(reverse == forward,
          "component registration order changed FIFO behavior");
}

void test_fifo_backpressure_is_counted() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 1);
  SequenceProducer<int> producer("producer", core, fifo, {1, 2});
  SequenceConsumer<int> consumer("consumer", core, fifo, 3);
  scheduler.add_component(producer);
  scheduler.add_component(consumer);
  scheduler.add_component(fifo);

  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 10);
  require(consumer.values == std::vector<int>({1, 2}), "FIFO reordered values");
  require(fifo.stats().push_stalls >= 2, "full FIFO stalls were not counted");
  require(fifo.stats().max_occupancy == 1, "FIFO max occupancy mismatch");
}

BankedMemoryConfig memory_config(
    ReadAfterWritePolicy policy = ReadAfterWritePolicy::kStall) {
  return BankedMemoryConfig{
      .banks = 1,
      .capacity_words = 1024,
      .read_ports_per_bank = 1,
      .write_ports_per_bank = 1,
      .latency_cycles = 2,
      .max_outstanding_per_port = 4,
      .raw_policy = policy,
  };
}

void register_port(Scheduler &scheduler, Component &producer,
                   Fifo<OnChipRequest> &requests,
                   Fifo<OnChipResponse> &responses, Component &consumer) {
  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
}

void test_banked_memory_conflict_and_round_robin() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  memory.initialize_word(2, 22);
  memory.initialize_word(4, 44);

  Fifo<OnChipRequest> req0("req0", core, 2);
  Fifo<OnChipResponse> rsp0("rsp0", core, 2);
  Fifo<OnChipRequest> req1("req1", core, 2);
  Fifo<OnChipResponse> rsp1("rsp1", core, 2);
  memory.attach_port(req0, rsp0);
  memory.attach_port(req1, rsp1);

  SequenceProducer<OnChipRequest> producer0(
      "producer0", core, req0,
      {{.transaction_id = 10,
        .operation = OnChipOperation::kRead,
        .word_address = 2}});
  SequenceProducer<OnChipRequest> producer1(
      "producer1", core, req1,
      {{.transaction_id = 11,
        .operation = OnChipOperation::kRead,
        .word_address = 4}});
  SequenceConsumer<OnChipResponse> consumer0("consumer0", core, rsp0);
  SequenceConsumer<OnChipResponse> consumer1("consumer1", core, rsp1);

  register_port(scheduler, producer0, req0, rsp0, consumer0);
  register_port(scheduler, producer1, req1, rsp1, consumer1);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] {
        return consumer0.values.size() == 1 && consumer1.values.size() == 1;
      },
      16);

  require(consumer0.values[0].read_data == 22, "port 0 read data mismatch");
  require(consumer1.values[0].read_data == 44, "port 1 read data mismatch");
  require(memory.stats().accepted_reads == 2, "read acceptance mismatch");
  require(memory.stats().read_bank_conflict_stalls >= 1,
          "same-bank conflict was not counted");
  require(memory.stats().max_outstanding >= 2,
          "outstanding request depth was not observed");
}

void test_banked_memory_stalls_read_after_write() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  memory.initialize_word(8, 1);

  Fifo<OnChipRequest> write_req("write-req", core, 2);
  Fifo<OnChipResponse> write_rsp("write-rsp", core, 2);
  Fifo<OnChipRequest> read_req("read-req", core, 2);
  Fifo<OnChipResponse> read_rsp("read-rsp", core, 2);
  memory.attach_port(write_req, write_rsp);
  memory.attach_port(read_req, read_rsp);

  SequenceProducer<OnChipRequest> writer("writer", core, write_req,
                                         {{.transaction_id = 20,
                                           .operation = OnChipOperation::kWrite,
                                           .word_address = 8,
                                           .write_data = 99}});
  SequenceProducer<OnChipRequest> reader("reader", core, read_req,
                                         {{.transaction_id = 21,
                                           .operation = OnChipOperation::kRead,
                                           .word_address = 8}});
  SequenceConsumer<OnChipResponse> write_sink("write-sink", core, write_rsp);
  SequenceConsumer<OnChipResponse> read_sink("read-sink", core, read_rsp);

  register_port(scheduler, writer, write_req, write_rsp, write_sink);
  register_port(scheduler, reader, read_req, read_rsp, read_sink);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] {
        return write_sink.values.size() == 1 && read_sink.values.size() == 1;
      },
      20);

  require(read_sink.values[0].read_data == 99,
          "RAW-protected read saw stale data");
  require(memory.inspect_word(8) == 99, "write did not update memory");
  require(memory.stats().raw_hazard_stalls >= 2, "RAW stalls were not counted");
}

void test_invalid_clock_and_capacity_are_rejected() {
  Scheduler scheduler;
  bool clock_failed = false;
  try {
    static_cast<void>(scheduler.add_clock_mhz("bad", 0.0));
  } catch (const std::invalid_argument &) {
    clock_failed = true;
  }
  require(clock_failed, "zero-frequency clock was accepted");

  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  bool address_failed = false;
  try {
    memory.initialize_word(1024, 1);
  } catch (const std::out_of_range &) {
    address_failed = true;
  }
  require(address_failed, "out-of-capacity address was accepted");
}

AxiConfig axi_config() {
  return AxiConfig{
      .initiator_id = 0,
      .data_width_bytes = 64,
      .max_burst_beats = 16,
      .channels = 2,
      .channel_interleave_bytes = 64,
      .max_pending_requests = 4,
      .max_outstanding_bursts = 2,
      .address_accepts_per_cycle = 1,
      .beat_issues_per_cycle = 2,
      .response_beats_per_cycle = 2,
      .fixed_channel = std::nullopt,
  };
}

MockMemoryConfig mock_memory_config(std::uint64_t latency = 3) {
  return MockMemoryConfig{
      .channels = 2,
      .latency_cycles = latency,
      .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 32,
      .response_queue_depth = 16,
  };
}

void test_memory_backend_tracks_per_initiator_locality_and_epochs() {
  MockMemoryBackend backend("locality-hbm", 0,
                            MockMemoryConfig{
                                .channels = 2,
                                .latency_cycles = 100,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 32,
                                .response_queue_depth = 16,
                            });
  backend.register_initiator(10);
  backend.register_initiator(11);
  std::uint64_t request_id = 0;
  std::uint64_t cycle = 0;
  const auto submit = [&](std::uint32_t initiator, std::size_t channel,
                          MemoryOperation operation, std::uint64_t address) {
    BackendRequest request{
        .initiator_id = initiator,
        .request_id = request_id++,
        .channel = channel,
        .operation = operation,
        .address = address,
        .bytes = 64,
        .write_data = operation == MemoryOperation::kWrite
                          ? std::vector<std::uint8_t>(64, 0x5a)
                          : std::vector<std::uint8_t>{},
    };
    require(backend.try_submit(request),
            "locality test request was unexpectedly rejected");
    backend.commit(CycleContext{.domain_cycle = cycle++, .clock_id = 0});
  };

  submit(10, 0, MemoryOperation::kRead, 0);
  submit(11, 1, MemoryOperation::kRead, 4096);
  submit(10, 0, MemoryOperation::kRead, 64);
  submit(11, 1, MemoryOperation::kRead, 4160);
  submit(10, 0, MemoryOperation::kRead, 64);
  submit(10, 0, MemoryOperation::kRead, 256);
  submit(10, 0, MemoryOperation::kWrite, 1024);
  submit(10, 0, MemoryOperation::kWrite, 1088);
  submit(10, 0, MemoryOperation::kRead, 320);

  const auto phase_one = backend.traffic_stats();
  const auto combined = combine_memory_traffic(phase_one);
  require(phase_one.reads.requests == 7 && phase_one.reads.bytes == 448 &&
              phase_one.reads.first_requests == 2 &&
              phase_one.reads.contiguous_requests == 3 &&
              phase_one.reads.repeated_requests == 1 &&
              phase_one.reads.discontinuous_requests == 1,
          "read locality classes did not preserve independent initiators");
  require(phase_one.writes.requests == 2 && phase_one.writes.bytes == 128 &&
              phase_one.writes.first_requests == 1 &&
              phase_one.writes.contiguous_requests == 1 &&
              phase_one.writes.repeated_requests == 0 &&
              phase_one.writes.discontinuous_requests == 0,
          "write locality was not independent from the read stream");
  require(combined.requests == 9 && combined.bytes == 576 &&
              combined.first_requests == 3 &&
              combined.contiguous_requests == 4 &&
              combined.repeated_requests == 1 &&
              combined.discontinuous_requests == 1,
          "combined memory locality does not close over read and write traffic");
  const auto &initiators = backend.traffic_stats_by_initiator();
  require(initiators.at(10).reads.requests == 5 &&
              initiators.at(10).reads.first_requests == 1 &&
              initiators.at(11).reads.requests == 2 &&
              initiators.at(11).reads.contiguous_requests == 1,
          "per-initiator traffic accounting was mixed");

  backend.begin_traffic_epoch();
  submit(10, 0, MemoryOperation::kRead, 384);
  submit(11, 1, MemoryOperation::kRead, 4224);
  const auto phase_two =
      subtract_memory_traffic(backend.traffic_stats(), phase_one);
  require(phase_two.reads.requests == 2 &&
              phase_two.reads.first_requests == 2 &&
              phase_two.reads.contiguous_requests == 0 &&
              phase_two.reads.repeated_requests == 0 &&
              phase_two.reads.discontinuous_requests == 0,
          "traffic epoch did not reset locality predecessors");
}

void test_registered_channel_arbiter_is_order_independent_and_fair() {
  const auto request = [](std::uint32_t initiator) {
    return BackendRequest{
        .initiator_id = initiator,
        .request_id = 0,
        .channel = 0,
        .operation = MemoryOperation::kRead,
        .address = static_cast<std::uint64_t>(initiator) * 64,
        .bytes = 64,
        .write_data = {},
    };
  };

  RegisteredChannelArbiter arbiter(1, 1);
  const BackendRequest first = request(10);
  const BackendRequest second = request(11);
  require(!arbiter.try_acquire(second) && !arbiter.try_acquire(first),
          "registered arbiter accepted an evaluate-phase intent");
  require(arbiter.intent_pending(10, 0) &&
              arbiter.intent_pending(11, 0),
          "registered arbiter did not expose pending evaluate intents");
  arbiter.account_duplicate_waits(10, 0, 7);
  const std::array<std::size_t, 1> empty{0};
  arbiter.arbitrate(empty, 32);
  require(arbiter.try_acquire(first),
          "registered arbiter depended on caller evaluation order");
  require(!arbiter.try_acquire(second),
          "registered arbiter exceeded the per-channel grant rate");
  const std::array<std::size_t, 1> one_outstanding{1};
  arbiter.arbitrate(one_outstanding, 32);
  require(arbiter.try_acquire(second),
          "registered arbiter did not rotate to the waiting initiator");

  const auto& stats = arbiter.stats();
  require(stats.unique_intents == 2 && stats.grants == 2 &&
              stats.consumed_grants == 2 && stats.contended_cycles == 1 &&
              stats.contention_losers == 1 &&
              stats.request_waits == 10 &&
              arbiter.pending_grants() == 0,
          "registered arbiter grant/consume/contention ledger did not close");

  RegisteredChannelArbiter blocked(1, 1);
  const BackendRequest blocked_request = request(12);
  require(!blocked.try_acquire(blocked_request),
          "capacity test unexpectedly bypassed evaluate/commit");
  const std::array<std::size_t, 1> full{1};
  blocked.arbitrate(full, 1);
  require(blocked.pending_intents() == 1 && blocked.pending_grants() == 0 &&
              blocked.stats().capacity_blocked_cycles == 1,
          "full outstanding window did not preserve and classify the intent");
  blocked.arbitrate(empty, 1);
  require(blocked.try_acquire(blocked_request) &&
              blocked.pending_intents() == 0 &&
              blocked.pending_grants() == 0,
          "capacity-blocked intent was not granted after the window reopened");
}

struct TwoMasterResult {
  std::uint64_t cycles{};
  std::uint64_t backend_stalls{};
};

TwoMasterResult run_two_axi_masters(std::size_t second_channel) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  MockMemoryBackend backend("shared-hbm", core, mock_memory_config());

  Fifo<AxiRequest> request0("request0", core, 2);
  Fifo<AxiResponse> response0("response0", core, 2);
  Fifo<AxiRequest> request1("request1", core, 2);
  Fifo<AxiResponse> response1("response1", core, 2);
  AxiConfig config0 = axi_config();
  config0.initiator_id = 10;
  config0.fixed_channel = 0;
  AxiConfig config1 = axi_config();
  config1.initiator_id = 11;
  config1.fixed_channel = second_channel;
  AxiMaster axi0("axi0", core, config0, request0, response0, backend);
  AxiMaster axi1("axi1", core, config1, request1, response1, backend);
  SequenceProducer<AxiRequest> producer0("producer0", core, request0,
                                         {{.transaction_id = 100,
                                           .operation = MemoryOperation::kRead,
                                           .address = 0,
                                           .bytes = 64,
                                           .write_data = {}}});
  SequenceProducer<AxiRequest> producer1("producer1", core, request1,
                                         {{.transaction_id = 200,
                                           .operation = MemoryOperation::kWrite,
                                           .address = 4096,
                                           .bytes = 64,
                                           .write_data = {}}});
  SequenceConsumer<AxiResponse> consumer0("consumer0", core, response0);
  SequenceConsumer<AxiResponse> consumer1("consumer1", core, response1);

  scheduler.add_component(producer0);
  scheduler.add_component(producer1);
  scheduler.add_component(request0);
  scheduler.add_component(request1);
  scheduler.add_component(axi0);
  scheduler.add_component(axi1);
  scheduler.add_component(backend);
  scheduler.add_component(response0);
  scheduler.add_component(response1);
  scheduler.add_component(consumer0);
  scheduler.add_component(consumer1);
  scheduler.run_until(
      [&] {
        return consumer0.values.size() == 1 && consumer1.values.size() == 1;
      },
      100);

  require(consumer0.values[0].transaction_id == 100,
          "initiator 0 received the wrong AXI response");
  require(consumer1.values[0].transaction_id == 200,
          "initiator 1 received the wrong AXI response");
  require(axi0.stats().read_bytes == 64 && axi0.stats().write_bytes == 0,
          "initiator 0 activity was mixed with initiator 1");
  require(axi1.stats().read_bytes == 0 && axi1.stats().write_bytes == 64,
          "initiator 1 activity was mixed with initiator 0");
  return TwoMasterResult{
      .cycles = scheduler.clock(core).completed_cycles,
      .backend_stalls = axi0.stats().backend_submit_stalls +
                        axi1.stats().backend_submit_stalls,
  };
}

void test_axi_multi_initiator_fixed_channel_isolation() {
  const TwoMasterResult separate = run_two_axi_masters(1);
  const TwoMasterResult contended = run_two_axi_masters(0);
  require(separate.backend_stalls == 0,
          "separate HBM channels unexpectedly contended");
  require(contended.backend_stalls > 0,
          "shared HBM channel contention was not visible");
  require(contended.cycles > separate.cycles,
          "shared HBM channel did not delay completion");
}

void test_axi_rejects_duplicate_initiator_id() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  MockMemoryBackend backend("shared-hbm", core, mock_memory_config());
  Fifo<AxiRequest> request0("request0", core, 2);
  Fifo<AxiResponse> response0("response0", core, 2);
  Fifo<AxiRequest> request1("request1", core, 2);
  Fifo<AxiResponse> response1("response1", core, 2);
  AxiConfig config = axi_config();
  config.initiator_id = 5;
  AxiMaster first("first", core, config, request0, response0, backend);
  bool failed = false;
  try {
    AxiMaster duplicate("duplicate", core, config, request1, response1,
                        backend);
  } catch (const std::invalid_argument &) {
    failed = true;
  }
  require(failed, "duplicate memory initiator ID was accepted");
}

void test_axi_splits_bursts_and_uses_backend_online() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 2);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config());
  AxiMaster axi("axi", core, axi_config(), requests, responses, backend);
  SequenceProducer<AxiRequest> producer("requester", core, requests,
                                        {{.transaction_id = 42,
                                          .operation = MemoryOperation::kRead,
                                          .address = 4032,
                                          .bytes = 1600,
                                          .write_data = {}}});
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses);

  scheduler.add_component(backend);
  scheduler.add_component(consumer);
  scheduler.add_component(responses);
  scheduler.add_component(axi);
  scheduler.add_component(requests);
  scheduler.add_component(producer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 1; }, 200);

  require(consumer.values[0].transaction_id == 42 && consumer.values[0].success,
          "AXI response mismatch");
  require(
      axi.stats().requests_accepted == 1 && axi.stats().requests_completed == 1,
      "AXI request counters mismatch");
  require(axi.stats().bursts_accepted == 3,
          "AXI max-burst/4 KiB splitting produced the wrong burst count");
  require(axi.stats().four_kib_splits == 1, "AXI missed a 4 KiB split");
  require(axi.stats().beats_issued == 25 && axi.stats().beats_completed == 25,
          "AXI beat counters mismatch");
  require(axi.stats().read_bytes == 1600, "AXI byte counter mismatch");
  require(axi.stats().max_outstanding_bursts == 2,
          "AXI outstanding burst limit was not exercised");
  require(backend.stats().accepted == 25,
          "mock backend did not see every beat");
}

struct AxiRegistrationOrderResult {
  std::uint64_t cycles{};
  std::vector<std::uint8_t> read_data;
  std::uint64_t requests_completed{};
  std::uint64_t bursts_accepted{};
  std::uint64_t beats_completed{};
  std::uint64_t backend_accepted{};
};

AxiRegistrationOrderResult run_axi_registration_order(bool backend_first) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 4);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config());
  AxiConfig config = axi_config();
  config.fixed_channel = 0;
  AxiMaster axi("axi", core, config, requests, responses, backend);

  std::vector<std::uint8_t> payload(1600);
  for (std::size_t index = 0; index < payload.size(); ++index) {
    payload[index] = static_cast<std::uint8_t>((index * 31 + 7) & 0xff);
  }
  backend.initialize_payload(0, 4032, payload);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {{.transaction_id = 42,
        .operation = MemoryOperation::kRead,
        .address = 4032,
        .bytes = payload.size(),
        .write_data = {}}});
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  if (backend_first) {
    scheduler.add_component(backend);
    scheduler.add_component(axi);
  } else {
    scheduler.add_component(axi);
    scheduler.add_component(backend);
  }
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 1; }, 300);

  require(consumer.values[0].transaction_id == 42 &&
              consumer.values[0].success,
          "registration-order AXI response mismatch");
  return AxiRegistrationOrderResult{
      .cycles = scheduler.clock(core).completed_cycles,
      .read_data = consumer.values[0].read_data,
      .requests_completed = axi.stats().requests_completed,
      .bursts_accepted = axi.stats().bursts_accepted,
      .beats_completed = axi.stats().beats_completed,
      .backend_accepted = backend.stats().accepted,
  };
}

void test_axi_response_view_is_registration_order_independent() {
  const AxiRegistrationOrderResult backend_first =
      run_axi_registration_order(true);
  const AxiRegistrationOrderResult axi_first =
      run_axi_registration_order(false);
  require(backend_first.cycles == axi_first.cycles &&
              backend_first.read_data == axi_first.read_data &&
              backend_first.requests_completed == axi_first.requests_completed &&
              backend_first.bursts_accepted == axi_first.bursts_accepted &&
              backend_first.beats_completed == axi_first.beats_completed &&
              backend_first.backend_accepted == axi_first.backend_accepted,
          "AXI response view depends on backend/component commit order");
}

void test_candidate10_axi_adapter_schedule_matches_rtl_oracle() {
  const auto run_requests = [](MemoryOperation operation,
                               std::uint64_t address,
                               std::uint64_t bytes,
                               std::size_t requests = 1,
                               std::uint64_t stride = 0,
                               std::size_t address_accepts_per_cycle = 1) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("core", 150.0);
    MockMemoryBackend backend("candidate10-adapter-hbm", core,
                              mock_memory_config(1));
    SpineAxiInterfaceProfile profile =
        SpineAxiInterfaceProfile::candidate10_1e61fc0();
    FixedAxiPortConfig config = profile.port_config(
        SpineAxiPortKind::kGraph, 2, 0, 77);
    config.burst_trace_limit = 16;
    config.address_accepts_per_cycle = address_accepts_per_cycle;
    FixedAxiPort port("candidate10-adapter", core, config, backend);
    std::vector<std::uint8_t> write_data;
    if (operation == MemoryOperation::kWrite) {
      write_data.assign(bytes, 0x5a);
    }
    std::vector<AxiRequest> request_list;
    request_list.reserve(requests);
    for (std::size_t index = 0; index < requests; ++index) {
      request_list.push_back(AxiRequest{
          .transaction_id = 9 + index,
          .operation = operation,
          .address = address + index * stride,
          .bytes = bytes,
          .write_data = write_data,
      });
    }
    SequenceProducer<AxiRequest> producer("candidate10-adapter-producer", core,
                                          port.requests(),
                                          std::move(request_list));
    SequenceConsumer<AxiResponse> consumer(
        "candidate10-adapter-consumer", core, port.responses());
    scheduler.add_component(producer);
    port.register_components(scheduler);
    scheduler.add_component(backend);
    scheduler.add_component(consumer);
    scheduler.run_until(
        [&] { return consumer.values.size() == requests; }, 2'000);
    return std::pair{port.master().burst_trace(), port.master().stats()};
  };

  const auto [read_trace, read_stats] =
      run_requests(MemoryOperation::kRead, 4'088, 17 * 8);
  std::cout << "EVIDENCE candidate10_axi_read bursts=" << read_trace.size();
  for (const auto &burst : read_trace) {
    std::cout << " [addr=" << burst.address << ",beats=" << burst.beats
              << ",accepted=" << burst.parent_accept_cycle
              << ",cycle=" << burst.address_issue_cycle << ']';
  }
  std::cout << " pipeline_stalls=" << read_stats.address_pipeline_stalls
            << '\n';
  require(read_trace.size() == 2 && read_trace[0].address == 4'088 &&
              read_trace[0].beats == 1 &&
              read_trace[1].address == 4'096 &&
              read_trace[1].beats == 16 &&
              read_trace[0].address_issue_cycle ==
                  read_trace[0].parent_accept_cycle + 7 &&
              read_trace[1].address_issue_cycle ==
                  read_trace[0].address_issue_cycle + 1 &&
              read_stats.address_pipeline_stalls >= 6,
          "Candidate10 read adapter schedule diverged from the RTL oracle");

  const auto [boundary_write_trace, boundary_write_stats] =
      run_requests(MemoryOperation::kWrite, 4'088, 17 * 8);
  std::cout << "EVIDENCE candidate10_axi_boundary_write bursts="
            << boundary_write_trace.size();
  for (const auto &burst : boundary_write_trace) {
    std::cout << " [addr=" << burst.address << ",beats=" << burst.beats
              << ",accepted=" << burst.parent_accept_cycle
              << ",cycle=" << burst.address_issue_cycle << ']';
  }
  std::cout << " pipeline_stalls="
            << boundary_write_stats.address_pipeline_stalls << '\n';
  require(boundary_write_trace.size() == 2 &&
              boundary_write_trace[0].address == 4'088 &&
              boundary_write_trace[0].beats == 1 &&
              boundary_write_trace[1].address == 4'096 &&
              boundary_write_trace[1].beats == 16 &&
              boundary_write_trace[0].address_issue_cycle ==
                  boundary_write_trace[0].parent_accept_cycle + 11 &&
              boundary_write_trace[1].address_issue_cycle ==
                  boundary_write_trace[0].address_issue_cycle + 16 &&
              boundary_write_stats.address_pipeline_stalls != 0,
          "Candidate10 boundary write buffering diverged from RTL");

  const auto [aligned_write_trace, aligned_write_stats] =
      run_requests(MemoryOperation::kWrite, 0, 17 * 8);
  std::cout << "EVIDENCE candidate10_axi_aligned_write bursts="
            << aligned_write_trace.size();
  for (const auto &burst : aligned_write_trace) {
    std::cout << " [addr=" << burst.address << ",beats=" << burst.beats
              << ",accepted=" << burst.parent_accept_cycle
              << ",cycle=" << burst.address_issue_cycle << ']';
  }
  std::cout << " serial_stalls="
            << aligned_write_stats.write_burst_serialization_stalls << '\n';
  require(aligned_write_trace.size() == 2 &&
              aligned_write_trace[0].beats == 16 &&
              aligned_write_trace[1].beats == 1 &&
              aligned_write_trace[0].address_issue_cycle ==
                  aligned_write_trace[0].parent_accept_cycle + 26 &&
              aligned_write_trace[1].address_issue_cycle ==
                  aligned_write_trace[0].address_issue_cycle + 17 &&
              aligned_write_stats.write_burst_serialization_stalls != 0,
          "Candidate10 ordered write bursts diverged from RTL");

  const auto [adjacent_read_trace, adjacent_read_stats] =
      run_requests(MemoryOperation::kRead, 0, 8 * 8, 2, 8 * 8);
  (void)adjacent_read_stats;
  require(adjacent_read_trace.size() == 2 &&
              adjacent_read_trace[0].beats == 8 &&
              adjacent_read_trace[1].beats == 8 &&
              adjacent_read_trace[0].address_issue_cycle ==
                  adjacent_read_trace[0].parent_accept_cycle + 7 &&
              adjacent_read_trace[1].address_issue_cycle ==
                  adjacent_read_trace[0].address_issue_cycle + 1,
          "Candidate10 adjacent reads diverged from the RTL oracle");

  const auto [adjacent_write_trace, adjacent_write_stats] =
      run_requests(MemoryOperation::kWrite, 0, 8 * 8, 2, 8 * 8);
  require(adjacent_write_trace.size() == 2 &&
              adjacent_write_trace[0].beats == 8 &&
              adjacent_write_trace[1].beats == 8 &&
              adjacent_write_trace[0].address_issue_cycle ==
                  adjacent_write_trace[0].parent_accept_cycle + 18 &&
              adjacent_write_trace[1].address_issue_cycle ==
                  adjacent_write_trace[0].address_issue_cycle + 9 &&
              adjacent_write_stats.write_burst_serialization_stalls > 0,
          "Candidate10 adjacent writes diverged from the RTL oracle");

  const auto [single_write_trace, single_write_stats] =
      run_requests(MemoryOperation::kWrite, 0, 8, 4, 8, 2);
  (void)single_write_stats;
  require(single_write_trace.size() == 4 &&
              single_write_trace[0].address_issue_cycle ==
                  single_write_trace[0].parent_accept_cycle + 11 &&
              single_write_trace[1].address_issue_cycle ==
                  single_write_trace[0].address_issue_cycle + 2 &&
              single_write_trace[2].address_issue_cycle ==
                  single_write_trace[1].address_issue_cycle + 2 &&
              single_write_trace[3].address_issue_cycle ==
                  single_write_trace[2].address_issue_cycle + 2,
          "Candidate10 single-beat write stream diverged from RTL");

  const std::array<std::size_t, 7> aligned_beats{1, 15, 16, 17, 31, 32, 33};
  const std::array<std::vector<std::uint64_t>, 7> expected_aw_cycles{
      std::vector<std::uint64_t>{11},
      std::vector<std::uint64_t>{25},
      std::vector<std::uint64_t>{26},
      std::vector<std::uint64_t>{26, 43},
      std::vector<std::uint64_t>{26, 44},
      std::vector<std::uint64_t>{26, 45},
      std::vector<std::uint64_t>{26, 45, 62},
  };
  for (std::size_t index = 0; index < aligned_beats.size(); ++index) {
    const auto [trace, stats] = run_requests(
        MemoryOperation::kWrite, 0, aligned_beats[index] * 8);
    require(trace.size() == expected_aw_cycles[index].size() &&
                stats.write_child_beats_accepted == aligned_beats[index] &&
                stats.write_store_to_bridge_beats == aligned_beats[index] &&
                stats.write_bridge_to_throttle_beats == aligned_beats[index],
            "Candidate10 aligned write ingress ledger changed at a boundary");
    for (std::size_t burst = 0; burst < trace.size(); ++burst) {
      require(trace[burst].address_issue_cycle -
                      trace.front().parent_accept_cycle ==
                  expected_aw_cycles[index][burst],
              "Candidate10 aligned write AW schedule diverged from RTL");
    }
  }
}

struct PeriodicAxiRun {
  std::uint64_t cycles{};
  AxiStats stats;
  std::vector<AxiBurstTrace> bursts;
  std::vector<AxiBeatTrace> beats;
  std::vector<AxiWriteIngressTrace> write_ingress;
  std::vector<std::uint64_t> child_accept_cycles;
  std::uint64_t child_stall_cycles{};
};

PeriodicAxiRun run_candidate10_periodic_axi(MemoryOperation operation) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 150.0);
  MockMemoryBackend backend("candidate10-periodic-hbm", core,
                            mock_memory_config(8));
  FixedAxiPortConfig config =
      SpineAxiInterfaceProfile::candidate10_1e61fc0().port_config(
          SpineAxiPortKind::kGraph, 1, 0, 91);
  config.stream_read_beats = operation == MemoryOperation::kRead;
  config.read_beat_fifo_depth = 256;
  config.response_fifo_depth = 32;
  config.burst_trace_limit = 16;
  config.beat_trace_limit = 128;
  if (operation == MemoryOperation::kRead) {
    config.read_address_stall =
        AxiPeriodicStall{
            .period_cycles = 4, .stall_cycles = 2, .phase_cycles = 3};
    config.read_response_stall =
        AxiPeriodicStall{
            .period_cycles = 5, .stall_cycles = 2, .phase_cycles = 4};
  } else {
    config.write_address_stall =
        AxiPeriodicStall{
            .period_cycles = 4, .stall_cycles = 2, .phase_cycles = 3};
    config.write_data_stall =
        AxiPeriodicStall{
            .period_cycles = 5, .stall_cycles = 2, .phase_cycles = 4};
  }
  FixedAxiPort port("candidate10-periodic-adapter", core, config, backend);
  std::vector<AxiRequest> requests;
  for (std::size_t index = 0; index < 2; ++index) {
    requests.push_back(AxiRequest{
        .transaction_id = 100 + index,
        .operation = operation,
        .address = 4'080 + index * 512,
        .bytes = 33 * 8,
        .stream_read_beats = operation == MemoryOperation::kRead,
        .write_data = operation == MemoryOperation::kWrite
                          ? std::vector<std::uint8_t>(33 * 8, 0x5a)
                          : std::vector<std::uint8_t>{},
    });
  }
  SequenceProducer<AxiRequest> producer(
      "candidate10-periodic-producer", core, port.requests(),
      std::move(requests));
  PeriodicSequenceConsumer<AxiReadBeatResponse> read_consumer(
      "candidate10-periodic-read-consumer", core, port.read_beats(),
      AxiPeriodicStall{
          .period_cycles = 7, .stall_cycles = 3, .phase_cycles = 6});
  PeriodicSequenceConsumer<AxiResponse> response_consumer(
      "candidate10-periodic-response-consumer", core, port.responses(),
      operation == MemoryOperation::kWrite
          ? AxiPeriodicStall{
                .period_cycles = 7, .stall_cycles = 3, .phase_cycles = 6}
          : AxiPeriodicStall{});

  scheduler.add_component(producer);
  port.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.add_component(read_consumer);
  scheduler.add_component(response_consumer);
  scheduler.run_until(
      [&] {
        const bool responses_done = response_consumer.values.size() == 2;
        const bool beats_done = operation == MemoryOperation::kWrite ||
                                read_consumer.values.size() == 66;
        return responses_done && beats_done && port.idle();
      },
      2'000);

  return PeriodicAxiRun{
      .cycles = scheduler.clock(core).completed_cycles,
      .stats = port.master().stats(),
      .bursts = port.master().burst_trace(),
      .beats = port.master().beat_trace(),
      .write_ingress = port.master().write_ingress_trace(),
      .child_accept_cycles = operation == MemoryOperation::kRead
                                 ? read_consumer.accepted_cycles
                                 : response_consumer.accepted_cycles,
      .child_stall_cycles = operation == MemoryOperation::kRead
                                ? read_consumer.stall_cycles
                                : response_consumer.stall_cycles,
  };
}

void test_candidate10_axi_periodic_backpressure_trace() {
  const PeriodicAxiRun read =
      run_candidate10_periodic_axi(MemoryOperation::kRead);
  const PeriodicAxiRun write =
      run_candidate10_periodic_axi(MemoryOperation::kWrite);
  const std::array<std::uint64_t, 6> expected_addresses{
      4'080, 4'096, 4'224, 4'592, 4'720, 4'848};
  const std::array<std::size_t, 6> expected_beats{2, 16, 15, 16, 16, 1};
  const auto trace_matches = [&](const PeriodicAxiRun &run) {
    if (run.bursts.size() != expected_addresses.size()) {
      return false;
    }
    for (std::size_t index = 0; index < run.bursts.size(); ++index) {
      if (run.bursts[index].address != expected_addresses[index] ||
          run.bursts[index].beats != expected_beats[index]) {
        return false;
      }
    }
    return run.beats.size() == 66 &&
           std::all_of(run.beats.begin(), run.beats.end(),
                       [](const AxiBeatTrace &beat) {
                         return beat.completion_cycle >= beat.issue_cycle &&
                                beat.completion_cycle != 0;
                       });
  };

  require(trace_matches(read) && trace_matches(write),
          "periodic AXI backpressure changed the burst/beat ledger");
  require(read.stats.read_address_channel_stalls > 0 &&
              read.stats.read_response_channel_stalls > 0 &&
              read.stats.write_address_channel_stalls == 0 &&
              read.stats.write_data_channel_stalls == 0 &&
              read.child_stall_cycles > 0,
          "periodic read AR/R/child backpressure was not observable");
  require(write.stats.write_address_channel_stalls > 0 &&
              write.stats.write_data_channel_stalls > 0 &&
              write.stats.read_address_channel_stalls == 0 &&
              write.stats.read_response_channel_stalls == 0 &&
              write.child_stall_cycles > 0,
          "periodic write AW/W/B-child backpressure was not observable");
  require(write.stats.write_child_beats_accepted == 66 &&
              write.stats.write_child_data_stalls == 20 &&
              write.stats.write_store_to_bridge_beats == 66 &&
              write.stats.write_bridge_to_throttle_beats == 66 &&
              write.stats.max_write_store_occupancy == 16 &&
              write.stats.max_write_throttle_occupancy == 16 &&
              write.write_ingress.size() == 198 &&
              std::count_if(
                  write.write_ingress.begin(), write.write_ingress.end(),
                  [](const AxiWriteIngressTrace &event) {
                    return event.stage ==
                               AxiWriteIngressStage::kBridgeToThrottle &&
                           event.last;
                  }) == 6 &&
              write.stats.write_ingress_trace_dropped == 0,
          "Candidate10 structural write-ingress ledger diverged from RTL");
  require(read.stats.beat_trace_dropped == 0 &&
              write.stats.beat_trace_dropped == 0 &&
              read.stats.beats_issued == read.stats.beats_completed &&
              write.stats.beats_issued == write.stats.beats_completed,
          "periodic AXI trace or completion ledger did not close");
  require(read.cycles - read.bursts.front().parent_accept_cycle == 137 &&
              write.cycles - write.bursts.front().parent_accept_cycle == 158 &&
              read.stats.max_outstanding_bursts == 5 &&
              write.stats.max_outstanding_bursts == 2 &&
              read.stats.read_data_pipeline_stalls > 0,
          "Candidate10 periodic AXI elapsed/outstanding schedule drifted");

  const auto print_trace = [](MemoryOperation operation,
                              const PeriodicAxiRun &run) {
    const int op = operation == MemoryOperation::kRead ? 0 : 1;
    std::uint64_t last_parent_cycle = std::numeric_limits<std::uint64_t>::max();
    std::size_t request_index = 0;
    for (std::size_t index = 0; index < run.bursts.size(); ++index) {
      const AxiBurstTrace &burst = run.bursts[index];
      if (burst.parent_accept_cycle != last_parent_cycle) {
        std::cout << "AXI_CORE_EVENT kind=child_request op=" << op
                  << " index=" << request_index++
                  << " cycle=" << burst.parent_accept_cycle << '\n';
        last_parent_cycle = burst.parent_accept_cycle;
      }
      std::cout << "AXI_CORE_BURST op=" << op << " index=" << index
                << " addr=" << burst.address << " beats=" << burst.beats
                << " issue_cycle=" << burst.address_issue_cycle << '\n';
    }
    for (std::size_t index = 0; index < run.beats.size(); ++index) {
      const AxiBeatTrace &beat = run.beats[index];
      std::cout << "AXI_CORE_BEAT op=" << op << " index=" << index
                << " addr=" << beat.address
                << " issue_cycle=" << beat.issue_cycle
                << " completion_cycle=" << beat.completion_cycle << '\n';
    }
    if (operation == MemoryOperation::kWrite) {
      std::array<std::size_t, 3> stage_indices{};
      for (const AxiWriteIngressTrace &event : run.write_ingress) {
        const char *kind = nullptr;
        std::size_t stage_index = 0;
        switch (event.stage) {
        case AxiWriteIngressStage::kChildAccept:
          kind = "child_data";
          stage_index = 0;
          break;
        case AxiWriteIngressStage::kStoreToBridge:
          kind = "internal_store_to_bridge";
          stage_index = 1;
          break;
        case AxiWriteIngressStage::kBridgeToThrottle:
          kind = "internal_bridge_to_throttle";
          stage_index = 2;
          break;
        }
        std::cout << "AXI_CORE_EVENT kind=" << kind << " op=1 index="
                  << stage_indices[stage_index]++
                  << " cycle=" << event.cycle
                  << " last=" << (event.last ? 1 : 0) << '\n';
      }
    }
    for (std::size_t index = 0; index < run.child_accept_cycles.size();
         ++index) {
      std::cout << "AXI_CORE_EVENT kind="
                << (operation == MemoryOperation::kRead ? "child_data"
                                                        : "child_response")
                << " op=" << op << " index=" << index
                << " cycle=" << run.child_accept_cycles[index] << '\n';
    }
    std::cout << "AXI_CORE_SUMMARY op=" << op << " cycles=" << run.cycles
              << " address_stalls="
              << (operation == MemoryOperation::kRead
                      ? run.stats.read_address_channel_stalls
                      : run.stats.write_address_channel_stalls)
              << " data_stalls=" << run.stats.write_data_channel_stalls
              << " response_stalls="
              << (operation == MemoryOperation::kRead
                      ? run.stats.read_response_channel_stalls
                      : run.stats.write_response_channel_stalls)
              << " max_outstanding=" << run.stats.max_outstanding_bursts
              << " child_stalls=" << run.child_stall_cycles
              << " child_data_stalls="
              << run.stats.write_child_data_stalls << '\n';
  };
  print_trace(MemoryOperation::kRead, read);
  print_trace(MemoryOperation::kWrite, write);

  std::cout << "EVIDENCE candidate10_axi_periodic read_cycles=" << read.cycles
            << " read_ar_stalls="
            << read.stats.read_address_channel_stalls
            << " read_r_stalls="
            << read.stats.read_response_channel_stalls
            << " read_child_stalls=" << read.child_stall_cycles
            << " write_cycles=" << write.cycles
            << " write_aw_stalls="
            << write.stats.write_address_channel_stalls
            << " write_w_stalls=" << write.stats.write_data_channel_stalls
            << " write_child_stalls=" << write.child_stall_cycles << '\n';
}

void test_axi_periodic_stall_validation_and_phase() {
  const AxiPeriodicStall shifted{
      .period_cycles = 4, .stall_cycles = 2, .phase_cycles = 3};
  require(shifted.valid() && shifted.stalled(1) && shifted.stalled(2) &&
              !shifted.stalled(3) && !shifted.stalled(4),
          "periodic AXI stall phase did not shift its closed interval");

  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<AxiRequest> requests("invalid-stall-requests", core, 2);
  Fifo<AxiResponse> responses("invalid-stall-responses", core, 2);
  MockMemoryBackend backend("invalid-stall-backend", core,
                            mock_memory_config());
  AxiConfig config = axi_config();
  config.read_address_stall =
      AxiPeriodicStall{.period_cycles = 4, .stall_cycles = 4};
  bool rejected = false;
  try {
    AxiMaster invalid("invalid-stall-axi", core, config, requests, responses,
                      backend);
    (void)invalid;
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "AXI accepted a schedule that stalls every cycle");
}

void test_axi_response_backpressure_is_lossless() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 1);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config(1));
  AxiMaster axi("axi", core, axi_config(), requests, responses, backend);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 1,
           .operation = MemoryOperation::kWrite,
           .address = 0,
           .bytes = 64,
           .write_data = {}},
          {.transaction_id = 2,
           .operation = MemoryOperation::kWrite,
           .address = 64,
           .bytes = 64,
           .write_data = {}},
      });
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses, 20);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 80);

  require(consumer.values[0].transaction_id == 1 &&
              consumer.values[1].transaction_id == 2,
          "AXI response backpressure reordered or lost requests");
  require(axi.stats().response_queue_stalls > 0,
          "AXI response FIFO backpressure was not counted");
  require(axi.stats().write_bytes == 128, "AXI write byte count mismatch");
}

void test_axi_payload_round_trip_across_beats_and_bursts() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 4);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config());
  AxiConfig config = axi_config();
  config.fixed_channel = 0;
  AxiMaster axi("axi", core, config, requests, responses, backend);

  std::vector<std::uint8_t> read_pattern(1600);
  for (std::size_t index = 0; index < read_pattern.size(); ++index) {
    read_pattern[index] = static_cast<std::uint8_t>((index * 17 + 3) & 0xff);
  }
  std::vector<std::uint8_t> write_pattern(130);
  for (std::size_t index = 0; index < write_pattern.size(); ++index) {
    write_pattern[index] = static_cast<std::uint8_t>((index * 29 + 11) & 0xff);
  }
  backend.initialize_payload(0, 4032, read_pattern);

  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 42,
           .operation = MemoryOperation::kRead,
           .address = 4032,
           .bytes = read_pattern.size(),
           .write_data = {}},
          {.transaction_id = 43,
           .operation = MemoryOperation::kWrite,
           .address = 8192,
           .bytes = write_pattern.size(),
           .write_data = write_pattern},
      });
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 300);

  const auto read_response =
      std::find_if(consumer.values.begin(), consumer.values.end(),
                   [](const AxiResponse &response) {
                     return response.transaction_id == 42;
                   });
  require(read_response != consumer.values.end() &&
              read_response->read_data == read_pattern,
          "AXI failed to reassemble payload across beats and bursts");
  require(
      backend.inspect_payload(0, 8192, write_pattern.size()) == write_pattern,
      "AXI write payload did not reach backend storage");
  require(axi.stats().zero_filled_write_bytes == 0,
          "explicit AXI write payload was reported as zero-filled");
}

void test_memory_backend_payload_pages_preserve_sparse_fill_semantics() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config(2));

  constexpr std::uint64_t kCrossPageBase = 4090;
  backend.fill_payload(0, 4088, 32, 0xaa);
  backend.fill_payload(1, 4088, 32, 0x5c);

  std::vector<std::uint8_t> explicit_payload(20);
  for (std::size_t index = 0; index < explicit_payload.size(); ++index) {
    explicit_payload[index] =
        static_cast<std::uint8_t>((index * 19 + 7) & 0xffU);
  }
  backend.initialize_payload(0, kCrossPageBase, explicit_payload);

  std::vector<std::uint8_t> expected(32, 0xaa);
  std::copy(explicit_payload.begin(), explicit_payload.end(),
            expected.begin() + 2);
  require(backend.inspect_payload(0, 4088, expected.size()) == expected,
          "paged payload storage changed cross-page sparse/fill resolution");
  require(backend.inspect_payload(1, 4088, expected.size()) ==
              std::vector<std::uint8_t>(expected.size(), 0x5c),
          "paged payload storage leaked explicit bytes across channels");

  backend.fill_payload(0, kCrossPageBase, explicit_payload.size(), 0x33);
  require(backend.inspect_payload(0, kCrossPageBase, explicit_payload.size()) ==
              explicit_payload,
          "a later fill incorrectly overrode explicit payload bytes");

  backend.initialize_payload(0, 4095, {0x11});
  backend.initialize_payload(0, 4097, {0x22});
  require(backend.inspect_payload(0, 4095, 3) ==
              std::vector<std::uint8_t>({0x11, explicit_payload[6], 0x22}),
          "paged payload validity lost a byte around the page boundary");

  bool inspect_overflow_rejected = false;
  try {
    (void)backend.inspect_payload(
        0, std::numeric_limits<std::uint64_t>::max() - 1, 2);
  } catch (const std::invalid_argument&) {
    inspect_overflow_rejected = true;
  }
  require(inspect_overflow_rejected,
          "paged payload inspection accepted an overflowing address range");
}

void test_axi_read_beat_stream_is_bounded_and_request_scoped() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 4);
  Fifo<AxiReadBeatResponse> read_beats("axi-read-beats", core, 2);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config(1));
  AxiConfig config = axi_config();
  config.data_width_bytes = 16;
  config.beat_issues_per_cycle = 1;
  config.response_beats_per_cycle = 1;
  config.fixed_channel = 0;
  AxiMaster axi("axi", core, config, requests, responses, backend, &read_beats);

  std::vector<std::uint8_t> payload(128);
  for (std::size_t index = 0; index < payload.size(); ++index) {
    payload[index] = static_cast<std::uint8_t>((index * 13 + 7) & 0xffU);
  }
  backend.initialize_payload(0, 0, payload);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 70,
           .operation = MemoryOperation::kRead,
           .address = 0,
           .bytes = 64,
           .stream_read_beats = true,
           .write_data = {}},
          {.transaction_id = 71,
           .operation = MemoryOperation::kRead,
           .address = 64,
           .bytes = 64,
           .stream_read_beats = false,
           .write_data = {}},
      });
  SequenceConsumer<AxiReadBeatResponse> beat_consumer("beat-consumer", core,
                                                      read_beats, 12);
  SequenceConsumer<AxiResponse> response_consumer("response-consumer", core,
                                                  responses);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(read_beats);
  scheduler.add_component(response_consumer);
  scheduler.add_component(beat_consumer);
  scheduler.run_until(
      [&] {
        return response_consumer.values.size() == 2 &&
               beat_consumer.values.size() == 4;
      },
      100);

  require(axi.stats().read_beat_queue_stalls > 0 &&
              axi.stats().read_beats_streamed == 4 &&
              read_beats.stats().max_occupancy == 2,
          "AXI read-beat FIFO did not apply finite backpressure");
  for (std::size_t index = 0; index < beat_consumer.values.size(); ++index) {
    const AxiReadBeatResponse &beat = beat_consumer.values[index];
    require(
        beat.transaction_id == 70 && beat.parent_offset == index * 16 &&
            beat.address == index * 16 && beat.last == (index == 3) &&
            beat.read_data ==
                std::vector<std::uint8_t>(
                    payload.begin() + static_cast<std::ptrdiff_t>(index * 16),
                    payload.begin() +
                        static_cast<std::ptrdiff_t>((index + 1) * 16)),
        "AXI read-beat stream changed payload order or framing");
  }
  const auto streamed_parent = std::find_if(
      response_consumer.values.begin(), response_consumer.values.end(),
      [](const AxiResponse &response) {
        return response.transaction_id == 70;
      });
  const auto ordinary_parent = std::find_if(
      response_consumer.values.begin(), response_consumer.values.end(),
      [](const AxiResponse &response) {
        return response.transaction_id == 71;
      });
  require(
      streamed_parent != response_consumer.values.end() &&
          ordinary_parent != response_consumer.values.end() &&
          streamed_parent->read_data ==
              std::vector<std::uint8_t>(payload.begin(),
                                        payload.begin() + 64) &&
          ordinary_parent->read_data ==
              std::vector<std::uint8_t>(payload.begin() + 64, payload.end()),
      "AXI parent responses diverged from streamed/non-streamed payloads");
}

void test_spine_l0_real_slice_vertical_path() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });

  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports;
  SpineL0Ports ports;
  for (std::size_t family = 0; family < graph_ports.size(); ++family) {
    graph_ports[family] = std::make_unique<FixedAxiPort>(
        "graph" + std::to_string(family), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = family,
            .initiator_id = static_cast<std::uint32_t>(family),
        },
        backend);
    ports.graph[family] = graph_ports[family].get();
  }
  FixedAxiPort sorted("sorted-edges", core,
                      FixedAxiPortConfig{
                          .memory_channels = 32,
                          .channel = 16,
                          .initiator_id = 16,
                      },
                      backend);
  FixedAxiPort metadata("metadata", core,
                        FixedAxiPortConfig{
                            .memory_channels = 32,
                            .channel = 20,
                            .initiator_id = 20,
                        },
                        backend);
  FixedAxiPort result("result", core,
                      FixedAxiPortConfig{
                          .memory_channels = 32,
                          .channel = 21,
                          .initiator_id = 21,
                      },
                      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  const auto workload = load_spine_edge_slice(fixture);
  SpineL0State state;
  SpineL0Maintenance maintenance("spine-l0-maintenance", core, SpineL0Config{},
                                 workload, ports, state);

  FixedAxiPort active_bins("active-bins", core,
                           FixedAxiPortConfig{
                               .memory_channels = 32,
                               .channel = 18,
                               .initiator_id = 18,
                           },
                           backend);
  FixedAxiPort vertex_state("vertex-state", core,
                            FixedAxiPortConfig{
                                .memory_channels = 32,
                                .channel = 17,
                                .initiator_id = 117,
                            },
                            backend);
  FixedAxiPort active_out("active-out", core,
                          FixedAxiPortConfig{
                              .memory_channels = 32,
                              .channel = 19,
                              .initiator_id = 119,
                          },
                          backend);
  FixedAxiPort active_bitmap("active-bitmap", core,
                             FixedAxiPortConfig{
                                 .memory_channels = 32,
                                 .channel = 22,
                                 .initiator_id = 122,
                             },
                             backend);
  FixedAxiPort compute_result("compute-result", core,
                              FixedAxiPortConfig{
                                  .memory_channels = 32,
                                  .channel = 21,
                                  .initiator_id = 121,
                              },
                              backend);
  Fifo<PartConvWord> edge_stream("edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("value-axis", core, 32);
  SpineReaderPorts reader_ports;
  reader_ports.graph = ports.graph;
  reader_ports.task_scratch = &sorted;
  reader_ports.active_bins = &active_bins;
  reader_ports.metadata = &metadata;
  reader_ports.result = &result;
  const auto algorithm_policy = std::make_shared<const GraphAlgorithmPolicy>(
      AlgorithmPolicyConfig{
          .kind = GraphAlgorithmKind::kWeightedSssp,
          .vertices = workload.vertices,
          .source = 2,
      });
  SpineSplitReader reader("spine-split-reader", core, maintenance, reader_ports,
                          {2}, edge_stream, value_stream,
                          spine::sim::SpineReaderMode::kDeviceDirty,
                          algorithm_policy);
  SpineSplitSsspCompute compute("spine-split-compute", core, workload.vertices,
                                2, 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &compute_result,
                                },
                                edge_stream, value_stream,
                                SpineSplitSsspCompute::kDefaultMemoryRequestWindow,
                                SpineSplitSsspCompute::
                                    kDefaultWriteOnlyRequestWindow,
                                {}, algorithm_policy);

  scheduler.add_component(maintenance);
  scheduler.add_component(reader);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  active_bins.register_components(scheduler);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  compute_result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] { return maintenance.done() && reader.done() && compute.done(); },
      100'000);

  require(!maintenance.failed(), "Spine L0 real-slice path reported failure");
  require(&reader.algorithm_policy() == &compute.algorithm_policy() &&
              reader.algorithm_policy().config().kind ==
                  GraphAlgorithmKind::kWeightedSssp,
          "Reader and Compute did not share the weighted SSSP policy");
  const auto &counters = maintenance.counters();
  require(counters.sorted_scan_passes == 20,
          "Spine L0 did not execute the expected HLS scan passes");
  require(counters.sorted_edge_visits == 200,
          "Spine L0 edge-visit count does not close against scan passes");
  require(counters.sorted_read_bytes == 3'200,
          "Spine sorted-edge HBM byte count mismatch");
  require(counters.hot_cold_count_edge_visits == 10 &&
              counters.family_precount_edge_visits == 160 &&
              counters.l0_write_edge_visits == 10,
          "Spine source-shaped scan classes do not close");
  require(counters.unique_sources == 1 && counters.active_families == 1,
          "Amazon top1 family/source structure mismatch");
  require(counters.persisted_edges == 10 && counters.persisted_rows == 1,
          "Spine L0 persisted payload shape mismatch");
  require(counters.family_edges[0] == 10 && counters.family_rows[0] == 1,
          "Spine family0 metadata mismatch");
  require(counters.pages_stamped == 1,
          "Spine L0 source-page stamp count mismatch");
  require(counters.persistent_read_bytes == 32 &&
              counters.persistent_write_bytes == 32,
          "Spine dirty-frontier HBM byte count mismatch");
  require(counters.dirty_bitmap_reads == 1 &&
              counters.dirty_bitmap_writes == 1 &&
              counters.dirty_list_reads == 1 &&
              counters.dirty_list_appends == 1 &&
              counters.dirty_duplicates_suppressed == 9 &&
              counters.dirty_generation_advances == 1 &&
              counters.dirty_count == 1 && counters.dirty_generation == 1,
          "Spine dirty-frontier operation ledger mismatch");
  require(counters.graph_write_bytes == 144,
          "Spine L0 graph layout write byte count mismatch");
  require(counters.graph_index_payload_write_bytes == 64 &&
              counters.graph_edge_payload_write_bytes == 80,
          "Spine L0 graph write payload ledger mismatch");
  require(counters.l0_writer_groups_seen == 10 &&
              counters.l0_writer_groups_emitted == 10 &&
              counters.l0_writer_groups_cancelled == 0 &&
              counters.l0_writer_edge_word_writes == 10 &&
              counters.l0_writer_row_word_writes == 1 &&
              counters.l0_writer_mask_word_writes == 1 &&
              counters.l0_writer_page_base_word_writes == 2 &&
              counters.l0_writer_bitmap_page_writes == 1 &&
              counters.l0_writer_page_list_word_writes == 1 &&
              counters.l0_writer_page_epoch_word_writes == 1 &&
              counters.l0_writer_memory_wait_cycles > 0 &&
              counters.l0_writer_memory_overlap_cycles > 0 &&
              counters.l0_writer_validation_failures == 0 &&
              counters.l0_writer_max_pending_tasks > 0,
          "Spine L0 online writer/packer ledger mismatch");
  require(counters.slice_epoch_reads == 1 &&
              counters.slice_epoch_responses == 1 &&
              counters.slice_epoch_payload_read_bytes == 8 &&
              counters.slice_epoch_validation_failures == 0 &&
              counters.metadata_read_bytes == 2'992 &&
              counters.page_list_payload_write_bytes == 8 &&
              counters.page_list_count_write_bytes > 0 &&
              counters.metadata_write_bytes ==
                  1'224 + counters.page_list_payload_write_bytes +
                      counters.page_list_count_write_bytes,
          "Spine L0 metadata byte ledger mismatch");
  require(counters.result_write_bytes == 384,
          "Spine maintenance result byte count mismatch");
  require(state.cold_levels[0][0] == workload.edges,
          "Spine L0 logical payload differs from the real input slice");
  for (std::size_t family = 1; family < graph_ports.size(); ++family) {
    require(state.cold_levels[family][0].empty(),
            "Spine L0 wrote an inactive destination family");
  }
  require(
      counters.end_cycle > counters.start_cycle + counters.sorted_edge_visits,
      "Spine timing did not include memory/control work");

  require(!reader.failed() && !compute.failed(),
          "Spine split reader/compute path reported failure");
  const auto &reader_counters = reader.counters();
  require(reader_counters.source_requests == 1 &&
              reader_counters.source_responses == 1 &&
              reader_counters.source_request_windows == 1 &&
              reader_counters.source_protocol_markers == 3 &&
              reader_counters.source_protocol_acks == 1 &&
              reader_counters.source_protocol_status == 0 &&
              reader_counters.dirty_status == 0 &&
              reader_counters.diagnostic_words == 10 &&
              reader_counters.done_words == 1 &&
              !reader_counters.done_overflow,
          "Spine source-value protocol did not close");
  require(
      reader_counters.tiles_emitted == 5 && reader_counters.edges_emitted == 10,
      "Spine reader tile/edge stream shape mismatch");
  require(reader_counters.active_bin_read_bytes == 0 &&
              reader_counters.dirty_list_read_bytes == 16 &&
              reader_counters.dirty_bitmap_read_bytes == 16 &&
              reader_counters.metadata_read_bytes == 2'928 &&
              reader_counters.metadata_write_bytes == 16 &&
              reader_counters.result_write_bytes == 64 &&
              reader_counters.level_cache_read_bytes == 2'880 &&
              reader_counters.row_lookup_metadata_bytes == 8 &&
              reader_counters.graph_read_bytes == 184,
          "Spine reader memory byte ledger mismatch");
  require(reader_counters.graph_index_payload_read_bytes == 24 &&
              reader_counters.graph_edge_payload_read_bytes == 160 &&
              reader_counters.graph_construction_payload_read_bytes == 80 &&
              reader_counters.graph_replay_payload_read_bytes == 80 &&
              reader_counters.graph_index_bitmap_misses == 0,
          "Spine reader graph index payload ledger mismatch");
  require(reader_counters.range_task_active_records == 1 &&
              reader_counters.range_task_family_probes == 16 &&
              reader_counters.range_task_level_checks == 176 &&
              reader_counters.range_task_row_lookups == 1 &&
              reader_counters.range_task_construction_payloads == 10 &&
              reader_counters.range_task_count == 5 &&
              reader_counters.range_task_replay_payloads == 10 &&
              reader_counters.range_task_clear_cycles == 256 &&
              reader_counters.range_task_prefix_cycles == 256 &&
              reader_counters.range_task_scatter_cycles == 5 &&
              reader_counters.range_task_verify_cycles == 256 &&
              reader_counters.range_task_path == 1,
          "Spine exact range-task work ledger mismatch");

  const auto &compute_counters = compute.counters();
  require(compute_counters.source_requests == 1 &&
              compute_counters.source_responses == 1 &&
              compute_counters.source_protocol_markers == 3 &&
              compute_counters.source_protocol_acks == 1 &&
              compute_counters.source_protocol_status == 0 &&
              compute_counters.source_count == 1 &&
              compute_counters.source_generation == 1 &&
              compute_counters.diagnostic_words == 10 &&
              compute_counters.done_words == 1 &&
              !compute_counters.done_overflow &&
              compute_counters.range_task_path ==
                  reader_counters.range_task_path &&
              compute_counters.range_task_count ==
                  reader_counters.range_task_count &&
              compute_counters.range_task_row_lookups ==
                  reader_counters.range_task_row_lookups &&
              compute_counters.range_task_construction_payloads ==
                  reader_counters.range_task_construction_payloads &&
              compute_counters.range_task_replay_payloads ==
                  reader_counters.range_task_replay_payloads &&
              compute_counters.range_task_active_records ==
                  reader_counters.range_task_active_records &&
              compute_counters.range_task_family_probes ==
                  reader_counters.range_task_family_probes &&
              compute_counters.range_task_family_skips ==
                  reader_counters.range_task_family_skips &&
              compute_counters.dirty_count == 1 &&
              compute_counters.dirty_generation == 1,
          "Spine compute source protocol ledger mismatch");
  require(compute_counters.touched_tiles == 5 &&
              compute_counters.fast_path_tiles == 5 &&
              compute_counters.full_path_tiles == 0,
          "Spine tiny-tile path selection mismatch");
  require(compute_counters.processed_edges == 10 &&
              compute_counters.gathered_vertex_words == 10 &&
              compute_counters.scattered_vertex_words == 10,
          "Spine tiny-tile work counters mismatch");
  require(compute_counters.vertex_read_bytes == 44 &&
              compute_counters.vertex_write_bytes == 40 &&
              compute_counters.active_out_write_bytes == 80 &&
              compute_counters.bitmap_bytes == 16 &&
              compute_counters.result_write_bytes == 384,
          "Spine compute memory byte ledger mismatch");
  require(compute.next_active().size() == 10,
          "Spine SSSP next frontier size mismatch");
  for (const auto &edge : workload.edges) {
    require(compute.values()[edge.dst] == 1,
            "Spine SSSP result differs from the expected fanout distance");
  }
  require(edge_stream.stats().pushes == 35 && edge_stream.stats().pops == 35,
          "Spine forward AXIS transfer count mismatch");
  require(value_stream.stats().pushes == 2 && value_stream.stats().pops == 2,
          "Spine reverse AXIS transfer count mismatch");
  require(edge_stream.stats().max_occupancy <= 32 &&
              value_stream.stats().max_occupancy <= 32,
          "Spine AXIS occupancy exceeded the configured depth");
  require(scheduler.clock(core).completed_cycles == 43'407 &&
              counters.end_cycle - counters.start_cycle == 2'370 &&
              reader_counters.end_cycle - reader_counters.start_cycle ==
                  4'478 &&
              compute_counters.end_cycle - compute_counters.start_cycle ==
                  40'968,
          "algorithm policy injection changed the accepted SSSP cycle ledger");
  std::cout << "EVIDENCE spine_vertical_slice e2e_cycles="
            << scheduler.clock(core).completed_cycles << " maintenance_cycles="
            << counters.end_cycle - counters.start_cycle << " reader_cycles="
            << reader_counters.end_cycle - reader_counters.start_cycle
            << " compute_cycles="
            << compute_counters.end_cycle - compute_counters.start_cycle
            << " edge_axis_max_occupancy=" << edge_stream.stats().max_occupancy
            << " l0_writer_edges=" << counters.l0_writer_edge_word_writes
            << " l0_writer_overlap="
            << counters.l0_writer_memory_overlap_cycles
            << " l0_writer_wait=" << counters.l0_writer_memory_wait_cycles
            << " l0_writer_max_pending="
            << counters.l0_writer_max_pending_tasks
            << '\n';
}

void test_spine_dirty_mark_preserves_persistent_state() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 5,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineAxiInterfaceProfile profile;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports;
  SpineL0Ports ports;
  for (std::size_t family = 0; family < graph_ports.size(); ++family) {
    graph_ports[family] = std::make_unique<FixedAxiPort>(
        "dirty-graph" + std::to_string(family), core,
        profile.port_config(SpineAxiPortKind::kGraph, 32, family,
                            static_cast<std::uint32_t>(family)),
        backend);
    ports.graph[family] = graph_ports[family].get();
  }
  FixedAxiPort sorted(
      "dirty-sorted", core,
      profile.port_config(SpineAxiPortKind::kSortedEdges, 32, 16, 16),
      backend);
  FixedAxiPort metadata(
      "dirty-metadata", core,
      profile.port_config(SpineAxiPortKind::kMetadata, 32, 20, 20), backend);
  FixedAxiPort result(
      "dirty-result", core,
      profile.port_config(SpineAxiPortKind::kMaintenanceResult, 32, 21, 21),
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice workload{
      .vertices = 8,
      .edges =
          {
              {.src = 2, .dst = 4, .weight = 1, .diff = 1},
              {.src = 3, .dst = 5, .weight = 1, .diff = 1},
          },
      .case_name = "persistent_dirty_duplicate_and_append",
  };
  SpineL0Config config;
  SpineL0State state;
  SpineL0Maintenance maintenance("dirty-maintenance", core, config, workload,
                                 ports, state);

  const std::vector<std::uint32_t> old_sources{2};
  const SpineDirtyIdentity old_identity = spine_dirty_identity(7, old_sources);
  const auto layout = spine_metadata_layout(config);
  std::vector<std::uint8_t> metadata_payload;
  for (const std::uint64_t word :
       {static_cast<std::uint64_t>(old_identity.count),
        static_cast<std::uint64_t>(old_identity.generation),
        old_identity.hash_sum, old_identity.hash_xor}) {
    const std::vector<std::uint8_t> bytes = u64_payload(word);
    metadata_payload.insert(metadata_payload.end(), bytes.begin(), bytes.end());
  }
  metadata.initialize_payload(
      config.metadata_base + layout.dirty_count_word * sizeof(std::uint64_t),
      metadata_payload);
  std::vector<std::uint8_t> bitmap(16, 0);
  bitmap[0] = 1U << 2;
  sorted.initialize_payload(config.persistent_dirty_bitmap_base, bitmap);
  std::vector<std::uint8_t> list(16, 0);
  const std::vector<std::uint8_t> source_two = u32_payload(2);
  std::copy(source_two.begin(), source_two.end(), list.begin());
  sorted.initialize_payload(config.persistent_dirty_list_base, list);

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle();
      },
      200'000);

  require(!maintenance.failed(),
          "persistent dirty duplicate/append maintenance failed");
  const auto &counters = maintenance.counters();
  const std::vector<std::uint32_t> expected_sources{2, 3};
  const SpineDirtyIdentity expected =
      spine_dirty_identity(8, expected_sources);
  std::cout << "EVIDENCE spine_dirty_persistent_state cycles="
            << scheduler.clock(core).completed_cycles
            << " bitmap_reads=" << counters.dirty_bitmap_reads
            << " bitmap_writes=" << counters.dirty_bitmap_writes
            << " list_appends=" << counters.dirty_list_appends
            << " duplicates=" << counters.dirty_duplicates_suppressed
            << " final_count=" << counters.dirty_count
            << " final_generation=" << counters.dirty_generation << '\n';
  require(counters.unique_sources == 2 && counters.dirty_bitmap_reads == 2 &&
              counters.dirty_bitmap_writes == 1 &&
              counters.dirty_list_reads == 1 &&
              counters.dirty_list_appends == 1 &&
              counters.dirty_duplicates_suppressed == 1 &&
              counters.dirty_generation_advances == 1 &&
              counters.dirty_count == expected.count &&
              counters.dirty_generation == expected.generation &&
              counters.dirty_hash_sum == expected.hash_sum &&
              counters.dirty_hash_xor == expected.hash_xor,
          "persistent dirty operation/state ledger diverged from HLS");
  require(counters.persistent_read_bytes == 48 &&
              counters.persistent_write_bytes == 32 &&
              counters.sorted_scan_passes == 20 &&
              counters.sorted_edge_visits == 40 &&
              counters.sorted_read_beats_received == 40,
          "persistent dirty memory/scan ledger diverged from HLS");

  const std::vector<std::uint8_t> final_bitmap = backend.inspect_payload(
      16, config.persistent_dirty_bitmap_base, 16);
  const std::vector<std::uint8_t> final_list = backend.inspect_payload(
      16, config.persistent_dirty_list_base, 16);
  require((final_bitmap[0] & ((1U << 2) | (1U << 3))) ==
              ((1U << 2) | (1U << 3)) &&
              final_list[0] == 2 && final_list[4] == 3,
          "persistent dirty bitmap/list payload was not preserved and appended");
  const std::vector<std::uint8_t> final_metadata = backend.inspect_payload(
      20,
      config.metadata_base + layout.dirty_count_word * sizeof(std::uint64_t),
      4 * sizeof(std::uint64_t));
  require(final_metadata ==
              [&] {
                std::vector<std::uint8_t> bytes;
                for (const std::uint64_t word :
                     {static_cast<std::uint64_t>(expected.count),
                      static_cast<std::uint64_t>(expected.generation),
                      expected.hash_sum, expected.hash_xor}) {
                  const auto encoded = u64_payload(word);
                  bytes.insert(bytes.end(), encoded.begin(), encoded.end());
                }
                return bytes;
              }(),
          "persistent dirty metadata payload did not close");
}

void test_spine_reusable_system_matches_vertical_slice() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  const auto workload = load_spine_edge_slice(fixture);
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 2);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  std::cout << "EVIDENCE spine_reusable_streamed_maintenance cycles="
            << scheduler.clock(core).completed_cycles << " scan_passes="
            << system.maintenance_counters().sorted_scan_passes
            << " scan_response_stalls="
            << system.maintenance_counters().sorted_scan_response_stall_cycles
            << " scan_ii_stalls="
            << system.maintenance_counters().sorted_scan_ii_stall_cycles
            << '\n';

  require(!system.failed(), "reusable Spine vertical-slice system failed");
  require(system.maintenance_counters().sorted_scan_passes == 20,
          "reusable Spine system changed maintenance work");
  require(system.reader_counters().graph_read_bytes == 184,
          "reusable Spine system changed reader memory work");
  require(system.compute_counters().processed_edges == 10,
          "reusable Spine system changed compute work");
  require(system.compute().next_active().size() == 10,
          "reusable Spine system changed the SSSP frontier");
}

SpineActiveBins build_spine_host_active_bins_reference(
    const SpineL0State &state, const SpineL0Config &config,
    const std::vector<std::uint32_t> &sources,
    const std::vector<std::uint32_t> &values) {
  SpineActiveBins result;
  for (const std::uint32_t source : sources) {
    if (source >= values.size()) {
      throw std::logic_error("host active source has no vertex-state value");
    }
    SpineActiveRecord base{
        .source = source,
        .source_value = values[source],
    };
    std::array<std::uint16_t, 16> hot_by_partition{};
    std::uint16_t any_partition = 0;
    for (std::size_t level = 0; level < config.levels; ++level) {
      std::uint16_t cold_mask = 0;
      for (std::size_t family = 0; family < config.partitions; ++family) {
        for (const SpineEdgeRecord &edge : state.cold_levels[family][level]) {
          if (edge.src == source) {
            const std::size_t partition = std::min<std::size_t>(
                edge.dst / config.vertex_partition_size,
                config.partitions - 1);
            cold_mask |= static_cast<std::uint16_t>(1U << partition);
          }
        }
        if (!state.hot_enabled) {
          continue;
        }
        for (const SpineEdgeRecord &edge : state.hot_levels[family][level]) {
          if (edge.src == source) {
            const std::size_t partition = std::min<std::size_t>(
                edge.dst / config.vertex_partition_size,
                config.partitions - 1);
            hot_by_partition[partition] |=
                static_cast<std::uint16_t>(1U << family);
          }
        }
      }
      base.level_masks[level] = cold_mask;
      any_partition |= cold_mask;
    }
    for (std::size_t partition = 0; partition < config.partitions;
         ++partition) {
      if (hot_by_partition[partition] != 0) {
        any_partition |= static_cast<std::uint16_t>(1U << partition);
      }
      if (((any_partition >> partition) & 1U) == 0) {
        continue;
      }
      SpineActiveRecord record = base;
      record.hot_shard_mask = hot_by_partition[partition];
      result.bins[partition].push_back(record);
    }
  }
  return result;
}

void test_spine_host_active_bin_builder_matches_scan_reference() {
  SpineL0Config config;
  config.partitions = 4;
  config.levels = 3;
  config.vertex_partition_size = 10;
  SpineL0State state;
  state.hot_enabled = true;
  state.cold_levels[0][0].push_back(
      {.src = 2, .dst = 5, .weight = 1, .diff = 1});
  state.cold_levels[1][1].push_back(
      {.src = 2, .dst = 21, .weight = 2, .diff = 1});
  state.cold_levels[2][2].push_back(
      {.src = 7, .dst = 35, .weight = 3, .diff = 1});
  state.cold_levels[3][0].push_back(
      {.src = 7, .dst = 15, .weight = 4, .diff = 1});
  state.cold_levels[0][2].push_back(
      {.src = 99, .dst = 9, .weight = 5, .diff = 1});
  state.hot_levels[3][2].push_back(
      {.src = 2, .dst = 12, .weight = 6, .diff = 1});
  state.hot_levels[1][0].push_back(
      {.src = 7, .dst = 35, .weight = 7, .diff = 1});
  state.hot_levels[0][1].push_back(
      {.src = 99, .dst = 25, .weight = 8, .diff = 1});
  std::vector<std::uint32_t> values(100);
  std::iota(values.begin(), values.end(), 1U);
  const std::vector<std::uint32_t> sources{7, 2, 7, 11, 2};

  const SpineActiveBins expected = build_spine_host_active_bins_reference(
      state, config, sources, values);
  const SpineActiveBins actual =
      build_spine_host_active_bins(state, config, sources, values);
  require(actual.size() == 10 && actual.size() == expected.size(),
          "optimized HOST_ACTIVE builder changed emitted record count");
  for (std::size_t partition = 0; partition < actual.bins.size();
       ++partition) {
    require(actual.bins[partition] == expected.bins[partition],
            "optimized HOST_ACTIVE builder changed record ordering or masks");
  }

  bool rejected = false;
  try {
    (void)build_spine_host_active_bins(state, config, {100}, values);
  } catch (const std::logic_error &) {
    rejected = true;
  }
  require(rejected,
          "optimized HOST_ACTIVE builder accepted an out-of-range source");
}

void test_spine_host_active_requires_exact_dirty_coverage() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  SpineVerticalSliceSystem system(
      scheduler, core, backend, load_spine_edge_slice(fixture), 2);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  require(system.reader_counters().acknowledgement_eligible,
          "successful DEVICE_DIRTY reader should be ACK eligible");
  system.restart_read_compute({2});
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);
  require(!system.failed() &&
              system.reader_counters().dirty_status ==
                  static_cast<std::uint32_t>(
                      spine::sim::SpineDirtyStatus::kCoverageMismatch) &&
              !system.reader_counters().host_coverage_match &&
              !system.reader_counters().acknowledgement_eligible,
          "HOST_ACTIVE accepted an unpublished dirty handoff");

  const std::vector<std::uint32_t> covered_sources{2};
  system.restart_read_compute(
      {2}, spine::sim::spine_dirty_identity(1, covered_sources));
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);
  require(!system.failed() && system.reader_counters().dirty_status == 0 &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().acknowledgement_eligible &&
              system.reader_counters().dirty_hash_sum ==
                  spine::sim::spine_dirty_hash_sum_term(2) &&
              system.reader_counters().dirty_hash_xor ==
                  spine::sim::spine_dirty_hash_xor_term(2),
          "HOST_ACTIVE rejected an exact generation/count/hash handoff");
}

void test_spine_device_dirty_source_request_windows() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineEdgeSlice workload{
      .vertices = 64,
      .edges = {},
      .case_name = "device_dirty_request_window_17",
  };
  for (std::uint32_t source = 0; source < 17; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 32 + source,
        .weight = 1,
        .diff = 1,
    });
  }
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  require(!system.failed() && reader.source_requests == 17 &&
              reader.source_responses == 17 &&
              reader.source_request_windows == 2 &&
              reader.source_protocol_markers == 3 &&
              reader.source_protocol_acks == 1 &&
              reader.source_protocol_status == 0 && reader.dirty_status == 0 &&
              reader.diagnostic_words == 10 && reader.done_words == 1 &&
              !reader.done_overflow,
          "reader did not execute two ordered 16-credit source windows");
  require(compute.source_requests == 17 && compute.source_responses == 17 &&
              compute.source_protocol_markers == 3 &&
              compute.source_protocol_acks == 1 &&
              compute.source_protocol_status == 0 &&
              compute.source_count == 17 && compute.source_generation == 1 &&
              compute.diagnostic_words == 10 && compute.done_words == 1 &&
              !compute.done_overflow && compute.dirty_count == 17 &&
              compute.dirty_generation == 1,
          "compute did not validate the 17-source protocol transcript");
  require(system.edge_stream_stats().max_occupancy > 1 &&
              system.edge_stream_stats().max_occupancy <= 32 &&
              system.value_stream_stats().max_occupancy <= 32,
          "source request window did not exercise finite AXIS buffering");
}

void test_spine_host_source_refresh_includes_edgeless_vertices() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineEdgeSlice workload{
      .vertices = 4,
      .edges = {{.src = 0, .dst = 1, .weight = 5, .diff = 1}},
      .case_name = "host_source_refresh_edgeless",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 2);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);
  require(!system.failed() &&
              system.compute().values()[1] ==
                  SpineSplitSsspCompute::kInfinity,
          "seed round unexpectedly reached the host-refresh destination");

  SpineActiveBins bins;
  SpineActiveRecord stale_record;
  stale_record.source = 0;
  stale_record.source_value = 0;
  stale_record.level_masks[0] = 1;
  bins.bins[0].push_back(stale_record);
  const SpineDirtyIdentity coverage =
      spine::sim::spine_dirty_identity(1, std::vector<std::uint32_t>{0});
  system.restart_read_compute_bins(bins, coverage, {0, 2});
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  std::cout << "EVIDENCE spine_host_source_refresh reader_requests="
            << reader.source_requests
            << " reader_responses=" << reader.source_responses
            << " windows=" << reader.source_request_windows
            << " compute_requests=" << compute.source_requests
            << " compute_responses=" << compute.source_responses
            << " compute_count=" << compute.source_count
            << " protocol=" << compute.source_protocol_status
            << " failed=" << system.failed()
            << " reader_protocol=" << reader.source_protocol_status
            << " dirty_status=" << reader.dirty_status
            << " range_path=" << reader.range_task_path
            << " range_error=" << reader.range_task_error
            << " overflow=" << reader.done_overflow
            << " source_ids=";
  for (const std::uint32_t source : system.reader_source_ids()) {
    std::cout << source << ',';
  }
  std::cout << " edges=" << reader.edges_emitted
            << " processed=" << compute.processed_edges
            << " next=" << system.compute().next_active().size()
            << " value1=" << system.compute().values()[1] << '\n';
  require(!system.failed() && reader.source_requests == 2 &&
              reader.source_responses == 2 &&
              reader.source_request_windows == 1 &&
              system.reader_source_ids() ==
                  std::vector<std::uint32_t>({0, 2}) &&
              compute.source_requests == 2 && compute.source_responses == 2 &&
              compute.source_count == 2 && compute.source_protocol_status == 0,
          "HOST_ACTIVE did not refresh both edge-bearing and edgeless sources");
  require(reader.edges_emitted == 1 && compute.processed_edges == 1 &&
              system.compute().next_active().empty() &&
              system.compute().values()[1] ==
                  SpineSplitSsspCompute::kInfinity,
          "Reader used stale host source_value instead of refreshed HBM payload");
}

void test_spine_host_active_gate_runs_tiled_fallback() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 327'681,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 1, .diff = 1},
              {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
              {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
              {.src = 0, .dst = 196'608, .weight = 4, .diff = 1},
              {.src = 0, .dst = 262'144, .weight = 5, .diff = 1},
          },
      .case_name = "host_active_gate_forced_dense",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 200'000);
  require(!system.failed(),
          "fallback fixture failed its DEVICE_DIRTY seed round");

  SpineActiveBins bins;
  SpineActiveRecord enabled;
  enabled.source = 0;
  enabled.source_value = 0;
  enabled.level_masks[0] = 1;
  bins.bins[0].push_back(enabled);
  SpineActiveRecord disabled;
  disabled.source = 0;
  disabled.source_value = 0;
  bins.bins[0].resize(16'385, disabled);
  const SpineDirtyIdentity coverage =
      spine::sim::spine_dirty_identity(1, std::vector<std::uint32_t>{0});
  system.restart_read_compute_bins(bins, coverage);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  std::cout << "EVIDENCE spine_forced_dense_controller swept="
            << compute.swept_vertex_words
            << " clear_words=" << compute.tile_active_clear_words
            << " emit_words=" << compute.active_emit_scan_words
            << " controller_cycles=" << compute.on_chip_controller_cycles
            << '\n';
  require(!system.failed() && reader.range_task_path == 2 &&
              reader.range_task_fallback_reason == 1 &&
              reader.range_task_error == 0 && !reader.done_overflow &&
              reader.range_task_active_records == 16'385 &&
              reader.range_task_count == 0 && reader.fallback_partitions == 1 &&
              reader.fallback_forced_dense_partitions == 1 &&
              reader.fallback_active_record_reads == 16'385 * 7ULL &&
              reader.fallback_active_record_read_bytes ==
                  16'385 * 7ULL * spine::sim::kSpineActiveRecordBytes &&
              reader.fallback_row_lookups == 7 &&
              reader.fallback_endpoint_reads == 2 &&
              reader.fallback_lower_bound_reads > 0 &&
              reader.fallback_replay_edges == 5 && reader.tiles_emitted == 6 &&
              reader.edges_emitted == 5 && reader.host_coverage_match &&
              reader.acknowledgement_eligible,
          "HOST_ACTIVE active-gate fallback did not match the HLS work shape");
  require(compute.range_task_path == 2 &&
              compute.range_task_fallback_reason == 1 &&
              compute.range_task_error == 0 && !compute.done_overflow &&
              compute.forced_dense_tiles == 6 && compute.full_path_tiles == 6 &&
              compute.processed_edges == 5 &&
              compute.swept_vertex_words == workload.vertices &&
              compute.tile_active_clear_words == 6 * 1024,
          "force-dense fallback was not honored by split compute");
}

void test_spine_device_dirty_limit_hands_off_to_host() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 8'192,
      .edges = {},
      .case_name = "device_dirty_4097_host_handoff",
  };
  for (std::uint32_t source = 0; source < 4'097; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 6'000,
        .weight = 1,
        .diff = -1,
    });
  }
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);

  require(system.failed() && system.recoverable_host_handoff() &&
              system.reader_counters().dirty_count == 4'097 &&
              system.reader_counters().dirty_status ==
                  static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost) &&
              system.reader_counters().range_task_path == 2 &&
              system.reader_counters().range_task_fallback_reason == 4 &&
              system.reader_counters().range_task_error == 0 &&
              system.reader_counters().dirty_list_read_bytes == 0 &&
              system.compute_counters().done_overflow,
          "DEVICE_DIRTY did not expose a recoverable 4097-source handoff");

  const std::vector<std::uint32_t> sources =
      system.restart_device_dirty_host_fallback();
  require(sources.size() == 4'097 && sources.front() == 0 &&
              sources.back() == 4'096 && !system.failed(),
          "host handoff did not recover the exact dirty-source list");
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);
  require(!system.failed() && system.reader_counters().dirty_count == 4'097 &&
              system.reader_counters().dirty_generation == 1 &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().acknowledgement_eligible &&
              system.reader_counters().range_task_active_records == 4'097 &&
              system.reader_counters().range_task_path == 1 &&
              !system.compute_counters().done_overflow,
          "HOST_ACTIVE did not complete the DEVICE_DIRTY handoff");

  system.start_dirty_ack();
  scheduler.run_until([&] { return system.dirty_ack_done() && system.idle(); },
                      1'000'000);
  require(!system.failed() && system.dirty_ack_counters().status == 0 &&
              system.dirty_ack_counters().captured.count == 4'097 &&
              system.dirty_ack_counters().result.count == 0 &&
              system.dirty_ack_counters().result.generation == 2 &&
              system.dirty_ack_counters().cleared_sources == 4'097,
          "ACK_DIRTY did not close the recovered host handoff");
}

void test_spine_device_task_limits_hand_off_to_tiled_fallback() {
  const auto run_case = [](const std::string &case_name,
                           std::uint32_t expected_reason,
                           SpineL0Config config) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("data", 141.0);
    MockMemoryBackend backend("hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 2,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 128,
                                  .response_queue_depth = 256,
                              });
    SpineEdgeSlice workload{
        .vertices = 131'073,
        .edges =
            {
                {.src = 0, .dst = 1, .weight = 1, .diff = 1},
                {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
                {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
            },
        .case_name = case_name,
    };
    SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0,
                                    4'096, std::move(config));
    system.register_components();
    scheduler.add_component(backend);
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);

    require(
        system.failed() && system.recoverable_host_handoff() &&
            system.reader_counters().dirty_count == 1 &&
            system.reader_counters().dirty_status ==
                static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost) &&
            system.reader_counters().range_task_path == 2 &&
            system.reader_counters().range_task_fallback_reason ==
                expected_reason &&
            system.reader_counters().range_task_error == 0 &&
            system.compute_counters().done_overflow,
        case_name + " did not expose a recoverable DEVICE handoff");

    const std::vector<std::uint32_t> sources =
        system.restart_device_dirty_host_fallback();
    require(sources == std::vector<std::uint32_t>{0} && !system.failed(),
            case_name + " did not recover the dirty source");
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);

    const auto &reader = system.reader_counters();
    const auto &compute = system.compute_counters();
    require(!system.failed() && reader.range_task_path == 2 &&
                reader.range_task_fallback_reason == expected_reason &&
                reader.range_task_error == 0 && !reader.done_overflow &&
                reader.host_coverage_match && reader.acknowledgement_eligible &&
                reader.fallback_partitions == 1 &&
                reader.fallback_active_record_reads == 4 &&
                reader.fallback_row_lookups == 4 &&
                reader.fallback_replay_edges == 3 &&
                reader.tiles_emitted == 3 && reader.edges_emitted == 3,
            case_name + " HOST tiled fallback work ledger diverged");
    require(compute.range_task_path == 2 &&
                compute.range_task_fallback_reason == expected_reason &&
                compute.range_task_error == 0 && !compute.done_overflow &&
                compute.processed_edges == 3 && compute.fast_path_tiles == 3 &&
                compute.full_path_tiles == 0,
            case_name + " compute did not consume the fallback edge stream");
  };

  SpineL0Config capacity;
  capacity.range_task_capacity = 2;
  run_case("device_capacity_host_tiled_fallback", 2, capacity);

  SpineL0Config payload;
  payload.range_task_payload_budget = 2;
  run_case("device_payload_host_tiled_fallback", 3, payload);
}

void test_spine_convergence_runner_records_host_handoff() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 131'073,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 1, .diff = 1},
              {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
              {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
          },
      .case_name = "convergence_runner_capacity_handoff",
  };
  SpineL0Config config;
  config.range_task_capacity = 2;
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0, 4'096,
                                  std::move(config));
  system.register_components();
  scheduler.add_component(backend);

  const auto result = system.run_sssp_to_convergence(4, 500'000);
  require(result.converged && !result.failed && result.rounds.size() == 2 &&
              result.host_handoffs.size() == 1,
          "convergence runner did not recover exactly one logical round");
  const auto &handoff = result.host_handoffs.front();
  require(handoff.logical_round == 0 && handoff.fallback_reason == 2 &&
              handoff.source_count == 1 &&
              handoff.host_list_read_bytes == spine::sim::kSpineSortWordBytes &&
              handoff.host_control_cycles == 0 && !handoff.host_control_timed &&
              handoff.device_attempt.reader.done_overflow &&
              handoff.device_attempt.compute.done_overflow &&
              handoff.device_attempt.end_cycle >
                  handoff.device_attempt.start_cycle,
          "host handoff evidence hid or misclassified the DEVICE attempt");
  require(result.rounds[0].reader.range_task_path == 2 &&
              result.rounds[0].reader.range_task_fallback_reason == 2 &&
              result.rounds[0].reader.fallback_replay_edges == 3 &&
              result.rounds[0].compute.processed_edges == 3 &&
              result.rounds[0].end_cycle - result.rounds[0].start_cycle >
                  handoff.device_attempt.end_cycle -
                      handoff.device_attempt.start_cycle &&
              result.rounds[1].active_in.size() == 3 &&
              result.rounds[1].active_out.empty(),
          "accepted round evidence did not include DEVICE plus HOST execution");
  require(system.compute().values()[1] == 1 &&
              system.compute().values()[65'536] == 2 &&
              system.compute().values()[131'072] == 3,
          "fallback convergence result diverged from weighted SSSP oracle");
}

void test_spine_convergence_runner_separates_host_replay_from_frontier() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 8'194,
      .edges = {},
      .case_name = "convergence_runner_4097_dirty_sources",
  };
  for (std::uint32_t source = 0; source < 4'097; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 4'097 + source,
        .weight = 1,
        .diff = 1,
    });
  }
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);

  const auto result = system.run_sssp_to_convergence(4, 10'000'000);
  require(result.converged && !result.failed && result.rounds.size() == 2 &&
              result.host_handoffs.size() == 1,
          "4097-source convergence did not recover one logical round");
  const auto &handoff = result.host_handoffs.front();
  require(handoff.logical_round == 0 && handoff.fallback_reason == 4 &&
              handoff.source_count == 4'097 &&
              handoff.device_attempt.active_in ==
                  std::vector<std::uint32_t>{0} &&
              handoff.device_attempt.reader.done_overflow &&
              handoff.device_attempt.compute.done_overflow,
          "4097-source DEVICE attempt lost its logical-frontier evidence");
  require(result.rounds[0].active_in == std::vector<std::uint32_t>{0} &&
              result.rounds[0].reader_sources.size() == 4'097 &&
              result.rounds[0].reader_sources.front() == 0 &&
              result.rounds[0].reader_sources.back() == 4'096 &&
              result.rounds[0].active_out ==
                  std::vector<std::uint32_t>{4'097} &&
              result.rounds[1].active_in ==
                  std::vector<std::uint32_t>{4'097} &&
              result.rounds[1].active_out.empty(),
          "host replay sources were conflated with the logical SSSP frontier");
  require(system.compute().values()[0] == 0 &&
              system.compute().values()[4'097] == 1 &&
              system.compute().values()[4'098] ==
                  SpineSplitSsspCompute::kInfinity,
          "4097-source host replay diverged from weighted SSSP semantics");
}

void test_spine_dirty_ack_rejects_stale_and_malformed_candidates() {
  const auto run_case = [](std::uint32_t expected_generation,
                           SpineDirtyIdentity candidate,
                           SpineDirtyStatus expected_status) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("data", 141.0);
    MockMemoryBackend backend("hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 3,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 64,
                                  .response_queue_depth = 128,
                              });
    FixedAxiPort scratch(
        "dirty-ack-scratch", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 16, .initiator_id = 916},
        backend);
    FixedAxiPort metadata(
        "dirty-ack-metadata", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 20, .initiator_id = 920},
        backend);
    FixedAxiPort result(
        "dirty-ack-result", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 21, .initiator_id = 921},
        backend);
    const SpineL0Config config;
    const auto layout = spine::sim::spine_metadata_layout(config);
    const SpineDirtyIdentity captured =
        spine::sim::spine_dirty_identity(7, std::vector<std::uint32_t>{2});
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_count_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.count));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_generation_word *
                spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.generation));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_hash_sum_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.hash_sum));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_hash_xor_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.hash_xor));
    std::vector<std::uint8_t> list_word(16, 0);
    list_word[0] = 2;
    scratch.initialize_payload(config.persistent_dirty_list_base, list_word);
    std::vector<std::uint8_t> bitmap_word(16, 0);
    bitmap_word[0] = 1U << 2;
    scratch.initialize_payload(config.persistent_dirty_bitmap_base,
                               bitmap_word);

    spine::sim::SpineDirtyAck ack(
        "dirty-ack", core, config,
        spine::sim::SpineDirtyAckPorts{
            .task_scratch = &scratch,
            .metadata = &metadata,
            .result = &result,
        });
    scheduler.add_component(ack);
    scratch.register_components(scheduler);
    metadata.register_components(scheduler);
    result.register_components(scheduler);
    scheduler.add_component(backend);
    ack.start(expected_generation, candidate);
    scheduler.run_until(
        [&] {
          return ack.done() && scratch.idle() && metadata.idle() &&
                 result.idle();
        },
        10'000);

    require(ack.failed() && ack.counters().status ==
                                static_cast<std::uint32_t>(expected_status) &&
                ack.counters().cleared_sources == 0 &&
                ack.counters().generation_advances == 0 &&
                backend.inspect_payload(16,
                                        config.persistent_dirty_bitmap_base,
                                        16) == bitmap_word &&
                backend.inspect_payload(
                    20,
                    config.metadata_base +
                        layout.dirty_generation_word *
                            spine::sim::kSpineMetadataWordBytes,
                    8) == u64_payload(7) &&
                backend.inspect_payload(21, 81 * 4, 4) ==
                    u32_payload(static_cast<std::uint32_t>(expected_status)) &&
                backend.inspect_payload(21, 83 * 4, 4) == u32_payload(7) &&
                backend.inspect_payload(21, 95 * 4, 4) == u32_payload(1),
            "failed dirty ACK changed owned frontier state");
  };

  const SpineDirtyIdentity exact =
      spine::sim::spine_dirty_identity(7, std::vector<std::uint32_t>{2});
  run_case(6, exact, SpineDirtyStatus::kStaleAck);
  SpineDirtyIdentity malformed = exact;
  ++malformed.hash_sum;
  run_case(7, malformed, SpineDirtyStatus::kMalformedAck);
}

void test_spine_compute_rejects_malformed_source_protocol() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  FixedAxiPort vertex_state(
      "protocol-vertex-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 17, .initiator_id = 817},
      backend);
  FixedAxiPort active_out(
      "protocol-active-out", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 19, .initiator_id = 819},
      backend);
  FixedAxiPort active_bitmap(
      "protocol-active-bitmap", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 22, .initiator_id = 822},
      backend);
  FixedAxiPort result(
      "protocol-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 821},
      backend);
  Fifo<PartConvWord> edge_stream("protocol-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("protocol-value-axis", core, 32);
  SequenceProducer<PartConvWord> producer(
      "malformed-protocol-reader", core, edge_stream,
      {
          PartConvWord{.kind = PartConvWordKind::kSourceRequest, .first = 0},
          PartConvWord{.kind = PartConvWordKind::kSourceCount, .first = 2},
          PartConvWord{.kind = PartConvWordKind::kSourceGeneration, .first = 9},
          PartConvWord{.kind = PartConvWordKind::kSourceRequestsDone},
          PartConvWord{.kind = PartConvWordKind::kDoneAll},
      });
  SequenceConsumer<SourceValueWord> consumer("malformed-protocol-host", core,
                                             value_stream);
  SpineSplitSsspCompute compute(
      "malformed-protocol-compute", core, 64, 0, 4096,
      SpineComputePorts{
          .vertex_state = &vertex_state,
          .active_out = &active_out,
          .active_bitmap = &active_bitmap,
          .result = &result,
      },
      edge_stream, value_stream);
  scheduler.add_component(producer);
  scheduler.add_component(consumer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               value_stream.empty() && vertex_state.idle() &&
               active_out.idle() && active_bitmap.idle() && result.idle();
      },
      100'000);

  require(compute.failed() && consumer.values.size() == 2 &&
              consumer.values[0].kind == SourceValueWord::Kind::kSourceValue &&
              consumer.values[1].kind == SourceValueWord::Kind::kProtocolAck &&
              consumer.values[1].value == static_cast<std::uint32_t>(
                                                spine::sim::
                                                    SpineSourceProtocolStatus::
                                                        kCount) &&
              compute.counters().source_protocol_status ==
                  static_cast<std::uint32_t>(
                      spine::sim::SpineSourceProtocolStatus::kCount),
          "compute accepted a source-count mismatch or returned the wrong ACK");
}

void test_spine_cold_l1_carry_and_reader() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "cold_l1_carry",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  require(!system.failed(), "cold L1 carry vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.target_level == 1 && maintenance.hot_target_level == -1,
          "cold carry selected the wrong binary target");
  require(maintenance.sorted_scan_passes == 19,
          "cold carry changed the HLS family-filter scan count");
  require(maintenance.carry_level_payload_reads == 1 &&
              maintenance.carry_new_batch_reads == 1 &&
              maintenance.carry_new_batch_read_bytes == 16 &&
              maintenance.carry_refill_wait_cycles > 0 &&
              maintenance.carry_max_buffered_heads == 2 &&
              maintenance.carry_merge_inputs == 2 &&
              maintenance.carry_outputs == 2 &&
              maintenance.carry_writer_groups_seen == 2 &&
              maintenance.carry_writer_groups_emitted == 2 &&
              maintenance.carry_writer_groups_cancelled == 0 &&
              maintenance.carry_writer_edge_word_writes == 2 &&
              maintenance.carry_writer_row_word_writes == 1 &&
              maintenance.carry_writer_mask_word_writes == 1 &&
              maintenance.carry_writer_page_base_word_writes == 2 &&
              maintenance.carry_writer_bitmap_page_writes == 1 &&
              maintenance.carry_writer_page_list_word_writes == 1 &&
              maintenance.carry_writer_page_epoch_word_writes == 1 &&
              maintenance.carry_writer_memory_wait_cycles > 0,
          "cold carry merge ledger mismatch");
  std::cout << "EVIDENCE spine_carry_refill cycles="
            << maintenance.end_cycle - maintenance.start_cycle
            << " new_batch_reads=" << maintenance.carry_new_batch_reads
            << " level_reads=" << maintenance.carry_level_payload_reads
            << " refill_wait=" << maintenance.carry_refill_wait_cycles
            << " writer_wait="
            << maintenance.carry_writer_memory_wait_cycles
            << " max_heads=" << maintenance.carry_max_buffered_heads << '\n';
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].size() == 2,
          "cold carry did not retire L0 into L1");
  std::cout << "EVIDENCE spine_carry_reader occupied="
            << system.reader_counters().occupied_levels
            << " emitted=" << system.reader_counters().edges_emitted
            << " epoch_misses="
            << system.reader_counters().graph_index_epoch_misses
            << " index_bytes="
            << system.reader_counters().graph_index_payload_read_bytes
            << " payload_bytes="
            << system.reader_counters().graph_edge_payload_read_bytes << '\n';
  const SpineLevelLayout carried_layout =
      spine_level_layout(SpineL0Config{}, false, 1);
  const auto carried_bitmap = backend.inspect_payload(
      0, carried_layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      32);
  const auto carried_rows = backend.inspect_payload(
      0,
      carried_layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
      8);
  std::cout << "EVIDENCE spine_carry_hbm bitmap0="
            << static_cast<unsigned>(carried_bitmap[0])
            << " row0=" << static_cast<unsigned>(carried_rows[0])
            << " row1=" << static_cast<unsigned>(carried_rows[4]) << '\n';
  require(carried_bitmap[0] == 1 && carried_rows[0] == 0 &&
              carried_rows[4] == 2,
          "carry writer did not persist its packed bitmap/row payload");
  require(system.reader_counters().occupied_levels == 1 &&
              system.reader_counters().edges_emitted == 2,
          "reader did not traverse the carried L1 payload");
  require(
      system.compute().values()[1] == 5 && system.compute().values()[2] == 3,
      "cold carry SSSP result mismatch");
}

void test_spine_carry_kway_refill_pipeline() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 7,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      {.src = 0, .dst = 1, .weight = 5, .diff = 1},
      {.src = 1, .dst = 2, .weight = 5, .diff = 1},
  };
  initial.cold_levels[0][1] = {
      {.src = 0, .dst = 3, .weight = 4, .diff = 1},
      {.src = 2, .dst = 4, .weight = 4, .diff = 1},
  };
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges =
          {
              {.src = 0, .dst = 5, .weight = 3, .diff = 1},
              {.src = 1, .dst = 6, .weight = 3, .diff = 1},
              {.src = 3, .dst = 7, .weight = 3, .diff = 1},
              {.src = 4, .dst = 8, .weight = 3, .diff = 1},
          },
      .case_name = "carry_kway_refill",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 200'000);

  require(!system.failed(), "L2 k-way carry vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  const auto &level = system.level_state().cold_levels[0][2];
  require(maintenance.target_level == 2 &&
              maintenance.carry_new_batch_reads == 4 &&
              maintenance.carry_new_batch_read_bytes == 64 &&
              maintenance.carry_level_payload_reads == 4 &&
              maintenance.carry_level_payload_read_bytes == 32 &&
              maintenance.carry_merge_inputs == 8 &&
              maintenance.carry_outputs == 8 &&
              maintenance.carry_writer_groups_seen == 8 &&
              maintenance.carry_writer_groups_emitted == 8 &&
              maintenance.carry_writer_groups_cancelled == 0 &&
              maintenance.carry_writer_edge_word_writes == 8 &&
              maintenance.carry_writer_row_word_writes == 3 &&
              maintenance.carry_writer_mask_word_writes == 2 &&
              maintenance.carry_writer_page_base_word_writes == 2 &&
              maintenance.carry_writer_bitmap_page_writes == 1 &&
              maintenance.carry_writer_page_list_word_writes == 1 &&
              maintenance.carry_writer_page_epoch_word_writes == 1 &&
              maintenance.carry_writer_memory_wait_cycles > 0 &&
              maintenance.carry_max_buffered_heads == 5 &&
              maintenance.carry_refill_wait_cycles > 0,
          "L2 k-way carry request/refill ledger diverged");
  require(level.size() == 8 && level.front().src == 0 &&
              level.front().dst == 1 && level.back().src == 4 &&
              level.back().dst == 8,
          "L2 k-way carry winner order or output payload diverged");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].empty(),
          "L2 k-way carry did not retire lower levels");
  std::cout << "EVIDENCE spine_carry_kway target=2 inputs="
            << maintenance.carry_merge_inputs
            << " new_batch_reads=" << maintenance.carry_new_batch_reads
            << " level_reads=" << maintenance.carry_level_payload_reads
            << " refill_wait=" << maintenance.carry_refill_wait_cycles
            << " writer_wait="
            << maintenance.carry_writer_memory_wait_cycles
            << " max_heads=" << maintenance.carry_max_buffered_heads << '\n';
}

void test_spine_carry_writer_crosses_page_and_packer_boundaries() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      {.src = 0, .dst = 1, .weight = 5, .diff = 1},
  };
  SpineEdgeSlice batch{
      .vertices = 1'280,
      .edges =
          {
              {.src = 256, .dst = 2, .weight = 4, .diff = 1},
              {.src = 512, .dst = 3, .weight = 4, .diff = 1},
              {.src = 768, .dst = 4, .weight = 4, .diff = 1},
              {.src = 1'024, .dst = 5, .weight = 4, .diff = 1},
          },
      .case_name = "carry_writer_five_pages",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 200'000);

  require(!system.failed(), "five-page carry-writer vertical slice failed");
  const SpineL0Counters &maintenance = system.maintenance_counters();
  require(maintenance.target_level == 1 &&
              maintenance.carry_outputs == 5 &&
              maintenance.carry_writer_groups_seen == 5 &&
              maintenance.carry_writer_groups_emitted == 5 &&
              maintenance.carry_writer_edge_word_writes == 5 &&
              maintenance.carry_writer_row_word_writes == 3 &&
              maintenance.carry_writer_mask_word_writes == 2 &&
              maintenance.carry_writer_page_base_word_writes == 4 &&
              maintenance.carry_writer_bitmap_page_writes == 5 &&
              maintenance.carry_writer_page_list_word_writes == 2 &&
              maintenance.carry_writer_page_epoch_word_writes == 5 &&
              maintenance.graph_index_payload_write_bytes == 232 &&
              maintenance.graph_edge_payload_write_bytes == 40 &&
              maintenance.page_list_payload_write_bytes == 16,
          "five-page carry writer diverged at a packed-word boundary");
  const auto &level = system.level_state().cold_levels[0][1];
  require(level.size() == 5 && level.front().src == 0 &&
              level.back().src == 1'024,
          "five-page carry writer changed sorted output state");

  const SpineMetadataLayout metadata = spine_metadata_layout(SpineL0Config{});
  const std::uint64_t target_slice = 1;
  const auto first_page_word = backend.inspect_payload(
      20,
      (metadata.page_list_base +
       target_slice * metadata.page_list_words_per_slice) *
          spine::sim::kSpineMetadataWordBytes,
      8);
  const auto second_page_word = backend.inspect_payload(
      20,
      (metadata.page_list_base +
       target_slice * metadata.page_list_words_per_slice + 1) *
          spine::sim::kSpineMetadataWordBytes,
      8);
  require(first_page_word == u64_payload(0x0003000200010000ULL) &&
              second_page_word == u64_payload(4),
          "carry writer did not persist packed page IDs across lane 3");
  std::cout << "EVIDENCE spine_carry_writer_pages=5 row_words="
            << maintenance.carry_writer_row_word_writes
            << " mask_words=" << maintenance.carry_writer_mask_word_writes
            << " page_base_words="
            << maintenance.carry_writer_page_base_word_writes
            << " page_list_words="
            << maintenance.carry_writer_page_list_word_writes << '\n';
}

void test_spine_independent_hot_and_cold_targets() {
  require(spine_hot_shard(17) == 5,
          "C++ hot hash diverges from the stable host/HLS hash");
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0Config config;
  config.hot_vertices = {17};
  SpineL0State initial;
  initial.hot_vertices.insert(17);
  initial.hot_enabled = true;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 7, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges =
          {
              SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1},
              SpineEdgeRecord{.src = 0, .dst = 17, .weight = 2, .diff = 1},
          },
      .case_name = "independent_hot_cold_targets",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, std::move(config), std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 150'000);

  require(!system.failed(), "mixed hot/cold vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.hot_enabled && maintenance.target_level == 1 &&
              maintenance.hot_target_level == 0,
          "cold and hot targets were not selected independently");
  require(maintenance.cold_input_edges == 1 &&
              maintenance.hot_input_edges == 1 &&
              maintenance.sorted_scan_passes == 36,
          "mixed hot/cold input scan ledger mismatch");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].size() == 2 &&
              system.level_state().hot_levels[5][0].size() == 1,
          "mixed hot/cold payloads reached the wrong level or shard");
  require(system.reader_counters().occupied_levels == 2 &&
              system.reader_counters().cold_edges_emitted == 2 &&
              system.reader_counters().hot_edges_emitted == 1,
          "reader did not combine cold and hot levels");
  require(system.compute().values()[1] == 7 &&
              system.compute().values()[2] == 3 &&
              system.compute().values()[17] == 2,
          "mixed hot/cold SSSP result mismatch");
}

void test_spine_fixed_level_layout_matches_stable_profile() {
  const SpineL0Config config;
  const auto cold_l0 = spine_level_layout(config, false, 0);
  const auto cold_l1 = spine_level_layout(config, false, 1);
  const auto cold_l10 = spine_level_layout(config, false, 10);
  const auto hot_l0 = spine_level_layout(config, true, 0);
  const auto compact_cold_l0 = spine_slice_layout(config, false, 0, 3);
  const auto compact_hot_l0 = spine_slice_layout(config, true, 0, 3);

  require(cold_l0.bitmap_offset_words == 0 && cold_l0.edge_capacity == 131'072,
          "cold L0 layout diverges from the stable HLS profile");
  require(
      cold_l1.bitmap_offset_words == 524'290 && cold_l1.edge_capacity == 16'384,
      "cold L1 layout diverges from the stable HLS profile");
  require(hot_l0.bitmap_offset_words ==
              cold_l10.edge_offset_words + cold_l10.edge_capacity,
          "hot level storage does not begin after the cold level region");
  require(compact_cold_l0.row_capacity_words == 2 &&
              compact_cold_l0.mask_capacity_words == 1 &&
              compact_cold_l0.edge_offset_words ==
                  compact_cold_l0.row_offset_offset_words + 3 &&
              compact_hot_l0.edge_offset_words -
                      compact_hot_l0.bitmap_offset_words ==
                  compact_cold_l0.edge_offset_words -
                      compact_cold_l0.bitmap_offset_words,
          "dynamic L0 layout does not match the row-sized HLS ABI");
  const std::array<std::pair<std::uint64_t, std::uint64_t>, 5>
      compact_word_counts{{{1, 0}, {1, 1}, {2, 1}, {2, 1}, {3, 1}}};
  for (std::uint64_t rows = 0; rows < compact_word_counts.size(); ++rows) {
    const SpineLevelLayout layout =
        spine_slice_layout(config, false, 0, rows);
    require(layout.row_capacity_words == compact_word_counts[rows].first &&
                layout.mask_capacity_words ==
                    compact_word_counts[rows].second &&
                layout.edge_offset_words + layout.edge_capacity <=
                    cold_l1.bitmap_offset_words,
            "dynamic L0 boundary layout escaped its fixed storage envelope");
  }
  SpineL0Config invalid_page = config;
  invalid_page.page_vertices = 128;
  bool invalid_page_rejected = false;
  try {
    (void)spine_level_layout(invalid_page, false, 0);
  } catch (const std::invalid_argument &) {
    invalid_page_rejected = true;
  }
  require(invalid_page_rejected,
          "fixed four-word bitmap accepted a non-256-vertex page");

  const SpineEdgeRecord edge{
      .src = 9, .dst = 0x12345678U, .weight = 0xabcdU, .diff = -7};
  const std::vector<std::uint8_t> payload = encode_spine_level_edge(edge);
  require(
      payload.size() == 8 && decode_spine_level_edge(payload, edge.src) == edge,
      "64-bit HLS CSR level payload does not round-trip");
  const std::vector<std::uint8_t> sort_payload = encode_spine_sort_edge(edge);
  require(
      sort_payload.size() == 16 && decode_spine_sort_edge(sort_payload) == edge,
      "128-bit HLS sorted edge payload does not round-trip");
}

void test_spine_carry_drops_signed_diff_cancellation() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = -1}},
      .case_name = "signed_diff_cancellation",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  require(!system.failed(), "signed-diff cancellation vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.target_level == 1 &&
              maintenance.carry_merge_inputs == 2 &&
              maintenance.carry_outputs == 0 &&
              maintenance.carry_writer_groups_seen == 1 &&
              maintenance.carry_writer_groups_emitted == 0 &&
              maintenance.carry_writer_groups_cancelled == 1 &&
              maintenance.carry_writer_edge_word_writes == 0 &&
              maintenance.carry_writer_row_word_writes == 1 &&
              maintenance.carry_writer_mask_word_writes == 0 &&
              maintenance.carry_writer_page_base_word_writes == 1 &&
              maintenance.carry_writer_bitmap_page_writes == 0 &&
              maintenance.carry_writer_page_list_word_writes == 0 &&
              maintenance.carry_writer_page_epoch_word_writes == 0 &&
              maintenance.graph_index_payload_write_bytes == 16,
          "carry did not coalesce insertion and deletion to an empty payload");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].empty(),
          "cancelled edge remained resident in a cold level");
  require(system.reader_counters().edges_emitted == 0 &&
              system.compute().next_active().empty(),
          "cancelled edge escaped into the reader/compute path");
}

struct ComputeTileObservation {
  SpineComputeCounters counters;
  FifoStats edge_stream;
  std::uint64_t cycles{};
  std::size_t next_active{};
  std::uint32_t duplicate_value{SpineSplitSsspCompute::kInfinity};
  std::vector<std::uint8_t> first_active_payload;
  bool distances_match{};
  bool failed{};
};

ComputeTileObservation run_compute_tile(std::size_t edge_count,
                                        bool duplicate_dst = false,
                                        std::size_t memory_request_window =
                                            SpineSplitSsspCompute::
                                                kDefaultMemoryRequestWindow,
                                        bool split_extreme_destinations = false,
                                        SpineOnChipMemoryProfile on_chip = {},
                                        std::size_t second_tile_edges = 0,
                                        std::uint64_t memory_latency_cycles = 3) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = memory_latency_cycles,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineAxiInterfaceProfile axi_profile;
  FixedAxiPort vertex_state(
      "boundary-vertex-state", core,
      axi_profile.port_config(SpineAxiPortKind::kVertexState, 32, 17, 217),
      backend);
  FixedAxiPort active_out(
      "boundary-active-out", core,
      axi_profile.port_config(SpineAxiPortKind::kActiveOut, 32, 19, 219),
      backend);
  FixedAxiPort active_bitmap(
      "boundary-active-bitmap", core,
      axi_profile.port_config(SpineAxiPortKind::kActiveBitmap, 32, 22, 222),
      backend);
  FixedAxiPort result(
      "boundary-result", core,
      axi_profile.port_config(SpineAxiPortKind::kComputeResult, 32, 21, 221),
      backend);
  Fifo<PartConvWord> edge_stream("boundary-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("boundary-value-axis", core, 32);
  const std::size_t vertices = second_tile_edges == 0 ? 65'536 : 131'072;
  std::vector<PartConvWord> words;
  words.reserve(edge_count + second_tile_edges + 5);
  words.push_back(
      PartConvWord{.kind = PartConvWordKind::kTileBegin, .first = 0});
  const auto destination_for = [&](std::size_t index) {
    if (duplicate_dst) {
      return 1U;
    }
    if (split_extreme_destinations && index >= edge_count / 2) {
      return static_cast<std::uint32_t>(
          65'535 - (edge_count - index));
    }
    return static_cast<std::uint32_t>(index);
  };
  for (std::size_t index = 0; index < edge_count; ++index) {
    words.push_back(PartConvWord{
        .kind = PartConvWordKind::kEdge,
        .first = destination_for(index),
        .second =
            duplicate_dst ? static_cast<std::uint32_t>(5 - 2 * index) : 1U,
    });
  }
  words.push_back(PartConvWord{
      .kind = PartConvWordKind::kTileEnd, .first = 0, .second = 65'536});
  if (second_tile_edges != 0) {
    words.push_back(PartConvWord{
        .kind = PartConvWordKind::kTileBegin, .first = 65'536});
    for (std::size_t index = 0; index < second_tile_edges; ++index) {
      words.push_back(PartConvWord{
          .kind = PartConvWordKind::kEdge,
          .first = static_cast<std::uint32_t>(65'536 + index),
          .second = 1,
      });
    }
    words.push_back(PartConvWord{.kind = PartConvWordKind::kTileEnd,
                                 .first = 65'536,
                                 .second = 65'536});
  }
  words.push_back(PartConvWord{.kind = PartConvWordKind::kDoneAll});
  SequenceProducer<PartConvWord> producer("boundary-reader", core, edge_stream,
                                          std::move(words));
  SpineSplitSsspCompute compute("boundary-compute", core, vertices,
                                static_cast<std::uint32_t>(vertices - 1), 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &result,
                                },
                                edge_stream, value_stream,
                                memory_request_window,
                                SpineSplitSsspCompute::
                                    kDefaultWriteOnlyRequestWindow,
                                on_chip);

  scheduler.add_component(producer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               vertex_state.idle() && active_out.idle() &&
               active_bitmap.idle() && result.idle();
      },
      500'000);

  bool distances_match = true;
  if (!duplicate_dst) {
    for (std::size_t index = 0; index < edge_count; ++index) {
      distances_match =
          distances_match && compute.values()[destination_for(index)] == 1;
    }
    for (std::size_t index = 0; index < second_tile_edges; ++index) {
      distances_match =
          distances_match && compute.values()[65'536 + index] == 1;
    }
  }
  return ComputeTileObservation{
      .counters = compute.counters(),
      .edge_stream = edge_stream.stats(),
      .cycles = scheduler.clock(core).completed_cycles,
      .next_active = compute.next_active().size(),
      .duplicate_value = compute.values()[1],
      .first_active_payload = backend.inspect_payload(19, 0, 8),
      .distances_match = distances_match,
      .failed = compute.failed(),
  };
}

void test_spine_cross_tile_write_response_overlap() {
  const ComputeTileObservation observation =
      run_compute_tile(1, false, 7, false, {}, 1, 4'096);
  std::cout << "EVIDENCE spine_cross_tile_overlap cycles="
            << observation.cycles << " overlap_cycles="
            << observation.counters.cross_tile_write_overlap_cycles
            << " max_writes_inflight="
            << observation.counters.max_cross_tile_writes_inflight << '\n';
  require(!observation.failed && observation.distances_match &&
              observation.next_active == 2 &&
              observation.counters.cross_tile_write_overlap_cycles > 0 &&
              observation.counters.max_cross_tile_writes_inflight > 0,
          "compute drained all AXI writes before accepting the next tile");
}

void test_spine_compute_overlaps_independent_store_bundles() {
  const ComputeTileObservation observation =
      run_compute_tile(256, false, 7, true);
  std::cout << "EVIDENCE spine_compute_store_bundle_overlap cycles="
            << observation.cycles << " controller_memory_overlap="
            << observation.counters.controller_memory_overlap_cycles
            << " max_total_inflight="
            << observation.counters.max_memory_requests_inflight
            << " max_vertex_inflight="
            << observation.counters.max_vertex_requests_inflight
            << " max_active_out_inflight="
            << observation.counters.max_active_out_requests_inflight
            << " max_active_ports="
            << observation.counters.max_active_memory_ports
            << " cross_port_overlap="
            << observation.counters.memory_cross_port_overlap_cycles
            << " max_responses_per_cycle="
            << observation.counters.max_memory_responses_completed_per_cycle
            << " multi_port_response_cycles="
            << observation.counters.multi_port_response_cycles << '\n';
  require(!observation.failed && observation.distances_match &&
              observation.next_active == 256 &&
              observation.counters.sparse_store_writes_generated == 256 &&
              observation.counters.active_emit_writes_generated == 256 &&
              observation.counters.controller_memory_overlap_cycles > 0 &&
              observation.counters.max_active_out_requests_inflight > 0 &&
              observation.counters.max_active_memory_ports == 2 &&
              observation.counters.memory_cross_port_overlap_cycles > 0,
          "independent vertex-state and active-output bundles did not overlap");
}

void test_spine_compute_gather_uses_bounded_outstanding_requests() {
  const ComputeTileObservation serial = run_compute_tile(256, false, 1);
  const ComputeTileObservation pipelined = run_compute_tile(256, false, 7);
  std::cout << "EVIDENCE spine_compute_gather_outstanding serial_cycles="
            << serial.cycles << " pipelined_cycles=" << pipelined.cycles
            << " serial_max_inflight="
            << serial.counters.max_vertex_requests_inflight
            << " pipelined_max_inflight="
            << pipelined.counters.max_vertex_requests_inflight
            << " pipelined_window_stalls="
            << pipelined.counters.memory_window_stall_cycles << '\n';
  require(!serial.failed && !pipelined.failed && serial.distances_match &&
              pipelined.distances_match && serial.next_active == 256 &&
              pipelined.next_active == 256,
          "compute gather window changed the SSSP result");
  require(serial.counters.max_vertex_requests_inflight == 1 &&
              pipelined.counters.max_vertex_requests_inflight == 7 &&
              serial.counters.memory_requests_issued ==
                  serial.counters.memory_requests_completed &&
              pipelined.counters.memory_requests_issued ==
                  pipelined.counters.memory_requests_completed,
          "compute gather did not enforce its configured request window");
  require(pipelined.cycles < serial.cycles &&
              pipelined.counters.memory_window_stall_cycles > 0,
          "bounded outstanding gather did not hide memory latency");
}

void test_spine_full_tile_threshold_boundaries() {
  for (const std::size_t edge_count : {4095U, 4096U, 4097U, 4098U}) {
    const ComputeTileObservation observation = run_compute_tile(edge_count);
    std::cout << "EVIDENCE spine_onchip_tile edges=" << edge_count
              << " cycles=" << observation.cycles
              << " clear_words="
              << observation.counters.tile_active_clear_words
              << " tiny_reads=" << observation.counters.tiny_buffer_reads
              << " sparse_scan_words="
              << observation.counters.sparse_store_scan_words
              << " sparse_bit_cycles="
              << observation.counters.sparse_store_bit_cycles
              << " emit_scan_words="
              << observation.counters.active_emit_scan_words
              << " emit_bit_cycles="
              << observation.counters.active_emit_bit_cycles
              << " controller_cycles="
              << observation.counters.on_chip_controller_cycles
              << " sparse_writes="
              << observation.counters.sparse_store_writes_generated
              << " active_writes="
              << observation.counters.active_emit_writes_generated
              << " controller_memory_overlap="
              << observation.counters.controller_memory_overlap_cycles
              << " controller_memory_stalls="
              << observation.counters.controller_memory_stall_cycles
              << " max_responses_per_cycle="
              << observation.counters.max_memory_responses_completed_per_cycle
              << " multi_port_response_cycles="
              << observation.counters.multi_port_response_cycles
              << " full_read_beats="
              << observation.counters.full_tile_read_beats
              << " full_read_words="
              << observation.counters.full_tile_read_words
              << " full_read_wait="
              << observation.counters.full_tile_read_wait_cycles << '\n';
    require(!observation.failed && observation.distances_match &&
                observation.next_active == edge_count,
            "full-tile boundary changed the SSSP result");
    require(observation.counters.processed_edges == edge_count,
            "full-tile boundary lost or duplicated an edge");
    require(observation.counters.tile_active_clear_words == 1024 &&
                observation.counters.tile_active_clear_lane_writes == 65'536 &&
                observation.counters.active_emit_scan_words == 1024 &&
                observation.counters.active_emit_lane_reads == 65'536 &&
                observation.counters.active_emit_lane_writes == 65'536 &&
                observation.counters.tile_active_mark_writes == edge_count &&
                observation.counters.active_emit_writes_generated ==
                    edge_count &&
                observation.counters.max_active_out_requests_inflight <= 4,
            "tile-active BRAM controller ledger diverged from the HLS loops");
    require(observation.counters.tiny_buffer_writes ==
                std::min<std::size_t>(edge_count, 4096),
            "tiny-edge BRAM write ledger crossed the threshold incorrectly");
    if (edge_count <= 4096) {
      require(observation.counters.fast_path_tiles == 1 &&
                  observation.counters.full_path_tiles == 0 &&
                  observation.counters.gathered_vertex_words == edge_count &&
                  observation.counters.swept_vertex_words == 0 &&
                  observation.counters.scattered_vertex_words == edge_count,
              "tiny boundary did not use gather/relax/sparse-store");
      require(observation.counters.vertex_read_bytes == edge_count * 4 &&
                  observation.counters.vertex_write_bytes == edge_count * 4 &&
                  observation.counters.memory_requests_issued ==
                      3 * edge_count + 3 &&
                  observation.counters.memory_requests_completed ==
                      3 * edge_count + 3,
              "tiny boundary vertex-memory bytes mismatch");
      require(observation.counters.tiny_buffer_reads == edge_count * 2 &&
                  observation.counters.sparse_store_scan_words == 1024 &&
                  observation.counters.sparse_store_lane_reads == 65'536 &&
                  observation.counters.sparse_store_bit_cycles ==
                      ((edge_count + 63) / 64) * 64 &&
                  observation.counters.sparse_store_writes_generated ==
                      edge_count &&
                  observation.counters.full_tile_read_beats == 0 &&
                  observation.counters.controller_memory_overlap_cycles > 0,
              "tiny-path BRAM read or sparse-scan ledger mismatch");
    } else {
      require(observation.counters.fast_path_tiles == 0 &&
                  observation.counters.full_path_tiles == 1 &&
                  observation.counters.full_buffer_replay_edges == 4096 &&
                  observation.counters.full_overflow_edges == 1 &&
                  observation.counters.full_stream_edges == edge_count - 4097,
              "full boundary did not load/replay/stream in HLS order");
      require(observation.counters.gathered_vertex_words == 0 &&
                  observation.counters.swept_vertex_words == 2 * 65'536 &&
                  observation.counters.scattered_vertex_words == 0 &&
                  observation.counters.vertex_read_bytes == 65'536 * 4 &&
                  observation.counters.vertex_write_bytes == 65'536 * 4 &&
                  observation.counters.memory_requests_issued ==
                      edge_count + 5 &&
                  observation.counters.memory_requests_completed ==
                      edge_count + 5,
              "full boundary tile sweep ledger mismatch");
      require(observation.counters.tiny_buffer_reads == 4096 &&
                  observation.counters.sparse_store_scan_words == 0 &&
                  observation.counters.sparse_store_bit_cycles == 0 &&
                  observation.counters.sparse_store_writes_generated == 0 &&
                  observation.counters.full_tile_read_beats == 65'536 &&
                  observation.counters.full_tile_read_words == 65'536 &&
                  observation.counters.full_tile_stream_error_count == 0,
              "dense replay incorrectly executed the sparse-store controller");
    }
  }
}

void test_spine_full_tile_load_replay_backpressures_axis() {
  const ComputeTileObservation observation = run_compute_tile(8192);
  require(!observation.failed && observation.distances_match,
          "large full tile produced an incorrect SSSP result");
  require(observation.counters.full_buffer_replay_edges == 4096 &&
              observation.counters.full_overflow_edges == 1 &&
              observation.counters.full_stream_edges == 4095,
          "large full tile work did not partition at the finite buffer");
  require(observation.edge_stream.max_occupancy == 32 &&
              observation.edge_stream.push_stalls > 0,
          "full-tile load/replay did not backpressure the finite AXIS FIFO");
}

void test_spine_tiny_gather_preserves_duplicate_reads() {
  const ComputeTileObservation observation = run_compute_tile(2, true);
  require(!observation.failed && observation.duplicate_value == 3 &&
              observation.next_active == 1,
          "duplicate-destination tiny relaxation is incorrect");
  require(observation.counters.gathered_vertex_words == 2 &&
              observation.counters.vertex_read_bytes == 8 &&
              observation.counters.tiny_buffer_writes == 2 &&
              observation.counters.tiny_buffer_reads == 4 &&
              observation.counters.scattered_vertex_words == 1 &&
              observation.counters.sparse_store_writes_generated == 1 &&
              observation.counters.active_emit_writes_generated == 1 &&
              observation.counters.vs_bypass_hits == 1 &&
              observation.counters.vs_bypass_misses == 1,
          "tiny gather incorrectly deduplicated repeated destination reads");
  require(observation.first_active_payload ==
              std::vector<std::uint8_t>({3, 0, 0, 0, 1, 0, 0, 0}),
          "active output did not use the HLS (id:32 | value:32) ABI");
}

void test_spine_on_chip_memory_profile_and_access_ledger() {
  SpineOnChipMemoryProfile fast;
  fast.active_bram_read_latency = 1;
  SpineOnChipMemoryProfile slow = fast;
  slow.active_bram_read_latency = 4;
  const ComputeTileObservation fast_observation =
      run_compute_tile(64, false, 7, false, fast);
  const ComputeTileObservation slow_observation =
      run_compute_tile(64, false, 7, false, slow);
  const SpineComputeCounters &counters = fast_observation.counters;
  std::cout << "EVIDENCE spine_onchip_memory fast_cycles="
            << fast_observation.cycles
            << " slow_cycles=" << slow_observation.cycles
            << " tiny_reads=" << counters.tiny_bram_read_requests
            << " vs_reads=" << counters.vs_uram_read_requests
            << " active_reads=" << counters.active_bram_read_requests
            << " bypass_hits=" << counters.vs_bypass_hits
            << " bypass_misses=" << counters.vs_bypass_misses << '\n';
  require(!fast_observation.failed && !slow_observation.failed &&
              fast_observation.distances_match &&
              slow_observation.distances_match &&
              slow_observation.cycles >= fast_observation.cycles + 6'000,
          "active-BRAM latency did not affect the execution-driven schedule");
  require(counters.tiny_bram_write_requests == 64 &&
              counters.tiny_bram_read_requests == 128 &&
              counters.vs_uram_read_requests == 192 &&
              counters.vs_uram_write_requests == 128 &&
              counters.active_bram_read_requests == 2'048 &&
              counters.active_bram_write_requests == 2'112 &&
              counters.vs_bypass_hits == 0 &&
              counters.vs_bypass_misses == 64 &&
              counters.max_tiny_reads_inflight > 1 &&
              counters.max_vs_reads_inflight > 1,
          "physical on-chip access ledger diverged from the HLS loop shape");
}

void test_spine_compute_consumes_vertex_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  FixedAxiPort vertex_state(
      "payload-vertex-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 17, .initiator_id = 317},
      backend);
  FixedAxiPort active_out(
      "payload-active-out", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 19, .initiator_id = 319},
      backend);
  FixedAxiPort active_bitmap(
      "payload-active-bitmap", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 22, .initiator_id = 322},
      backend);
  FixedAxiPort result(
      "payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 321},
      backend);
  Fifo<PartConvWord> edge_stream("payload-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("payload-value-axis", core, 32);
  SequenceProducer<PartConvWord> producer(
      "payload-reader", core, edge_stream,
      {
          {.kind = PartConvWordKind::kTileBegin, .first = 0},
          {.kind = PartConvWordKind::kEdge, .first = 1, .second = 10},
          {.kind = PartConvWordKind::kTileEnd, .first = 0, .second = 4},
          {.kind = PartConvWordKind::kDoneAll},
      });
  SpineSplitSsspCompute compute("payload-compute", core, 4, 0, 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &result,
                                },
                                edge_stream, value_stream);

  // The compute mirror still contains infinity for vertex 1. Only HBM is 7.
  vertex_state.initialize_payload(4, {7, 0, 0, 0});
  scheduler.add_component(producer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               vertex_state.idle() && active_out.idle() &&
               active_bitmap.idle() && result.idle();
      },
      10'000);

  require(!compute.failed() && compute.values()[1] == 7 &&
              compute.next_active().empty(),
          "compute ignored the HBM vertex payload and used its stale mirror");
  require(compute.counters().vertex_payload_read_bytes == 4 &&
              compute.counters().vertex_payload_write_bytes == 0,
          "compute vertex payload ledger does not match the HBM gather");
  require(vertex_state.master().stats().zero_filled_write_bytes == 0 &&
              active_out.master().stats().zero_filled_write_bytes == 0 &&
              active_bitmap.master().stats().zero_filled_write_bytes == 0 &&
              result.master().stats().zero_filled_write_bytes == 0,
          "migrated compute path issued an implicit zero-filled write");
}

void test_spine_full_tile_consumes_streamed_vertex_payload() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineAxiInterfaceProfile profile;
  FixedAxiPort vertex_state(
      "full-payload-vertex-state", core,
      profile.port_config(SpineAxiPortKind::kVertexState, 32, 17, 417),
      backend);
  FixedAxiPort active_out(
      "full-payload-active-out", core,
      profile.port_config(SpineAxiPortKind::kActiveOut, 32, 19, 419),
      backend);
  FixedAxiPort active_bitmap(
      "full-payload-active-bitmap", core,
      profile.port_config(SpineAxiPortKind::kActiveBitmap, 32, 22, 422),
      backend);
  FixedAxiPort result(
      "full-payload-result", core,
      profile.port_config(SpineAxiPortKind::kComputeResult, 32, 21, 421),
      backend);
  Fifo<PartConvWord> edge_stream("full-payload-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("full-payload-value-axis", core, 32);
  SequenceProducer<PartConvWord> producer(
      "full-payload-reader", core, edge_stream,
      {
          {.kind = PartConvWordKind::kTileBegin, .first = 0, .second = 1},
          {.kind = PartConvWordKind::kEdge, .first = 1, .second = 10},
          {.kind = PartConvWordKind::kTileEnd, .first = 0, .second = 4},
          {.kind = PartConvWordKind::kDoneAll},
      });
  SpineSplitSsspCompute compute(
      "full-payload-compute", core, 4, 0, 4096,
      SpineComputePorts{
          .vertex_state = &vertex_state,
          .active_out = &active_out,
          .active_bitmap = &active_bitmap,
          .result = &result,
      },
      edge_stream, value_stream);

  vertex_state.initialize_payload(4, {7, 0, 0, 0});
  scheduler.add_component(producer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               vertex_state.idle() && active_out.idle() &&
               active_bitmap.idle() && result.idle();
      },
      20'000);

  const SpineComputeCounters &counters = compute.counters();
  std::cout << "EVIDENCE spine_full_tile_stream_payload final_vertex="
            << compute.values()[1]
            << " active_vertices=" << compute.next_active().size()
            << " read_beats=" << counters.full_tile_read_beats
            << " read_words=" << counters.full_tile_read_words
            << " payload_bytes=" << counters.vertex_payload_read_bytes
            << " stream_errors=" << counters.full_tile_stream_error_count
            << '\n';
  require(!compute.failed() && compute.values()[1] == 7 &&
              compute.next_active().empty(),
          "full tile ignored streamed HBM payload and used its local mirror");
  require(counters.full_tile_read_beats == 4 &&
              counters.full_tile_read_words == 4 &&
              counters.full_tile_stream_error_count == 0 &&
              counters.vertex_payload_read_bytes == 16,
          "full-tile streamed payload ledger does not close");
}

void test_spine_reader_consumes_graph_edge_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "reader-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(400 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "reader-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 416},
      backend);
  FixedAxiPort metadata(
      "reader-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 420},
      backend);
  FixedAxiPort result(
      "reader-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 421},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice batch{
      .vertices = 512,
      .edges =
          {
              SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1},
              SpineEdgeRecord{.src = 130, .dst = 2, .weight = 7, .diff = 1},
              SpineEdgeRecord{.src = 256, .dst = 3, .weight = 9, .diff = 1},
          },
      .case_name = "reader_graph_payload_antibypass",
  };
  SpineL0State state;
  const SpineL0Config config;
  SpineL0Maintenance maintenance("reader-payload-maintenance", core, config,
                                 std::move(batch), ports, state);
  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      50'000);

  require(!maintenance.failed(), "reader payload setup maintenance failed");
  require(maintenance.counters().l0_writer_groups_seen == 3 &&
              maintenance.counters().l0_writer_groups_emitted == 3 &&
              maintenance.counters().l0_writer_row_word_writes == 2 &&
              maintenance.counters().l0_writer_mask_word_writes == 1 &&
              maintenance.counters().l0_writer_page_base_word_writes == 2 &&
              maintenance.counters().l0_writer_bitmap_page_writes == 2 &&
              maintenance.counters().l0_writer_page_list_word_writes == 1 &&
              maintenance.counters().l0_writer_page_epoch_word_writes == 2 &&
              maintenance.counters().l0_writer_validation_failures == 0,
          "multi-page L0 online writer did not flush each finite packer");
  require(state.cold_levels[0][0].size() == 3 &&
              state.cold_levels[0][0][0].dst == 1 &&
              state.cold_levels[0][0][0].weight == 5,
          "reader payload anti-bypass setup changed logical level state");

  const auto set_device_dirty_source = [&](std::uint32_t source) {
    const auto meta = spine::sim::spine_metadata_layout(config);
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_count_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(1));
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_hash_sum_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(spine::sim::spine_dirty_hash_sum_term(source)));
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_hash_xor_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(spine::sim::spine_dirty_hash_xor_term(source)));
    std::vector<std::uint8_t> list_word(spine::sim::kSpineSortWordBytes, 0);
    for (std::size_t byte = 0; byte < sizeof(source); ++byte) {
      list_word[byte] =
          static_cast<std::uint8_t>((source >> (byte * 8)) & 0xffU);
    }
    sorted.initialize_payload(config.persistent_dirty_list_base, list_word);
  };
  set_device_dirty_source(0);

  const SpineLevelLayout layout = spine_slice_layout(config, false, 0, 3);
  const SpineLevelLayout fixed_l0 = spine_level_layout(config, false, 0);
  require(layout.edge_offset_words != fixed_l0.edge_offset_words &&
              backend.inspect_payload(
                  20, 6 * spine::sim::kSpineMetadataWordBytes,
                  spine::sim::kSpineMetadataWordBytes) ==
                  u64_payload(layout.edge_offset_words) &&
              backend.inspect_payload(
                  0,
                  fixed_l0.edge_offset_words *
                      spine::sim::kSpineGraphWordBytes,
                  spine::sim::kSpineGraphWordBytes) ==
                  std::vector<std::uint8_t>(
                      spine::sim::kSpineGraphWordBytes, 0),
          "maintenance published or populated the old fixed-capacity L0 "
          "edge offset");
  require(backend.inspect_payload(
              0, layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
              spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}),
          "maintenance bitmap payload does not match the HLS index layout");
  require(
      backend.inspect_payload(
          0, layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
          spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({0, 0, 0, 0, 2, 0, 0, 0}),
      "maintenance page-base payload does not match the HLS index layout");
  require(backend.inspect_payload(0,
                                  (layout.bitmap_offset_words + 2) *
                                      spine::sim::kSpineGraphWordBytes,
                                  spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({4, 0, 0, 0, 0, 0, 0, 0}),
          "maintenance bitmap rank word does not contain source 130");
  require(
      backend.inspect_payload(
          0, layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
          spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({0, 0, 0, 0, 1, 0, 0, 0}),
      "maintenance row-offset payload does not match the HLS index layout");
  require(
      backend.inspect_payload(0,
                              (layout.row_offset_offset_words + 1) *
                                  spine::sim::kSpineGraphWordBytes,
                              spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({2, 0, 0, 0, 3, 0, 0, 0}),
      "maintenance terminal row offset does not match the HLS index layout");
  require(backend.inspect_payload(
              0, layout.mask_offset_words * spine::sim::kSpineGraphWordBytes,
              spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({1, 0, 1, 0, 1, 0, 0, 0}),
          "maintenance row partition mask does not match the HLS index layout");
  graph_ports[0]->initialize_payload(
      layout.edge_offset_words * spine::sim::kSpineGraphWordBytes,
      encode_spine_level_edge(
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 2, .diff = 1}));

  FixedAxiPort active_bins(
      "reader-payload-active-bins", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 18, .initiator_id = 418},
      backend);
  Fifo<PartConvWord> edge_stream("reader-payload-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("reader-payload-value-axis", core, 4);
  SpineReaderPorts reader_ports;
  reader_ports.graph = ports.graph;
  reader_ports.task_scratch = &sorted;
  reader_ports.active_bins = &active_bins;
  reader_ports.metadata = &metadata;
  reader_ports.result = &result;
  SpineSplitReader reader("reader-payload-reader", core, maintenance,
                          reader_ports, {0}, edge_stream, value_stream);
  SequenceProducer<SourceValueWord> source_values(
      "reader-payload-source-values", core, value_stream,
      source_protocol_reply(0, 10));
  SequenceConsumer<PartConvWord> edge_words("reader-payload-edge-words", core,
                                            edge_stream);
  scheduler.add_component(reader);
  scheduler.add_component(source_values);
  scheduler.add_component(edge_words);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  active_bins.register_components(scheduler);
  scheduler.run_until(
      [&] {
        return reader.done() && source_values.done() && edge_stream.empty() &&
               value_stream.empty() && active_bins.idle() && metadata.idle() &&
               graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> edges;
  for (const PartConvWord &word : edge_words.values) {
    if (word.kind == PartConvWordKind::kEdge) {
      edges.push_back(word);
    }
  }
  require(!reader.failed(), "reader graph payload anti-bypass path failed");
  require(edges.size() == 1 && edges[0].first == 2 && edges[0].second == 12,
          "reader ignored HBM graph edge payload and used logical state");
  require(reader.counters().graph_edge_payload_read_bytes == 16 &&
              reader.counters().graph_construction_payload_read_bytes == 8 &&
              reader.counters().graph_replay_payload_read_bytes == 8,
          "reader graph edge payload ledger does not close");

  const std::size_t first_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_missing_bitmap(
      "reader-payload-source-values-missing-bitmap", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_missing_bitmap);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_missing_bitmap.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> second_run_edges;
  for (std::size_t index = first_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      second_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && second_run_edges.empty(),
          "reader ignored HBM bitmap payload and emitted a missing row");
  require(reader.counters().graph_index_bitmap_misses == 1 &&
              reader.counters().graph_index_payload_read_bytes == 8 &&
              reader.counters().graph_edge_payload_read_bytes == 0,
          "reader bitmap anti-bypass ledger mismatch");

  const std::size_t second_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}));
  graph_ports[0]->initialize_payload(
      layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 2, 0, 0, 0}));
  SequenceProducer<SourceValueWord> source_values_shifted_page_base(
      "reader-payload-source-values-shifted-page-base", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_shifted_page_base);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_shifted_page_base.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> third_run_edges;
  for (std::size_t index = second_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      third_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && third_run_edges.size() == 1 &&
              third_run_edges[0].first == 2 && third_run_edges[0].second == 17,
          "reader ignored the HBM page-base payload");
  require(reader.counters().graph_index_payload_read_bytes == 32 &&
              reader.counters().graph_edge_payload_read_bytes == 16,
          "reader page-base anti-bypass ledger mismatch");

  const std::size_t third_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({0, 0, 0, 0, 2, 0, 0, 0}));
  graph_ports[0]->initialize_payload(
      layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_empty_row(
      "reader-payload-source-values-empty-row", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_empty_row);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_empty_row.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> fourth_run_edges;
  for (std::size_t index = third_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      fourth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && fourth_run_edges.empty(),
          "reader ignored the HBM row-offset payload");
  require(reader.counters().graph_index_payload_read_bytes == 24 &&
              reader.counters().graph_edge_payload_read_bytes == 0,
          "reader row-offset anti-bypass ledger mismatch");

  const std::size_t fourth_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({0, 0, 0, 0, 1, 0, 0, 0}));
  SequenceProducer<SourceValueWord> source_values_ranked(
      "reader-payload-source-values-ranked", core, value_stream,
      source_protocol_reply(130, 20));
  scheduler.add_component(source_values_ranked);
  set_device_dirty_source(130);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_ranked.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> fifth_run_edges;
  for (std::size_t index = fourth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      fifth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && fifth_run_edges.size() == 1 &&
              fifth_run_edges[0].first == 2 && fifth_run_edges[0].second == 27,
          "reader bitmap rank did not select source 130's row");
  require(reader.counters().graph_index_bitmap_words == 3 &&
              reader.counters().graph_index_payload_read_bytes == 48 &&
              reader.counters().graph_edge_payload_read_bytes == 16,
          "reader bitmap-rank payload ledger mismatch");

  const std::size_t fifth_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_changed_rank(
      "reader-payload-source-values-changed-rank", core, value_stream,
      source_protocol_reply(130, 20));
  scheduler.add_component(source_values_changed_rank);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_changed_rank.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> sixth_run_edges;
  for (std::size_t index = fifth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      sixth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && sixth_run_edges.size() == 1 &&
              sixth_run_edges[0].first == 2 && sixth_run_edges[0].second == 22,
          "reader ignored HBM bitmap-prefix changes when computing rank");

  const auto metadata_layout = spine::sim::spine_metadata_layout(config);
  const std::uint64_t slice0_base = config.metadata_base;
  set_device_dirty_source(0);
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}));

  const std::size_t sixth_run_words = edge_words.values.size();
  metadata.initialize_payload(
      slice0_base + 7 * spine::sim::kSpineMetadataWordBytes, u64_payload(0));
  SequenceProducer<SourceValueWord> source_values_metadata_unoccupied(
      "reader-payload-source-values-metadata-unoccupied", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_metadata_unoccupied);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_metadata_unoccupied.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::size_t seventh_edges = 0;
  for (std::size_t index = sixth_run_words; index < edge_words.values.size();
       ++index) {
    seventh_edges += edge_words.values[index].kind == PartConvWordKind::kEdge;
  }
  require(!reader.failed() && seventh_edges == 0 &&
              reader.counters().occupied_levels == 0 &&
              reader.active_source_ids() == std::vector<std::uint32_t>({0}),
          "reader bypassed dirty-list or occupied metadata payload");

  metadata.initialize_payload(
      slice0_base + 7 * spine::sim::kSpineMetadataWordBytes, u64_payload(1));
  metadata.initialize_payload(
      config.metadata_base +
          metadata_layout.page_epoch_base * spine::sim::kSpineMetadataWordBytes,
      u64_payload(0));
  const std::size_t seventh_run_words = edge_words.values.size();
  SequenceProducer<SourceValueWord> source_values_stale_page(
      "reader-payload-source-values-stale-page", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_stale_page);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_stale_page.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::size_t eighth_edges = 0;
  for (std::size_t index = seventh_run_words; index < edge_words.values.size();
       ++index) {
    eighth_edges += edge_words.values[index].kind == PartConvWordKind::kEdge;
  }
  require(!reader.failed() && eighth_edges == 0 &&
              reader.counters().graph_index_epoch_misses == 1 &&
              reader.counters().graph_index_payload_read_bytes == 0,
          "reader ignored a stale page epoch or issued a gated graph read");

  metadata.initialize_payload(
      config.metadata_base +
          metadata_layout.page_epoch_base * spine::sim::kSpineMetadataWordBytes,
      u64_payload(1));
  metadata.initialize_payload(
      slice0_base + 6 * spine::sim::kSpineMetadataWordBytes,
      u64_payload(layout.edge_offset_words + 1));
  const std::size_t eighth_run_words = edge_words.values.size();
  SequenceProducer<SourceValueWord> source_values_shifted_edge_base(
      "reader-payload-source-values-shifted-edge-base", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_shifted_edge_base);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_shifted_edge_base.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::vector<PartConvWord> ninth_edges;
  for (std::size_t index = eighth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      ninth_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && ninth_edges.size() == 1 &&
              ninth_edges[0].first == 2 && ninth_edges[0].second == 17,
          "reader ignored the HBM level edge-offset metadata");

  const std::size_t ninth_run_words = edge_words.values.size();
  metadata.initialize_payload(
      config.metadata_base + metadata_layout.hot_enabled_word *
                                 spine::sim::kSpineMetadataWordBytes,
      u64_payload(0));
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle();
      },
      50'000);
  require(reader.failed() && reader.counters().range_task_error == 1,
          "reader accepted an invalid metadata control payload");
  require(edge_words.values.size() ==
                  ninth_run_words + spine::sim::kSpineReaderDiagnosticWords +
                      1 &&
              reader.counters().diagnostic_words == 10 &&
              reader.counters().done_words == 1 &&
              reader.counters().done_overflow,
          "reader error path did not emit the complete terminal transcript");
  const PartConvWord &status_word = edge_words.values[ninth_run_words];
  const PartConvWord &done_word = edge_words.values.back();
  require(status_word.kind == PartConvWordKind::kDiagnostic &&
              status_word.first == static_cast<std::uint32_t>(
                                       spine::sim::SpineDiagnosticKind::
                                           kTaskStatus) &&
              ((status_word.second >> 16) & 0xffU) == 1 &&
              done_word.kind == PartConvWordKind::kDoneAll &&
              done_word.second == 1,
          "reader error diagnostics or DONE overflow payload mismatch");
}

void test_spine_target_selector_consumes_metadata_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "target-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(480 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "target-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 496},
      backend);
  FixedAxiPort metadata(
      "target-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 500},
      backend);
  FixedAxiPort result(
      "target-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 501},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0State state;
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 2, .diff = 1}},
      .case_name = "target_metadata_payload_antibypass",
  };
  SpineL0Maintenance maintenance("target-payload-maintenance", core,
                                 SpineL0Config{}, std::move(batch), ports,
                                 state);

  // The constructor mirrors logical state into HBM. Mutating both target
  // fields afterward makes HBM authoritative and intentionally stale relative
  // to the C++ state mirror.
  metadata.initialize_payload(0, u64_payload(0));
  metadata.initialize_payload(7 * spine::sim::kSpineMetadataWordBytes,
                              u64_payload(0));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      100'000);

  const SpineL0Counters &counters = maintenance.counters();
  require(!maintenance.failed() && counters.target_level == 0 &&
              state.cold_levels[0][0].size() == 1 &&
              state.cold_levels[0][0][0].dst == 2,
          "target selector bypassed HBM metadata and used logical level state");
  require(counters.target_selector_invocations == 1 &&
              counters.target_selector_levels_scanned == 11 &&
              counters.target_selector_family_iterations == 176 &&
              counters.target_selector_metadata_reads == 352 &&
              counters.target_selector_responses == 352 &&
              counters.target_selector_payload_read_bytes == 2'816 &&
              counters.target_selector_cycles >= 562 &&
              counters.target_selector_max_inflight > 1 &&
              counters.target_selector_max_inflight <= 16 &&
              counters.target_selector_validation_failures == 0,
          "target selector request/response or synthesis-floor ledger diverged");
  const SpineMaintenanceResult maint_result =
      decode_spine_maintenance_result(backend.inspect_payload(
          21, SpineL0Config{}.result_base,
          spine::sim::kSpineMaintenanceResultBytes));
  require(counters.result_metadata_reads == 16 &&
              counters.result_metadata_responses == 16 &&
              counters.result_metadata_payload_read_bytes == 128 &&
              counters.result_metadata_max_inflight > 1 &&
              counters.result_metadata_max_inflight <= 16 &&
              counters.result_payload_write_bytes == 384 &&
              counters.result_write_responses == 1 &&
              counters.result_validation_failures == 0,
          "maintenance result request/response ledger diverged");
  require(maint_result[SpineMaintenanceResult::kInputEdges] == 1 &&
              maint_result[SpineMaintenanceResult::kOverflow] == 0 &&
              maint_result[SpineMaintenanceResult::kLevels] == 11 &&
              maint_result[SpineMaintenanceResult::kPartitions] == 16 &&
              maint_result[SpineMaintenanceResult::kMaxSort] == 131'072 &&
              maint_result[SpineMaintenanceResult::kTargetLevel] == 0 &&
              maint_result[SpineMaintenanceResult::kPersistedEdges] == 1 &&
              maint_result[SpineMaintenanceResult::kPath] == 2 &&
              maint_result[SpineMaintenanceResult::kNonemptyPartitions] == 1 &&
              maint_result[SpineMaintenanceResult::kPartitionEdgeCountBase] ==
                  1 &&
              maint_result[SpineMaintenanceResult::kEpochPartitionsWritten] ==
                  1 &&
              maint_result[SpineMaintenanceResult::kEpochPagesStamped] == 1 &&
              maint_result[SpineMaintenanceResult::kHotEdges] == 0 &&
              maint_result[SpineMaintenanceResult::kColdEdges] == 1 &&
              maint_result[SpineMaintenanceResult::kLayoutVersion] == 3 &&
              maint_result[SpineMaintenanceResult::kMetadataFormatVersion] ==
                  2 &&
              maint_result[SpineMaintenanceResult::kDirtyStatus] == 0 &&
              maint_result[SpineMaintenanceResult::kDirtyCount] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyGeneration] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyUniqueInputSources] ==
                  1 &&
              maint_result[SpineMaintenanceResult::kDirtyBitmapReads] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyBitmapWrites] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyListAppends] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyGenerationAdvances] ==
                  1,
          "maintenance result payload diverged from the HLS ABI");
  for (std::size_t family = 1; family < 16; ++family) {
    require(maint_result[SpineMaintenanceResult::kPartitionEdgeCountBase +
                         family] == 0,
            "maintenance result reported a false nonempty partition");
  }
  std::cout << "EVIDENCE spine_target_selector target="
            << counters.target_level << " reads="
            << counters.target_selector_metadata_reads << " cycles="
            << counters.target_selector_cycles << " max_inflight="
            << counters.target_selector_max_inflight << " result_reads="
            << counters.result_metadata_reads << " result_max_inflight="
            << counters.result_metadata_max_inflight << '\n';
}

void test_spine_hot_classifier_consumes_bitmap_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 40,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "hot-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(520 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted("hot-payload-sorted", core,
                      FixedAxiPortConfig{.memory_channels = 32,
                                         .channel = 16,
                                         .initiator_id = 536},
                      backend);
  FixedAxiPort metadata("hot-payload-metadata", core,
                        FixedAxiPortConfig{.memory_channels = 32,
                                           .channel = 20,
                                           .initiator_id = 540},
                        backend);
  FixedAxiPort result("hot-payload-result", core,
                      FixedAxiPortConfig{.memory_channels = 32,
                                         .channel = 21,
                                         .initiator_id = 541},
                      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0Config config;
  config.hot_vertices = {17};
  SpineL0State state;
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {},
      .case_name = "hot_bitmap_payload_antibypass",
  };
  for (std::size_t index = 0; index < 16; ++index) {
    batch.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = 17, .weight = 5, .diff = 1});
  }
  for (std::size_t index = 0; index < 16; ++index) {
    batch.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = 18, .weight = 3, .diff = 1});
  }
  SpineL0Maintenance maintenance("hot-payload-maintenance", core, config,
                                 std::move(batch), ports, state);

  // Constructor state marks 17 hot. Make the HBM payload authoritative by
  // changing that bitmap word to mark only 18 hot before execution starts.
  const SpineMetadataLayout layout = spine_metadata_layout(config);
  metadata.initialize_payload(config.metadata_base +
                                  layout.hot_bitmap_base *
                                      spine::sim::kSpineMetadataWordBytes,
                              u64_payload(std::uint64_t{1} << 18));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      150'000);

  const std::size_t hot_family = spine_hot_shard(18);
  const SpineL0Counters &counters = maintenance.counters();
  require(!maintenance.failed() && counters.hot_enabled &&
              counters.cold_input_edges == 16 &&
              counters.hot_input_edges == 16 &&
              state.cold_levels[0][0].size() == 1 &&
              state.cold_levels[0][0][0].dst == 17 &&
              state.hot_levels[hot_family][0].size() == 1 &&
              state.hot_levels[hot_family][0][0].dst == 18,
          "hot classifier bypassed HBM bitmap payload and used C++ state");
  require(counters.metadata_control_reads == 1 &&
              counters.metadata_control_payload_read_bytes == 8 &&
              counters.hot_bitmap_reads == 1'120 &&
              counters.hot_bitmap_scan_reads == 1'120 &&
              counters.hot_bitmap_carry_reads == 0 &&
              counters.hot_bitmap_responses == counters.hot_bitmap_reads &&
              counters.hot_bitmap_payload_read_bytes ==
                  counters.hot_bitmap_reads * 8 &&
              counters.hot_bitmap_scan_wait_cycles > 0 &&
              counters.hot_bitmap_max_inflight == 16 &&
              counters.hot_bitmap_validation_failures == 0,
          "hot-bitmap request/response and backpressure ledger diverged");
  std::cout << "EVIDENCE spine_hot_bitmap reads=" << counters.hot_bitmap_reads
            << " wait_cycles=" << counters.hot_bitmap_scan_wait_cycles
            << " max_inflight=" << counters.hot_bitmap_max_inflight
            << " cold_dst=" << state.cold_levels[0][0][0].dst
            << " hot_dst=" << state.hot_levels[hot_family][0][0].dst << '\n';
}

void test_spine_logical_overflow_writes_complete_result() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "overflow-result-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(560 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "overflow-result-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 576},
      backend);
  FixedAxiPort metadata(
      "overflow-result-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 580},
      backend);
  FixedAxiPort result(
      "overflow-result-output", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 581},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0Config config;
  SpineL0State state;
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "dirty_metadata_overflow_result",
  };
  SpineL0Maintenance maintenance("overflow-result-maintenance", core, config,
                                 std::move(batch), ports, state);
  const SpineMetadataLayout layout = spine_metadata_layout(config);
  metadata.initialize_payload(
      config.metadata_base +
          layout.dirty_count_word * spine::sim::kSpineMetadataWordBytes,
      u64_payload(static_cast<std::uint64_t>(config.max_vertices) + 1));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      20'000);

  const SpineL0Counters &counters = maintenance.counters();
  const SpineMaintenanceResult maint_result =
      decode_spine_maintenance_result(backend.inspect_payload(
          21, config.result_base, spine::sim::kSpineMaintenanceResultBytes));
  require(maintenance.failed() &&
              maintenance.failure() ==
                  "Spine persistent dirty count exceeds MAX_N" &&
              counters.logical_overflow_events == 1 &&
              counters.result_metadata_reads == 0 &&
              counters.result_metadata_responses == 0 &&
              counters.result_payload_write_bytes == 384 &&
              counters.result_write_responses == 1 &&
              counters.result_validation_failures == 0,
          "logical overflow terminated before its result transaction retired");
  require(maint_result[SpineMaintenanceResult::kInputEdges] == 1 &&
              maint_result[SpineMaintenanceResult::kOverflow] == 1 &&
              maint_result[SpineMaintenanceResult::kTargetLevel] == -1 &&
              maint_result[SpineMaintenanceResult::kPersistedEdges] == 0 &&
              maint_result[SpineMaintenanceResult::kPath] == 5 &&
              maint_result[SpineMaintenanceResult::kLayoutVersion] == 3 &&
              maint_result[SpineMaintenanceResult::kMetadataFormatVersion] ==
                  2 &&
              maint_result[SpineMaintenanceResult::kDirtyStatus] == 1 &&
              maint_result[SpineMaintenanceResult::kDirtyCount] ==
                  static_cast<std::int32_t>(config.max_vertices + 1) &&
              maint_result[SpineMaintenanceResult::kDirtyGeneration] == 0 &&
              maint_result[SpineMaintenanceResult::kDirtyGenerationAdvances] ==
                  0,
          "logical overflow result payload diverged from the HLS ABI");
  std::cout << "EVIDENCE spine_overflow_result cycles="
            << counters.end_cycle - counters.start_cycle
            << " payload_bytes=" << counters.result_payload_write_bytes
            << " responses=" << counters.result_write_responses
            << " dirty_count="
            << maint_result[SpineMaintenanceResult::kDirtyCount] << '\n';
}

void test_spine_full_hierarchy_overflow_preserves_dirty_result() {
  SpineL0State state;
  for (std::size_t level = 0; level < 11; ++level) {
    state.cold_levels[0][level] = {
        SpineEdgeRecord{.src = 0,
                        .dst = static_cast<std::uint32_t>(level + 16),
                        .weight = 1,
                        .diff = 1}};
  }
  const MaintenanceOnlyRun run = run_maintenance_only(
      SpineL0Config{}, std::move(state),
      SpineEdgeSlice{
          .vertices = 128,
          .edges = {
              SpineEdgeRecord{.src = 1, .dst = 2, .weight = 3, .diff = 1}},
          .case_name = "full_hierarchy_overflow_result",
      });

  require(run.failed &&
              run.failure ==
                  "Spine cold level hierarchy has no capacity-safe free target" &&
              run.counters.logical_overflow_events == 1 &&
              run.counters.target_selector_levels_scanned == 11 &&
              run.counters.result_metadata_reads == 0 &&
              run.counters.result_payload_write_bytes == 384 &&
              run.counters.result_write_responses == 1,
          "full hierarchy overflow did not retire through the result path");
  require(run.result[SpineMaintenanceResult::kOverflow] == 1 &&
              run.result[SpineMaintenanceResult::kTargetLevel] == -1 &&
              run.result[SpineMaintenanceResult::kPersistedEdges] == 0 &&
              run.result[SpineMaintenanceResult::kPath] == 5 &&
              run.result[SpineMaintenanceResult::kDirtyStatus] == 0 &&
              run.result[SpineMaintenanceResult::kDirtyCount] == 1 &&
              run.result[SpineMaintenanceResult::kDirtyGeneration] == 1 &&
              run.result[SpineMaintenanceResult::kDirtyUniqueInputSources] ==
                  1 &&
              run.result[SpineMaintenanceResult::kDirtyConservativeSources] ==
                  1,
          "full hierarchy overflow discarded successful dirty-frontier state");
  for (std::size_t level = 0; level < 11; ++level) {
    require(run.state.cold_levels[0][level].size() == 1,
            "full hierarchy overflow committed partial logical level state");
  }
  std::cout << "EVIDENCE spine_full_hierarchy_overflow target="
            << run.result[SpineMaintenanceResult::kTargetLevel]
            << " dirty_generation="
            << run.result[SpineMaintenanceResult::kDirtyGeneration]
            << " result_responses=" << run.counters.result_write_responses
            << '\n';
}

void test_spine_l0_epoch_wrap_reads_hbm_and_clears_index() {
  SpineL0Config config;
  config.max_vertices = 512;
  config.max_sort_edges = 16;
  const MaintenanceOnlyRun run = run_maintenance_only(
      config, SpineL0State{},
      SpineEdgeSlice{
          .vertices = 128,
          .edges = {
              SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
          .case_name = "l0_epoch_wrap_hbm",
      },
      [](FixedAxiPort &metadata, SpineL0Ports &ports,
         const SpineL0Config &local_config) {
        const SpineMetadataLayout layout =
            spine_metadata_layout(local_config);
        metadata.initialize_payload(
            local_config.metadata_base +
                layout.slice_epoch_base *
                    spine::sim::kSpineMetadataWordBytes,
            u64_payload(std::numeric_limits<std::uint32_t>::max()));
        ports.graph[0]->initialize_payload(
            7 * spine::sim::kSpineGraphWordBytes,
            u64_payload(std::numeric_limits<std::uint64_t>::max()));
      });

  require(!run.failed && run.counters.slice_epoch_reads == 1 &&
              run.counters.slice_epoch_responses == 1 &&
              run.counters.slice_epoch_payload_read_bytes == 8 &&
              run.counters.slice_epoch_validation_failures == 0,
          "L0 writer did not consume its packed epoch from HBM");
  require(run.counters.epoch_full_clear_fallbacks == 1 &&
              run.counters.epoch_wrap_events == 1 &&
              run.counters.epoch_commit_failures == 0 &&
              run.counters.epoch_clear_parent_writes == 4 &&
              run.counters.epoch_clear_word_writes == 12 &&
              run.counters.epoch_clear_payload_write_bytes == 96 &&
              run.counters.epoch_clear_write_responses == 4 &&
              run.counters.epoch_clear_wait_cycles > 0 &&
              std::all_of(run.graph0_word7.begin(), run.graph0_word7.end(),
                          [](std::uint8_t byte) { return byte == 0; }),
          "L0 epoch wrap did not clear its complete reachable index area");
  require(run.result[SpineMaintenanceResult::kEpochFullClearFallbacks] == 1 &&
              run.result[SpineMaintenanceResult::kEpochWrapEvents] == 1 &&
              run.result[SpineMaintenanceResult::kEpochCommitFailures] == 0 &&
              run.result[SpineMaintenanceResult::kTargetLevel] == 0 &&
              run.result[SpineMaintenanceResult::kOverflow] == 0,
          "L0 epoch-wrap counters did not reach the maintenance result");
  std::cout << "EVIDENCE spine_l0_epoch_wrap clear_words="
            << run.counters.epoch_clear_word_writes
            << " clear_bytes="
            << run.counters.epoch_clear_payload_write_bytes
            << " clear_wait=" << run.counters.epoch_clear_wait_cycles << '\n';
}

void test_spine_carry_epoch_wrap_uses_fixed_target_clear() {
  SpineL0Config config;
  config.max_vertices = 512;
  config.max_sort_edges = 16;
  SpineL0State state;
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 1, .diff = 1}};
  const MaintenanceOnlyRun run = run_maintenance_only(
      config, std::move(state),
      SpineEdgeSlice{
          .vertices = 128,
          .edges = {
              SpineEdgeRecord{.src = 1, .dst = 2, .weight = 2, .diff = 1}},
          .case_name = "carry_epoch_wrap_hbm",
      },
      [](FixedAxiPort &metadata, SpineL0Ports &,
         const SpineL0Config &local_config) {
        const SpineMetadataLayout layout =
            spine_metadata_layout(local_config);
        const std::uint64_t packed =
            (static_cast<std::uint64_t>(
                 std::numeric_limits<std::uint32_t>::max())
             << 32) |
            1U;
        metadata.initialize_payload(
            local_config.metadata_base +
                layout.slice_epoch_base *
                    spine::sim::kSpineMetadataWordBytes,
            u64_payload(packed));
      });

  require(!run.failed && run.counters.target_level == 1 &&
              run.counters.slice_epoch_reads == 1 &&
              run.counters.slice_epoch_responses == 1 &&
              run.counters.epoch_full_clear_fallbacks == 1 &&
              run.counters.epoch_wrap_events == 1,
          "carry writer did not derive its wrapped epoch from HBM");
  require(run.counters.epoch_clear_parent_writes == 4 &&
              run.counters.epoch_clear_word_writes == 13 &&
              run.counters.epoch_clear_payload_write_bytes == 104 &&
              run.counters.epoch_clear_write_responses == 4 &&
              run.counters.epoch_clear_wait_cycles > 0,
          "carry wrap did not clear the fixed target index layout");
  require(run.result[SpineMaintenanceResult::kEpochFullClearFallbacks] == 1 &&
              run.result[SpineMaintenanceResult::kEpochWrapEvents] == 1 &&
              run.result[SpineMaintenanceResult::kTargetLevel] == 1 &&
              run.result[SpineMaintenanceResult::kPath] == 3 &&
              run.result[SpineMaintenanceResult::kOverflow] == 0,
          "carry epoch-wrap result transcript is incomplete");
  std::cout << "EVIDENCE spine_carry_epoch_wrap clear_words="
            << run.counters.epoch_clear_word_writes
            << " clear_bytes="
            << run.counters.epoch_clear_payload_write_bytes
            << " clear_wait=" << run.counters.epoch_clear_wait_cycles << '\n';
}

void test_spine_l0_skips_undersized_empty_targets() {
  SpineL0Config config;
  config.max_sort_edges = 8;
  SpineL0State state;
  state.cold_levels[0][0].reserve(8);
  for (std::uint32_t index = 0; index < 8; ++index) {
    state.cold_levels[0][0].push_back(
        SpineEdgeRecord{.src = index, .dst = index + 1, .weight = 1, .diff = 1});
  }
  SpineEdgeSlice workload{
      .vertices = 16,
      .edges = {
          SpineEdgeRecord{.src = 8, .dst = 9, .weight = 1, .diff = 1},
      },
      .case_name = "l0_capacity_escalation",
  };
  const MaintenanceOnlyRun run = run_maintenance_only(
      config, std::move(state), std::move(workload));

  require(!run.failed && run.counters.target_level == 5 &&
              run.counters.target_selector_capacity_skips == 4 &&
              run.result[SpineMaintenanceResult::kTargetLevel] == 5 &&
              run.result[SpineMaintenanceResult::kPath] == 3 &&
              run.state.cold_levels[0][0].empty() &&
              run.state.cold_levels[0][5].size() == 9,
          "Spine maintenance did not skip undersized empty target levels");
}

void test_spine_capacity_selector_uses_raw_family_input_bound() {
  SpineL0Config config;
  config.max_sort_edges = 8;
  SpineL0State state;
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 1, .diff = 1},
      SpineEdgeRecord{.src = 1, .dst = 2, .weight = 1, .diff = 1},
  };
  SpineEdgeSlice workload{
      .vertices = 16,
      .edges = {
          SpineEdgeRecord{.src = 8, .dst = 9, .weight = 1, .diff = 1},
          SpineEdgeRecord{.src = 8, .dst = 9, .weight = 1, .diff = 1},
          SpineEdgeRecord{.src = 8, .dst = 9, .weight = 1, .diff = 1},
      },
      .case_name = "raw_family_capacity_bound",
  };
  const MaintenanceOnlyRun run = run_maintenance_only(
      config, std::move(state), std::move(workload));

  require(!run.failed && run.counters.target_level == 4 &&
              run.counters.target_selector_capacity_skips == 3 &&
              run.state.cold_levels[0][4].size() == 3,
          "Spine selector did not use the HLS raw-family input bound");
}

void test_spine_resident_snapshot_spans_fixed_levels() {
  SpineL0Config config;
  config.max_sort_edges = 8;
  SpineEdgeSlice snapshot{
      .vertices = 1'024,
      .edges = {},
      .case_name = "resident_multilevel_snapshot",
  };
  snapshot.edges.reserve(600);
  for (std::uint32_t source = 0; source < 600; ++source) {
    snapshot.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = source + 1,
        .weight = 1,
        .diff = 1,
    });
  }

  SpineL0State state = preload_spine_resident_snapshot(snapshot, config);
  require(state.cold_levels[0][0].empty() &&
              state.cold_levels[0][8].size() == 88 &&
              state.cold_levels[0][10].size() == 512,
          "resident bootstrap did not span capacity-bounded fixed levels");
  std::size_t persisted = 0;
  for (std::size_t level = 0; level < config.levels; ++level) {
    const auto &run = state.cold_levels[0][level];
    persisted += run.size();
    require(run.size() <= spine_level_layout(config, false, level).edge_capacity,
            "resident bootstrap exceeded a per-level capacity");
    require(std::is_sorted(
                run.begin(), run.end(),
                [](const SpineEdgeRecord &left, const SpineEdgeRecord &right) {
                  return std::pair(left.src, left.dst) <
                         std::pair(right.src, right.dst);
                }),
            "resident bootstrap emitted an unsorted run");
  }
  require(persisted == snapshot.edges.size(),
          "resident bootstrap lost or duplicated records");

  const MaintenanceOnlyRun update = run_maintenance_only(
      config, std::move(state),
      SpineEdgeSlice{
          .vertices = snapshot.vertices,
          .edges = {SpineEdgeRecord{
              .src = 700, .dst = 701, .weight = 1, .diff = 1}},
          .case_name = "resident_multilevel_update",
      });
  require(!update.failed && update.counters.target_level == 0 &&
              update.state.cold_levels[0][0].size() == 1 &&
              update.state.cold_levels[0][8].size() == 88 &&
              update.state.cold_levels[0][10].size() == 512,
          "resident bootstrap did not preserve L0 for the next micro-batch");
}

void test_spine_resident_snapshot_auto_promotes_hot_destinations() {
  SpineL0Config config;
  config.max_sort_edges = 8;
  SpineEdgeSlice snapshot{
      .vertices = 128,
      .edges = {},
      .case_name = "resident_hot_classification",
  };
  snapshot.edges.reserve(1'200);
  for (std::uint32_t index = 0; index < 1'200; ++index) {
    snapshot.edges.push_back(SpineEdgeRecord{
        .src = index % 128,
        .dst = index % 16,
        .weight = static_cast<std::uint16_t>(index / 128 + 1),
        .diff = 1,
    });
  }

  SpineResidentClassification classification;
  SpineL0State state =
      preload_spine_resident_snapshot(snapshot, config, &classification);
  require(classification.automatic_hot_promotion &&
              !classification.hot_vertices.empty() &&
              classification.top_level_preload &&
              !classification.multilevel_fallback &&
              classification.max_cold_partition_edges <=
                  classification.cold_partition_target &&
              classification.max_hot_shard_edges <=
                  classification.hot_shard_edge_capacity &&
              config.hot_vertices == classification.hot_vertices &&
              state.hot_vertices.size() == classification.hot_vertices.size(),
          "resident preload did not apply the HLS degree-based hot policy");
  std::size_t persisted = 0;
  for (const auto &families : {&state.cold_levels, &state.hot_levels}) {
    for (const auto &levels : *families) {
      for (std::size_t level = 0; level < config.levels; ++level) {
        if (level != config.levels - 1) {
          require(levels[level].empty(),
                  "classified resident graph occupied a non-top level");
        }
        persisted += levels[level].size();
      }
    }
  }
  require(persisted == snapshot.edges.size(),
          "classified resident preload lost physical records");
}

void test_spine_resident_snapshot_rejects_superhub() {
  SpineL0Config config;
  config.max_sort_edges = 8;
  SpineEdgeSlice snapshot{
      .vertices = 1'024,
      .edges = {},
      .case_name = "resident_superhub_overflow",
  };
  snapshot.edges.reserve(513);
  for (std::uint32_t source = 0; source < 513; ++source) {
    snapshot.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 700,
        .weight = 1,
        .diff = 1,
    });
  }
  bool rejected = false;
  try {
    (void)preload_spine_resident_snapshot(snapshot, config);
  } catch (const std::overflow_error &error) {
    rejected = std::string(error.what()) ==
               "Spine resident hot/cold classifier rejects a super-hub";
  }
  require(rejected, "resident bootstrap accepted an unshardable super-hub");
}

void test_spine_capacity_selector_rejects_before_writer() {
  SpineL0Config config;
  config.max_sort_edges = 16;
  SpineL0State state;
  std::uint32_t source = 0;
  for (std::size_t level = 0; level < 10; ++level) {
    const std::size_t count = static_cast<std::size_t>(
        spine_level_layout(config, false, level).edge_capacity);
    auto &run = state.cold_levels[0][level];
    run.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
      run.push_back(SpineEdgeRecord{
          .src = source,
          .dst = source + 1,
          .weight = 1,
          .diff = 1,
      });
      ++source;
    }
  }
  SpineEdgeSlice workload{
      .vertices = 2'048,
      .edges = {},
      .case_name = "capacity_safe_target_overflow",
  };
  for (std::size_t index = 0; index < config.max_sort_edges; ++index) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = source + 1,
        .weight = 1,
        .diff = 1,
    });
    ++source;
  }
  const MaintenanceOnlyRun run = run_maintenance_only(
      config, std::move(state), std::move(workload));

  require(run.failed &&
              run.failure ==
                  "Spine cold level hierarchy has no capacity-safe free target" &&
              run.counters.logical_overflow_events == 1 &&
              run.counters.target_selector_capacity_skips == 1 &&
              run.counters.slice_epoch_reads == 0 &&
              run.counters.slice_epoch_responses == 0,
          "capacity overflow was not rejected before writer launch");
  require(run.counters.epoch_commit_failures == 0 &&
              run.counters.epoch_retire_writes == 0 &&
              run.counters.epoch_retire_write_responses == 0 &&
              run.counters.result_payload_write_bytes == 384 &&
              run.counters.result_write_responses == 1,
          "capacity selector did not retire through the result path");
  require(run.result[SpineMaintenanceResult::kOverflow] == 1 &&
              run.result[SpineMaintenanceResult::kTargetLevel] == -1 &&
              run.result[SpineMaintenanceResult::kEpochCommitFailures] == 0 &&
              run.result[SpineMaintenanceResult::kPath] == 5,
          "capacity-selector failure is absent from the result ABI");
  for (std::size_t level = 0; level < 10; ++level) {
    require(run.state.cold_levels[0][level].size() ==
                spine_level_layout(config, false, level).edge_capacity,
            "capacity selector committed partial logical level state");
  }
  require(run.state.cold_levels[0][10].empty(),
          "capacity selector wrote the undersized empty target");
  std::cout << "EVIDENCE spine_capacity_safe_reject skips="
            << run.counters.target_selector_capacity_skips
            << " writer_epoch_reads=" << run.counters.slice_epoch_reads
            << '\n';
}

void test_spine_maintenance_consumes_sorted_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "sorted-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(500 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "sorted-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 516},
      backend);
  FixedAxiPort metadata(
      "sorted-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 520},
      backend);
  FixedAxiPort result(
      "sorted-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 521},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}},
      .case_name = "sorted_payload_antibypass",
  };
  SpineL0State state;
  SpineL0Maintenance maintenance("sorted-payload-maintenance", core,
                                 SpineL0Config{}, std::move(batch), ports,
                                 state);
  sorted.initialize_payload(
      0, encode_spine_sort_edge(
             SpineEdgeRecord{.src = 0, .dst = 2, .weight = 2, .diff = 1}));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      50'000);

  require(!maintenance.failed(),
          "sorted payload anti-bypass maintenance failed");
  require(state.cold_levels[0][0].size() == 1 &&
              state.cold_levels[0][0][0].dst == 2 &&
              state.cold_levels[0][0][0].weight == 2,
          "maintenance ignored HBM sorted payload and used logical workload");
  const SpineLevelLayout l0_layout =
      spine_slice_layout(SpineL0Config{}, false, 0, 1);
  require(decode_spine_level_edge(
              backend.inspect_payload(
                  0,
                  l0_layout.edge_offset_words *
                      spine::sim::kSpineGraphWordBytes,
                  spine::sim::kSpineGraphWordBytes),
              0) == state.cold_levels[0][0][0] &&
              maintenance.counters().l0_writer_groups_seen == 1 &&
              maintenance.counters().l0_writer_groups_emitted == 1 &&
              maintenance.counters().l0_writer_validation_failures == 0,
          "L0 online writer bypassed the returned sorted-edge payload");
  require(maintenance.counters().sorted_payload_read_bytes ==
                  maintenance.counters().sorted_read_bytes &&
              maintenance.counters().sorted_payload_read_bytes > 0,
          "sorted payload read ledger does not close");
}

void test_spine_carry_merge_consumes_level_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "carry-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(600 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "carry-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 616},
      backend);
  FixedAxiPort metadata(
      "carry-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 620},
      backend);
  FixedAxiPort result(
      "carry-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 621},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0State state;
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 256, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 512,
      .edges = {
          SpineEdgeRecord{.src = 256, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "carry_payload_antibypass",
  };
  SpineL0Maintenance maintenance("carry-payload-maintenance", core,
                                 SpineL0Config{}, std::move(batch), ports,
                                 state);
  const SpineMetadataLayout metadata_layout =
      spine_metadata_layout(SpineL0Config{});
  require(backend.inspect_payload(
              20,
              metadata_layout.page_list_count_base *
                  spine::sim::kSpineMetadataWordBytes,
              8) == u64_payload(1) &&
              backend.inspect_payload(
                  20,
                  metadata_layout.page_list_base *
                      spine::sim::kSpineMetadataWordBytes,
                  8) == u64_payload(1),
          "preloaded level did not initialize page-list metadata");
  const SpineLevelLayout cold_l0 =
      spine_slice_layout(SpineL0Config{}, false, 0, 1);
  graph_ports[0]->initialize_payload(
      cold_l0.edge_offset_words * spine::sim::kSpineGraphWordBytes,
      encode_spine_level_edge(
          SpineEdgeRecord{.src = 0, .dst = 4, .weight = 2, .diff = 1}));
  std::vector<std::uint8_t> cursor_bitmap(4 *
                                          spine::sim::kSpineGraphWordBytes);
  cursor_bitmap[5] = 1U << 4;
  graph_ports[0]->initialize_payload(
      (cold_l0.bitmap_offset_words + 4) *
          spine::sim::kSpineGraphWordBytes,
      cursor_bitmap);

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      100'000);

  require(!maintenance.failed(),
          "carry payload anti-bypass maintenance failed");
  const auto &level = state.cold_levels[0][1];
  require(level.size() == 2 && level[0].dst == 2 && level[0].weight == 3 &&
              level[0].src == 256 && level[1].dst == 4 &&
              level[1].weight == 2 && level[1].src == 300,
          "carry merge ignored HBM cursor/payload and used logical level state");
  require(maintenance.counters().carry_level_payload_reads == 1 &&
              maintenance.counters().carry_level_payload_read_bytes == 8 &&
              maintenance.counters().carry_new_batch_reads == 1 &&
              maintenance.counters().carry_new_batch_read_bytes == 16 &&
              maintenance.counters().carry_cursor_metadata_read_bytes == 96 &&
              maintenance.counters().carry_cursor_page_ids == 1 &&
              maintenance.counters().carry_cursor_pages_visited == 1 &&
              maintenance.counters().carry_cursor_bitmap_words == 4 &&
              maintenance.counters().carry_cursor_bits_inspected == 256 &&
              maintenance.counters().carry_cursor_refill_cycles == 261 &&
              maintenance.counters().carry_cursor_rows_entered == 1 &&
              maintenance.counters().carry_cursor_row_offset_reads == 2 &&
              maintenance.counters().carry_cursor_validation_failures == 0 &&
              maintenance.counters().page_list_payload_write_bytes == 8 &&
              maintenance.counters().page_list_count_write_bytes > 0,
          "carry level payload read ledger does not close");
  const auto count_payload = backend.inspect_payload(
      20,
      metadata_layout.page_list_count_base *
          spine::sim::kSpineMetadataWordBytes,
      8);
  const auto list_payload = backend.inspect_payload(
      20,
      (metadata_layout.page_list_base +
       metadata_layout.page_list_words_per_slice) *
          spine::sim::kSpineMetadataWordBytes,
      8);
  std::cout << "EVIDENCE spine_page_list count_lane4="
            << static_cast<unsigned>(count_payload[4])
            << " first_page=" << static_cast<unsigned>(list_payload[0])
            << '\n';
  require(count_payload == u64_payload(1ULL << 32) &&
              list_payload == u64_payload(1),
          "carry commit did not publish target page-list count and page ID");
  const SpineMaintenanceResult maint_result =
      decode_spine_maintenance_result(backend.inspect_payload(
          21, 0, spine::sim::kSpineMaintenanceResultBytes));
  const std::array<std::uint64_t, 9> expected_carry{
      1,
      0,
      maintenance.counters().carry_cursor_pages_visited,
      maintenance.counters().carry_cursor_bits_inspected,
      maintenance.counters().carry_cursor_rows_entered,
      maintenance.counters().carry_level_payload_reads,
      maintenance.counters().carry_refill_wait_cycles,
      maintenance.counters().carry_merge_inputs,
      maintenance.counters().carry_writer_groups_emitted,
  };
  for (std::size_t counter = 0; counter < expected_carry.size(); ++counter) {
    require(maintenance_result_counter(
                maint_result, SpineMaintenanceResult::kCarryColdBase,
                counter) == expected_carry[counter] &&
                maintenance_result_counter(
                    maint_result, SpineMaintenanceResult::kCarryHotBase,
                    counter) == 0,
            "maintenance result carry counters diverged from execution");
  }
}

void test_spine_carry_rejects_stale_page_epoch() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "carry_stale_page_epoch",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  const SpineMetadataLayout metadata = spine_metadata_layout(SpineL0Config{});
  backend.initialize_payload(
      20, metadata.page_epoch_base * spine::sim::kSpineMetadataWordBytes,
      u64_payload(0));
  system.register_components();
  scheduler.add_component(backend);

  bool rejected = false;
  try {
    scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);
  } catch (const std::logic_error &error) {
    rejected =
        std::string(error.what()) == "Spine carry page epoch/base validation failed";
  }
  require(rejected &&
              system.maintenance_counters().carry_cursor_validation_failures ==
                  1,
          "carry cursor accepted stale HBM page-epoch metadata");
}

void test_spine_hls_metadata_and_active_record_abi() {
  const SpineL0Config config;
  const auto layout = spine::sim::spine_metadata_layout(config);
  require(layout.page_count == 65'536 && layout.slice_count == 32 * 11 &&
              layout.slice_words == 32 * 11 * 8 &&
              layout.active_bin_offset_base == layout.slice_words &&
              layout.active_bin_count_base == layout.slice_words + 16 &&
              layout.dirty_count_word == layout.dirty_base &&
              layout.dirty_hash_xor_word == layout.dirty_base + 3 &&
              layout.dirty_candidate_generation_word ==
                  layout.dirty_base + 4 &&
              layout.dirty_candidate_valid_word == layout.dirty_base + 8 &&
              layout.dirty_host_generation_word == layout.dirty_base + 9 &&
              layout.dirty_host_valid_word == layout.dirty_base + 13 &&
              layout.dirty_last_status_word == layout.dirty_base + 15,
          "Spine metadata layout diverged from the production HLS ABI");

  const std::uint64_t control = spine::sim::spine_metadata_control_word(true);
  require(spine::sim::spine_metadata_control_valid(control) &&
              !spine::sim::spine_metadata_control_valid(control ^ (1ULL << 32)),
          "Spine metadata control validation is not fail closed");

  SpineMaintenanceResult result_codec;
  result_codec.words[SpineMaintenanceResult::kInputEdges] = 17;
  result_codec.words[SpineMaintenanceResult::kTargetLevel] = -1;
  result_codec.words[SpineMaintenanceResult::kDirtyHashSumLow] =
      std::bit_cast<std::int32_t>(0xfedcba98U);
  require(decode_spine_maintenance_result(
              encode_spine_maintenance_result(result_codec))
              .words == result_codec.words,
          "Spine maintenance result codec changed signed 32-bit ABI words");

  spine::sim::SpineActiveRecord record{
      .source = 0x04030201U,
      .source_value = 0x08070605U,
      .hot_shard_mask = 0x5aa5U,
  };
  for (std::size_t level = 0; level < record.level_masks.size(); ++level) {
    record.level_masks[level] = static_cast<std::uint16_t>(0x100U + level);
  }
  const auto encoded = spine::sim::encode_spine_active_record(record);
  require(encoded.size() == spine::sim::kSpineActiveRecordBytes &&
              encoded[0] == 0x01 && encoded[4] == 0x05 && encoded[8] == 0x00 &&
              encoded[9] == 0x01 && encoded[30] == 0xa5 &&
              encoded[31] == 0x5a &&
              spine::sim::decode_spine_active_record(encoded) == record,
          "Spine 256-bit active-record codec diverged from the HLS bit layout");
}

std::vector<std::uint32_t> sorted_vertices(
    std::vector<std::uint32_t> vertices) {
  std::sort(vertices.begin(), vertices.end());
  return vertices;
}

void test_spine_multiround_weighted_sssp_converges() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "weighted_chain_shortcut.slice";
  SpineVerticalSliceSystem system(scheduler, core, backend,
                                  load_spine_edge_slice(fixture), 0);
  system.register_components();
  scheduler.add_component(backend);
  const auto result = system.run_sssp_to_convergence(16, 200'000);

  require(result.converged && !result.failed && result.rounds.size() == 6,
          "weighted SSSP did not converge in the oracle round count");
  require(result.dirty_ack.has_value() && result.dirty_ack->status == 0 &&
              result.dirty_ack->captured ==
                  spine::sim::spine_dirty_identity(
                      1, std::vector<std::uint32_t>{0, 1, 2, 3, 4}) &&
              result.dirty_ack->candidate == result.dirty_ack->captured &&
              result.dirty_ack->result == SpineDirtyIdentity{
                                              .generation = 2,
                                          } &&
              result.dirty_ack->candidate_write_bytes == 40 &&
              result.dirty_ack->metadata_read_bytes == 72 &&
              result.dirty_ack->metadata_write_bytes == 64 &&
              result.dirty_ack->list_read_bytes == 160 &&
              result.dirty_ack->bitmap_read_bytes == 160 &&
              result.dirty_ack->bitmap_write_bytes == 80 &&
              result.dirty_ack->result_write_bytes == 384 &&
              result.dirty_ack->validated_sources == 5 &&
              result.dirty_ack->cleared_sources == 5 &&
              result.dirty_ack->generation_advances == 1,
          "weighted SSSP dirty ACK work ledger does not match HLS");
  const std::vector<std::vector<std::uint32_t>> expected_inputs = {
      {0}, {1, 2, 5}, {1, 3}, {3, 4}, {4, 5}, {5}};
  const std::vector<std::vector<std::uint32_t>> expected_outputs = {
      {1, 2, 5}, {1, 3}, {3, 4}, {4, 5}, {5}, {}};
  const std::vector<std::vector<std::uint32_t>> expected_reader_sources = {
      {0, 1, 2, 3, 4}, {1, 2}, {1, 3}, {3, 4}, {4}, {}};
  const std::vector<std::uint64_t> expected_requests = {5, 0, 0, 0, 0, 0};
  const std::vector<std::uint64_t> expected_edges = {8, 3, 2, 2, 1, 0};
  for (std::size_t round = 0; round < result.rounds.size(); ++round) {
    const auto &evidence = result.rounds[round];
    require(sorted_vertices(evidence.active_in) == expected_inputs[round] &&
                sorted_vertices(evidence.active_out) == expected_outputs[round],
            "weighted SSSP frontier diverged from the round oracle");
    require(sorted_vertices(evidence.reader_sources) ==
                expected_reader_sources[round],
            "weighted SSSP HLS reader-source set mismatch");
    require(evidence.reader.source_requests == expected_requests[round] &&
                evidence.reader.source_responses == expected_requests[round] &&
                evidence.compute.processed_edges == expected_edges[round],
            "weighted SSSP round work ledger mismatch");
    require(evidence.compute.full_path_tiles == 0 &&
                evidence.edge_axis.max_occupancy <= 32 &&
                evidence.end_cycle > evidence.start_cycle,
            "weighted SSSP round violated tile/FIFO/timing invariants");
    require(evidence.reader.metadata_write_bytes == 16 &&
                evidence.reader.result_write_bytes == 64,
            "weighted SSSP reader result side effects do not match HLS");
    if (round != 0) {
      require(evidence.reader.dirty_count == 0 &&
                  evidence.reader.dirty_generation == 2,
              "HOST_ACTIVE round did not observe acknowledged generation");
    }
  }
  require(system.compute().values() ==
              std::vector<std::uint32_t>({0, 3, 2, 7, 8, 10}),
          "weighted SSSP final distances diverge from the dual oracle");
  require(system.maintenance_counters().sorted_scan_passes == 20 &&
              system.level_state().cold_levels[0][0].size() == 8,
          "multi-round SSSP repeated maintenance or mutated graph levels");
}

void test_spine_incremental_update_reuses_persistent_system() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice initial{
      .vertices = 4,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 5, .diff = 1},
              {.src = 0, .dst = 2, .weight = 20, .diff = 1},
              {.src = 1, .dst = 2, .weight = 5, .diff = 1},
              {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          },
      .case_name = "persistent_initial",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, initial, 0);
  system.register_components();
  scheduler.add_component(backend);

  const auto cold = system.run_sssp_to_convergence(16, 200'000);
  require(cold.converged && !cold.failed &&
              system.compute().values() ==
                  std::vector<std::uint32_t>({0, 5, 10, 11}) &&
              cold.dirty_ack.has_value() &&
              cold.dirty_ack->result.generation == 2,
          "initial persistent SSSP run diverged from its oracle");

  SpineEdgeSlice update{
      .vertices = 4,
      .edges = {{.src = 0, .dst = 2, .weight = 2, .diff = 1}},
      .case_name = "persistent_shortcut_update",
  };
  system.restart_incremental_update(std::move(update));
  const auto incremental = system.run_sssp_to_convergence(16, 200'000);

  const auto &level = system.level_state().cold_levels[0][1];
  const auto shortcut = std::find_if(
      level.begin(), level.end(), [](const SpineEdgeRecord &edge) {
        return edge.src == 0 && edge.dst == 2;
      });
  require(incremental.converged && !incremental.failed &&
              system.compute().values() ==
                  std::vector<std::uint32_t>({0, 5, 2, 3}) &&
              system.maintenance_counters().target_level == 1 &&
              system.level_state().cold_levels[0][0].empty() &&
              shortcut != level.end() && shortcut->weight == 2 &&
              incremental.dirty_ack.has_value() &&
              incremental.dirty_ack->captured ==
                  spine::sim::spine_dirty_identity(
                      3, std::vector<std::uint32_t>{0}) &&
              incremental.dirty_ack->result.generation == 4 &&
              incremental.rounds.front().reader_sources ==
                  std::vector<std::uint32_t>{0},
          "persistent incremental batch lost graph, dirty, or SSSP state");
  std::cout << "EVIDENCE spine_incremental_update cold_cycles="
            << cold.end_cycle - cold.start_cycle
            << " update_cycles="
            << incremental.end_cycle - incremental.start_cycle
            << " update_rounds=" << incremental.rounds.size()
            << " target_level=" << system.maintenance_counters().target_level
            << " generation="
            << incremental.dirty_ack->result.generation << '\n';
}

struct SpineFullRebuildObservation {
  std::vector<std::uint32_t> values;
  SpineL0Counters maintenance;
  SpineComputeCounters first_round_compute;
  std::uint64_t fallback_cycles{};
  std::uint64_t backend_requests{};
  std::uint32_t dirty_generation{};
  bool converged{};
  bool failed{};
};

SpineFullRebuildObservation run_spine_full_rebuild_snapshot(
    SpineEdgeSlice snapshot) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice initial{
      .vertices = 4,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 5, .diff = 1},
              {.src = 0, .dst = 2, .weight = 100, .diff = 1},
              {.src = 1, .dst = 2, .weight = 5, .diff = 1},
              {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          },
      .case_name = "full_rebuild_initial",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, initial, 0);
  system.register_components();
  scheduler.add_component(backend);
  const SpineSsspRunResult cold =
      system.run_sssp_to_convergence(16, 300'000);
  require(cold.converged && !cold.failed &&
              system.compute().values() ==
                  std::vector<std::uint32_t>({0, 5, 10, 11}),
          "full-rebuild fixture did not converge before its update");

  const std::uint64_t start = scheduler.clock(core).completed_cycles;
  system.restart_full_rebuild(std::move(snapshot));
  const SpineSsspRunResult fallback =
      system.run_sssp_to_convergence(16, 2'000'000);
  require(!fallback.rounds.empty() && fallback.dirty_ack.has_value(),
          "full rebuild produced no timed round or dirty ACK evidence");
  return SpineFullRebuildObservation{
      .values = system.compute().values(),
      .maintenance = system.maintenance_counters(),
      .first_round_compute = fallback.rounds.front().compute,
      .fallback_cycles = scheduler.clock(core).completed_cycles - start,
      .backend_requests = backend.stats().accepted,
      .dirty_generation = fallback.dirty_ack->result.generation,
      .converged = fallback.converged,
      .failed = fallback.failed,
  };
}

void test_spine_nonmonotonic_update_uses_timed_full_rebuild() {
  SpineEdgeSlice deleted{
      .vertices = 4,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 5, .diff = 1},
              {.src = 0, .dst = 2, .weight = 100, .diff = 1},
              {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          },
      .case_name = "full_rebuild_delete_snapshot",
  };
  const SpineFullRebuildObservation deletion =
      run_spine_full_rebuild_snapshot(std::move(deleted));

  SpineEdgeSlice increased{
      .vertices = 4,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 5, .diff = 1},
              {.src = 0, .dst = 2, .weight = 100, .diff = 1},
              {.src = 1, .dst = 2, .weight = 50, .diff = 1},
              {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          },
      .case_name = "full_rebuild_weight_increase_snapshot",
  };
  const SpineFullRebuildObservation increase =
      run_spine_full_rebuild_snapshot(std::move(increased));

  const SpineMetadataLayout metadata = spine_metadata_layout(SpineL0Config{});
  const std::uint64_t expected_clear_bytes =
      (metadata.slice_words +
       2 * ((metadata.slice_count + 1) / 2)) *
      sizeof(std::uint64_t);
  const auto require_timed_rebuild = [&](const SpineFullRebuildObservation &run,
                                         const std::vector<std::uint32_t> &oracle) {
    require(run.converged && !run.failed && run.values == oracle,
            "non-monotonic full rebuild diverged from its SSSP oracle");
    require(run.maintenance.target_level == 0 &&
                run.maintenance.full_rebuild_clear_requests == 3 &&
                run.maintenance.full_rebuild_clear_bytes ==
                    expected_clear_bytes &&
                run.maintenance.full_rebuild_clear_cycles > 0,
            "full rebuild did not invalidate the persisted hierarchy through "
            "timed metadata writes");
    require(run.first_round_compute.full_recompute_reset_words == 4 &&
                run.first_round_compute.full_recompute_reset_write_bytes == 16 &&
                run.first_round_compute.full_recompute_reset_cycles > 0 &&
                run.first_round_compute.vertex_write_bytes >= 16,
            "full recompute did not reset vertex state through timed AXI writes");
    require(run.fallback_cycles > 0 && run.backend_requests > 0 &&
                run.dirty_generation == 4,
            "full rebuild did not preserve a timed persistent invocation");
  };
  require_timed_rebuild(deletion, {0, 5, 100, 101});
  require_timed_rebuild(increase, {0, 5, 55, 56});

  std::cout << "EVIDENCE spine_nonmonotonic_full_rebuild delete_cycles="
            << deletion.fallback_cycles
            << " increase_cycles=" << increase.fallback_cycles
            << " metadata_clear_bytes="
            << deletion.maintenance.full_rebuild_clear_bytes
            << " vertex_reset_bytes="
            << deletion.first_round_compute.full_recompute_reset_write_bytes
            << '\n';
}

struct SpineMemoryWindowObservation {
  std::uint64_t cycles{};
  std::vector<std::uint32_t> values;
  std::vector<std::uint32_t> next_active;
  SpineL0Counters maintenance;
  SpineReaderCounters reader;
  AxiStats sorted_axi;
  std::uint64_t backend_requests{};
};

SpineMemoryWindowObservation run_spine_memory_window(std::size_t window) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 12,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "weighted_chain_shortcut.slice";
  SpineL0Config config;
  config.memory_request_window = window;
  SpineVerticalSliceSystem system(scheduler, core, backend,
                                  load_spine_edge_slice(fixture), 0, 4096,
                                  config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      1'000'000);
  return SpineMemoryWindowObservation{
      .cycles = scheduler.clock(core).completed_cycles,
      .values = system.compute().values(),
      .next_active = system.compute().next_active(),
      .maintenance = system.maintenance_counters(),
      .reader = system.reader_counters(),
      .sorted_axi = system.axi_stats(SpineAxiPortKind::kSortedEdges),
      .backend_requests = backend.stats().accepted,
  };
}

void test_spine_memory_request_window_hides_latency() {
  const SpineMemoryWindowObservation serialized = run_spine_memory_window(1);
  const SpineMemoryWindowObservation pipelined = run_spine_memory_window(32);

  std::cout << "EVIDENCE spine_memory_window serialized_cycles="
            << serialized.cycles << " pipelined_cycles=" << pipelined.cycles
            << " maintenance_max_inflight="
            << pipelined.maintenance.max_memory_requests_inflight
            << " serialized_max_per_port="
            << serialized.maintenance.max_memory_requests_inflight_per_port
            << " serialized_non_target_max_per_port="
            << serialized.maintenance
                   .max_non_target_memory_requests_inflight_per_port
            << " target_max_inflight="
            << serialized.maintenance.target_selector_max_inflight
            << " serialized_active_ports="
            << serialized.maintenance.max_active_memory_ports
            << " serialized_cross_port_cycles="
            << serialized.maintenance.memory_cross_port_overlap_cycles
            << " serialized_max_issue_per_cycle="
            << serialized.maintenance.max_memory_requests_issued_per_cycle
            << " serialized_max_retire_per_cycle="
            << serialized.maintenance.max_memory_responses_completed_per_cycle
            << " serialized_multi_issue_cycles="
            << serialized.maintenance.multi_port_issue_cycles
            << " serialized_multi_retire_cycles="
            << serialized.maintenance.multi_port_response_cycles
            << " pipelined_max_per_port="
            << pipelined.maintenance.max_memory_requests_inflight_per_port
            << " reader_max_inflight="
            << pipelined.reader.max_memory_requests_inflight
            << " dependency_stalls="
            << pipelined.maintenance.memory_dependency_stall_cycles << '\n';

  require(serialized.values == pipelined.values &&
              serialized.next_active == pipelined.next_active,
          "memory request window changed Spine functional results");
  require(serialized.backend_requests == pipelined.backend_requests &&
              serialized.maintenance.memory_tasks ==
                  pipelined.maintenance.memory_tasks &&
              serialized.reader.graph_read_bytes ==
                  pipelined.reader.graph_read_bytes &&
              serialized.reader.metadata_read_bytes ==
                  pipelined.reader.metadata_read_bytes,
          "memory request window changed the Spine memory work ledger");
  require(serialized.maintenance
                  .max_non_target_memory_requests_inflight_per_port == 1 &&
              serialized.maintenance.target_selector_max_inflight > 1 &&
              serialized.maintenance.target_selector_max_inflight <= 16,
          "default profile violated its loop-specific AXI request windows");
  require(serialized.maintenance.max_active_memory_ports > 1 &&
              serialized.maintenance.memory_cross_port_overlap_cycles > 0,
          "default profile serialized independent HLS m_axi bundles");
  require(serialized.maintenance.max_memory_requests_issued_per_cycle > 1 &&
              serialized.maintenance.multi_port_issue_cycles > 0,
          "maintenance did not issue independent AXI bundles in one cycle");
  require(
      serialized.maintenance.max_memory_responses_completed_per_cycle > 1 &&
          serialized.maintenance.multi_port_response_cycles > 0,
      "maintenance did not retire independent AXI bundles in one cycle");
  require(pipelined.maintenance.max_memory_requests_inflight_per_port > 1,
          "coarse what-if did not overlap same-port maintenance tasks");
  require(serialized.reader.edge_pipeline_max_inflight > 1 &&
              pipelined.reader.edge_pipeline_max_inflight > 1,
          "source-faithful II=1 edge loops did not exercise concurrency");
  require(pipelined.maintenance.memory_requests_issued ==
                  pipelined.maintenance.memory_requests_completed &&
              pipelined.reader.memory_requests_issued ==
                  pipelined.reader.memory_requests_completed,
          "pipelined profile did not retire every issued memory request");
  require(pipelined.cycles < serialized.cycles,
          "pipelined request window did not hide backend latency");
}

void test_spine_axi_interface_profile_matches_hls_rtl() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineEdgeSlice workload{
      .vertices = 2,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 1, .diff = 1}},
      .case_name = "axi_profile",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);

  const auto require_shape = [&](SpineAxiPortKind kind,
                                 std::uint32_t expected_bytes,
                                 std::size_t expected_pending) {
    const auto &config = system.axi_config(kind);
    require(config.data_width_bytes == expected_bytes &&
                config.max_burst_beats == 16 &&
                config.max_pending_requests == expected_pending &&
                config.max_outstanding_bursts == 16 &&
                config.address_accepts_per_cycle == 1 &&
                config.beat_issues_per_cycle == 1 &&
                config.response_beats_per_cycle == 1,
            "Spine AXI interface shape diverged from the accepted HLS RTL");
  };
  require(system.axi_profile().profile_id == "hls_split_9c08763",
          "Spine did not select the source-shaped AXI profile by default");
  require_shape(SpineAxiPortKind::kGraph, 8, 7);
  require_shape(SpineAxiPortKind::kSortedEdges, 16, 7);
  require_shape(SpineAxiPortKind::kActiveBins, 32, 7);
  require_shape(SpineAxiPortKind::kMetadata, 8, 7);
  require_shape(SpineAxiPortKind::kMaintenanceResult, 4, 4);
  require_shape(SpineAxiPortKind::kVertexState, 4, 7);
  require_shape(SpineAxiPortKind::kActiveOut, 8, 4);
  require_shape(SpineAxiPortKind::kActiveBitmap, 8, 7);
  require_shape(SpineAxiPortKind::kComputeResult, 4, 4);

  const SpineAxiInterfaceProfile legacy =
      SpineAxiInterfaceProfile::legacy_uniform64();
  const auto legacy_graph =
      legacy.port_config(SpineAxiPortKind::kGraph, 32, 0, 0);
  const auto legacy_sorted =
      legacy.port_config(SpineAxiPortKind::kSortedEdges, 32, 16, 16);
  require(legacy.profile_id == "legacy_uniform64" &&
              legacy_graph.data_width_bytes == 64 &&
              legacy_sorted.response_beats_per_cycle == 4,
          "legacy uniform-64 AXI profile is not explicit and reproducible");

  const SpineAxiInterfaceProfile candidate =
      SpineAxiInterfaceProfile::candidate10_1e61fc0();
  const auto candidate_graph =
      candidate.port_config(SpineAxiPortKind::kGraph, 32, 0, 0);
  const auto candidate_result = candidate.port_config(
      SpineAxiPortKind::kMaintenanceResult, 32, 21, 21);
  const auto inherited_compute = candidate.port_config(
      SpineAxiPortKind::kVertexState, 32, 17, 117);
  require(candidate.profile_id == "candidate10_gmem_1e61fc0" &&
              candidate_graph.data_width_bytes == 8 &&
              candidate_graph.request_fifo_depth == 32 &&
              candidate_graph.response_fifo_depth == 32 &&
              candidate_graph.max_pending_requests == 70 &&
              candidate_graph.max_outstanding_bursts == 16 &&
              candidate_graph.read_reorder_capacity == 256 &&
              candidate_graph.read_address_pipeline_cycles == 7 &&
              candidate_graph.read_data_pipeline_cycles == 1 &&
              candidate_graph.write_buffer_pipeline_cycles == 0 &&
              candidate_graph.serialize_write_bursts &&
              candidate_graph.write_ingress_fifo_depth == 16 &&
              candidate_graph.write_throttle_fifo_depth == 16 &&
              candidate_graph.write_ingress_pipeline_cycles == 8 &&
              candidate_graph.write_address_after_full_burst_cycles == 2 &&
              candidate_result.data_width_bytes == 8 &&
              candidate_result.max_pending_requests == 67 &&
              inherited_compute.data_width_bytes == 4 &&
              inherited_compute.max_pending_requests == 7 &&
              inherited_compute.read_reorder_capacity == 32 &&
              inherited_compute.read_address_pipeline_cycles == 0 &&
              inherited_compute.write_buffer_pipeline_cycles == 0 &&
              inherited_compute.write_ingress_fifo_depth == 0 &&
              inherited_compute.write_throttle_fifo_depth == 0 &&
              !inherited_compute.serialize_write_bursts,
          "Candidate10 maintenance adapter profile lost frozen RTL parameters");
}

SpineMemoryWindowObservation run_spine_edge_pipeline(std::size_t depth,
                                                     std::size_t capacity) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 24,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 512,
      .edges = {},
      .case_name = "edge_pipeline_256",
  };
  for (std::uint32_t dst = 1; dst <= 256; ++dst) {
    workload.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = dst, .weight = 1, .diff = 1});
  }
  SpineL0Config config;
  config.memory_request_window = 1;
  config.reader_edge_pipeline_depth = depth;
  config.reader_edge_response_capacity = capacity;
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(workload),
                                  0, 4096, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      1'000'000);
  return SpineMemoryWindowObservation{
      .cycles = scheduler.clock(core).completed_cycles,
      .values = system.compute().values(),
      .next_active = system.compute().next_active(),
      .maintenance = system.maintenance_counters(),
      .reader = system.reader_counters(),
      .sorted_axi = system.axi_stats(SpineAxiPortKind::kSortedEdges),
      .backend_requests = backend.stats().accepted,
  };
}

void test_spine_edge_pipeline_is_ordered_bounded_and_latency_hiding() {
  const SpineMemoryWindowObservation serialized = run_spine_edge_pipeline(1, 1);
  const SpineMemoryWindowObservation capacity_two =
      run_spine_edge_pipeline(32, 2);
  const SpineMemoryWindowObservation pipelined =
      run_spine_edge_pipeline(32, 32);

  std::cout << "EVIDENCE spine_edge_pipeline serialized_cycles="
            << serialized.cycles << " capacity2_cycles=" << capacity_two.cycles
            << " pipelined_cycles=" << pipelined.cycles
            << " max_inflight=" << pipelined.reader.edge_pipeline_max_inflight
            << " max_buffered=" << pipelined.reader.edge_pipeline_max_buffered
            << " credit_stalls="
            << pipelined.reader.edge_pipeline_credit_stall_cycles
            << " maintenance_scan_buffer="
            << pipelined.maintenance.max_sorted_scan_buffered_edges
            << " maintenance_reorder_stalls="
            << pipelined.maintenance.sorted_scan_reorder_full_stall_cycles
            << " axi_beat_fifo_stalls="
            << pipelined.sorted_axi.read_beat_queue_stalls << '\n';

  require(serialized.values == capacity_two.values &&
              serialized.values == pipelined.values &&
              serialized.next_active == capacity_two.next_active &&
              serialized.next_active == pipelined.next_active,
          "edge-pipeline credits changed the functional result or order");
  require(serialized.backend_requests == capacity_two.backend_requests &&
              serialized.backend_requests == pipelined.backend_requests &&
              serialized.reader.graph_read_bytes ==
                  pipelined.reader.graph_read_bytes,
          "edge-pipeline credits changed the memory work ledger");
  require(serialized.reader.construction_pipeline_requests == 256 &&
              serialized.reader.construction_pipeline_retires == 256 &&
              serialized.reader.replay_pipeline_requests == 256 &&
              serialized.reader.replay_pipeline_retires == 256 &&
              pipelined.reader.construction_pipeline_requests == 256 &&
              pipelined.reader.construction_pipeline_retires == 256 &&
              pipelined.reader.replay_pipeline_requests == 256 &&
              pipelined.reader.replay_pipeline_retires == 256,
          "edge-pipeline issue/retire ledger did not close");
  require(serialized.reader.edge_pipeline_max_inflight == 1 &&
              capacity_two.reader.edge_pipeline_max_inflight <= 2 &&
              pipelined.reader.edge_pipeline_max_inflight > 2 &&
              pipelined.reader.edge_pipeline_max_inflight <= 32,
          "edge-pipeline request or response capacity was not enforced");
  require(serialized.reader.edge_pipeline_credit_stall_cycles > 0 &&
              capacity_two.reader.edge_pipeline_credit_stall_cycles > 0 &&
              pipelined.cycles < capacity_two.cycles &&
              capacity_two.cycles < serialized.cycles,
          "edge-pipeline credits did not hide backend latency monotonically");
  require(pipelined.maintenance.max_sorted_scan_buffered_edges == 32 &&
              pipelined.maintenance.sorted_scan_reorder_full_stall_cycles > 0 &&
              pipelined.sorted_axi.read_beat_queue_stalls > 0,
          "large maintenance scan bypassed finite beat/reorder backpressure");
}

void test_spine_l0_online_writer_backpressure_is_finite() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 24,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 512,
      .edges = {},
      .case_name = "l0_writer_backpressure_256_rows",
  };
  for (std::uint32_t source = 0; source < 256; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source, .dst = 511, .weight = 1, .diff = 1});
  }
  SpineL0Config config;
  config.maintenance_l0_write_scan_ii = 1;
  SpineVerticalSliceSystem system(scheduler, core, backend,
                                  std::move(workload), 0, 4096, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      2'000'000);

  const SpineL0Counters &maintenance = system.maintenance_counters();
  std::cout << "EVIDENCE spine_l0_writer_backpressure cycles="
            << maintenance.end_cycle - maintenance.start_cycle
            << " groups=" << maintenance.l0_writer_groups_emitted
            << " stalls="
            << maintenance.l0_writer_backpressure_stall_cycles
            << " max_pending=" << maintenance.l0_writer_max_pending_tasks
            << " max_pending_per_port="
            << maintenance.l0_writer_max_pending_tasks_per_port << '\n';
  require(!system.failed() &&
              system.level_state().cold_levels[0][0].size() == 256,
          "finite L0 writer queue changed the persisted graph");
  require(maintenance.l0_writer_groups_seen == 256 &&
              maintenance.l0_writer_groups_emitted == 256 &&
              maintenance.l0_writer_groups_cancelled == 0 &&
              maintenance.l0_writer_edge_word_writes == 256 &&
              maintenance.l0_writer_row_word_writes == 129 &&
              maintenance.l0_writer_mask_word_writes == 64 &&
              maintenance.l0_writer_page_base_word_writes == 2 &&
              maintenance.l0_writer_bitmap_page_writes == 1 &&
              maintenance.l0_writer_page_list_word_writes == 1 &&
              maintenance.l0_writer_page_epoch_word_writes == 1,
          "finite L0 writer queue changed the HLS packer work ledger");
  require(maintenance.l0_writer_backpressure_stall_cycles > 0 &&
              maintenance.l0_writer_max_pending_tasks_per_port <= 32 &&
              maintenance.l0_writer_validation_failures == 0 &&
              maintenance.memory_requests_issued ==
                  maintenance.memory_requests_completed,
          "L0 writer did not propagate finite issue-queue backpressure");
}

void test_spine_candidate10_writer_propagates_finite_queue_backpressure() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 150.0);
  MockMemoryBackend backend("candidate10-writer-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 24,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 4'096,
      .edges = {},
      .case_name = "candidate10_writer_backpressure_4096_rows",
  };
  workload.edges.reserve(workload.vertices);
  for (std::uint32_t source = 0; source < workload.vertices; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = static_cast<std::uint32_t>((source + 1) % workload.vertices),
        .weight = static_cast<std::uint16_t>((source % 16) + 1),
        .diff = 1,
    });
  }
  SpineL0Config config;
  config.maintenance_architecture =
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  SpineVerticalSliceSystem system(
      scheduler, core, backend, std::move(workload), 0, 4'096, config,
      SpineL0State{}, SpineAxiInterfaceProfile::candidate10_1e61fc0());
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      10'000'000);

  const SpineL0Counters &maintenance = system.maintenance_counters();
  const AxiStats maintenance_axi = system.maintenance_axi_stats();
  std::cout << "EVIDENCE spine_candidate10_writer_backpressure cycles="
            << maintenance.end_cycle - maintenance.start_cycle
            << " stalls=" << maintenance.l0_writer_backpressure_stall_cycles
            << " max_pending_per_port="
            << maintenance.l0_writer_max_pending_tasks_per_port << '\n';
  require(!system.failed() &&
              system.level_state().cold_levels[0][0].size() == 4'096,
          "Candidate10 writer backpressure changed the persisted graph");
  require(maintenance.l0_writer_groups_emitted == 4'096 &&
              maintenance.l0_writer_backpressure_stall_cycles > 0 &&
              maintenance.l0_writer_max_pending_tasks_per_port <= 32 &&
              maintenance.l0_writer_validation_failures == 0 &&
              maintenance.memory_requests_issued ==
                  maintenance.memory_requests_completed &&
              maintenance_axi.requests_accepted ==
                  maintenance_axi.requests_completed &&
              maintenance_axi.address_pipeline_stalls > 0 &&
              maintenance_axi.write_burst_serialization_stalls > 0 &&
              maintenance_axi.max_outstanding_bursts <= 16,
          "Candidate10 bucket writer bypassed finite issue-queue backpressure");
  require(maintenance.memory_ledger_closed &&
              maintenance.first_memory_issue_cycle >= maintenance.start_cycle &&
              maintenance.last_memory_issue_cycle >=
                  maintenance.first_memory_issue_cycle &&
              maintenance.last_memory_completion_cycle >=
                  maintenance.last_memory_issue_cycle &&
              maintenance.memory_active_span_cycles ==
                  maintenance.last_memory_completion_cycle -
                      maintenance.first_memory_issue_cycle &&
              maintenance.post_memory_drain_cycles ==
                  maintenance.end_cycle -
                      maintenance.last_memory_completion_cycle,
          "Candidate10 launch/memory/drain timing ledger did not close");
}

void test_spine_edge_pipeline_propagates_axis_backpressure() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 8,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 8'193,
      .edges = {},
      .case_name = "edge_pipeline_axis_backpressure",
  };
  for (std::uint32_t dst = 1; dst <= 8'192; ++dst) {
    workload.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = dst, .weight = 1, .diff = 1});
  }
  SpineL0Config config;
  config.reader_edge_pipeline_depth = 32;
  config.reader_edge_response_capacity = 32;
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(workload),
                                  0, 4096, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      2'000'000);

  const SpineReaderCounters &reader = system.reader_counters();
  const SpineComputeCounters &compute = system.compute_counters();
  std::cout << "EVIDENCE spine_edge_pipeline_backpressure cycles="
            << scheduler.clock(core).completed_cycles
            << " axis_stalls=" << reader.edge_pipeline_axis_stall_cycles
            << " axis_max=" << system.edge_stream_stats().max_occupancy << '\n';
  require(!system.failed() && reader.edges_emitted == 8'192 &&
              reader.construction_pipeline_requests == 8'192 &&
              reader.construction_pipeline_retires == 8'192 &&
              reader.replay_pipeline_requests == 8'192 &&
              reader.replay_pipeline_retires == 8'192,
          "backpressured edge pipeline lost or duplicated work");
  require(reader.edge_pipeline_axis_stall_cycles > 0 &&
              system.edge_stream_stats().max_occupancy == 32 &&
              system.edge_stream_stats().push_stalls > 0,
          "compute pause did not propagate through AXIS to edge retirement");
  require(compute.full_path_tiles == 1 &&
              compute.full_buffer_replay_edges == 4'096 &&
              compute.full_overflow_edges == 1 &&
              compute.full_stream_edges == 4'095,
          "backpressure fixture did not exercise the full-tile transition");
  require(std::all_of(system.compute().values().begin() + 1,
                      system.compute().values().end(),
                      [](std::uint32_t value) { return value == 1; }),
          "backpressured replay changed the final distances");
}

void test_algorithm_policy_rejects_invalid_configuration() {
  bool rejected = false;
  try {
    (void)GraphAlgorithmPolicy(
        AlgorithmPolicyConfig{.vertices = 0, .source = 0});
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "algorithm policy accepted an empty graph");

  rejected = false;
  try {
    (void)GraphAlgorithmPolicy(AlgorithmPolicyConfig{
        .kind = GraphAlgorithmKind::kFullPageRank,
        .vertices = 4,
        .source = 0,
        .damping = 1.0F,
    });
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "algorithm policy accepted invalid PageRank damping");
}

void test_algorithm_policy_profiles_and_update_modes() {
  const GraphAlgorithmPolicy sssp(
      AlgorithmPolicyConfig{.vertices = 8, .source = 2});
  const GraphAlgorithmPolicy full(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = 8,
      .source = 0,
  });
  const GraphAlgorithmPolicy residual(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = 8,
      .source = 0,
  });
  const GraphAlgorithmPolicy cc(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kConnectedComponents,
      .vertices = 8,
      .source = 0,
  });

  const auto sssp_storage = sssp.storage_profile();
  const auto full_storage = full.storage_profile();
  const auto residual_storage = residual.storage_profile();
  const auto cc_storage = cc.storage_profile();
  require(sssp.name() == "weighted_sssp" &&
              sssp_storage.primary_state_arrays == 1 &&
              sssp_storage.auxiliary_state_arrays == 0 &&
              sssp_storage.degree_arrays == 0,
          "weighted SSSP storage profile is not one distance array");
  require(full.name() == "full_pagerank" &&
              full_storage.primary_state_arrays == 2 &&
              full_storage.degree_arrays == 1 &&
              full_storage.double_buffered_primary,
          "full PageRank storage profile does not expose ping-pong ranks");
  require(residual.name() == "thresholded_residual_pagerank" &&
              residual_storage.primary_state_arrays == 1 &&
              residual_storage.auxiliary_state_arrays == 1 &&
              residual_storage.degree_arrays == 1,
          "residual PageRank storage profile does not expose rank and residual");
  require(cc.name() == "connected_components" &&
              cc_storage.primary_state_arrays == 1 &&
              cc_storage.auxiliary_state_arrays == 0 &&
              cc_storage.degree_arrays == 0 &&
              !cc_storage.double_buffered_primary &&
              cc.reduction_identity_word() ==
                  std::numeric_limits<std::uint32_t>::max(),
          "connected-components storage/reduction profile is wrong");
  require(!sssp.operation_profile().timing_characterized &&
              !full.operation_profile().timing_characterized &&
              !residual.operation_profile().timing_characterized &&
              !cc.operation_profile().timing_characterized,
          "an unintegrated algorithm policy claimed characterized timing");

  require(sssp.update_mode(true, false) ==
              AlgorithmUpdateMode::kIncremental &&
              sssp.update_mode(false, true) ==
                  AlgorithmUpdateMode::kFullRecomputeFallback,
          "weighted SSSP update safety modes are wrong");
  require(full.update_mode(true, true) == AlgorithmUpdateMode::kWarmStart &&
              residual.update_mode(true, true) ==
                  AlgorithmUpdateMode::kSignedResidual &&
              cc.update_mode(true, false) ==
                  AlgorithmUpdateMode::kIncremental &&
              cc.update_mode(false, true) ==
                  AlgorithmUpdateMode::kFullRecomputeFallback,
          "PageRank update modes are wrong");
}

void test_connected_components_algorithm_policy_semantics() {
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kConnectedComponents,
      .vertices = 8,
      .source = 0,
  });
  require(policy.initial_state(0).primary == 0 &&
              policy.initial_state(7).primary == 7,
          "connected-components initial labels are not vertex IDs");

  const auto source = policy.prepare_source({.primary = 3}, 99);
  require(source.edge_payload == 3 && !source.primary_changed &&
              policy.map_edge(source.edge_payload, 65535) == 3,
          "connected-components source/map semantics are wrong");
  require(policy.reduce(5, 3) == 3 && policy.reduce(2, 3) == 2,
          "connected-components reduction is not unsigned min");

  const auto improved = policy.apply({.primary = 6}, 3);
  const auto unchanged = policy.apply({.primary = 2}, 3);
  const auto empty = policy.apply({.primary = 6}, std::nullopt);
  require(improved.active && improved.state_after.primary == 3 &&
              !unchanged.active && unchanged.state_after.primary == 2 &&
              !empty.active && empty.state_after.primary == 6,
          "connected-components apply did not enforce strict label decrease");
}

void test_weighted_sssp_algorithm_policy_semantics() {
  const GraphAlgorithmPolicy policy(
      AlgorithmPolicyConfig{.vertices = 4, .source = 0});
  require(policy.initial_state(0).primary == 0 &&
              policy.initial_state(1).primary ==
                  GraphAlgorithmPolicy::kSsspInfinity,
          "weighted SSSP initial state is wrong");

  const auto source = policy.prepare_source({.primary = 5}, 3);
  require(source.edge_payload == 5 && !source.primary_changed &&
              policy.map_edge(source.edge_payload, 7) == 12,
          "weighted SSSP source/map semantics are wrong");
  require(policy.map_edge(GraphAlgorithmPolicy::kSsspInfinity, 1) ==
              GraphAlgorithmPolicy::kSsspInfinity,
          "weighted SSSP infinity did not saturate");
  const std::uint32_t reduced = policy.reduce(15, 12);
  const auto improved = policy.apply({.primary = 20}, reduced);
  const auto unchanged = policy.apply({.primary = 10}, reduced);
  require(improved.active && improved.state_after.primary == 12 &&
              !unchanged.active && unchanged.state_after.primary == 10,
          "weighted SSSP min-reduce/apply semantics are wrong");
}

void test_full_pagerank_algorithm_policy_semantics() {
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = 4,
      .source = 0,
      .damping = 0.85F,
  });
  const std::uint32_t rank_word = GraphAlgorithmPolicy::float_to_word(0.25F);
  const auto source = policy.prepare_source({.primary = rank_word}, 2);
  require(std::fabs(GraphAlgorithmPolicy::word_to_float(source.edge_payload) -
                    0.10625F) < 1.0e-6F,
          "full PageRank source contribution is wrong");
  const auto dangling = policy.prepare_source({.primary = rank_word}, 0);
  require(GraphAlgorithmPolicy::word_to_float(dangling.edge_payload) == 0.0F &&
              GraphAlgorithmPolicy::word_to_float(
                  dangling.dangling_payload) == 0.25F,
          "full PageRank dangling contribution is wrong");

  const auto reduced = policy.reduce(
      GraphAlgorithmPolicy::float_to_word(0.1F),
      GraphAlgorithmPolicy::float_to_word(0.2F));
  const auto applied = policy.apply(
      {.primary = rank_word}, reduced,
      AlgorithmIterationContext{
          .base = policy.initial_base_word(),
          .dangling_share = GraphAlgorithmPolicy::float_to_word(0.01F),
      });
  require(applied.active &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            applied.state_after.primary) -
                        0.3475F) < 1.0e-6F &&
              std::fabs(applied.error - 0.0975F) < 1.0e-6F,
          "full PageRank sum/apply semantics are wrong");
}

void test_residual_pagerank_algorithm_policy_semantics() {
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = 4,
      .source = 0,
      .damping = 0.85F,
      .epsilon = 0.04F,
  });
  const auto source = policy.prepare_source(
      {.primary = GraphAlgorithmPolicy::float_to_word(0.3F),
       .auxiliary = GraphAlgorithmPolicy::float_to_word(-0.1F)},
      2);
  require(source.primary_changed && source.auxiliary_changed &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            source.state_after.primary) -
                        0.2F) < 1.0e-6F &&
              GraphAlgorithmPolicy::word_to_float(
                  source.state_after.auxiliary) == 0.0F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            source.edge_payload) +
                        0.0425F) < 1.0e-6F,
          "residual PageRank signed source-map semantics are wrong");

  const auto applied = policy.apply(
      {.primary = GraphAlgorithmPolicy::float_to_word(0.2F),
       .auxiliary = GraphAlgorithmPolicy::float_to_word(0.01F)},
      GraphAlgorithmPolicy::float_to_word(-0.02F),
      AlgorithmIterationContext{
          .dangling_share = GraphAlgorithmPolicy::float_to_word(-0.005F),
      });
  require(applied.active &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            applied.state_after.auxiliary) +
                        0.015F) < 1.0e-6F &&
              std::fabs(applied.error - 0.015F) < 1.0e-6F,
          "residual PageRank signed reduce/apply semantics are wrong");
}

void test_delta_hls_residual_pagerank_contract() {
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = 4,
      .source = 0,
      .damping = 0.85F,
      .epsilon = 0.04F,
      .residual_contract =
          spine::sim::ResidualPageRankContract::kDeltaHlsSinkFreeLinfWarm,
  });
  require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                        policy.activation_threshold_word()) -
                    0.04F) < 1.0e-7F,
          "Delta.hls residual activation threshold was divided by N");

  const auto source = policy.prepare_source(
      {.primary = GraphAlgorithmPolicy::float_to_word(0.3F),
       .auxiliary = GraphAlgorithmPolicy::float_to_word(-0.1F)},
      0);
  require(GraphAlgorithmPolicy::word_to_float(source.dangling_payload) ==
              0.0F,
          "Delta.hls sink-free contract emitted a dangling contribution");

  const auto applied = policy.apply(
      {.primary = GraphAlgorithmPolicy::float_to_word(0.2F),
       .auxiliary = GraphAlgorithmPolicy::float_to_word(0.03F)},
      std::nullopt,
      AlgorithmIterationContext{
          .dangling_share = GraphAlgorithmPolicy::float_to_word(0.02F),
      });
  require(!applied.active &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            applied.state_after.auxiliary) -
                        0.03F) < 1.0e-7F,
          "Delta.hls sink-free contract consumed dangling mass");
}

void test_algorithm_state_layout_shares_one_hbm_channel() {
  const GraphAlgorithmPolicy sssp(
      AlgorithmPolicyConfig{.vertices = 1'025, .source = 0});
  const GraphAlgorithmPolicy full(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = 1'025,
      .source = 0,
  });
  const GraphAlgorithmPolicy residual(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = 1'025,
      .source = 0,
  });
  const GraphAlgorithmPolicy cc(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kConnectedComponents,
      .vertices = 1'025,
      .source = 0,
  });

  const auto sssp_layout = sssp.state_layout();
  require(sssp_layout.primary_read.base == 0 &&
              sssp_layout.primary_read.bytes == 4'100 &&
              sssp_layout.primary_write.base == 0 &&
              !sssp_layout.primary_ping_pong &&
              !sssp_layout.auxiliary.has_value() &&
              !sssp_layout.degree.has_value() &&
              sssp_layout.total_bytes == 8'192,
          "weighted SSSP state layout is wrong");

  const auto full_layout = full.state_layout();
  require(full_layout.primary_read.base == 0 &&
              full_layout.primary_write.base == 8'192 &&
              full_layout.primary_ping_pong &&
              !full_layout.auxiliary.has_value() &&
              full_layout.degree.has_value() &&
              full_layout.degree->base == 16'384 &&
              full_layout.total_bytes == 24'576,
          "full PageRank state layout is wrong");

  const auto residual_layout = residual.state_layout();
  require(residual_layout.primary_read.base == 0 &&
              residual_layout.primary_write.base == 0 &&
              residual_layout.auxiliary.has_value() &&
              residual_layout.auxiliary->base == 8'192 &&
              residual_layout.degree.has_value() &&
              residual_layout.degree->base == 16'384 &&
              residual_layout.total_bytes == 24'576,
          "residual PageRank state layout is wrong");

  const auto cc_layout = cc.state_layout();
  require(cc_layout.primary_read.base == 0 &&
              cc_layout.primary_read.bytes == 4'100 &&
              cc_layout.primary_write.base == 0 &&
              !cc_layout.primary_ping_pong &&
              !cc_layout.auxiliary.has_value() &&
              !cc_layout.degree.has_value() &&
              cc_layout.total_bytes == 8'192,
          "connected-components state layout is wrong");

  bool rejected = false;
  try {
    (void)sssp.state_layout(0);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected, "algorithm state layout accepted zero alignment");
}

void test_algorithm_pipeline_models_latency_ii_capacity_and_backpressure() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("algorithm", 250.0);
  Fifo<AlgorithmPipelineRequest> source_requests("source-requests", core, 4);
  Fifo<AlgorithmPipelineResponse> source_responses("source-responses", core, 1);
  Fifo<AlgorithmPipelineRequest> edge_requests("edge-requests", core, 2);
  Fifo<AlgorithmPipelineResponse> edge_responses("edge-responses", core, 2);
  Fifo<AlgorithmPipelineRequest> reduce_requests("reduce-requests", core, 2);
  Fifo<AlgorithmPipelineResponse> reduce_responses("reduce-responses", core, 2);
  Fifo<AlgorithmPipelineRequest> apply_requests("apply-requests", core, 2);
  Fifo<AlgorithmPipelineResponse> apply_responses("apply-responses", core, 2);

  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = 4,
      .source = 0,
      .damping = 0.85F,
  });
  AlgorithmPipeline pipeline(
      "algorithm-pipeline", core, policy,
      AlgorithmPipelineConfig{
          .source_map = {.latency_cycles = 3,
                         .initiation_interval = 2,
                         .capacity = 2},
          .edge_map = {.latency_cycles = 2,
                       .initiation_interval = 1,
                       .capacity = 2},
          .reduce = {.latency_cycles = 3,
                     .initiation_interval = 1,
                     .capacity = 2},
          .apply = {.latency_cycles = 4,
                    .initiation_interval = 1,
                    .capacity = 2},
      },
      AlgorithmPipelinePorts{
          .source_requests = &source_requests,
          .source_responses = &source_responses,
          .edge_requests = &edge_requests,
          .edge_responses = &edge_responses,
          .reduce_requests = &reduce_requests,
          .reduce_responses = &reduce_responses,
          .apply_requests = &apply_requests,
          .apply_responses = &apply_responses,
      });

  const auto word = [](float value) {
    return GraphAlgorithmPolicy::float_to_word(value);
  };
  SequenceProducer<AlgorithmPipelineRequest> source_producer(
      "source-producer", core, source_requests,
      {
          {.stage = AlgorithmPipelineStage::kSourceMap,
           .transaction_id = 1,
           .state = {.primary = word(0.25F)},
           .out_degree = 2,
           .source_payload = 0,
           .edge_weight = 0,
           .current = std::nullopt,
           .candidate = 0,
           .reduced = std::nullopt,
           .context = {}},
          {.stage = AlgorithmPipelineStage::kSourceMap,
           .transaction_id = 2,
           .state = {.primary = word(0.5F)},
           .out_degree = 4,
           .source_payload = 0,
           .edge_weight = 0,
           .current = std::nullopt,
           .candidate = 0,
           .reduced = std::nullopt,
           .context = {}},
          {.stage = AlgorithmPipelineStage::kSourceMap,
           .transaction_id = 3,
           .state = {.primary = word(0.75F)},
           .out_degree = 0,
           .source_payload = 0,
           .edge_weight = 0,
           .current = std::nullopt,
           .candidate = 0,
           .reduced = std::nullopt,
           .context = {}},
      });
  SequenceProducer<AlgorithmPipelineRequest> edge_producer(
      "edge-producer", core, edge_requests,
      {{.stage = AlgorithmPipelineStage::kEdgeMap,
        .transaction_id = 4,
        .state = {},
        .out_degree = 0,
        .source_payload = word(0.125F),
        .edge_weight = 7,
        .current = std::nullopt,
        .candidate = 0,
        .reduced = std::nullopt,
        .context = {}}});
  SequenceProducer<AlgorithmPipelineRequest> reduce_producer(
      "reduce-producer", core, reduce_requests,
      {{.stage = AlgorithmPipelineStage::kReduce,
        .transaction_id = 5,
        .state = {},
        .out_degree = 0,
        .source_payload = 0,
        .edge_weight = 0,
        .current = word(0.1F),
        .candidate = word(0.2F),
        .reduced = std::nullopt,
        .context = {}}});
  SequenceProducer<AlgorithmPipelineRequest> apply_producer(
      "apply-producer", core, apply_requests,
      {{.stage = AlgorithmPipelineStage::kApply,
        .transaction_id = 6,
        .state = {.primary = word(0.25F)},
        .out_degree = 0,
        .source_payload = 0,
        .edge_weight = 0,
        .current = std::nullopt,
        .candidate = 0,
        .reduced = word(0.3F),
        .context = {.base = policy.initial_base_word(),
                    .dangling_share = word(0.01F)}}});

  SequenceConsumer<AlgorithmPipelineResponse> source_consumer(
      "source-consumer", core, source_responses, 10);
  SequenceConsumer<AlgorithmPipelineResponse> edge_consumer(
      "edge-consumer", core, edge_responses);
  SequenceConsumer<AlgorithmPipelineResponse> reduce_consumer(
      "reduce-consumer", core, reduce_responses);
  SequenceConsumer<AlgorithmPipelineResponse> apply_consumer(
      "apply-consumer", core, apply_responses);

  scheduler.add_component(source_producer);
  scheduler.add_component(edge_producer);
  scheduler.add_component(reduce_producer);
  scheduler.add_component(apply_producer);
  scheduler.add_component(pipeline);
  scheduler.add_component(source_consumer);
  scheduler.add_component(edge_consumer);
  scheduler.add_component(reduce_consumer);
  scheduler.add_component(apply_consumer);
  scheduler.add_component(source_requests);
  scheduler.add_component(source_responses);
  scheduler.add_component(edge_requests);
  scheduler.add_component(edge_responses);
  scheduler.add_component(reduce_requests);
  scheduler.add_component(reduce_responses);
  scheduler.add_component(apply_requests);
  scheduler.add_component(apply_responses);
  scheduler.run_until(
      [&] {
        return source_producer.done() && edge_producer.done() &&
               reduce_producer.done() && apply_producer.done() &&
               source_consumer.values.size() == 3 &&
               edge_consumer.values.size() == 1 &&
               reduce_consumer.values.size() == 1 &&
               apply_consumer.values.size() == 1 && pipeline.drained();
      },
      1'000);

  require(source_consumer.values[0].transaction_id == 1 &&
              source_consumer.values[1].transaction_id == 2 &&
              source_consumer.values[2].transaction_id == 3,
          "source-map pipeline did not preserve response order");
  require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                        source_consumer.values[0].source.edge_payload) -
                    0.10625F) < 1.0e-6F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            source_consumer.values[1].source.edge_payload) -
                        0.10625F) < 1.0e-6F &&
              GraphAlgorithmPolicy::word_to_float(
                  source_consumer.values[2].source.edge_payload) == 0.0F &&
              GraphAlgorithmPolicy::word_to_float(
                  source_consumer.values[2].source.dangling_payload) == 0.75F,
          "source-map pipeline changed PageRank contributions");
  require(GraphAlgorithmPolicy::word_to_float(
              edge_consumer.values[0].mapped) == 0.125F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            reduce_consumer.values[0].reduced) -
                        0.3F) < 1.0e-6F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            apply_consumer.values[0]
                                .applied.state_after.primary) -
                        0.3475F) < 1.0e-6F,
          "independent algorithm pipeline stages returned wrong values");

  const auto &counters = pipeline.counters();
  require(counters.source_map.accepted == 3 &&
              counters.source_map.completed == 3 &&
              counters.source_map.initiation_interval_stalls > 0 &&
              counters.source_map.capacity_stalls > 0 &&
              counters.source_map.output_backpressure_stalls > 0 &&
              counters.source_map.max_inflight == 2,
          "source-map pipeline did not expose II/capacity/backpressure");
  require(counters.edge_map.accepted == 1 &&
              counters.edge_map.completed == 1 &&
              counters.reduce.accepted == 1 &&
              counters.reduce.completed == 1 &&
              counters.apply.accepted == 1 &&
              counters.apply.completed == 1,
          "independent algorithm pipeline stages lost work");
  std::cout << "EVIDENCE algorithm_pipeline cycles="
            << scheduler.clock(core).completed_cycles
            << " source_accepted=" << counters.source_map.accepted
            << " source_ii_stalls="
            << counters.source_map.initiation_interval_stalls
            << " source_capacity_stalls="
            << counters.source_map.capacity_stalls
            << " source_output_stalls="
            << counters.source_map.output_backpressure_stalls
            << " source_max_inflight=" << counters.source_map.max_inflight
            << '\n';
}

void test_spine_timed_full_pagerank_compute_uses_hbm_and_pipelines() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("pagerank", 200.0);
  MockMemoryBackend backend("pagerank-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  FixedAxiPort vertex_state(
      "pagerank-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32,
          .channel = 17,
          .initiator_id = 217,
          .data_width_bytes = 4,
          .max_burst_beats = 16,
          .request_fifo_depth = 32,
          .response_fifo_depth = 32,
          .read_beat_fifo_depth = 32,
          .read_reorder_capacity = 32,
          .stream_read_beats = false,
          .max_pending_requests = 32,
          .max_outstanding_bursts = 32,
          .address_accepts_per_cycle = 1,
          .beat_issues_per_cycle = 1,
          .response_beats_per_cycle = 1,
      },
      backend);
  Fifo<PartConvWord> edge_stream("pagerank-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("pagerank-value-axis", core, 2);
  const auto word = [](float value) {
    return GraphAlgorithmPolicy::float_to_word(value);
  };
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = 4,
      .source = 0,
      .damping = 0.8F,
  });
  SpineSplitPageRankCompute compute(
      "pagerank-compute", core, policy, {2, 1, 0, 1}, vertex_state,
      edge_stream, value_stream,
      AlgorithmPipelineConfig{
          .source_map = {.latency_cycles = 3,
                         .initiation_interval = 1,
                         .capacity = 4},
          .edge_map = {.latency_cycles = 1,
                       .initiation_interval = 1,
                       .capacity = 4},
          .reduce = {.latency_cycles = 2,
                     .initiation_interval = 1,
                     .capacity = 8},
          .apply = {.latency_cycles = 3,
                    .initiation_interval = 1,
                    .capacity = 8},
      },
      8, 4);
  SequenceProducer<PartConvWord> producer(
      "pagerank-reader", core, edge_stream,
      {
          {.kind = PartConvWordKind::kSourceRequest, .first = 0},
          {.kind = PartConvWordKind::kSourceRequest, .first = 1},
          {.kind = PartConvWordKind::kSourceRequest, .first = 2},
          {.kind = PartConvWordKind::kSourceRequest, .first = 3},
          {.kind = PartConvWordKind::kSourceCount, .first = 4},
          {.kind = PartConvWordKind::kSourceGeneration, .first = 1},
          {.kind = PartConvWordKind::kSourceRequestsDone},
          {.kind = PartConvWordKind::kTileBegin, .first = 0},
          {.kind = PartConvWordKind::kEdge, .first = 1, .second = word(0.1F)},
          {.kind = PartConvWordKind::kEdge, .first = 2, .second = word(0.1F)},
          {.kind = PartConvWordKind::kEdge, .first = 2, .second = word(0.2F)},
          {.kind = PartConvWordKind::kEdge, .first = 2, .second = word(0.2F)},
          {.kind = PartConvWordKind::kTileEnd, .first = 0},
          {.kind = PartConvWordKind::kDoneAll},
      });
  SequenceConsumer<SourceValueWord> consumer("pagerank-reader-values", core,
                                             value_stream, 2);

  scheduler.add_component(producer);
  compute.register_components(scheduler);
  scheduler.add_component(consumer);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && vertex_state.idle() &&
               backend.outstanding() == 0 && consumer.values.size() == 5;
      },
      20'000);

  const std::vector<float> expected{0.1F, 0.2F, 0.6F, 0.1F};
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                          compute.rank_words().at(vertex)) -
                      expected[vertex]) < 1.0e-5F,
            "timed PageRank compute produced the wrong rank");
  }
  const std::vector<std::uint8_t> hbm_ranks = backend.inspect_payload(
      vertex_state.channel(), compute.state_layout().primary_write.base,
      expected.size() * sizeof(std::uint32_t));
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    const std::size_t offset = vertex * sizeof(std::uint32_t);
    const std::uint32_t rank_word =
        static_cast<std::uint32_t>(hbm_ranks[offset]) |
        (static_cast<std::uint32_t>(hbm_ranks[offset + 1]) << 8) |
        (static_cast<std::uint32_t>(hbm_ranks[offset + 2]) << 16) |
        (static_cast<std::uint32_t>(hbm_ranks[offset + 3]) << 24);
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(rank_word) -
                      expected[vertex]) < 1.0e-5F,
            "timed PageRank output did not reach the HBM ping-pong region");
  }
  require(std::fabs(compute.dangling_mass() - 0.25F) < 1.0e-6F &&
              std::fabs(compute.dangling_share() - 0.05F) < 1.0e-6F,
          "timed PageRank compute produced the wrong dangling contribution");
  const auto &counters = compute.counters();
  require(!compute.failed() && counters.source_requests == 4 &&
              counters.source_responses == 4 &&
              counters.source_protocol_acks == 1 &&
              counters.source_protocol_status == 0 &&
              counters.source_map_operations == 4 &&
              counters.dangling_reduce_operations == 4 &&
              counters.edges_received == 4 &&
              counters.edge_reduce_operations == 4 &&
              counters.vertices_applied == 4 &&
              counters.primary_read_bytes == 32 &&
              counters.degree_read_bytes == 16 &&
              counters.primary_write_bytes == 16 &&
              counters.memory_requests_issued == 16 &&
              counters.memory_requests_completed == 16,
          "timed PageRank compute bypassed a required operation or HBM access");
  require(compute.pipeline_counters().source_map.completed == 4 &&
              compute.pipeline_counters().reduce.completed == 8 &&
              compute.pipeline_counters().apply.completed == 4,
          "timed PageRank arithmetic did not traverse finite pipelines");
  require(consumer.values.back().kind ==
              SourceValueWord::Kind::kProtocolAck &&
              consumer.values.back().value == 0,
          "timed PageRank source protocol did not return a valid ACK");
  require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                        consumer.values[0].value) -
                    0.1F) < 1.0e-6F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            consumer.values[1].value) -
                        0.2F) < 1.0e-6F &&
              GraphAlgorithmPolicy::word_to_float(consumer.values[2].value) ==
                  0.0F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(
                            consumer.values[3].value) -
                        0.2F) < 1.0e-6F,
          "timed PageRank source replies did not use HBM rank and degree");
  std::cout << "EVIDENCE spine_timed_pagerank cycles="
            << scheduler.clock(core).completed_cycles
            << " memory_requests=" << counters.memory_requests_issued
            << " primary_read_bytes=" << counters.primary_read_bytes
            << " degree_read_bytes=" << counters.degree_read_bytes
            << " primary_write_bytes=" << counters.primary_write_bytes
            << " source_ops=" << counters.source_map_operations
            << " reduce_ops="
            << counters.dangling_reduce_operations +
                   counters.edge_reduce_operations
            << " apply_ops=" << counters.vertices_applied
            << " dangling_share=" << compute.dangling_share()
            << " rank_sum="
            << GraphAlgorithmPolicy::word_to_float(compute.rank_words()[0]) +
                   GraphAlgorithmPolicy::word_to_float(compute.rank_words()[1]) +
                   GraphAlgorithmPolicy::word_to_float(compute.rank_words()[2]) +
                   GraphAlgorithmPolicy::word_to_float(compute.rank_words()[3])
            << '\n';
}

void test_spine_full_pagerank_vertical_slice_reads_level_edges() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("pagerank-system", 200.0);
  MockMemoryBackend backend("pagerank-system-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 0, .dst = 2, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 3, .dst = 2, .weight = 1, .diff = 1},
      },
      .case_name = "pagerank_vertical_slice",
  };
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, workload, 0.8F, SpineL0Config{},
      SpineAxiInterfaceProfile{},
      AlgorithmPipelineConfig{
          .source_map = {.latency_cycles = 3,
                         .initiation_interval = 1,
                         .capacity = 4},
          .edge_map = {.latency_cycles = 1,
                       .initiation_interval = 1,
                       .capacity = 4},
          .reduce = {.latency_cycles = 2,
                     .initiation_interval = 1,
                     .capacity = 8},
          .apply = {.latency_cycles = 3,
                    .initiation_interval = 1,
                    .capacity = 8},
      });
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      500'000);

  const std::vector<float> expected{0.1F, 0.2F, 0.6F, 0.1F};
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                          system.compute().rank_words().at(vertex)) -
                      expected[vertex]) < 1.0e-5F,
            "PageRank vertical slice produced the wrong rank");
  }
  require(!system.failed() &&
              system.maintenance_counters().dirty_mark_edge_visits == 4 &&
              system.maintenance_counters().persisted_edges == 4 &&
              system.reader_counters().source_requests == 4 &&
              system.reader_counters().source_responses == 4 &&
              system.reader_counters().source_request_windows == 1 &&
              system.reader_counters().source_protocol_status == 0 &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().edges_emitted == 4 &&
              system.reader_counters().graph_edge_payload_read_bytes == 64 &&
              system.compute_counters().edges_received == 4 &&
              system.compute_counters().vertices_applied == 4,
          "PageRank vertical slice bypassed maintenance, Reader, or compute");
  require(system.edge_stream_stats().pushes == 24,
          "PageRank vertical slice lost protocol, diagnostic, or edge words");
  std::cout << "EVIDENCE spine_pagerank_vertical cycles="
            << scheduler.clock(core).completed_cycles
            << " maintenance="
            << system.maintenance_counters().end_cycle -
                   system.maintenance_counters().start_cycle
            << " reader_edges=" << system.reader_counters().edges_emitted
            << " graph_payload_bytes="
            << system.reader_counters().graph_edge_payload_read_bytes
            << " state_memory_requests="
            << system.compute_counters().memory_requests_issued
            << " edge_axis_stalls="
            << system.edge_stream_stats().push_stalls
            << " rank_sum="
            << GraphAlgorithmPolicy::word_to_float(
                   system.compute().rank_words()[0]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[1]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[2]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[3])
            << '\n';

  const std::uint64_t first_output_base =
      system.compute().primary_write_base();
  const std::uint64_t maintenance_end =
      system.maintenance_counters().end_cycle;
  system.restart_iteration();
  require(system.compute().primary_read_base() == first_output_base &&
              system.compute().primary_write_base() ==
                  system.compute().state_layout().primary_read.base,
          "PageRank restart copied ranks instead of swapping physical bases");
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      500'000);

  const std::vector<float> second_expected{0.17F, 0.21F, 0.45F, 0.17F};
  for (std::size_t vertex = 0; vertex < second_expected.size(); ++vertex) {
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                          system.compute().rank_words().at(vertex)) -
                      second_expected[vertex]) < 1.0e-5F,
            "second timed PageRank iteration used the wrong rank buffer");
  }
  require(!system.failed() &&
              system.maintenance_counters().end_cycle == maintenance_end &&
              system.reader_counters().edges_emitted == 4 &&
              system.compute_counters().memory_requests_issued == 16 &&
              system.compute().pipeline_counters().source_map.completed == 4 &&
              system.compute().pipeline_counters().reduce.completed == 8 &&
              system.compute().pipeline_counters().apply.completed == 4 &&
              std::fabs(system.compute().dangling_mass() - 0.6F) < 1.0e-5F &&
              std::fabs(system.compute().dangling_share() - 0.12F) < 1.0e-5F,
          "PageRank restart reran maintenance or retained stale round state");
  std::cout << "EVIDENCE spine_pagerank_second_iteration cycles="
            << scheduler.clock(core).completed_cycles
            << " maintenance_end=" << maintenance_end
            << " read_base=" << system.compute().primary_read_base()
            << " write_base=" << system.compute().primary_write_base()
            << " dangling_share=" << system.compute().dangling_share()
            << " rank_sum="
            << GraphAlgorithmPolicy::word_to_float(
                   system.compute().rank_words()[0]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[1]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[2]) +
                   GraphAlgorithmPolicy::word_to_float(
                       system.compute().rank_words()[3])
            << '\n';

  std::vector<float> oracle = second_expected;
  const std::array<std::uint32_t, 4> degrees{2, 1, 0, 1};
  const std::array<std::pair<std::uint32_t, std::uint32_t>, 4> edges{
      std::pair<std::uint32_t, std::uint32_t>{0, 1},
      {0, 2},
      {1, 2},
      {3, 2},
  };
  float max_oracle_error = 0.0F;
  for (std::size_t iteration = 2; iteration < 25; ++iteration) {
    float dangling = 0.0F;
    for (std::size_t vertex = 0; vertex < oracle.size(); ++vertex) {
      dangling += degrees[vertex] == 0 ? oracle[vertex] : 0.0F;
    }
    std::vector<float> next(oracle.size(),
                            0.05F + 0.8F * dangling / oracle.size());
    for (const auto &[source, destination] : edges) {
      next[destination] +=
          0.8F * oracle[source] / static_cast<float>(degrees[source]);
    }
    oracle = std::move(next);
    system.restart_iteration();
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);
    for (std::size_t vertex = 0; vertex < oracle.size(); ++vertex) {
      max_oracle_error = std::max(
          max_oracle_error,
          std::fabs(GraphAlgorithmPolicy::word_to_float(
                        system.compute().rank_words()[vertex]) -
                    oracle[vertex]));
    }
  }
  require(!system.failed() && max_oracle_error < 1.0e-5F &&
              system.maintenance_counters().end_cycle == maintenance_end &&
              system.compute().iteration_error() < 1.0e-5F,
          "multi-iteration PageRank diverged from the independent CPU oracle");
  std::cout << "EVIDENCE spine_pagerank_convergence iterations=25"
            << " total_cycles=" << scheduler.clock(core).completed_cycles
            << " max_oracle_error=" << max_oracle_error
            << " final_l1_error=" << system.compute().iteration_error()
            << " maintenance_reruns=0\n";
}

void test_spine_pagerank_active_gate_fallback_preserves_tile_identity() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("pagerank-fallback", 200.0);
  MockMemoryBackend backend("pagerank-fallback-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 3,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 2, .dst = 0, .weight = 1, .diff = 1},
      },
      .case_name = "pagerank_active_gate_fallback",
  };
  SpineL0Config maintenance_config;
  maintenance_config.range_task_active_gate = 1;
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, workload, 0.8F, maintenance_config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return (system.done() || system.failed()) && system.idle() &&
               backend.outstanding() == 0;
      },
      500'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  bool ranks_match = true;
  for (const std::uint32_t rank_word : system.compute().rank_words()) {
    ranks_match =
        ranks_match &&
        std::fabs(GraphAlgorithmPolicy::word_to_float(rank_word) - 1.0F / 3.0F) <
            1.0e-5F;
  }
  require(!system.failed() && system.done() && reader.range_task_path == 2 &&
              reader.range_task_fallback_reason == 1 &&
              reader.range_task_active_records == 3 &&
              reader.source_requests == 3 && reader.source_responses == 3 &&
              reader.fallback_replay_edges == 3 &&
              compute.edges_received == 3 && compute.tiles_received == 1 &&
              compute.source_map_operations == 3 &&
              compute.vertices_applied == 3 && compute.done_words == 1 &&
              ranks_match,
          "PageRank active-gate fallback lost source refresh, tile identity, "
          "or arithmetic correctness");
}

void test_spine_pagerank_fallback_reuses_launch_level_cache() {
  struct Run {
    bool failed{};
    std::uint64_t cycles{};
    std::uint64_t backend_requests{};
    SpineReaderCounters reader;
    spine::sim::SpinePageRankCounters compute;
    std::vector<std::uint32_t> ranks;
  };
  const auto run = [](bool reuse) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("pagerank-cache-reuse", 200.0);
    MockMemoryBackend backend("pagerank-cache-reuse-hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 2,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 128,
                                  .response_queue_depth = 256,
                              });
    SpineEdgeSlice workload{
        .vertices = 129,
        .edges = {},
        .case_name = reuse ? "pagerank_cache_reuse_on"
                           : "pagerank_cache_reuse_off",
    };
    for (std::uint32_t source = 0; source < workload.vertices; ++source) {
      workload.edges.push_back(
          {.src = source,
           .dst = static_cast<std::uint32_t>((source + 1) % workload.vertices),
           .weight = 1,
           .diff = 1});
    }
    SpineL0Config config;
    config.range_task_active_gate = 128;
    config.fallback_level_cache_reuse = reuse;
    SpinePageRankVerticalSliceSystem system(scheduler, core, backend, workload,
                                            0.8F, config);
    system.register_components();
    scheduler.add_component(backend);
    scheduler.run_until(
        [&] {
          return (system.done() || system.failed()) && system.idle() &&
                 backend.outstanding() == 0;
        },
        500'000);
    return Run{
        .failed = system.failed(),
        .cycles = scheduler.clock(core).completed_cycles,
        .backend_requests = backend.stats().accepted,
        .reader = system.reader_counters(),
        .compute = system.compute_counters(),
        .ranks = system.compute().rank_words(),
    };
  };

  const Run baseline = run(false);
  const Run optimized = run(true);
  std::cout << "EVIDENCE spine_pagerank_fallback_level_cache_reuse"
            << " baseline_failed=" << baseline.failed
            << " optimized_failed=" << optimized.failed
            << " ranks_equal=" << (baseline.ranks == optimized.ranks)
            << " baseline_edges=" << baseline.reader.edges_emitted
            << " optimized_edges=" << optimized.reader.edges_emitted
            << " baseline_compute_edges=" << baseline.compute.edges_received
            << " optimized_compute_edges=" << optimized.compute.edges_received
            << " baseline_cycles=" << baseline.cycles
            << " optimized_cycles=" << optimized.cycles
            << " baseline_requests=" << baseline.backend_requests
            << " optimized_requests=" << optimized.backend_requests
            << " optimized_reuses="
            << optimized.reader.fallback_level_cache_reuses
            << " optimized_empty_skips="
            << optimized.reader.fallback_level_cache_empty_skips
            << " optimized_row_lookups="
            << optimized.reader.fallback_row_lookups
            << " optimized_bitmap_misses="
            << optimized.reader.graph_index_bitmap_misses
            << " optimized_epoch_misses="
            << optimized.reader.graph_index_epoch_misses
            << " optimized_range_error=" << optimized.reader.range_task_error
            << '\n';
  require(!baseline.failed && !optimized.failed &&
              baseline.ranks == optimized.ranks &&
              baseline.reader.edges_emitted == optimized.reader.edges_emitted &&
              baseline.compute.edges_received == optimized.compute.edges_received,
          "fallback level-cache reuse changed PageRank semantics or work");
  require(baseline.reader.fallback_level_cache_reuses == 0 &&
              optimized.reader.fallback_level_cache_reuses > 0 &&
              optimized.reader.memory_requests_issued ==
                  optimized.reader.memory_requests_completed,
          "fallback level-cache reuse was bypassed or left an open ledger");
  require(optimized.reader.fallback_metadata_read_bytes <
                  baseline.reader.fallback_metadata_read_bytes &&
              optimized.reader.row_lookup_metadata_bytes <
                  baseline.reader.row_lookup_metadata_bytes &&
              optimized.backend_requests < baseline.backend_requests &&
              optimized.cycles < baseline.cycles,
          "fallback level-cache reuse did not remove metadata traffic and cycles");
}

void test_spine_pagerank_source_page_cache_is_finite_and_exact() {
  struct Run {
    bool failed{};
    std::uint64_t cycles{};
    std::uint64_t backend_requests{};
    SpineReaderCounters reader;
    std::vector<std::uint32_t> ranks;
  };
  const auto run = [](bool cache, std::size_t active_gate) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("pagerank-page-cache", 200.0);
    MockMemoryBackend backend("pagerank-page-cache-hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 2,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 128,
                                  .response_queue_depth = 256,
                              });
    SpineEdgeSlice workload{
        .vertices = 257,
        .edges = {},
        .case_name = cache ? "pagerank_page_cache_on"
                           : "pagerank_page_cache_off",
    };
    for (std::uint32_t source = 0; source < workload.vertices; ++source) {
      workload.edges.push_back(
          {.src = source,
           .dst = static_cast<std::uint32_t>((source + 1) % workload.vertices),
           .weight = 1,
           .diff = 1});
    }
    SpineL0Config config;
    config.range_task_active_gate = active_gate;
    config.fallback_level_cache_reuse = true;
    config.source_page_index_cache = cache;
    SpinePageRankVerticalSliceSystem system(scheduler, core, backend, workload,
                                            0.8F, config);
    system.register_components();
    scheduler.add_component(backend);
    scheduler.run_until(
        [&] {
          return (system.done() || system.failed()) && system.idle() &&
                 backend.outstanding() == 0;
        },
        1'000'000);
    return Run{
        .failed = system.failed(),
        .cycles = scheduler.clock(core).completed_cycles,
        .backend_requests = backend.stats().accepted,
        .reader = system.reader_counters(),
        .ranks = system.compute().rank_words(),
    };
  };

  const Run exact_baseline = run(false, 4096);
  const Run exact_cached = run(true, 4096);
  const Run fallback_baseline = run(false, 256);
  const Run fallback_cached = run(true, 256);
  std::cout << "EVIDENCE spine_pagerank_source_page_cache"
            << " exact_ranks_equal="
            << (exact_baseline.ranks == exact_cached.ranks)
            << " exact_base_cycles=" << exact_baseline.cycles
            << " exact_cached_cycles=" << exact_cached.cycles
            << " exact_base_requests=" << exact_baseline.backend_requests
            << " exact_cached_requests=" << exact_cached.backend_requests
            << " exact_hits=" << exact_cached.reader.source_page_cache_hits
            << " exact_misses=" << exact_cached.reader.source_page_cache_misses
            << " exact_fills=" << exact_cached.reader.source_page_cache_fills
            << " fallback_ranks_equal="
            << (fallback_baseline.ranks == fallback_cached.ranks)
            << " fallback_base_cycles=" << fallback_baseline.cycles
            << " fallback_cached_cycles=" << fallback_cached.cycles
            << " fallback_base_requests=" << fallback_baseline.backend_requests
            << " fallback_cached_requests=" << fallback_cached.backend_requests
            << " fallback_hits="
            << fallback_cached.reader.source_page_cache_hits
            << " fallback_misses="
            << fallback_cached.reader.source_page_cache_misses
            << " fallback_fills="
            << fallback_cached.reader.source_page_cache_fills << '\n';
  require(!exact_baseline.failed && !exact_cached.failed &&
              !fallback_baseline.failed && !fallback_cached.failed &&
              exact_baseline.ranks == exact_cached.ranks &&
              fallback_baseline.ranks == fallback_cached.ranks,
          "source-page cache changed PageRank semantics");
  require(exact_baseline.reader.edges_emitted ==
                  exact_cached.reader.edges_emitted &&
              fallback_baseline.reader.edges_emitted ==
                  fallback_cached.reader.edges_emitted &&
              exact_cached.reader.memory_requests_issued ==
                  exact_cached.reader.memory_requests_completed &&
              fallback_cached.reader.memory_requests_issued ==
                  fallback_cached.reader.memory_requests_completed,
          "source-page cache changed edge work or left an open ledger");
  require(exact_cached.reader.source_page_cache_hits > 0 &&
              exact_cached.reader.source_page_cache_misses >= 2 &&
              exact_cached.reader.source_page_cache_fills >= 2 &&
              fallback_cached.reader.source_page_cache_hits > 0 &&
              fallback_cached.reader.source_page_cache_misses >= 2 &&
              exact_cached.backend_requests < exact_baseline.backend_requests &&
              fallback_cached.backend_requests <
                  fallback_baseline.backend_requests &&
              exact_cached.cycles < exact_baseline.cycles &&
              fallback_cached.cycles < fallback_baseline.cycles,
          "finite source-page cache did not expose hits, page replacement, "
          "and timing benefit");
}

void test_spine_pagerank_reports_maintenance_failure_without_compute_done() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("pagerank-failure", 200.0);
  MockMemoryBackend backend("pagerank-failure-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 1,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 2'048,
      .edges = {},
      .case_name = "pagerank_maintenance_failure",
  };
  SpineL0Config config;
  config.max_vertices = 2'048;
  config.max_sort_edges = 16;
  SpineL0State initial_state;
  std::uint32_t source = 0;
  for (std::size_t level = 0; level < 10; ++level) {
    const std::size_t count = static_cast<std::size_t>(
        spine_level_layout(config, false, level).edge_capacity);
    for (std::size_t index = 0; index < count; ++index) {
      initial_state.cold_levels[0][level].push_back(
          {.src = source, .dst = source + 1, .weight = 1, .diff = 1});
      ++source;
    }
  }
  for (std::size_t index = 0; index < config.max_sort_edges; ++index) {
    workload.edges.push_back(
        {.src = source, .dst = source + 1, .weight = 1, .diff = 1});
    ++source;
  }
  SpinePageRankVerticalSliceSystem system(scheduler, core, backend, workload,
                                          0.8F, config,
                                          SpineAxiInterfaceProfile{},
                                          AlgorithmPipelineConfig{},
                                          SpineSplitPageRankCompute::
                                              kDefaultMemoryRequestWindow,
                                          std::move(initial_state));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.failed(); }, 500'000);

  require(system.failed() && system.maintenance_done() && !system.done() &&
              system.failure() ==
                  "maintenance: Spine cold level hierarchy has no "
                  "capacity-safe free target",
          "PageRank system did not expose terminal maintenance failure");
}

void test_spine_dynamic_pagerank_times_only_update_then_final_graph() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("dynamic-pagerank", 200.0);
  MockMemoryBackend backend("dynamic-pagerank-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineEdgeSlice initial{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 0, .dst = 2, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 3, .dst = 2, .weight = 1, .diff = 1},
      },
      .case_name = "dynamic_pagerank_initial",
  };
  SpineEdgeSlice update{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 2, .weight = 1, .diff = -1},
          {.src = 2, .dst = 3, .weight = 1, .diff = 1},
      },
      .case_name = "dynamic_pagerank_update",
  };
  const SpineEdgeSlice final_graph{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          {.src = 3, .dst = 2, .weight = 1, .diff = 1},
      },
      .case_name = "dynamic_pagerank_final",
  };
  SpineL0State initial_state;
  initial_state.cold_levels[0][0] = initial.edges;
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kFullPageRank,
      .vertices = final_graph.vertices,
      .source = 0,
      .damping = 0.8F,
  });
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, std::move(update), policy, SpineL0Config{},
      SpineAxiInterfaceProfile{}, AlgorithmPipelineConfig{},
      SpineSplitPageRankCompute::kDefaultMemoryRequestWindow,
      std::move(initial_state), final_graph,
      spine::sim::spine_dirty_identity(
          1, std::vector<std::uint32_t>{0, 2}));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      500'000);

  const std::vector<float> expected{0.05F, 0.25F, 0.45F, 0.25F};
  for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
    require(std::fabs(GraphAlgorithmPolicy::word_to_float(
                          system.compute().rank_words().at(vertex)) -
                      expected[vertex]) < 1.0e-5F,
            "dynamic PageRank computed the pre-update graph");
  }
  const auto &level = system.level_state().cold_levels[0][1];
  require(!system.failed() && system.maintenance_counters().target_level == 1 &&
              system.maintenance_counters().persisted_edges == 4 &&
              system.level_state().cold_levels[0][0].empty() &&
              level == final_graph.edges &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().edges_emitted == 4,
          "dynamic PageRank did not preserve update, level, or host coverage");
  std::cout << "EVIDENCE spine_dynamic_pagerank update_edges=2 final_edges=4"
            << " maintenance_cycles="
            << system.maintenance_counters().end_cycle -
                   system.maintenance_counters().start_cycle
            << " total_cycles=" << scheduler.clock(core).completed_cycles
            << " target_level="
            << system.maintenance_counters().target_level << '\n';
}

void test_spine_residual_pagerank_tracks_thresholded_frontier() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("residual-pagerank-system", 200.0);
  MockMemoryBackend backend("residual-pagerank-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineEdgeSlice workload{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 0, .dst = 2, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 3, .dst = 2, .weight = 1, .diff = 1},
      },
      .case_name = "residual_pagerank_vertical_slice",
  };
  constexpr float kDamping = 0.8F;
  constexpr float kEpsilon = 1.0e-5F;
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = workload.vertices,
      .source = 0,
      .damping = kDamping,
      .epsilon = kEpsilon,
  });
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, workload, policy, SpineL0Config{},
      SpineAxiInterfaceProfile{},
      AlgorithmPipelineConfig{
          .source_map = {.latency_cycles = 3,
                         .initiation_interval = 1,
                         .capacity = 4},
          .edge_map = {.latency_cycles = 1,
                       .initiation_interval = 1,
                       .capacity = 4},
          .reduce = {.latency_cycles = 2,
                     .initiation_interval = 1,
                     .capacity = 8},
          .apply = {.latency_cycles = 3,
                    .initiation_interval = 1,
                    .capacity = 8},
      });
  system.register_components();
  scheduler.add_component(backend);

  const std::array<std::uint32_t, 4> degrees{2, 1, 0, 1};
  const std::array<std::pair<std::uint32_t, std::uint32_t>, 4> edges{
      std::pair<std::uint32_t, std::uint32_t>{0, 1},
      {0, 2},
      {1, 2},
      {3, 2},
  };
  std::vector<float> oracle_rank(4, 0.0F);
  std::vector<float> oracle_residual(4, (1.0F - kDamping) / 4.0F);
  std::vector<std::uint32_t> active{0, 1, 2, 3};
  float max_oracle_error = 0.0F;
  std::size_t rounds = 0;
  for (; rounds < 256; ++rounds) {
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);

    std::vector<float> deltas(4, 0.0F);
    float dangling = 0.0F;
    for (const std::uint32_t source : active) {
      deltas[source] = oracle_residual[source];
      oracle_residual[source] = 0.0F;
      oracle_rank[source] += deltas[source];
      if (degrees[source] == 0) {
        dangling += deltas[source];
      }
    }
    const float dangling_share = kDamping * dangling / 4.0F;
    for (float &residual : oracle_residual) {
      residual += dangling_share;
    }
    for (const auto &[source, destination] : edges) {
      if (deltas[source] != 0.0F) {
        oracle_residual[destination] +=
            kDamping * deltas[source] / static_cast<float>(degrees[source]);
      }
    }
    std::vector<std::uint32_t> next;
    for (std::size_t vertex = 0; vertex < oracle_rank.size(); ++vertex) {
      const float actual_rank = GraphAlgorithmPolicy::word_to_float(
          system.compute().rank_words().at(vertex));
      const float actual_residual = GraphAlgorithmPolicy::word_to_float(
          system.compute().residual_words().at(vertex));
      max_oracle_error =
          std::max({max_oracle_error, std::fabs(actual_rank - oracle_rank[vertex]),
                    std::fabs(actual_residual - oracle_residual[vertex])});
      if (std::fabs(oracle_residual[vertex]) > kEpsilon / 4.0F) {
        next.push_back(static_cast<std::uint32_t>(vertex));
      }
    }
    require(system.compute().next_active() == next &&
                system.reader_counters().source_requests == active.size() &&
                system.compute_counters().source_requests == active.size() &&
                system.compute_counters().vertices_activated == next.size() &&
                system.compute_counters().memory_requests_issued ==
                    5 * active.size() + 8,
            "residual PageRank did not execute its thresholded memory frontier");
    active = std::move(next);
    if (active.empty()) {
      ++rounds;
      break;
    }
    system.restart_iteration();
  }

  float rank_sum = 0.0F;
  float residual_l1 = 0.0F;
  for (const std::uint32_t word : system.compute().rank_words()) {
    rank_sum += GraphAlgorithmPolicy::word_to_float(word);
  }
  for (const std::uint32_t word : system.compute().residual_words()) {
    residual_l1 +=
        std::fabs(GraphAlgorithmPolicy::word_to_float(word));
  }
  std::cout << "EVIDENCE spine_residual_pagerank rounds=" << rounds
            << " cycles=" << scheduler.clock(core).completed_cycles
            << " max_oracle_error=" << max_oracle_error
            << " rank_sum=" << rank_sum
            << " residual_l1=" << residual_l1
            << " final_active=" << active.size()
            << " failed=" << system.failed() << '\n';
  require(!system.failed() && active.empty() && rounds < 256 &&
              max_oracle_error < 1.0e-5F &&
              residual_l1 <= kEpsilon * 1.01F &&
              std::fabs(rank_sum - 1.0F) <
                  kEpsilon / (1.0F - kDamping) &&
              system.maintenance_counters().persisted_edges == 4,
          "thresholded residual PageRank failed to converge to its oracle");
}

void test_spine_connected_components_converges_with_min_labels() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("connected-components-system", 200.0);
  MockMemoryBackend backend("connected-components-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineEdgeSlice graph{
      .vertices = 6,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 1, .dst = 0, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 2, .dst = 1, .weight = 1, .diff = 1},
          {.src = 3, .dst = 4, .weight = 1, .diff = 1},
          {.src = 4, .dst = 3, .weight = 1, .diff = 1},
      },
      .case_name = "connected_components_vertical_slice",
  };
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kConnectedComponents,
      .vertices = graph.vertices,
      .source = 0,
  });
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, graph, policy, SpineL0Config{},
      SpineAxiInterfaceProfile{}, AlgorithmPipelineConfig{});
  system.register_components();
  scheduler.add_component(backend);

  const std::vector<std::vector<std::uint32_t>> expected_frontiers{
      {1, 2, 4},
      {2},
      {},
  };
  std::uint64_t total_degree_reads = 0;
  std::uint64_t total_auxiliary_reads = 0;
  std::uint64_t total_dangling_reductions = 0;
  std::size_t rounds = 0;
  for (; rounds < expected_frontiers.size(); ++rounds) {
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);
    require(!system.failed() &&
                system.compute().next_active() == expected_frontiers[rounds],
            "Spine CC produced the wrong per-round frontier");
    total_degree_reads += system.compute_counters().degree_read_bytes;
    total_auxiliary_reads += system.compute_counters().auxiliary_read_bytes;
    total_dangling_reductions +=
        system.compute_counters().dangling_reduce_operations;
    if (!system.compute().next_active().empty()) {
      system.restart_iteration();
    }
  }

  const std::vector<std::uint32_t> expected_labels{0, 0, 0, 3, 3, 5};
  std::cout << "EVIDENCE spine_connected_components rounds=" << rounds
            << " cycles=" << scheduler.clock(core).completed_cycles
            << " final_active=" << system.compute().next_active().size()
            << " degree_read_bytes=" << total_degree_reads
            << " auxiliary_read_bytes=" << total_auxiliary_reads
            << " dangling_reductions=" << total_dangling_reductions << '\n';
  require(system.compute().rank_words() == expected_labels &&
              system.compute().next_active().empty() &&
              total_degree_reads == 0 && total_auxiliary_reads == 0 &&
              total_dangling_reductions == 0,
          "Spine CC labels or non-CC memory ledger are wrong");
}

void test_spine_delta_hls_residual_uses_warm_seed_frontier() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("delta-hls-warm-spine", 200.0);
  MockMemoryBackend backend("delta-hls-warm-spine-hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 4,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineEdgeSlice graph{
      .vertices = 4,
      .edges = {
          {.src = 0, .dst = 1, .weight = 1, .diff = 1},
          {.src = 1, .dst = 2, .weight = 1, .diff = 1},
          {.src = 2, .dst = 3, .weight = 1, .diff = 1},
          {.src = 3, .dst = 0, .weight = 1, .diff = 1},
      },
      .case_name = "delta_hls_warm_spine",
  };
  const GraphAlgorithmPolicy policy(AlgorithmPolicyConfig{
      .kind = GraphAlgorithmKind::kResidualPageRank,
      .vertices = graph.vertices,
      .source = 0,
      .damping = 0.5F,
      .epsilon = 0.04F,
      .residual_contract =
          spine::sim::ResidualPageRankContract::kDeltaHlsSinkFreeLinfWarm,
  });
  const spine::sim::AlgorithmInitialState warm{
      .primary = {
          GraphAlgorithmPolicy::float_to_word(0.1F),
          GraphAlgorithmPolicy::float_to_word(0.2F),
          GraphAlgorithmPolicy::float_to_word(0.3F),
          GraphAlgorithmPolicy::float_to_word(0.4F),
      },
      .auxiliary = {
          GraphAlgorithmPolicy::float_to_word(0.0F),
          GraphAlgorithmPolicy::float_to_word(0.06F),
          GraphAlgorithmPolicy::float_to_word(0.0F),
          GraphAlgorithmPolicy::float_to_word(0.0F),
      },
      .active_vertices = {1},
  };
  SpinePageRankVerticalSliceSystem system(
      scheduler, core, backend, graph, policy, SpineL0Config{},
      SpineAxiInterfaceProfile{}, AlgorithmPipelineConfig{},
      SpineSplitPageRankCompute::kDefaultMemoryRequestWindow, SpineL0State{},
      std::nullopt, std::nullopt, warm);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      1'000'000);

  const auto &rank = system.compute().rank_words();
  const auto &residual = system.compute().residual_words();
  std::cout << "EVIDENCE spine_delta_hls_warm sources="
            << system.reader_counters().source_requests
            << " edges=" << system.reader_counters().edges_emitted
            << " next_active=" << system.compute().next_active().size()
            << " rank1=" << GraphAlgorithmPolicy::word_to_float(rank[1])
            << " residual2="
            << GraphAlgorithmPolicy::word_to_float(residual[2]) << '\n';
  require(!system.failed() && system.done() &&
              system.reader_counters().source_requests == 1 &&
              system.reader_counters().edges_emitted == 1 &&
              system.compute().next_active().empty() &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(rank[1]) - 0.26F) <
                  1.0e-6F &&
              std::fabs(GraphAlgorithmPolicy::word_to_float(residual[2]) -
                        0.03F) < 1.0e-6F,
          "Spine Delta.hls warm residual seed was not isolated or drained");
}

}  // namespace

int main(int argc, char **argv) {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"multiclock_scheduler", test_multiclock_scheduler},
      {"scheduler_component_removal",
       test_scheduler_component_removal_is_exact},
      {"scheduler_phase_dispatch",
       test_scheduler_dispatches_only_declared_phases},
      {"scheduler_component_profile",
       test_scheduler_component_sampling_profile},
      {"scheduler_dynamic_readiness",
       test_scheduler_dynamic_phase_readiness},
      {"scheduler_latched_evaluate_bitmap",
       test_scheduler_latched_evaluate_bitmap_ordering},
      {"fifo_latched_commit_readiness", test_fifo_latched_commit_readiness},
      {"fifo_transition_notifiers",
       test_fifo_transition_notifiers_and_bulk_stalls},
      {"scheduler_latched_commit_bitmap",
       test_scheduler_latched_commit_bitmap_ordering},
      {"fixed_axi_busy_unregister",
       test_fixed_axi_port_rejects_busy_unregister},
      {"fifo_no_fallthrough", test_fifo_has_no_same_cycle_fallthrough},
      {"fifo_order_independent", test_fifo_is_registration_order_independent},
      {"fifo_backpressure", test_fifo_backpressure_is_counted},
      {"bank_conflict", test_banked_memory_conflict_and_round_robin},
      {"raw_hazard", test_banked_memory_stalls_read_after_write},
      {"invalid_config", test_invalid_clock_and_capacity_are_rejected},
      {"spine_empty_update_slice",
       test_spine_edge_slice_empty_update_contract},
      {"axi_online_backend", test_axi_splits_bursts_and_uses_backend_online},
      {"axi_response_view_order_independent",
       test_axi_response_view_is_registration_order_independent},
      {"candidate10_axi_adapter_schedule",
       test_candidate10_axi_adapter_schedule_matches_rtl_oracle},
      {"candidate10_axi_periodic_backpressure",
       test_candidate10_axi_periodic_backpressure_trace},
      {"axi_periodic_stall_validation",
       test_axi_periodic_stall_validation_and_phase},
      {"memory_backend_locality",
       test_memory_backend_tracks_per_initiator_locality_and_epochs},
      {"memory_registered_arbiter",
       test_registered_channel_arbiter_is_order_independent_and_fair},
      {"axi_response_backpressure", test_axi_response_backpressure_is_lossless},
      {"axi_payload_round_trip",
       test_axi_payload_round_trip_across_beats_and_bursts},
      {"memory_backend_payload_pages",
       test_memory_backend_payload_pages_preserve_sparse_fill_semantics},
      {"axi_read_beat_stream",
       test_axi_read_beat_stream_is_bounded_and_request_scoped},
      {"axi_multi_initiator", test_axi_multi_initiator_fixed_channel_isolation},
      {"axi_duplicate_initiator", test_axi_rejects_duplicate_initiator_id},
      {"spine_l0_real_slice", test_spine_l0_real_slice_vertical_path},
      {"spine_candidate10_one_pass",
       test_spine_candidate10_one_pass_publication_payloads},
      {"spine_candidate10_hot_metadata_carry",
       test_spine_candidate10_hot_metadata_carry_retires_new_batch_request},
      {"spine_candidate10_publication_formula",
       test_spine_candidate10_publication_rtl_window_formula},
      {"spine_candidate10_l0_writer_formula",
       test_spine_candidate10_l0_writer_rtl_formula},
      {"spine_candidate10_repeated_frontier",
       test_spine_candidate10_repeated_frontier_uses_grouped_payload_reads},
      {"spine_candidate10_boundaries",
       test_spine_candidate10_block_and_publication_window_boundaries},
      {"spine_candidate10_zero_edge", test_spine_candidate10_zero_edge_batch},
      {"spine_dirty_persistent_state",
       test_spine_dirty_mark_preserves_persistent_state},
      {"spine_reusable_system",
       test_spine_reusable_system_matches_vertical_slice},
      {"spine_host_active_bin_builder",
       test_spine_host_active_bin_builder_matches_scan_reference},
      {"spine_host_dirty_coverage",
       test_spine_host_active_requires_exact_dirty_coverage},
      {"spine_device_dirty_request_windows",
       test_spine_device_dirty_source_request_windows},
      {"spine_host_source_refresh",
       test_spine_host_source_refresh_includes_edgeless_vertices},
      {"spine_host_active_gate_fallback",
       test_spine_host_active_gate_runs_tiled_fallback},
      {"spine_device_dirty_host_handoff",
       test_spine_device_dirty_limit_hands_off_to_host},
      {"spine_device_task_limit_handoffs",
       test_spine_device_task_limits_hand_off_to_tiled_fallback},
      {"spine_convergence_host_handoff",
       test_spine_convergence_runner_records_host_handoff},
      {"spine_convergence_4097_host_handoff",
       test_spine_convergence_runner_separates_host_replay_from_frontier},
      {"spine_dirty_ack_rejections",
       test_spine_dirty_ack_rejects_stale_and_malformed_candidates},
      {"spine_source_protocol_error",
       test_spine_compute_rejects_malformed_source_protocol},
      {"spine_cold_l1_carry", test_spine_cold_l1_carry_and_reader},
      {"spine_carry_kway_refill", test_spine_carry_kway_refill_pipeline},
      {"spine_carry_writer_packer_boundaries",
       test_spine_carry_writer_crosses_page_and_packer_boundaries},
      {"spine_hot_cold_targets", test_spine_independent_hot_and_cold_targets},
      {"spine_fixed_level_layout",
       test_spine_fixed_level_layout_matches_stable_profile},
      {"spine_signed_diff_cancellation",
       test_spine_carry_drops_signed_diff_cancellation},
      {"spine_full_tile_boundaries", test_spine_full_tile_threshold_boundaries},
      {"spine_compute_gather_outstanding",
       test_spine_compute_gather_uses_bounded_outstanding_requests},
      {"spine_compute_store_bundle_overlap",
       test_spine_compute_overlaps_independent_store_bundles},
      {"spine_cross_tile_write_overlap",
       test_spine_cross_tile_write_response_overlap},
      {"spine_full_tile_axis_backpressure",
       test_spine_full_tile_load_replay_backpressures_axis},
      {"spine_tiny_duplicate_gather",
       test_spine_tiny_gather_preserves_duplicate_reads},
      {"spine_onchip_memory_profile",
       test_spine_on_chip_memory_profile_and_access_ledger},
      {"spine_compute_hbm_payload",
       test_spine_compute_consumes_vertex_payload_from_hbm},
      {"spine_full_tile_stream_payload",
       test_spine_full_tile_consumes_streamed_vertex_payload},
      {"spine_reader_hbm_graph_payload",
       test_spine_reader_consumes_graph_edge_payload_from_hbm},
      {"spine_target_hbm_metadata_payload",
       test_spine_target_selector_consumes_metadata_payload_from_hbm},
      {"spine_hot_hbm_bitmap_payload",
       test_spine_hot_classifier_consumes_bitmap_payload_from_hbm},
      {"spine_overflow_result_payload",
       test_spine_logical_overflow_writes_complete_result},
      {"spine_full_hierarchy_result_payload",
       test_spine_full_hierarchy_overflow_preserves_dirty_result},
      {"spine_l0_epoch_wrap",
       test_spine_l0_epoch_wrap_reads_hbm_and_clears_index},
      {"spine_l0_level_escalation",
       test_spine_l0_skips_undersized_empty_targets},
      {"spine_raw_family_capacity_bound",
       test_spine_capacity_selector_uses_raw_family_input_bound},
      {"spine_resident_multilevel",
       test_spine_resident_snapshot_spans_fixed_levels},
      {"spine_resident_hot_classification",
       test_spine_resident_snapshot_auto_promotes_hot_destinations},
      {"spine_resident_superhub_capacity",
       test_spine_resident_snapshot_rejects_superhub},
      {"spine_carry_epoch_wrap",
       test_spine_carry_epoch_wrap_uses_fixed_target_clear},
      {"spine_capacity_safe_reject",
       test_spine_capacity_selector_rejects_before_writer},
      {"spine_maintenance_hbm_sorted_payload",
       test_spine_maintenance_consumes_sorted_payload_from_hbm},
      {"spine_carry_hbm_level_payload",
       test_spine_carry_merge_consumes_level_payload_from_hbm},
      {"spine_carry_stale_page_epoch",
       test_spine_carry_rejects_stale_page_epoch},
      {"spine_hls_metadata_active_abi",
       test_spine_hls_metadata_and_active_record_abi},
      {"spine_multiround_weighted_sssp",
       test_spine_multiround_weighted_sssp_converges},
      {"spine_incremental_update",
       test_spine_incremental_update_reuses_persistent_system},
      {"spine_nonmonotonic_full_rebuild",
       test_spine_nonmonotonic_update_uses_timed_full_rebuild},
      {"spine_memory_request_window",
       test_spine_memory_request_window_hides_latency},
      {"spine_axi_interface_profile",
       test_spine_axi_interface_profile_matches_hls_rtl},
      {"spine_edge_pipeline",
       test_spine_edge_pipeline_is_ordered_bounded_and_latency_hiding},
      {"spine_l0_writer_backpressure",
       test_spine_l0_online_writer_backpressure_is_finite},
      {"spine_candidate10_writer_backpressure",
       test_spine_candidate10_writer_propagates_finite_queue_backpressure},
      {"spine_edge_pipeline_backpressure",
       test_spine_edge_pipeline_propagates_axis_backpressure},
      {"algorithm_policy_invalid",
       test_algorithm_policy_rejects_invalid_configuration},
      {"algorithm_policy_profiles",
       test_algorithm_policy_profiles_and_update_modes},
      {"algorithm_policy_connected_components",
       test_connected_components_algorithm_policy_semantics},
      {"algorithm_policy_weighted_sssp",
       test_weighted_sssp_algorithm_policy_semantics},
      {"algorithm_policy_full_pagerank",
       test_full_pagerank_algorithm_policy_semantics},
      {"algorithm_policy_residual_pagerank",
       test_residual_pagerank_algorithm_policy_semantics},
      {"algorithm_policy_delta_hls_residual",
       test_delta_hls_residual_pagerank_contract},
      {"algorithm_state_layout",
       test_algorithm_state_layout_shares_one_hbm_channel},
      {"algorithm_pipeline",
       test_algorithm_pipeline_models_latency_ii_capacity_and_backpressure},
      {"spine_timed_pagerank_compute",
       test_spine_timed_full_pagerank_compute_uses_hbm_and_pipelines},
      {"spine_pagerank_vertical_slice",
       test_spine_full_pagerank_vertical_slice_reads_level_edges},
      {"spine_pagerank_active_gate_fallback",
       test_spine_pagerank_active_gate_fallback_preserves_tile_identity},
      {"spine_pagerank_fallback_level_cache_reuse",
       test_spine_pagerank_fallback_reuses_launch_level_cache},
      {"spine_pagerank_source_page_cache",
       test_spine_pagerank_source_page_cache_is_finite_and_exact},
      {"spine_pagerank_maintenance_failure",
       test_spine_pagerank_reports_maintenance_failure_without_compute_done},
      {"spine_dynamic_pagerank",
       test_spine_dynamic_pagerank_times_only_update_then_final_graph},
      {"spine_residual_pagerank",
       test_spine_residual_pagerank_tracks_thresholded_frontier},
      {"spine_connected_components",
       test_spine_connected_components_converges_with_min_labels},
      {"spine_delta_hls_warm_residual",
       test_spine_delta_hls_residual_uses_warm_seed_frontier},
  };
  const std::string filter = argc > 1 ? argv[1] : "";
  std::size_t failures = 0;
  std::size_t executed = 0;
  for (const auto &[name, test] : tests) {
    if (!filter.empty() && name.find(filter) == std::string::npos) {
      continue;
    }
    ++executed;
    try {
      test();
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception &error) {
      ++failures;
      std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    }
  }
  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return 1;
  }
  std::cout << executed << " test(s) passed\n";
  return 0;
}
