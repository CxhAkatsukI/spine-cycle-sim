#pragma once

#include <array>
#include <optional>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

using GatherOutputs = std::array<Fifo<VertexPair>*, kGatherLanes>;

struct GatherCounters {
  std::uint64_t bursts{};
  std::uint64_t valid_updates{};
  std::uint64_t dummy_updates{};
  std::uint64_t forwarded_reads{};
  std::uint64_t uram_reads{};
  std::uint64_t uram_writes{};
  std::uint64_t drain_read_pairs{};
  std::uint64_t drain_clear_pairs{};
  std::uint64_t partitions{};
  std::uint64_t input_wait_cycles{};
};

class LittleGather final : public Component {
 public:
  LittleGather(std::string name, ClockId clock, Fifo<UpdateBurst>& input,
               GatherOutputs outputs, LittleTiming timing = {});
  void begin_partition(std::uint64_t bursts);
  bool finished() const noexcept;
  const GatherCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& gather_pipeline() const noexcept {
    return updates_.counters();
  }
  const PipelineCounters& drain_pipeline() const noexcept {
    return drain_.counters();
  }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  enum class Phase { kFinished, kGather, kDrain };
  struct Write {
    std::size_t row{};
    VertexPair value{};
    bool valid{};
  };
  using Writes = std::array<Write, kGatherLanes>;
  Writes map_updates(const UpdateBurst&);

  Fifo<UpdateBurst>& input_;
  GatherOutputs outputs_;
  std::array<std::vector<VertexPair>, kGatherLanes> memory_;
  std::array<std::array<Write, kForwardingEntries>, kGatherLanes> forwarding_{};
  detail::LatencyPipe<UpdateBurst> updates_;
  detail::LatencyPipe<Writes> writes_{{kUramWriteLatency, 1, kForwardingEntries}};
  detail::LatencyPipe<LanePairs> drain_;
  std::optional<UpdateBurst> accepted_;
  std::optional<Writes> retired_writes_;
  std::optional<std::size_t> issued_row_;
  Phase phase_{Phase::kFinished};
  std::uint64_t expected_{};
  std::uint64_t accepted_count_{};
  std::size_t next_row_{};
  GatherCounters counters_;
};

}  // namespace spine::sim::original_regraph
