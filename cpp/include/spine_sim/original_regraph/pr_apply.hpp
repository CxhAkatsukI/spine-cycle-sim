#pragma once

#include <deque>
#include <optional>

#include "spine_sim/original_regraph/state_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

struct ApplyCounters {
  std::uint64_t lines{};
  std::uint64_t degree_responses{};
  std::uint64_t degree_bytes{};
  std::uint64_t zero_degree_vertices{};
  std::uint64_t credit_stalls{};
  std::uint64_t request_stalls{};
  std::uint64_t input_terminators{};
  std::uint64_t output_terminators{};
  std::size_t max_live_lines{};
};

class PrApply final : public Component {
 public:
  PrApply(std::string name, ClockId clock, TransactionPort degree,
          Fifo<PropertyWrite>& input, Fifo<PropertyWrite>& output,
          std::uint64_t degree_address, std::uint64_t degree_bytes,
          PipelineTiming timing = kApplyPostReadTiming,
          std::size_t line_credits = kApplyLineCredits);
  void begin(std::uint32_t lines, std::uint32_t argument);
  bool finished() const noexcept { return !active_; }
  const ApplyCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  struct Pending {
    std::uint64_t transaction{};
    PropertyWrite packet;
    std::optional<PropertyLine> degree;
  };
  TransactionPort degree_;
  Fifo<PropertyWrite>& input_;
  Fifo<PropertyWrite>& output_;
  std::uint64_t address_{};
  std::uint64_t bytes_{};
  std::size_t line_credits_{};
  detail::LatencyPipe<PropertyWrite> pipeline_;
  std::deque<Pending> pending_;
  std::uint64_t next_transaction_{1};
  std::uint32_t expected_{};
  std::uint32_t accepted_{};
  std::uint32_t argument_{};
  bool active_{};
  bool input_ended_{};
  std::optional<Pending> staged_input_;
  std::optional<std::pair<std::uint64_t, PropertyLine>> staged_response_;
  bool stage_compute_{};
  bool stage_input_end_{};
  bool stage_output_end_{};
  ApplyCounters counters_;
};

}  // namespace spine::sim::original_regraph
