#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>

#include "spine_sim/algorithm.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"

namespace spine::sim {

enum class AlgorithmPipelineStage { kSourceMap, kEdgeMap, kReduce, kApply };

struct AlgorithmPipelineRequest {
  AlgorithmPipelineStage stage{AlgorithmPipelineStage::kSourceMap};
  std::uint64_t transaction_id{};
  AlgorithmVertexState state;
  std::uint32_t out_degree{};
  std::uint32_t source_payload{};
  std::uint16_t edge_weight{};
  std::optional<std::uint32_t> current;
  std::uint32_t candidate{};
  std::optional<std::uint32_t> reduced;
  AlgorithmIterationContext context;
};

struct AlgorithmPipelineResponse {
  AlgorithmPipelineStage stage{AlgorithmPipelineStage::kSourceMap};
  std::uint64_t transaction_id{};
  AlgorithmSourceResult source;
  std::uint32_t mapped{};
  std::uint32_t reduced{};
  AlgorithmApplyResult applied;
};

struct AlgorithmPipelineStageConfig {
  std::uint64_t latency_cycles{1};
  std::uint64_t initiation_interval{1};
  std::size_t capacity{16};
};

struct AlgorithmPipelineConfig {
  AlgorithmPipelineStageConfig source_map;
  AlgorithmPipelineStageConfig edge_map;
  AlgorithmPipelineStageConfig reduce;
  AlgorithmPipelineStageConfig apply;
};

struct AlgorithmPipelineStageCounters {
  std::uint64_t accepted{};
  std::uint64_t completed{};
  std::uint64_t initiation_interval_stalls{};
  std::uint64_t capacity_stalls{};
  std::uint64_t output_backpressure_stalls{};
  std::size_t max_inflight{};
};

struct AlgorithmPipelineCounters {
  AlgorithmPipelineStageCounters source_map;
  AlgorithmPipelineStageCounters edge_map;
  AlgorithmPipelineStageCounters reduce;
  AlgorithmPipelineStageCounters apply;
};

struct AlgorithmPipelinePorts {
  Fifo<AlgorithmPipelineRequest> *source_requests{};
  Fifo<AlgorithmPipelineResponse> *source_responses{};
  Fifo<AlgorithmPipelineRequest> *edge_requests{};
  Fifo<AlgorithmPipelineResponse> *edge_responses{};
  Fifo<AlgorithmPipelineRequest> *reduce_requests{};
  Fifo<AlgorithmPipelineResponse> *reduce_responses{};
  Fifo<AlgorithmPipelineRequest> *apply_requests{};
  Fifo<AlgorithmPipelineResponse> *apply_responses{};
};

class AlgorithmPipeline final : public Component {
 public:
  AlgorithmPipeline(std::string name, ClockId clock_id,
                    GraphAlgorithmPolicy policy,
                    AlgorithmPipelineConfig config,
                    AlgorithmPipelinePorts ports);

  [[nodiscard]] const GraphAlgorithmPolicy &policy() const noexcept {
    return policy_;
  }
  [[nodiscard]] const AlgorithmPipelineConfig &config() const noexcept {
    return config_;
  }
  [[nodiscard]] const AlgorithmPipelineCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] bool drained() const noexcept;

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  struct Completion {
    std::uint64_t due_cycle{};
    AlgorithmPipelineResponse response;
  };

  struct StageState {
    AlgorithmPipelineStage kind{AlgorithmPipelineStage::kSourceMap};
    Fifo<AlgorithmPipelineRequest> *requests{};
    Fifo<AlgorithmPipelineResponse> *responses{};
    AlgorithmPipelineStageConfig config;
    std::deque<Completion> completions;
    std::optional<AlgorithmPipelineRequest> staged_request;
    std::optional<std::uint64_t> last_accept_cycle;
    bool staged_retire{};
  };

  void validate_stage(const StageState &stage) const;
  void evaluate_stage(StageState &stage,
                      AlgorithmPipelineStageCounters &counters,
                      const CycleContext &context);
  void commit_stage(StageState &stage,
                    AlgorithmPipelineStageCounters &counters,
                    const CycleContext &context);
  [[nodiscard]] AlgorithmPipelineResponse execute(
      const AlgorithmPipelineRequest &request) const;

  GraphAlgorithmPolicy policy_;
  AlgorithmPipelineConfig config_;
  AlgorithmPipelinePorts ports_;
  AlgorithmPipelineCounters counters_;
  StageState source_map_;
  StageState edge_map_;
  StageState reduce_;
  StageState apply_;
};

}  // namespace spine::sim
