#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_dirty.hpp"
#include "spine_sim/spine_l0.hpp"
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
  std::size_t max_outstanding_bursts{16};
  std::size_t response_beats_per_cycle{1};
  std::uint32_t graph_bytes{8};
  std::uint32_t sorted_edge_bytes{16};
  std::uint32_t active_bin_bytes{32};
  std::uint32_t metadata_bytes{8};
  std::uint32_t result_bytes{4};
  std::uint32_t vertex_state_bytes{4};
  std::uint32_t active_out_bytes{8};
  std::uint32_t active_bitmap_bytes{8};

  [[nodiscard]] static SpineAxiInterfaceProfile legacy_uniform64();
  [[nodiscard]] FixedAxiPortConfig
  port_config(SpineAxiPortKind kind, std::size_t memory_channels,
              std::size_t channel, std::uint32_t initiator_id) const;
};

struct SpineSsspRoundEvidence {
  std::size_t round{};
  std::vector<std::uint32_t> active_in;
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
                                   kDefaultWriteOnlyRequestWindow);

  void register_components();
  void restart_read_compute(
      std::vector<std::uint32_t> active_sources,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt);
  void restart_read_compute_bins(
      const SpineActiveBins &active_bins,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt);
  [[nodiscard]] std::vector<std::uint32_t>
  restart_device_dirty_host_fallback();
  [[nodiscard]] bool recoverable_host_handoff() const noexcept;
  void start_dirty_ack();
  [[nodiscard]] bool dirty_ack_started() const noexcept;
  [[nodiscard]] bool dirty_ack_done() const noexcept;
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

 private:
  [[nodiscard]] std::unique_ptr<FixedAxiPort> make_port(
      const std::string &name, std::uint32_t initiator_id, std::size_t channel,
      SpineAxiPortKind kind);

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  SpineAxiInterfaceProfile axi_profile_;
  Fifo<PartConvWord> edge_stream_;
  Fifo<SourceValueWord> value_stream_;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports_;
  std::unique_ptr<FixedAxiPort> sorted_;
  std::unique_ptr<FixedAxiPort> metadata_;
  std::unique_ptr<FixedAxiPort> maintenance_result_;
  std::unique_ptr<FixedAxiPort> active_bins_;
  std::unique_ptr<FixedAxiPort> vertex_state_;
  std::unique_ptr<FixedAxiPort> active_out_;
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
};

}  // namespace spine::sim
