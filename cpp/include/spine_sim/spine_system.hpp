#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_l0.hpp"
#include "spine_sim/spine_split.hpp"

namespace spine::sim {

class SpineVerticalSliceSystem {
 public:
  SpineVerticalSliceSystem(Scheduler &scheduler, ClockId clock_id,
                           MemoryBackend &backend, SpineEdgeSlice workload,
                           std::uint32_t source,
                           std::size_t tiny_threshold = 4096,
                           SpineL0Config maintenance_config = {},
                           SpineL0State initial_state = {});

  void register_components();

  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] bool idle() const noexcept;
  [[nodiscard]] const SpineL0Counters &maintenance_counters() const noexcept;
  [[nodiscard]] const SpineReaderCounters &reader_counters() const noexcept;
  [[nodiscard]] const SpineComputeCounters &compute_counters() const noexcept;
  [[nodiscard]] const SpineSplitSsspCompute &compute() const noexcept;
  [[nodiscard]] const SpineL0State &level_state() const noexcept;
  [[nodiscard]] const FifoStats &edge_stream_stats() const noexcept;
  [[nodiscard]] const FifoStats &value_stream_stats() const noexcept;

 private:
  [[nodiscard]] std::unique_ptr<FixedAxiPort> make_port(
      const std::string &name, std::uint32_t initiator_id, std::size_t channel);

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
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
  bool registered_{};
};

}  // namespace spine::sim
