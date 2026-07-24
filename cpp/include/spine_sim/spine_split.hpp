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
  kSourceCount,
  kSourceGeneration,
  kSourceRequestsDone,
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
  enum class Kind { kSourceValue, kProtocolAck };

  Kind kind{Kind::kSourceValue};
  std::uint32_t source{};
  std::uint32_t value{};
};

inline constexpr std::size_t kSpineDirtyRequestWindow = 16;

enum class SpineDirtyStatus : std::uint32_t {
  kOk = 0,
  kInvalidState = 1,
  kRequiresHost = 2,
  kProtocolError = 3,
  kStaleAck = 4,
  kCoverageMismatch = 5,
  kTaskError = 6,
  kMalformedAck = 7,
};

enum class SpineSourceProtocolStatus : std::uint32_t {
  kOk = 0,
  kUnexpected = 1,
  kSourceBounds = 2,
  kResponseSource = 3,
  kCount = 4,
  kGeneration = 5,
  kMetadataDuplicate = 6,
};

struct SpineReaderCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t source_request_windows{};
  std::uint64_t source_protocol_markers{};
  std::uint64_t source_protocol_acks{};
  std::uint32_t source_protocol_status{};
  std::uint32_t dirty_status{};
  std::uint64_t active_bin_read_bytes{};
  std::uint64_t dirty_list_read_bytes{};
  std::uint64_t dirty_bitmap_read_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t level_cache_read_bytes{};
  std::uint64_t row_lookup_metadata_bytes{};
  std::uint64_t graph_read_bytes{};
  std::uint64_t graph_index_payload_read_bytes{};
  std::uint64_t graph_edge_payload_read_bytes{};
  std::uint64_t graph_construction_payload_read_bytes{};
  std::uint64_t graph_replay_payload_read_bytes{};
  std::uint64_t graph_index_bitmap_misses{};
  std::uint64_t graph_index_epoch_misses{};
  std::uint64_t graph_index_bitmap_words{};
  std::uint64_t range_task_active_records{};
  std::uint64_t range_task_family_probes{};
  std::uint64_t range_task_family_skips{};
  std::uint64_t range_task_level_checks{};
  std::uint64_t range_task_row_lookups{};
  std::uint64_t range_task_construction_payloads{};
  std::uint64_t range_task_count{};
  std::uint64_t range_task_replay_payloads{};
  std::uint64_t range_task_clear_cycles{};
  std::uint64_t range_task_prefix_cycles{};
  std::uint64_t range_task_scatter_cycles{};
  std::uint64_t range_task_verify_cycles{};
  std::uint32_t range_task_path{1};
  std::uint32_t range_task_fallback_reason{};
  std::uint32_t range_task_error{};
  std::uint64_t tiles_emitted{};
  std::uint64_t edges_emitted{};
  std::uint64_t occupied_levels{};
  std::uint64_t cold_edges_emitted{};
  std::uint64_t hot_edges_emitted{};
};

struct SpineReaderPorts {
  std::array<FixedAxiPort *, 16> graph{};
  FixedAxiPort *task_scratch{};
  FixedAxiPort *active_bins{};
  FixedAxiPort *metadata{};
};

enum class SpineReaderMode { kDeviceDirty, kHostActive };

