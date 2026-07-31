#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_dirty.hpp"
#include "spine_sim/spine_l0.hpp"
#include "spine_sim/spine_pagerank.hpp"
#include "spine_sim/spine_split.hpp"

namespace spine::sim {

enum class SpineAxiPortKind {
  kGraph,
  kSortedEdges,
  kActiveBins,
  kMetadata,
  kMaintenanceResult,
  kVertexState,
  kActiveOut,
  kActiveBitmap,
  kComputeResult,
};

struct SpineAxiInterfaceProfile {
  std::string profile_id{"hls_split_9c08763"};
  std::uint32_t max_burst_beats{16};
  std::size_t readwrite_max_pending_requests{7};
  std::size_t writeonly_max_pending_requests{4};
  // Zero means use the corresponding generic/compute capacity above.
  std::size_t maintenance_readwrite_max_pending_requests{};
  std::size_t maintenance_writeonly_max_pending_requests{};
  std::size_t max_outstanding_bursts{16};
  std::size_t response_beats_per_cycle{1};
  std::size_t read_reorder_capacity{32};
  std::uint64_t read_address_pipeline_cycles{};
  std::uint64_t read_data_pipeline_cycles{};
  std::uint64_t write_buffer_pipeline_cycles{};
  bool serialize_write_bursts{};
  std::size_t write_ingress_fifo_depth{};
  std::size_t write_throttle_fifo_depth{};
  std::uint64_t write_ingress_pipeline_cycles{};
  std::uint64_t write_address_after_full_burst_cycles{};
  // Zero/false means inherit the generic/compute setting above.
  std::size_t maintenance_read_reorder_capacity{};
  std::uint64_t maintenance_read_address_pipeline_cycles{};
  std::uint64_t maintenance_read_data_pipeline_cycles{};
  std::uint64_t maintenance_write_buffer_pipeline_cycles{};
  bool maintenance_serialize_write_bursts{};
  std::size_t maintenance_write_ingress_fifo_depth{};
  std::size_t maintenance_write_throttle_fifo_depth{};
  std::uint64_t maintenance_write_ingress_pipeline_cycles{};
  std::uint64_t maintenance_write_address_after_full_burst_cycles{};
  std::size_t burst_trace_limit{};
  std::uint32_t graph_bytes{8};
  std::uint32_t sorted_edge_bytes{16};
  std::uint32_t active_bin_bytes{32};
  std::uint32_t metadata_bytes{8};
  std::uint32_t result_bytes{4};
  // Zero means use result_bytes for the maintenance result port.
  std::uint32_t maintenance_result_bytes{};
  std::uint32_t vertex_state_bytes{4};
  std::uint32_t active_out_bytes{8};
  std::uint32_t active_bitmap_bytes{8};

  [[nodiscard]] static SpineAxiInterfaceProfile legacy_uniform64();
  [[nodiscard]] static SpineAxiInterfaceProfile candidate10_1e61fc0();
  [[nodiscard]] FixedAxiPortConfig
  port_config(SpineAxiPortKind kind, std::size_t memory_channels,
              std::size_t channel, std::uint32_t initiator_id) const;
};

struct SpineSsspRoundEvidence {
  std::size_t round{};
  // Map-reduce frontier for the logical algorithm round.
  std::vector<std::uint32_t> active_in;
  // Physical sources consumed by the reader, including host fallback replay.
  std::vector<std::uint32_t> reader_sources;
  std::vector<std::uint32_t> active_out;
  SpineReaderCounters reader;
  SpineComputeCounters compute;
  FifoStats edge_axis;
  FifoStats value_axis;
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
};

struct SpineHostHandoffEvidence {
  std::size_t logical_round{};
  std::uint32_t fallback_reason{};
  std::size_t source_count{};
  std::uint64_t host_list_read_bytes{};
  std::uint64_t host_control_cycles{};
  bool host_control_timed{};
  SpineSsspRoundEvidence device_attempt;
};

struct SpineSsspRunResult {
  bool converged{};
  bool failed{};
  std::vector<SpineSsspRoundEvidence> rounds;
  std::vector<SpineHostHandoffEvidence> host_handoffs;
  std::optional<SpineDirtyAckCounters> dirty_ack;
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
};

struct SpineInitialActiveOutputCounters {
  bool enabled{};
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::size_t active_vertices{};
  std::uint64_t write_bytes{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::size_t max_memory_requests_inflight{};
};

// Builds the untimed host-side HOST_ACTIVE payload consumed by the reader.
// The emitted records preserve source order and duplicate-source semantics.
[[nodiscard]] SpineActiveBins build_spine_host_active_bins(
    const SpineL0State &state, const SpineL0Config &config,
    const std::vector<std::uint32_t> &sources,
    const std::vector<std::uint32_t> &values);

class SpineVerticalSliceSystem {
 public:
  SpineVerticalSliceSystem(Scheduler &scheduler, ClockId clock_id,
                           MemoryBackend &backend, SpineEdgeSlice workload,
                           std::uint32_t source,
                           std::size_t tiny_threshold = 4096,
                           SpineL0Config maintenance_config = {},
                           SpineL0State initial_state = {},
                           SpineAxiInterfaceProfile axi_profile = {},
                           std::size_t compute_memory_request_window =
                               SpineSplitSsspCompute::kDefaultMemoryRequestWindow,
                           std::size_t compute_writeonly_request_window =
                               SpineSplitSsspCompute::
                                   kDefaultWriteOnlyRequestWindow,
                           SpineOnChipMemoryProfile on_chip_profile = {},
                           bool initial_host_active = false,
                           std::optional<AlgorithmInitialState>
                               algorithm_initial_state = std::nullopt);

