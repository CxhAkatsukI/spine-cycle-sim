#pragma once

#include "spine_sim/original_regraph/big_gather.hpp"

namespace spine::sim::original_regraph {

class BigResultPacker final : public Component {
 public:
  BigResultPacker(std::string name, ClockId clock,
      std::array<Fifo<VertexPair>*, kGatherLanes> inputs, Fifo<PropertyLine>& output,
      PipelineTiming timing = BigTiming{}.pack);
  void begin_partition();
  bool finished() const noexcept { return remaining_ == 0 && pipeline_.drained(); }
  const PipelineCounters& counters() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  std::array<Fifo<VertexPair>*, kGatherLanes> inputs_;
  Fifo<PropertyLine>& output_;
  detail::LatencyPipe<PropertyLine> pipeline_;
  std::size_t remaining_{};
  bool accepted_{};
};

class BigGlobalMerge final : public Component {
 public:
  BigGlobalMerge(std::string name, ClockId clock, std::vector<Fifo<PropertyLine>*> inputs,
      Fifo<PropertyLine>& output, PipelineTiming timing = BigTiming{}.merge);
  void begin_partition();
  void begin_partitions(unsigned count);
  bool finished() const noexcept { return remaining_ == 0 && pipeline_.drained(); }
  const PipelineCounters& counters() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  std::vector<Fifo<PropertyLine>*> inputs_;
  Fifo<PropertyLine>& output_;
  detail::LatencyPipe<PropertyLine> pipeline_;
  std::size_t remaining_{};
  bool accepted_{};
};

}  // namespace spine::sim::original_regraph