class SpineSplitReader final : public Component {
 public:
  SpineSplitReader(std::string name, ClockId clock_id,
                   const SpineL0Maintenance &maintenance,
                   SpineReaderPorts ports,
                   std::vector<std::uint32_t> active_sources,
                   Fifo<PartConvWord> &edge_out,
                   Fifo<SourceValueWord> &value_in,
                   SpineReaderMode mode = SpineReaderMode::kDeviceDirty);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineReaderCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] std::vector<std::uint32_t> active_source_ids() const;
  void reset_round(std::vector<std::uint32_t> active_sources);
  void reset_host_round(const SpineActiveBins &active_bins);

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  struct RangeTask {
    std::uint64_t absolute_word{};
    std::uint32_t length{};
    std::uint32_t source{};
    std::uint32_t source_value{};
    std::uint16_t tile{};
    std::uint8_t graph_bank{};
    bool hot{};
  };

  struct TileTask {
    std::uint32_t tile_base{};
    std::vector<RangeTask> ranges;
  };

  struct RangeProbe {
    std::uint32_t source{};
    std::uint32_t source_value{};
    std::size_t family{};
    std::size_t level{};
    bool hot{};
    SpineLevelLayout layout;
    std::uint32_t edge_count{};
    std::uint32_t slice_epoch{};
    std::uint32_t page_epoch{};
    std::uint32_t page{};
    std::uint32_t lane_word{};
    std::uint32_t lane_bit{};
    std::vector<std::uint64_t> bitmap_words;
    std::uint64_t page_base_word{};
    std::uint64_t row_word{};
    std::uint64_t next_row_word{};
    std::uint32_t rank{};
    std::uint32_t row{};
    std::uint32_t start{};
    std::uint32_t end{};
  };

  struct LevelCacheEntry {
    bool occupied{};
    bool valid{true};
    std::uint64_t edge_count{};
    std::uint64_t row_count{};
    SpineLevelLayout layout;
    std::uint32_t slice_epoch{};
  };

  enum class MemoryPayloadKind {
    kNone,
    kMetadataControl,
    kDirtyCount,
    kDirtyGeneration,
    kDirtyHashSum,
    kDirtyHashXor,
    kDirtyList,
    kDirtyBitmap,
    kActiveBinMetadata,
    kActiveRecords,
    kLevelOccupied,
    kLevelFields,
    kSliceEpoch,
    kPageEpoch,
    kIndexBitmapSelected,
    kIndexBitmapPrefix,
    kIndexPageBase,
    kIndexRow,
    kIndexNextRow,
    kConstructionEdge,
    kReplayEdge,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::uint32_t edge_source{};
    std::size_t item_index{};
    MemoryPayloadKind payload_kind{MemoryPayloadKind::kNone};
  };

  enum class Phase {
    kWaitMaintenance,
    kSourceHeaderResolve,
    kDirtyListResolve,
    kDirtyBitmapResolve,
    kHostActiveResolve,
    kRequestSourceWindow,
    kWaitSourceWindow,
    kSendSourceCount,
    kSendSourceGeneration,
    kSendSourceDone,
    kWaitSourceAck,
    kLevelOccupancyBegin,
    kLevelDetailsBegin,
    kSetupReads,
    kBinClear,
    kProbeBegin,
    kProbeEpochResolve,
    kProbeIndexResolve,
    kProbeRankResolve,
    kProbePageResolve,
    kProbeRowResolve,
    kConstructionRead,
    kConstructionConsume,
    kProbeAdvance,
    kBinPrefix,
    kBinScatter,
    kBinVerify,
    kTileScan,
    kTileBegin,
    kEdgeRead,
    kEdgeEmit,
    kTileEnd,
    kDone,
  };

  enum class Action { kNone, kAdvance, kIssue, kComplete, kPush, kPopValue };

  void advance(const CycleContext &context);
  void enqueue_level_cache_reads();
  void enqueue_level_detail_reads();
  void begin_source_header_reads();
  void validate_control();
  void finalize_level_cache();
  void prepare_range_probes();
  void enqueue_probe_index_reads();
  void resolve_probe_epoch();
  void resolve_probe_index();
  void resolve_probe_rank();
  void resolve_probe_page();
  void enqueue_probe_row_reads();
  void resolve_probe_row();
  void consume_construction_edge();
  void flush_construction_run();
  void enqueue_read(FixedAxiPort &port, std::uint64_t address,
                    std::uint64_t bytes,
                    MemoryPayloadKind payload_kind = MemoryPayloadKind::kNone,
                    std::size_t probe_index = 0, std::uint32_t edge_source = 0);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  void reset_state();
  [[nodiscard]] PartConvWord current_stream_word() const;

  const SpineL0Maintenance &maintenance_;
  SpineReaderPorts ports_;
  SpineReaderMode mode_{SpineReaderMode::kDeviceDirty};
  std::vector<std::uint32_t> active_sources_;
  SpineActiveBins host_active_bins_;
  std::vector<SpineActiveRecord> active_records_;
  Fifo<PartConvWord> &edge_out_;
  Fifo<SourceValueWord> &value_in_;
  SpineReaderCounters counters_;
  std::array<TileTask, 256> tiles_;
  std::array<std::uint32_t, 256> tile_counts_{};
  std::array<std::uint32_t, 256> tile_offsets_{};
  std::array<std::uint32_t, 256> tile_cursors_{};
  std::vector<RangeProbe> range_probes_;
  std::vector<RangeTask> range_tasks_;
  std::array<LevelCacheEntry, kSpineFamilyCount * kSpineLevelCount>
      level_cache_{};
  std::unordered_map<std::uint32_t, std::uint32_t> source_values_;
  std::deque<MemoryTask> memory_tasks_;
  Phase phase_{Phase::kWaitMaintenance};
  Action staged_action_{Action::kNone};
  PartConvWord staged_stream_word_;
  SourceValueWord staged_value_;
  AxiResponse staged_response_;
  SpineEdgeRecord loaded_edge_;
  SpineEdgeRecord construction_edge_;
  std::uint64_t metadata_control_{};
  std::uint64_t dirty_count_{};
  std::uint32_t dirty_generation_{};
  std::uint64_t dirty_hash_sum_{};
  std::uint64_t dirty_hash_xor_{};
  std::array<std::uint64_t, 16> active_bin_offsets_{};
  std::array<std::uint64_t, 16> active_bin_counts_{};
  bool dirty_payload_valid_{true};
  std::size_t probe_index_{};
  std::uint32_t construction_position_{};
  bool construction_run_valid_{};
  std::uint16_t construction_run_tile_{};
  std::uint64_t construction_run_start_{};
  std::uint32_t construction_run_length_{};
  std::uint32_t construction_previous_dst_{};
  bool construction_have_previous_dst_{};
  std::size_t bin_index_{};
  std::size_t scatter_index_{};
  std::size_t tile_index_{};
  std::size_t range_index_{};
  std::uint32_t range_edge_index_{};
  std::size_t source_request_index_{};
  std::size_t source_response_index_{};
  std::size_t source_window_end_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_memory_{};
  bool done_{};
  bool failed_{};
  std::string failure_;
};