  void register_components();
  void restart_device_active_compute(std::vector<std::uint32_t> active_sources);
  void restart_read_compute(
      std::vector<std::uint32_t> active_sources,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt);
  void restart_read_compute_bins(
      const SpineActiveBins &active_bins,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt,
      std::vector<std::uint32_t> source_refresh = {});
  void restart_incremental_update(SpineEdgeSlice workload);
  void restart_full_rebuild(SpineEdgeSlice snapshot);
  [[nodiscard]] std::vector<std::uint32_t>
  restart_device_dirty_host_fallback();
  [[nodiscard]] bool recoverable_host_handoff() const noexcept;
  void start_dirty_ack();
  [[nodiscard]] bool dirty_ack_started() const noexcept;
  [[nodiscard]] bool dirty_ack_done() const noexcept;
  [[nodiscard]] bool resident_bootstrap_pending() const noexcept;
  [[nodiscard]] SpineSsspRunResult run_sssp_to_convergence(
      std::size_t max_rounds, std::uint64_t max_events_per_round);

  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] bool idle() const noexcept;
  [[nodiscard]] const SpineL0Counters &maintenance_counters() const noexcept;
  [[nodiscard]] const SpineReaderCounters &reader_counters() const noexcept;
  [[nodiscard]] std::vector<std::uint32_t> reader_source_ids() const;
  [[nodiscard]] const SpineComputeCounters &compute_counters() const noexcept;
  [[nodiscard]] const SpineDirtyAckCounters &dirty_ack_counters() const
      noexcept;
  [[nodiscard]] const SpineSplitSsspCompute &compute() const noexcept;
  [[nodiscard]] const SpineL0State &level_state() const noexcept;
  [[nodiscard]] const FifoStats &edge_stream_stats() const noexcept;
  [[nodiscard]] const FifoStats &value_stream_stats() const noexcept;
  [[nodiscard]] const SpineAxiInterfaceProfile &axi_profile() const noexcept {
    return axi_profile_;
  }
  [[nodiscard]] const AxiConfig &axi_config(SpineAxiPortKind kind) const;
  [[nodiscard]] const AxiStats &axi_stats(SpineAxiPortKind kind) const;
  [[nodiscard]] AxiStats maintenance_axi_stats() const noexcept;

