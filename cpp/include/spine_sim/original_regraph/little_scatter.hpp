#pragma once

#include <optional>
#include <vector>

#include "spine_sim/original_regraph/frontend_types.hpp"
#include "spine_sim/original_regraph/detail/latency_pipe.hpp"

namespace spine::sim::original_regraph {

struct ScatterCounters {
  std::uint64_t bursts{};
  std::uint64_t source_round_requests{};
  std::uint64_t source_lines_loaded{};
  std::uint64_t source_lines_discarded{};
  std::uint64_t buffer_write_bytes{};
  std::uint64_t source_lookups{};
  std::uint64_t end_requests{};
  std::uint64_t end_responses{};
  std::uint64_t source_wait_cycles{};
  std::uint64_t edge_wait_cycles{};
  std::uint64_t request_stalls{};
  std::uint64_t trace_dropped{};
};

class LittleScatter final : public Component {
 public:
  LittleScatter(std::string name, ClockId clock, Fifo<EdgeBurst>& edges,
                Fifo<SourceRequest>& requests, Fifo<SourceResponse>& responses,
                Fifo<UpdateBurst>& updates, PipelineTiming timing = kScatterTiming,
                std::size_t trace_limit = 0);
  void begin_partition(std::uint32_t physical_edges);
  bool finished() const noexcept;
  const ScatterCounters& counters() const noexcept { return counters_; }
  const PipelineCounters& pipeline() const noexcept { return pipeline_.counters(); }
  const std::vector<SourceRequest>& request_trace() const noexcept { return request_trace_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  enum class Phase { kFinished, kRequest, kResponse, kEdge, kEmit, kEndRequest, kDrain };
  struct Control {
    Phase phase{Phase::kFinished};
    std::uint32_t request_round{};
    std::uint32_t last_request_round{};
    std::uint32_t read_round{};
    std::uint32_t write_round{};
    std::uint32_t expected_bursts{};
    std::uint32_t emitted_bursts{};
    bool waiting{};
    EdgeBurst edge{};
  };
  UpdateBurst map_edge(const Control&) const;
  void record_request(SourceRequest);

  Fifo<EdgeBurst>& edges_;
  Fifo<SourceRequest>& requests_;
  Fifo<SourceResponse>& responses_;
  Fifo<UpdateBurst>& updates_;
  detail::LatencyPipe<UpdateBurst> pipeline_;
  std::array<std::array<std::array<PropertyLine, kSourceWindowLines>, 2>, 8> buffers_{};
  std::array<std::array<std::optional<std::uint32_t>, kSourceWindowLines>, 2> valid_{};
  Control control_;
  Control next_;
  std::optional<SourceResponse> loaded_;
  std::size_t trace_limit_{};
  std::vector<SourceRequest> request_trace_;
  ScatterCounters counters_;
};

}  // namespace spine::sim::original_regraph
