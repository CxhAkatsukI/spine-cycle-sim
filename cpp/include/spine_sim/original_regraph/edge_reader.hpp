#pragma once

#include "spine_sim/original_regraph/frontend_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

struct EdgeReaderCounters {
  std::uint64_t physical_edges{};
  std::uint64_t read_bytes{};
  std::uint64_t parent_requests{};
  std::uint64_t acknowledgements{};
};

class LittleEdgeReader final : public Component {
 public:
  LittleEdgeReader(std::string name, ClockId clock, ReadPort memory,
                   Fifo<EdgeBurst>& output, PipelineTiming timing = kEdgeReaderTiming);
  void begin_partition(std::uint64_t address, std::uint64_t physical_edges,
                       std::uint32_t destination_offset);
  bool finished() const noexcept;
  const EdgeReaderCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  ReadPort memory_;
  Fifo<EdgeBurst>& output_;
  detail::LatencyPipe<EdgeBurst> pipeline_;
  std::uint64_t next_transaction_{1};
  std::uint64_t transaction_{};
  std::uint64_t address_{};
  std::uint64_t bursts_{};
  std::uint64_t received_{};
  std::uint32_t destination_offset_{};
  bool started_{};
  bool issued_{};
  bool acknowledged_{};
  bool stage_issue_{};
  bool stage_ack_{};
  bool stage_beat_{};
  EdgeReaderCounters counters_;
};

}  // namespace spine::sim::original_regraph
