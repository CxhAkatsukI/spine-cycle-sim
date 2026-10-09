#pragma once

#include "spine_sim/original_regraph/state_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

// Author merge_big_little_writes: independent address counters, Little priority.
class MixedWriteIndexer final : public Component {
 public:
  MixedWriteIndexer(std::string name, ClockId clock, Fifo<PropertyLine>& little,
      Fifo<PropertyLine>& big, Fifo<PropertyWrite>& output,
      PipelineTiming timing = kWriteIndexTiming);
  void begin(std::uint32_t little_lines, std::uint32_t big_lines);
  bool finished() const noexcept { return !active_; }
  const PipelineCounters& counters() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  Fifo<PropertyLine>& little_;
  Fifo<PropertyLine>& big_;
  Fifo<PropertyWrite>& output_;
  detail::LatencyPipe<PropertyWrite> pipeline_;
  std::uint32_t little_lines_{}, big_lines_{}, little_index_{}, big_index_{};
  bool active_{}, accepted_little_{}, accepted_big_{}, ended_{};
};

}  // namespace spine::sim::original_regraph