 private:
  [[nodiscard]] std::unique_ptr<FixedAxiPort> make_port(
      const std::string &name, std::uint32_t initiator_id, std::size_t channel,
      SpineAxiPortKind kind);

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  SpineAxiInterfaceProfile axi_profile_;
  std::uint32_t source_{};
  Fifo<PartConvWord> edge_stream_;
  Fifo<SourceValueWord> value_stream_;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports_;
  std::unique_ptr<FixedAxiPort> sorted_;
  std::unique_ptr<FixedAxiPort> metadata_;
  std::unique_ptr<FixedAxiPort> maintenance_result_;
  std::unique_ptr<FixedAxiPort> active_bins_;
  std::unique_ptr<FixedAxiPort> vertex_state_;
  std::unique_ptr<FixedAxiPort> active_out_;
  std::unique_ptr<FixedAxiPort> active_out_reader_;
  std::unique_ptr<FixedAxiPort> active_bitmap_;
  std::unique_ptr<FixedAxiPort> compute_result_;
  SpineL0State state_;
  std::unique_ptr<SpineL0Maintenance> maintenance_;
  std::unique_ptr<SpineSplitReader> reader_;
  std::unique_ptr<SpineSplitSsspCompute> compute_;
  std::unique_ptr<SpineDirtyAck> dirty_ack_;
  std::vector<std::uint32_t> current_frontier_;
  bool registered_{};
  bool convergence_run_started_{};
  bool resident_bootstrap_pending_{};
};

class SpinePageRankVerticalSliceSystem {
 public:
  SpinePageRankVerticalSliceSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      SpineEdgeSlice workload, float damping = 0.85F,
      SpineL0Config maintenance_config = {},
      SpineAxiInterfaceProfile axi_profile = {},
      AlgorithmPipelineConfig pipeline_config = {},
      std::size_t compute_memory_request_window =
          SpineSplitPageRankCompute::kDefaultMemoryRequestWindow,
      SpineL0State initial_state = {},
      std::optional<SpineEdgeSlice> execution_graph = std::nullopt,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt,
      std::optional<AlgorithmInitialState> algorithm_initial_state =
          std::nullopt);
  SpinePageRankVerticalSliceSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      SpineEdgeSlice workload, GraphAlgorithmPolicy policy,
      SpineL0Config maintenance_config = {},
      SpineAxiInterfaceProfile axi_profile = {},
      AlgorithmPipelineConfig pipeline_config = {},
      std::size_t compute_memory_request_window =
          SpineSplitPageRankCompute::kDefaultMemoryRequestWindow,
      SpineL0State initial_state = {},
      std::optional<SpineEdgeSlice> execution_graph = std::nullopt,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt,
      std::optional<AlgorithmInitialState> algorithm_initial_state =
          std::nullopt);

  void register_components();
  void restart_iteration();
  [[nodiscard]] bool maintenance_done() const noexcept;
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] std::string failure() const;
  [[nodiscard]] bool idle() const noexcept;
  [[nodiscard]] const SpineL0Counters &maintenance_counters() const noexcept;
  [[nodiscard]] const SpineReaderCounters &reader_counters() const noexcept;
  [[nodiscard]] const SpinePageRankCounters &compute_counters() const noexcept;
  [[nodiscard]] const SpineInitialActiveOutputCounters &
  initial_active_counters() const noexcept;
  [[nodiscard]] const SpineSplitPageRankCompute &compute() const noexcept;
  [[nodiscard]] const SpineL0State &level_state() const noexcept;
  [[nodiscard]] const FifoStats &edge_stream_stats() const noexcept;
  [[nodiscard]] const FifoStats &value_stream_stats() const noexcept;

 private:
  [[nodiscard]] std::unique_ptr<FixedAxiPort> make_port(
      const std::string &name, std::uint32_t initiator_id, std::size_t channel,
      SpineAxiPortKind kind);

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  SpineAxiInterfaceProfile axi_profile_;
  SpineL0Config maintenance_config_;
  Fifo<PartConvWord> edge_stream_;
  Fifo<SourceValueWord> value_stream_;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports_;
  std::unique_ptr<FixedAxiPort> sorted_;
  std::unique_ptr<FixedAxiPort> metadata_;
  std::unique_ptr<FixedAxiPort> maintenance_result_;
  std::unique_ptr<FixedAxiPort> active_bins_;
  std::unique_ptr<FixedAxiPort> vertex_state_;
  std::unique_ptr<FixedAxiPort> active_seed_out_;
  std::unique_ptr<FixedAxiPort> active_out_;
  std::unique_ptr<FixedAxiPort> active_out_reader_;
  SpineL0State state_;
  std::shared_ptr<const GraphAlgorithmPolicy> algorithm_policy_;
  std::unique_ptr<SpineL0Maintenance> maintenance_;
  std::unique_ptr<SpineSplitReader> reader_;
  std::unique_ptr<SpineSplitPageRankCompute> compute_;
  std::unique_ptr<Component> initial_active_writer_;
  SpineInitialActiveOutputCounters initial_active_counters_;
  SpineActiveBins active_bins_payload_;
  std::vector<std::uint32_t> source_refresh_;
  std::optional<SpineDirtyIdentity> host_coverage_;
  bool initial_active_ready_{true};
  bool initial_active_failed_{};
  std::string initial_active_failure_;
  bool registered_{};
};

}  // namespace spine::sim
