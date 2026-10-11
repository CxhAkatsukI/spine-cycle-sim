#pragma once

#include <deque>
#include <optional>

#include "spine_sim/original_regraph/detail/latency_pipe.hpp"
#include "spine_sim/original_regraph/state_types.hpp"

namespace spine::sim::original_regraph {

// Local SSSP HLS response-to-output schedule, not calibrated A4 timing.
// Capacity two permits II=1 with registered retirement and latency one.
inline constexpr PipelineTiming kSsspSchedulePostReadTiming{1, 1, 2};

struct SsspApplyCounters {
  std::uint64_t lines{};
  std::uint64_t old_state_responses{};
  std::uint64_t old_state_bytes{};
  std::uint64_t active_vertices{};
  std::uint64_t credit_stalls{};
  std::uint64_t request_stalls{};
  std::uint64_t input_terminators{};
  std::uint64_t output_terminators{};
  std::size_t max_live_lines{};
};

class SsspApply final : public Component {
 public:
  // kApplyPostReadTiming is inherited from PR, not audited SSSP HLS timing.
  // response_anchored explicitly starts timing on old-state response acceptance.
  // Output stalls/order dependencies may extend the nominal schedule.
  SsspApply(std::string name, ClockId clock, TransactionPort old_state,
            Fifo<PropertyWrite>& input, Fifo<PropertyWrite>& output,
            std::uint64_t old_state_address, std::uint64_t old_state_bytes,
            PipelineTiming timing = kApplyPostReadTiming,
            std::size_t line_credits = kApplyLineCredits,
            bool response_anchored = false);
  void begin(std::uint32_t lines,
             std::optional<std::uint64_t> old_state_address = std::nullopt);
  // Completion emits the terminator; downstream replica acks belong to the writer.
  bool finished() const noexcept { return !active_; }
  const SsspApplyCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  struct Pending {
    std::uint64_t transaction{};
    PropertyWrite packet;
    std::optional<PropertyLine> old_state;
  };
  TransactionPort old_state_;
  Fifo<PropertyWrite>& input_;
  Fifo<PropertyWrite>& output_;
  std::uint64_t address_{};
  std::uint64_t bytes_{};
  std::size_t line_credits_{};
  bool response_anchored_{};
  detail::LatencyPipe<PropertyWrite> pipeline_;
  std::deque<Pending> pending_;
  std::uint64_t next_transaction_{1};
  std::uint32_t expected_{};
  std::uint32_t accepted_{};
  bool active_{};
  bool input_ended_{};
  std::optional<Pending> staged_input_;
  std::optional<std::pair<std::uint64_t, PropertyLine>> staged_response_;
  std::uint64_t staged_active_vertices_{};
  bool stage_compute_{};
  bool stage_input_end_{};
  bool stage_output_end_{};
  SsspApplyCounters counters_;
};

}  // namespace spine::sim::original_regraph