struct SpineComputeCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t source_protocol_markers{};
  std::uint64_t source_protocol_acks{};
  std::uint32_t source_protocol_status{};
  std::uint32_t source_count{};
  std::uint32_t source_generation{};
  std::uint64_t touched_tiles{};
  std::uint64_t fast_path_tiles{};
  std::uint64_t full_path_tiles{};
  std::uint64_t processed_edges{};
  std::uint64_t gathered_vertex_words{};
  std::uint64_t swept_vertex_words{};
  std::uint64_t scattered_vertex_words{};
  std::uint64_t tiny_buffered_edges{};
  std::uint64_t full_buffer_replay_edges{};
  std::uint64_t full_overflow_edges{};
  std::uint64_t full_stream_edges{};
  std::uint64_t vertex_read_bytes{};
  std::uint64_t vertex_write_bytes{};
  std::uint64_t vertex_payload_read_bytes{};
  std::uint64_t vertex_payload_write_bytes{};
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
  void reset_round();

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::vector<std::uint8_t> write_data;
  };

  enum class Phase {
    kInput,
    kSourceRead,
    kSourceReply,
    kGatherBegin,
    kGatherAdvance,
    kRelax,
    kFullLoad,
    kFullReplay,
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
                      std::uint64_t address, std::uint64_t bytes,
                      std::vector<std::uint8_t> write_data = {});
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  void prepare_gather();
  void prepare_store();
  void begin_full_path(const PartConvWord &overflow_edge);
  void relax_edge(const PartConvWord &edge);
  void reset_tile();

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
  std::vector<std::uint32_t> tile_values_;
  std::deque<MemoryTask> memory_tasks_;
  std::unordered_map<std::uint32_t, std::uint32_t> gathered_values_;
  Phase phase_{Phase::kInput};
  Action staged_action_{Action::kNone};
  PartConvWord staged_edge_word_;
  SourceValueWord staged_value_word_;
  AxiResponse staged_response_;
  std::uint32_t pending_source_{};
  std::uint32_t pending_source_value_{kInfinity};
  SourceValueWord::Kind pending_value_kind_{SourceValueWord::Kind::kSourceValue};
  std::uint32_t tile_base_{};
  std::size_t tile_size_{};
  std::size_t gather_index_{};
  std::size_t relax_index_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_memory_{};
  bool source_reply_pending_{};
  bool source_count_seen_{};
  bool source_generation_seen_{};
  bool source_protocol_overflow_{};
  bool tile_open_{};
  bool full_path_{};
  bool overflow_edge_pending_{};
  PartConvWord overflow_edge_;
  bool done_{};
  bool failed_{};
};

}  // namespace spine::sim
