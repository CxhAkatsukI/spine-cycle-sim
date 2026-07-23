#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/spine_l0.hpp"

namespace spine::sim {

enum class PartConvWordKind {
  kSourceRequest,
  kTileBegin,
  kEdge,
  kTileEnd,
  kDoneAll,
};

struct PartConvWord {
  PartConvWordKind kind{PartConvWordKind::kEdge};
  std::uint32_t first{};
  std::uint32_t second{};
};

struct SourceValueWord {
  std::uint32_t source{};
  std::uint32_t value{};
};

struct SpineReaderCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t active_bin_read_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t level_cache_read_bytes{};
  std::uint64_t row_lookup_metadata_bytes{};
  std::uint64_t graph_read_bytes{};
  std::uint64_t tiles_emitted{};
  std::uint64_t edges_emitted{};
  std::uint64_t occupied_levels{};
  std::uint64_t cold_edges_emitted{};
  std::uint64_t hot_edges_emitted{};
};

struct SpineReaderPorts {
  std::array<FixedAxiPort *, 16> graph{};
  FixedAxiPort *active_bins{};
  FixedAxiPort *metadata{};
};

class SpineSplitReader final : public Component {
 public:
  SpineSplitReader(std::string name, ClockId clock_id,
                   const SpineL0Maintenance &maintenance,
                   const SpineL0State &state, SpineReaderPorts ports,
                   std::vector<std::uint32_t> active_sources,
                   Fifo<PartConvWord> &edge_out,
                   Fifo<SourceValueWord> &value_in);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const SpineReaderCounters &counters() const noexcept {
    return counters_;
  }

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  struct TileTask {
    struct Edge {
      SpineEdgeRecord payload;
      std::uint64_t graph_word_address{};
      std::size_t graph_bank{};
      bool hot{};
    };

    std::uint32_t tile_base{};
    std::vector<Edge> edges;
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    std::uint64_t address{};
    std::uint64_t bytes{};
  };

  enum class Phase {
    kWaitMaintenance,
    kRequestSource,
    kWaitSource,
    kSetupReads,
    kTileBegin,
    kEdgeRead,
    kEdgeEmit,
    kTileEnd,
    kDone,
  };

  enum class Action { kNone, kAdvance, kIssue, kComplete, kPush, kPopValue };

  void advance(const CycleContext &context);
  void build_tiles();
  void enqueue_level_cache_reads();
  void enqueue_index_reads();
  void enqueue_read(FixedAxiPort &port, std::uint64_t address,
                    std::uint64_t bytes);
  [[nodiscard]] PartConvWord current_stream_word() const;

  const SpineL0Maintenance &maintenance_;
  const SpineL0State &state_;
  SpineReaderPorts ports_;
  std::vector<std::uint32_t> active_sources_;
  Fifo<PartConvWord> &edge_out_;
  Fifo<SourceValueWord> &value_in_;
  SpineReaderCounters counters_;
  std::vector<TileTask> tiles_;
  std::unordered_map<std::uint32_t, std::uint32_t> source_values_;
  std::deque<MemoryTask> memory_tasks_;
  Phase phase_{Phase::kWaitMaintenance};
  Action staged_action_{Action::kNone};
  PartConvWord staged_stream_word_;
  SourceValueWord staged_value_;
  AxiResponse staged_response_;
  std::size_t tile_index_{};
  std::size_t edge_index_{};
  std::size_t source_index_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_memory_{};
  bool done_{};
  bool failed_{};
};

struct SpineComputeCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t touched_tiles{};
  std::uint64_t fast_path_tiles{};
  std::uint64_t full_path_tiles{};
  std::uint64_t processed_edges{};
  std::uint64_t gathered_vertex_words{};
  std::uint64_t scattered_vertex_words{};
  std::uint64_t vertex_read_bytes{};
  std::uint64_t vertex_write_bytes{};
  std::uint64_t active_out_write_bytes{};
  std::uint64_t bitmap_bytes{};
  std::uint64_t result_write_bytes{};
};

struct SpineComputePorts {
  FixedAxiPort *vertex_state{};
  FixedAxiPort *active_out{};
  FixedAxiPort *active_bitmap{};
  FixedAxiPort *result{};
};

class SpineSplitSsspCompute final : public Component {
 public:
  static constexpr std::uint32_t kInfinity = 0xffffffffU;

  SpineSplitSsspCompute(std::string name, ClockId clock_id,
                        std::size_t vertices, std::uint32_t source,
                        std::size_t tiny_threshold, SpineComputePorts ports,
                        Fifo<PartConvWord> &edge_in,
                        Fifo<SourceValueWord> &value_out);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::vector<std::uint32_t> &values() const noexcept {
    return values_;
  }
  [[nodiscard]] const std::vector<std::uint32_t> &next_active() const noexcept {
    return next_active_;
  }
  [[nodiscard]] const SpineComputeCounters &counters() const noexcept {
    return counters_;
  }

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
  };

  enum class Phase {
    kInput,
    kSourceRead,
    kSourceReply,
    kGatherBegin,
    kGatherAdvance,
    kRelax,
    kStore,
    kFinish,
  };

  enum class Action {
    kNone,
    kAdvance,
    kIssue,
    kComplete,
    kPopEdge,
    kPushValue,
  };

  void advance(const CycleContext &context);
  void handle_edge_word(const PartConvWord &word);
  void enqueue_memory(FixedAxiPort &port, MemoryOperation operation,
                      std::uint64_t address, std::uint64_t bytes);
  void prepare_gather();
  void prepare_store();

  std::size_t vertices_{};
  std::uint32_t source_{};
  std::size_t tiny_threshold_{};
  SpineComputePorts ports_;
  Fifo<PartConvWord> &edge_in_;
  Fifo<SourceValueWord> &value_out_;
  SpineComputeCounters counters_;
  std::vector<std::uint32_t> values_;
  std::vector<std::uint32_t> next_active_;
  std::vector<PartConvWord> tile_edges_;
  std::vector<std::uint32_t> gather_vertices_;
  std::vector<std::uint32_t> changed_vertices_;
  std::deque<MemoryTask> memory_tasks_;
  std::unordered_map<std::uint32_t, std::uint32_t> gathered_values_;
  Phase phase_{Phase::kInput};
  Action staged_action_{Action::kNone};
  PartConvWord staged_edge_word_;
  SourceValueWord staged_value_word_;
  AxiResponse staged_response_;
  std::uint32_t pending_source_{};
  std::uint32_t tile_base_{};
  std::size_t gather_index_{};
  std::size_t relax_index_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_memory_{};
  bool source_reply_pending_{};
  bool done_{};
  bool failed_{};
};

}  // namespace spine::sim
