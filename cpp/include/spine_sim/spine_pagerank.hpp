#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "spine_sim/algorithm_pipeline.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/spine_split.hpp"

namespace spine::sim {

struct SpinePageRankCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t source_protocol_markers{};
  std::uint64_t source_protocol_acks{};
  std::uint32_t source_protocol_status{};
  std::uint32_t source_count{};
  std::uint64_t source_map_operations{};
  std::uint64_t dangling_reduce_operations{};
  std::uint64_t tiles_received{};
  std::uint64_t empty_tiles_applied{};
  std::uint64_t edges_received{};
  std::uint64_t edge_reduce_operations{};
  std::uint64_t vertices_applied{};
  std::uint64_t vertices_activated{};
  std::uint64_t primary_read_bytes{};
  std::uint64_t primary_write_bytes{};
  std::uint64_t auxiliary_read_bytes{};
  std::uint64_t auxiliary_write_bytes{};
  std::uint64_t degree_read_bytes{};
  std::uint64_t active_out_write_bytes{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t memory_window_stall_cycles{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::size_t max_memory_requests_inflight{};
  std::size_t max_edge_reductions_inflight{};
  std::size_t max_apply_operations_inflight{};
  std::uint64_t done_words{};
};

class SpineSplitPageRankCompute final : public Component {
 public:
  static constexpr std::size_t kDefaultMemoryRequestWindow = 16;
  static constexpr std::size_t kDefaultTileVertices = 65'536;

  SpineSplitPageRankCompute(
      std::string name, ClockId clock_id, GraphAlgorithmPolicy policy,
      std::vector<std::uint32_t> out_degrees, FixedAxiPort &vertex_state,
      FixedAxiPort *active_out,
      Fifo<PartConvWord> &edge_in, Fifo<SourceValueWord> &value_out,
      AlgorithmPipelineConfig pipeline_config = {},
      std::size_t memory_request_window = kDefaultMemoryRequestWindow,
      std::size_t tile_vertices = kDefaultTileVertices,
      std::optional<AlgorithmInitialState> initial_state = std::nullopt);

  void register_components(Scheduler &scheduler);
  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::vector<std::uint32_t> &rank_words() const noexcept {
    return rank_words_;
  }
  [[nodiscard]] const std::vector<std::uint32_t> &residual_words() const
      noexcept {
    return residual_words_;
  }
  [[nodiscard]] const std::vector<std::uint32_t> &next_active() const noexcept {
    return next_active_;
  }
  [[nodiscard]] GraphAlgorithmKind algorithm_kind() const noexcept {
    return policy_.config().kind;
  }
  [[nodiscard]] const SpinePageRankCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] const AlgorithmPipelineCounters &pipeline_counters() const
      noexcept {
    return pipeline_.counters();
  }
  [[nodiscard]] const AlgorithmStateLayout &state_layout() const noexcept {
    return state_layout_;
  }
  [[nodiscard]] std::uint64_t primary_read_base() const noexcept {
    return primary_read_base_;
  }
  [[nodiscard]] std::uint64_t primary_write_base() const noexcept {
    return primary_write_base_;
  }
  [[nodiscard]] float dangling_mass() const noexcept;
  [[nodiscard]] float dangling_share() const noexcept;
  [[nodiscard]] float iteration_error() const noexcept {
    return iteration_error_;
  }
  void reset_iteration();

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  enum class Phase {
    kInput,
    kSourceMemory,
    kSourceMapPush,
    kSourceMapWait,
    kDanglingReducePush,
    kDanglingReduceWait,
    kSourceStateWriteWait,
    kSourceReply,
    kApplyTile,
    kFinish,
  };

  enum class MemoryPayloadKind {
    kSourcePrimary,
    kSourceAuxiliary,
    kSourceDegree,
    kApplyPrimary,
    kApplyAuxiliary,
    kSourcePrimaryWrite,
    kSourceAuxiliaryWrite,
    kApplyPrimaryWrite,
    kApplyAuxiliaryWrite,
    kActiveOutputWrite,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{4};
    std::vector<std::uint8_t> write_data;
    MemoryPayloadKind kind{MemoryPayloadKind::kSourcePrimary};
    std::uint32_t vertex{};
  };

  struct EdgeReduction {
    std::uint32_t destination{};
  };

  struct ReadyApply {
    std::uint32_t vertex{};
    AlgorithmVertexState old_state;
    std::optional<std::uint32_t> reduced;
  };

  enum class InputAction {
    kNone,
    kSourceRequest,
    kSourceCount,
    kSourceGeneration,
    kSourceDone,
    kTileBegin,
    kEdge,
    kTileEnd,
    kDiagnostic,
    kDoneAll,
  };

  void initialize_state_payload(
      const std::vector<std::uint32_t> &out_degrees,
      const std::optional<AlgorithmInitialState> &initial_state);
  void enqueue_read(std::uint64_t address, MemoryPayloadKind kind,
                    std::uint32_t vertex);
  void enqueue_write(std::uint64_t address, std::uint32_t value,
                     MemoryPayloadKind kind, std::uint32_t vertex);
  void enqueue_active_output(std::size_t index, std::uint32_t vertex,
                             std::uint32_t value);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  void begin_apply_tile(std::uint32_t tile_base, bool empty_tile);
  void advance_after_apply_tile();
  [[nodiscard]] std::optional<std::uint32_t> next_unapplied_tile() const;
  [[nodiscard]] bool memory_drained() const noexcept;
  [[nodiscard]] bool algorithm_queues_drained() const noexcept;
  [[nodiscard]] bool tile_apply_drained() const noexcept;
  void set_protocol_status(SpineSourceProtocolStatus status);

  GraphAlgorithmPolicy policy_;
  std::size_t vertices_{};
  std::size_t tile_vertices_{};
  FixedAxiPort &vertex_state_;
  FixedAxiPort *active_out_{};
  Fifo<PartConvWord> &edge_in_;
  Fifo<SourceValueWord> &value_out_;
  AlgorithmStateLayout state_layout_;
  std::uint64_t primary_read_base_{};
  std::uint64_t primary_write_base_{};
  std::size_t memory_request_window_{};

  Fifo<AlgorithmPipelineRequest> source_requests_;
  Fifo<AlgorithmPipelineResponse> source_responses_;
  Fifo<AlgorithmPipelineRequest> edge_requests_;
  Fifo<AlgorithmPipelineResponse> edge_responses_;
  Fifo<AlgorithmPipelineRequest> reduce_requests_;
  Fifo<AlgorithmPipelineResponse> reduce_responses_;
  Fifo<AlgorithmPipelineRequest> apply_requests_;
  Fifo<AlgorithmPipelineResponse> apply_responses_;
  AlgorithmPipeline pipeline_;

  SpinePageRankCounters counters_;
  std::vector<std::uint32_t> rank_words_;
  std::vector<std::uint32_t> residual_words_;
  std::vector<std::uint32_t> next_active_;
  std::vector<bool> tile_applied_;
  std::vector<std::uint32_t> tile_accumulators_;
  std::deque<MemoryTask> memory_tasks_;
  std::unordered_map<std::uint64_t, MemoryTask> inflight_memory_;
  std::unordered_map<std::uint64_t, EdgeReduction> edge_reductions_;
  std::unordered_map<std::uint64_t, std::uint32_t> apply_transactions_;
  std::unordered_set<std::uint32_t> pending_destinations_;
  std::deque<ReadyApply> ready_apply_;

  Phase phase_{Phase::kInput};
  InputAction staged_input_action_{InputAction::kNone};
  PartConvWord staged_input_word_;
  std::optional<std::pair<std::uint64_t, AxiResponse>> staged_memory_response_;
  std::optional<AlgorithmPipelineResponse> staged_source_response_;
  std::optional<AlgorithmPipelineResponse> staged_reduce_response_;
  std::optional<AlgorithmPipelineResponse> staged_apply_response_;
  std::optional<AlgorithmPipelineRequest> staged_source_request_;
  std::optional<AlgorithmPipelineRequest> staged_reduce_request_;
  std::optional<AlgorithmPipelineRequest> staged_apply_request_;
  std::optional<std::uint32_t> staged_apply_read_vertex_;
  std::optional<Phase> staged_phase_transition_;
  bool staged_memory_issue_{};
  bool staged_value_push_{};
  bool staged_apply_tile_complete_{};
  bool staged_done_{};
  SourceValueWord staged_value_word_;

  std::uint64_t next_memory_transaction_{};
  std::uint64_t next_algorithm_transaction_{};
  std::uint32_t pending_source_{};
  std::optional<std::uint32_t> pending_source_rank_;
  std::optional<std::uint32_t> pending_source_residual_;
  std::optional<std::uint32_t> pending_source_degree_;
  std::optional<AlgorithmSourceResult> pending_source_result_;
  std::optional<std::uint64_t> pending_dangling_transaction_;
  std::uint32_t dangling_mass_word_{};
  std::uint32_t dangling_share_word_{};
  std::uint32_t tile_base_{};
  std::size_t tile_size_{};
  std::size_t apply_reads_issued_{};
  std::size_t apply_reads_completed_{};
  std::size_t apply_operations_issued_{};
  std::size_t apply_operations_completed_{};
  std::size_t apply_writes_completed_{};
  float iteration_error_{};
  bool source_count_seen_{};
  bool source_generation_seen_{};
  bool source_ack_pending_{};
  bool tile_open_{};
  bool reader_done_seen_{};
  bool registered_{};
  bool done_{};
  bool failed_{};
};

}  // namespace spine::sim
