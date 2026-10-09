#pragma once

#include "spine_sim/original_regraph/big_frontend_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

class BigResponseRouter final : public Component {
 public:
  BigResponseRouter(std::string name, ClockId clock, Fifo<CachelineResponse>& input, LanePropertyPorts outputs);
  void begin_partition();
  bool finished() const noexcept { return finished_; }
  std::uint64_t responses() const noexcept { return responses_; }
  std::uint64_t output_stalls() const noexcept { return output_stalls_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<CachelineResponse>& input_;
  LanePropertyPorts outputs_;
  bool initial_{};
  bool finished_{true};
  std::optional<CachelineResponse> accepted_;
  std::uint64_t responses_{};
  std::uint64_t output_stalls_{};
};

struct BigScatterCounters {
  std::uint64_t bursts{};
  std::uint64_t initial_lines{};
  std::uint64_t lane_lines{};
  std::uint64_t source_lookups{};
  std::uint64_t source_wait_cycles{};
};

class BigScatter final : public Component {
 public:
  BigScatter(std::string name, ClockId clock, Fifo<EdgeBurst>& input, LanePropertyPorts properties,
             Fifo<UpdateBurst>& output, PipelineTiming timing = kScatterTiming);
  void begin_partition(std::uint64_t bursts);
  bool finished() const noexcept { return !remaining_ && initialized_ && pipeline_.drained(); }
  const BigScatterCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<EdgeBurst>& input_;
  LanePropertyPorts properties_;
  Fifo<UpdateBurst>& output_;
  detail::LatencyPipe<UpdateBurst> pipeline_;
  std::uint64_t remaining_{};
  bool initialized_{true};
  bool stage_initial_{};
  bool stage_burst_{};
  PropertyLine last_{};
  std::uint32_t last_line_{};
  PropertyLine next_last_{};
  std::uint32_t next_line_{};
  BigScatterCounters counters_;
};

}  // namespace spine::sim::original_regraph
