#pragma once

#include "spine_sim/original_regraph/state_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

class LittleWriteIndexer final : public Component {
 public:
  LittleWriteIndexer(std::string name, ClockId clock, Fifo<PropertyLine>& input,
                     Fifo<PropertyWrite>& output, PipelineTiming timing = kWriteIndexTiming);
  void begin(std::uint32_t lines);
  bool finished() const noexcept { return !active_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  Fifo<PropertyLine>& input_;
  Fifo<PropertyWrite>& output_;
  detail::LatencyPipe<PropertyWrite> pipeline_;
  std::uint32_t expected_{};
  std::uint32_t indexed_{};
  bool active_{};
  bool stage_line_{};
  bool stage_end_{};
};

}  // namespace spine::sim::original_regraph
