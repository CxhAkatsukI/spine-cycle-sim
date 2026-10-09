#pragma once

#include <optional>
#include <vector>

#include "spine_sim/original_regraph/big_routing.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

struct BigBankCounters {
  std::uint64_t valid_updates{};
  std::uint64_t dummy_updates{};
  std::uint64_t forwarded_reads{};
  std::uint64_t uram_reads{};
  std::uint64_t uram_writes{};
  std::uint64_t drain_read_pairs{};
  std::uint64_t drain_clear_pairs{};
  std::uint64_t ends{};
  std::uint64_t partitions{};
};

class BigGatherBank final : public Component {
 public:
  BigGatherBank(std::string name, ClockId clock, unsigned bank,
                Fifo<RoutedUpdate>& input, Fifo<VertexPair>& output, BigTiming timing = {});
  void begin_partition();
  bool finished() const noexcept { return phase_ == Phase::kFinished; }
  const BigBankCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& gather_pipeline() const noexcept { return updates_.counters(); }
  const PipelineCounters& drain_pipeline() const noexcept { return drain_.counters(); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  enum class Phase { kFinished, kGather, kFlush, kDrain };
  struct Write { std::size_t row{}; VertexPair value{}; bool valid{}; };
  Write accumulate(Update);
  unsigned bank_;
  Fifo<RoutedUpdate>& input_;
  Fifo<VertexPair>& output_;
  std::vector<VertexPair> memory_;
  std::array<Write, kForwardingEntries> forwarding_{};
  detail::LatencyPipe<Update> updates_;
  detail::LatencyPipe<Write> writes_{{kUramWriteLatency, 1, kForwardingEntries}};
  detail::LatencyPipe<VertexPair> drain_;
  Phase phase_{Phase::kFinished};
  std::optional<RoutedUpdate> accepted_;
  std::optional<Write> retired_;
  std::optional<std::size_t> issued_row_;
  std::size_t next_row_{};
  BigBankCounters counters_;
};

}  // namespace spine::sim::original_regraph
