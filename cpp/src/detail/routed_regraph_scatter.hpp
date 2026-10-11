#pragma once

#include <deque>

#include "routed_regraph_source.hpp"
#include "spine_sim/regraph_pma_adapter.hpp"

namespace spine::sim::detail {

struct RoutedScatterTiming {
  std::uint64_t latency{4}, initiation_interval{1};
  std::size_t capacity{5};
};

struct RoutedScatterPartition {
  std::size_t physical_slots{}, destination_base{}, destination_vertices{};
  AlgorithmIterationContext iteration{};
};

struct RoutedScatterCounters {
  std::uint64_t packets{}, emitted{}, source_requests{}, source_lines{}, discarded_lines{},
      end_requests{}, end_responses{}, source_waits{}, edge_waits{}, output_stalls{},
      pipeline_stalls{}, request_stalls{}, buffer_write_bytes{};
  std::size_t max_inflight{};
  bool operator==(const RoutedScatterCounters &) const = default;
};

// done() is the Gather input boundary; finished() also includes the source
// terminator drain. Neither waits for the independent raw adapter kernel.
class RoutedScatter final : public Component, public ReGraphReaderContext {
public:
  RoutedScatter(std::string name, ClockId clock, GraphAlgorithmPolicy policy,
                ReGraphPmaFormat format, Fifo<ReGraphPmaPacket> &edges,
                RoutedSourceWorker source, Fifo<PmaEdgeBatch> &output,
                RoutedScatterTiming timing = {});
  void start_partition(RoutedScatterPartition partition);
  [[nodiscard]] bool done() const noexcept override { return stream_done_; }
  [[nodiscard]] bool finished() const noexcept;
  [[nodiscard]] AlgorithmIterationContext iteration_context() const noexcept override { return partition_.iteration; }
  [[nodiscard]] const RoutedScatterCounters &counters() const noexcept { return counters_; }
  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

private:
  enum class Phase { kIdle, kRequest, kResponse, kEdge, kEmit, kEndRequest, kDrain, kFinished };
  struct Control {
    Phase phase{Phase::kIdle};
    std::size_t request_round{}, last_request{}, read_round{}, write_round{}, accepted{}, emitted{};
    bool waiting{};
    ReGraphPmaPacket edge;
  };
  struct Entry { std::uint64_t ready; PmaEdgeBatch batch; };
  PmaEdgeBatch map_sources() const;

  GraphAlgorithmPolicy policy_;
  ReGraphPmaFormat format_;
  Fifo<ReGraphPmaPacket> &edges_;
  RoutedSourceWorker source_;
  Fifo<PmaEdgeBatch> &output_;
  RoutedScatterTiming timing_;
  RoutedScatterPartition partition_;
  Control control_, next_;
  std::array<std::array<std::array<std::uint32_t, 16>, kRoutedSourceLines>, 2> cache_{};
  std::array<std::array<std::optional<std::size_t>, kRoutedSourceLines>, 2> valid_{};
  std::optional<ReGraphSourceCacheResponse> loaded_;
  std::deque<Entry> pipeline_;
  std::optional<Entry> accepted_;
  std::uint64_t next_issue_{};
  bool retired_{}, stream_done_{};
  RoutedScatterCounters counters_;
};

} // namespace spine::sim::detail
