#pragma once

#include <optional>
#include <vector>

#include "spine_sim/original_regraph/little_gather.hpp"

namespace spine::sim::original_regraph {

class LittleLocalMerge final : public Component {
 public:
  LittleLocalMerge(std::string name, ClockId clock, GatherOutputs inputs,
                   Fifo<VertexPair>& output, PipelineTiming timing = {3, 1, 4});
  bool drained() const noexcept { return pipeline_.drained(); }
  const PipelineCounters& counters() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  GatherOutputs inputs_;
  Fifo<VertexPair>& output_;
  detail::LatencyPipe<VertexPair> pipeline_;
};

class LittleGlobalMerge final : public Component {
 public:
  LittleGlobalMerge(std::string name, ClockId clock,
                    std::vector<Fifo<VertexPair>*> inputs,
                    Fifo<PropertyLine>& output,
                    PipelineTiming timing = {4, 1, 5});
  bool drained() const noexcept;
  const PipelineCounters& counters() const noexcept { return pipeline_.counters(); }
  std::uint64_t emitted_lines() const noexcept { return emitted_lines_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  std::vector<Fifo<VertexPair>*> inputs_;
  Fifo<PropertyLine>& output_;
  std::vector<std::optional<VertexPair>> held_;
  std::vector<std::optional<VertexPair>> captured_;
  detail::LatencyPipe<VertexPair> pipeline_;
  PropertyLine packing_{};
  std::size_t packed_pairs_{};
  std::optional<VertexPair> retired_;
  bool consumed_{};
  std::uint64_t emitted_lines_{};
};

}  // namespace spine::sim::original_regraph
