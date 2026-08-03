#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/algorithm.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/spine_l0.hpp"

namespace spine::sim {

class SpineOwnerScheduler;

enum class PartConvWordKind {
  kSourceRequest,
  kSourceCount,
  kSourceGeneration,
  kSourceRequestsDone,
  kDeferActiveBegin,
  kTileBegin,
  kEdge,
  kTileEnd,
  kDiagnostic,
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
inline constexpr std::size_t kSpineReaderDiagnosticWords = 10;

enum class SpineDiagnosticKind : std::uint32_t {
  kTaskStatus = 0xfffffff3U,
  kTaskCount = 0xfffffff4U,
  kTaskRowLookups = 0xfffffff5U,
  kTaskConstructionPayloads = 0xfffffff6U,
  kTaskReplayPayloads = 0xfffffff7U,
  kTaskActiveRecords = 0xfffffff8U,
  kTaskFamilyProbes = 0xfffffff9U,
  kTaskFamilySkips = 0xfffffffaU,
  kDirtyCount = 0xfffffffbU,
  kDirtyGeneration = 0xfffffffcU,
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
  std::uint32_t dirty_count{};
  std::uint32_t dirty_generation{};
  std::uint64_t dirty_hash_sum{};
  std::uint64_t dirty_hash_xor{};
  bool acknowledgement_eligible{};
  bool host_coverage_match{};
  std::uint64_t diagnostic_words{};
  std::uint64_t done_words{};
  bool done_overflow{};
  std::uint64_t active_bin_read_bytes{};
  std::uint64_t dirty_list_read_bytes{};
  std::uint64_t dirty_bitmap_read_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t metadata_write_bytes{};
  std::uint64_t result_write_bytes{};
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
  std::uint64_t range_task_hot_lower_bound_reads{};
  std::uint64_t range_task_construction_payloads{};
  std::uint64_t range_task_count{};
  std::uint64_t range_task_replay_payloads{};
  std::uint64_t range_task_clear_cycles{};
  std::uint64_t range_task_prefix_cycles{};
  std::uint64_t range_task_scatter_cycles{};
  std::uint64_t range_task_verify_cycles{};
  std::uint64_t range_task_control_cycles{};
  std::uint64_t segmented_validation_payloads{};
  std::uint64_t segmented_task_count{};
  std::uint64_t segmented_replay_payloads{};
  std::uint64_t segmented_segment_count{};
  std::uint64_t segmented_setup_cycles{};
  std::uint64_t fallback_partitions{};
  std::uint64_t fallback_forced_dense_partitions{};
  std::uint64_t fallback_active_record_reads{};
  std::uint64_t fallback_active_record_read_bytes{};
  std::uint64_t fallback_metadata_read_bytes{};
  std::uint64_t fallback_level_cache_reuses{};
  std::uint64_t fallback_level_cache_empty_skips{};
  std::uint64_t source_page_cache_hits{};
  std::uint64_t source_page_cache_misses{};
  std::uint64_t source_page_cache_negative_hits{};
  std::uint64_t source_page_cache_fills{};
  std::uint64_t fallback_row_lookups{};
  std::uint64_t fallback_lower_bound_reads{};
  std::uint64_t fallback_endpoint_reads{};
  std::uint64_t fallback_replay_edges{};
  std::uint32_t range_task_path{1};
  std::uint32_t range_task_fallback_reason{};
  std::uint32_t range_task_error{};
  std::uint64_t tiles_emitted{};
  std::uint64_t edges_emitted{};
  std::uint64_t occupied_levels{};
  std::uint64_t cold_edges_emitted{};
  std::uint64_t hot_edges_emitted{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t memory_window_stall_cycles{};
  std::uint64_t memory_dependency_stall_cycles{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::size_t max_memory_requests_inflight{};
  std::size_t max_memory_requests_inflight_per_port{};
  std::size_t max_active_memory_ports{};
  std::uint64_t memory_cross_port_overlap_cycles{};
  std::uint64_t construction_pipeline_requests{};
  std::uint64_t construction_pipeline_retires{};
  std::uint64_t replay_pipeline_requests{};
  std::uint64_t replay_pipeline_retires{};
  std::uint64_t edge_pipeline_credit_stall_cycles{};
  std::uint64_t edge_pipeline_request_fifo_stall_cycles{};
  std::uint64_t edge_pipeline_axis_stall_cycles{};
  std::size_t edge_pipeline_max_inflight{};
  std::size_t edge_pipeline_max_buffered{};
};

struct SpineReaderPorts {
  std::array<FixedAxiPort *, 16> graph{};
  FixedAxiPort *task_scratch{};
  FixedAxiPort *active_bins{};
  FixedAxiPort *active_out{};
  FixedAxiPort *metadata{};
  FixedAxiPort *result{};
};

enum class SpineReaderMode { kDeviceDirty, kHostActive, kDeviceActiveList };

class SpineSplitReader final : public Component {
 public:
  SpineSplitReader(std::string name, ClockId clock_id,
                   const SpineL0Maintenance &maintenance,
                   SpineReaderPorts ports,
                   std::vector<std::uint32_t> active_sources,
                   Fifo<PartConvWord> &edge_out,
                   Fifo<SourceValueWord> &value_in,
                   SpineReaderMode mode = SpineReaderMode::kDeviceDirty,
                   std::shared_ptr<const GraphAlgorithmPolicy>
                       algorithm_policy = nullptr);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] bool recoverable_host_handoff() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineReaderCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] std::vector<std::uint32_t> active_source_ids() const;
  [[nodiscard]] const GraphAlgorithmPolicy &algorithm_policy() const noexcept {
    return *algorithm_policy_;
  }
  void reset_round(std::vector<std::uint32_t> active_sources);
  void reset_active_list_round(std::size_t active_count);
  void reset_host_round(
      const SpineActiveBins &active_bins,
      std::optional<SpineDirtyIdentity> host_coverage = std::nullopt,
      std::vector<std::uint32_t> source_refresh = {});
  void configure_initial_active_list_round(std::size_t active_count,
                                           const bool *start_ready);
  void configure_start_gate(const bool *start_ready);
  void configure_initial_host_round(
      SpineActiveBins active_bins,
      std::optional<SpineDirtyIdentity> host_coverage,
      std::vector<std::uint32_t> source_refresh);

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
    std::size_t destination_partition{};
    bool hot{};
    bool clip_hot_to_partition{};
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

  struct SourcePageCacheEntry {
    bool valid{};
    bool epoch_matches{};
    std::uint32_t page{};
    std::uint32_t slice_epoch{};
    std::uint32_t page_epoch{};
    std::array<std::uint64_t, 4> bitmap_words{};
    std::uint64_t page_base_word{};
  };

  struct FallbackLookup {
    SpineActiveRecord record;
    std::size_t partition{};
    std::size_t family{};
    std::size_t level{};
    bool hot{};
    bool occupied{};
    std::uint32_t slice_epoch{};
    std::uint32_t page_epoch{};
    SpineLevelLayout layout;
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

  enum class MemoryPayloadKind {
    kNone,
    kMetadataControl,
    kDirtyCount,
    kDirtyGeneration,
    kDirtyHashSum,
    kDirtyHashXor,
    kDirtyHostGeneration,
    kDirtyHostCount,
    kDirtyHostHashSum,
    kDirtyHostHashXor,
    kDirtyHostValid,
    kDirtyList,
    kDirtyBitmap,
    kDeviceActiveOutput,
    kActiveBinMetadata,
    kActiveRecords,
    kLevelOccupied,
    kLevelFields,
    kSliceEpoch,
    kPageEpoch,
    kIndexBitmapPage,
    kIndexBitmapSelected,
    kIndexBitmapPrefix,
    kIndexPageBase,
    kIndexRow,
    kIndexNextRow,
    kProbeBinaryEdge,
    kConstructionEdge,
    kReplayEdge,
    kFallbackActiveRecord,
    kFallbackOccupied,
    kFallbackSliceEpoch,
    kFallbackPageEpoch,
    kFallbackBitmapPage,
    kFallbackBitmapOffset,
    kFallbackPageBaseOffset,
    kFallbackRowOffset,
    kFallbackEdgeOffset,
    kFallbackBitmapSelected,
    kFallbackBitmapPrefix,
    kFallbackPageBase,
    kFallbackRow,
    kFallbackNextRow,
    kFallbackBinaryEdge,
    kFallbackFirstEdge,
    kFallbackLastEdge,
    kFallbackReplayEdge,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::vector<std::uint8_t> write_data;
    std::uint32_t edge_source{};
    std::uint32_t edge_source_value{};
    std::uint32_t edge_tile_base{};
    std::uint32_t edge_tile_end{};
    std::size_t item_index{};
    std::uint64_t stream_sequence{};
    bool edge_hot{};
    MemoryPayloadKind payload_kind{MemoryPayloadKind::kNone};
  };

  struct BufferedPipelineEdge {
    SpineEdgeRecord edge;
    std::uint32_t source_value{};
    std::uint32_t tile_base{};
    std::uint32_t tile_end{};
    bool hot{};
  };

  enum class EdgePipelineMode {
    kNone,
    kConstruction,
    kExactReplay,
    kFallbackReplay,
  };

  enum class SegmentedPass {
    kNone,
    kValidation,
    kExecution,
  };

  enum class Phase {
    kWaitMaintenance,
    kSourceHeaderResolve,
    kDirtyListResolve,
    kDirtyBitmapResolve,
    kDeviceActiveResolve,
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
    kRefactor31Control,
    kRefactor31SegmentSetup,
    kSegmentedDeferActive,
    kBinClear,
    kProbeBegin,
    kProbeEpochResolve,
    kProbeIndexResolve,
    kProbeRankResolve,
    kProbePageResolve,
    kProbeRowResolve,
    kProbeLowerBoundRead,
    kProbeLowerBoundResolve,
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
    kFallbackLevelCacheBegin,
    kFallbackLevelCacheDetails,
    kFallbackLevelCacheResolve,
    kFallbackPartitionBegin,
    kFallbackPassBegin,
    kFallbackRecordRead,
    kFallbackRecordResolve,
    kFallbackLevelBegin,
    kFallbackLookupHeaderResolve,
    kFallbackLookupBitmapOffsetResolve,
    kFallbackLookupIndexResolve,
    kFallbackLookupRankResolve,
    kFallbackLookupOffsetsResolve,
    kFallbackLookupPageResolve,
    kFallbackLookupRowResolve,
    kFallbackRangeResolve,
    kFallbackLowerBoundRead,
    kFallbackLowerBoundResolve,
    kFallbackEndpointResolve,
    kFallbackLevelAdvance,
    kFallbackRecordAdvance,
    kFallbackPassAdvance,
    kFallbackTileScan,
    kFallbackTileBegin,
    kFallbackEdgeRead,
    kFallbackEdgeEmit,
    kFallbackTileEnd,
    kDiagnostic,
    kDone,
  };

  enum class Action {
    kNone,
    kAdvance,
    kPush,
    kPopValue,
    kRetireConstruction,
    kPipelineError,
    kFinishPipelineAbort,
  };

  void advance(const CycleContext &context);
  void enqueue_level_cache_reads();
  void enqueue_level_detail_reads();
  void begin_source_header_reads();
  void validate_control();
  void finalize_level_cache();
  void prepare_range_probes();
  void begin_refactor31_control();
  void finish_refactor31_validation_pass();
  void enqueue_probe_index_reads();
  [[nodiscard]] std::size_t source_page_cache_index(
      std::size_t family, std::size_t level, bool hot) const;
  [[nodiscard]] bool use_cached_probe_page(RangeProbe &probe);
  [[nodiscard]] bool use_cached_fallback_page();
  void fill_probe_page_cache(const RangeProbe &probe, bool epoch_matches);
  void fill_fallback_page_cache(bool epoch_matches);
  void clear_source_page_cache();
  void resolve_probe_epoch();
  void resolve_probe_index();
  void resolve_probe_rank();
  void resolve_probe_page();
  void enqueue_probe_row_reads();
  void resolve_probe_row();
  void begin_probe_lower_bound(std::uint32_t low, std::uint32_t high,
                               std::uint32_t limit, bool second);
  void advance_probe_lower_bound();
  void begin_probe_construction();
  void consume_construction_edge();
  void flush_construction_run();
  void start_host_fallback(std::uint32_t reason);
  void advance_fallback();
  void begin_fallback_pass();
  void advance_fallback_pass();
  void enqueue_fallback_lookup_header();
  void resolve_fallback_lookup_header();
  void resolve_fallback_lookup_bitmap_offset();
  void resolve_fallback_lookup_index();
  void resolve_fallback_lookup_rank();
  void resolve_fallback_lookup_offsets();
  void resolve_fallback_lookup_page();
  void resolve_fallback_lookup_row();
  void begin_fallback_range();
  void begin_fallback_lower_bound(std::uint32_t low, std::uint32_t high,
                                  std::uint32_t limit, bool second);
  void finish_fallback_range();
  void finish_fallback_discovery();
  [[nodiscard]] std::uint32_t fallback_partition_base() const;
  [[nodiscard]] std::uint32_t fallback_partition_end() const;
  [[nodiscard]] std::uint32_t fallback_tile_base() const;
  [[nodiscard]] std::uint32_t fallback_tile_end() const;
  void enqueue_read(FixedAxiPort &port, std::uint64_t address,
                    std::uint64_t bytes,
                    MemoryPayloadKind payload_kind = MemoryPayloadKind::kNone,
                    std::size_t probe_index = 0, std::uint32_t edge_source = 0);
  void enqueue_write(FixedAxiPort &port, std::uint64_t address,
                     std::vector<std::uint8_t> write_data);
  void enqueue_terminal_writes();
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  [[nodiscard]] bool memory_task_conflicts(const MemoryTask &task) const;
  [[nodiscard]] std::size_t
  inflight_memory_tasks_for_port(const FixedAxiPort *port) const noexcept;
  [[nodiscard]] std::size_t active_memory_ports() const noexcept;
  void update_memory_concurrency_counters(const FixedAxiPort *issued_port);
  [[nodiscard]] bool stage_memory_completion();
  [[nodiscard]] bool edge_pipeline_active() const noexcept;
  void begin_edge_pipeline(EdgePipelineMode mode, FixedAxiPort &port,
                           std::uint64_t base_address, std::uint32_t length,
                           std::uint32_t source, std::uint32_t source_value,
                           std::uint32_t tile_base, std::uint32_t tile_end,
                           bool hot);
  void evaluate_edge_pipeline();
  void commit_edge_pipeline_issue();
  void retire_construction_edge();
  void retire_replay_edge();
  void finish_edge_pipeline();
  [[nodiscard]] const BufferedPipelineEdge *next_pipeline_edge() const;
  [[nodiscard]] bool next_pipeline_edge_valid() const;
  void initialize_host_payload(
      const SpineActiveBins &active_bins,
      std::optional<SpineDirtyIdentity> host_coverage);
  void validate_source_refresh(
      const std::vector<std::uint32_t> &source_refresh) const;
  void reset_state();
  void begin_terminal(bool overflow, std::string failure = {});
  [[nodiscard]] PartConvWord current_stream_word() const;
  [[nodiscard]] PartConvWord current_diagnostic_word() const;

  const SpineL0Maintenance &maintenance_;
  std::shared_ptr<const GraphAlgorithmPolicy> algorithm_policy_;
  SpineReaderPorts ports_;
  SpineReaderMode mode_{SpineReaderMode::kDeviceDirty};
  std::vector<std::uint32_t> active_sources_;
  SpineActiveBins host_active_bins_;
  std::optional<SpineActiveBins> initial_host_bins_;
  std::optional<SpineDirtyIdentity> initial_host_coverage_;
  const bool *initial_start_gate_{};
  std::size_t device_active_count_{};
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
  std::array<SourcePageCacheEntry, kSpineFamilyCount * kSpineLevelCount>
      source_page_cache_{};
  bool level_cache_ready_{};
  std::unordered_map<std::uint32_t, std::uint32_t> source_values_;
  FallbackLookup fallback_lookup_;
  SpineEdgeRecord fallback_binary_edge_;
  SpineEdgeRecord fallback_first_edge_;
  SpineEdgeRecord fallback_last_edge_;
  std::array<std::uint16_t, 16> fallback_touched_masks_{};
  std::array<bool, 16> fallback_force_dense_{};
  std::deque<MemoryTask> memory_tasks_;
  std::unordered_map<std::uint64_t, MemoryTask> inflight_memory_tasks_;
  std::map<std::uint64_t, BufferedPipelineEdge> edge_response_buffer_;
  Phase phase_{Phase::kWaitMaintenance};
  Action staged_action_{Action::kNone};
  PartConvWord staged_stream_word_;
  SourceValueWord staged_value_;
  AxiResponse staged_response_;
  SpineEdgeRecord loaded_edge_;
  SpineEdgeRecord probe_binary_edge_;
  SpineEdgeRecord construction_edge_;
  std::uint64_t metadata_control_{};
  std::uint64_t dirty_count_{};
  std::uint32_t dirty_generation_{};
  std::uint64_t dirty_hash_sum_{};
  std::uint64_t dirty_hash_xor_{};
  std::uint32_t dirty_host_generation_{};
  std::uint64_t dirty_host_count_{};
  std::uint64_t dirty_host_hash_sum_{};
  std::uint64_t dirty_host_hash_xor_{};
  bool dirty_host_valid_{};
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
  std::uint32_t probe_lower_low_{};
  std::uint32_t probe_lower_high_{};
  std::uint32_t probe_lower_limit_{};
  std::uint32_t probe_clipped_start_{};
  bool probe_lower_second_{};
  std::size_t bin_index_{};
  std::size_t scatter_index_{};
  std::size_t tile_index_{};
  std::size_t range_index_{};
  std::uint32_t range_edge_index_{};
  std::size_t source_request_index_{};
  std::size_t source_response_index_{};
  std::size_t source_window_end_{};
  std::size_t diagnostic_index_{};
  std::size_t fallback_partition_{};
  std::size_t fallback_shard_{};
  std::size_t fallback_record_index_{};
  std::size_t fallback_level_{};
  std::size_t fallback_tile_local_{};
  std::uint32_t fallback_lower_low_{};
  std::uint32_t fallback_lower_high_{};
  std::uint32_t fallback_lower_limit_{};
  std::uint32_t fallback_clipped_start_{};
  std::uint32_t fallback_clipped_end_{};
  std::uint32_t fallback_replay_position_{};
  bool fallback_discovery_{true};
  bool fallback_hot_{};
  bool fallback_lower_second_{};
  bool fallback_active_record_valid_{};
  bool fallback_enabled_{};
  bool fallback_after_source_refresh_{};
  SegmentedPass segmented_pass_{SegmentedPass::kNone};
  std::uint64_t refactor31_control_remaining_{};
  std::uint64_t refactor31_setup_remaining_{};
  std::uint64_t refactor31_validation_payload_base_{};
  bool source_page_cache_current_hit_{};
  std::uint64_t next_transaction_id_{};
  bool staged_memory_issue_{};
  bool staged_memory_completion_{};
  std::optional<MemoryTask> staged_edge_issue_task_;
  EdgePipelineMode edge_pipeline_mode_{EdgePipelineMode::kNone};
  FixedAxiPort *edge_pipeline_port_{};
  std::uint64_t edge_pipeline_base_address_{};
  std::uint32_t edge_pipeline_length_{};
  std::uint32_t edge_pipeline_issue_index_{};
  std::uint32_t edge_pipeline_retire_index_{};
  std::uint32_t edge_pipeline_source_{};
  std::uint32_t edge_pipeline_source_value_{};
  std::uint32_t edge_pipeline_tile_base_{};
  std::uint32_t edge_pipeline_tile_end_{};
  bool edge_pipeline_hot_{};
  bool edge_pipeline_abort_{};
  bool terminal_pending_{};
  bool terminal_overflow_{};
  bool terminal_failed_{};
  bool done_{};
  bool failed_{};
  std::string failure_;
};

struct SpineComputeCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t full_recompute_reset_cycles{};
  std::uint64_t full_recompute_reset_words{};
  std::uint64_t full_recompute_reset_write_bytes{};
  std::uint64_t source_requests{};
  std::uint64_t source_responses{};
  std::uint64_t source_protocol_markers{};
  std::uint64_t source_protocol_acks{};
  std::uint32_t source_protocol_status{};
  std::uint32_t source_count{};
  std::uint32_t source_generation{};
  std::uint64_t diagnostic_words{};
  std::uint64_t done_words{};
  bool done_overflow{};
  std::uint32_t range_task_path{};
  std::uint32_t range_task_fallback_reason{};
  std::uint32_t range_task_error{};
  std::uint64_t range_task_count{};
  std::uint64_t range_task_row_lookups{};
  std::uint64_t range_task_construction_payloads{};
  std::uint64_t range_task_replay_payloads{};
  std::uint64_t range_task_active_records{};
  std::uint64_t range_task_family_probes{};
  std::uint64_t range_task_family_skips{};
  std::uint32_t dirty_count{};
  std::uint32_t dirty_generation{};
  std::uint64_t touched_tiles{};
  std::uint64_t fast_path_tiles{};
  std::uint64_t full_path_tiles{};
  std::uint64_t forced_dense_tiles{};
  std::uint64_t processed_edges{};
  std::uint64_t gathered_vertex_words{};
  std::uint64_t swept_vertex_words{};
  std::uint64_t scattered_vertex_words{};
  std::uint64_t tiny_buffered_edges{};
  std::uint64_t tiny_buffer_writes{};
  std::uint64_t tiny_buffer_reads{};
  std::uint64_t vs_tile_reads{};
  std::uint64_t vs_tile_writes{};
  std::uint64_t tile_active_clear_words{};
  std::uint64_t tile_active_clear_lane_writes{};
  std::uint64_t tile_active_mark_writes{};
  std::uint64_t sparse_store_scan_words{};
  std::uint64_t sparse_store_lane_reads{};
  std::uint64_t sparse_store_bit_cycles{};
  std::uint64_t active_emit_scan_words{};
  std::uint64_t active_emit_lane_reads{};
  std::uint64_t active_emit_lane_writes{};
  std::uint64_t active_emit_bit_cycles{};
  std::uint64_t on_chip_controller_cycles{};
  std::uint64_t full_buffer_replay_edges{};
  std::uint64_t full_overflow_edges{};
  std::uint64_t full_stream_edges{};
  std::uint64_t vertex_read_bytes{};
  std::uint64_t vertex_write_bytes{};
  std::uint64_t vertex_payload_read_bytes{};
  std::uint64_t vertex_payload_write_bytes{};
  std::uint64_t active_out_write_bytes{};
  std::uint64_t bitmap_bytes{};
  std::uint64_t deferred_active_markers{};
  std::uint64_t deferred_active_clear_words{};
  std::uint64_t deferred_active_clear_cycles{};
  std::uint64_t deferred_active_merge_words{};
  std::uint64_t deferred_active_merge_cycles{};
  std::uint64_t deferred_active_sweep_read_words{};
  std::uint64_t deferred_active_sweep_read_cycles{};
  std::uint64_t deferred_active_sweep_nonzero_words{};
  std::uint64_t deferred_active_sweep_bit_cycles{};
  std::uint64_t deferred_active_published_vertices{};
  std::uint64_t deferred_active_final_clear_words{};
  std::uint64_t deferred_active_final_clear_cycles{};
  std::uint64_t result_write_bytes{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t memory_window_stall_cycles{};
  std::uint64_t memory_dependency_stall_cycles{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::uint64_t controller_memory_overlap_cycles{};
  std::uint64_t controller_memory_stall_cycles{};
  std::uint64_t sparse_store_writes_generated{};
  std::uint64_t active_emit_writes_generated{};
  std::uint64_t owner_activation_attempts{};
  std::uint64_t owner_activations_accepted{};
  std::uint64_t owner_activation_backpressure_cycles{};
  std::size_t max_memory_requests_inflight{};
  std::size_t max_vertex_requests_inflight{};
  std::size_t max_active_out_requests_inflight{};
  std::size_t max_active_memory_ports{};
  std::uint64_t memory_cross_port_overlap_cycles{};
  std::size_t max_memory_responses_completed_per_cycle{};
  std::uint64_t multi_port_response_cycles{};
  std::uint64_t tiny_bram_read_requests{};
  std::uint64_t tiny_bram_write_requests{};
  std::uint64_t vs_uram_read_requests{};
  std::uint64_t vs_uram_write_requests{};
  std::uint64_t active_bram_read_requests{};
  std::uint64_t active_bram_write_requests{};
  std::uint64_t on_chip_read_wait_cycles{};
  std::uint64_t on_chip_pipeline_stall_cycles{};
  std::uint64_t vs_bypass_hits{};
  std::uint64_t vs_bypass_misses{};
  std::size_t max_tiny_reads_inflight{};
  std::size_t max_vs_reads_inflight{};
  std::uint64_t full_tile_read_beats{};
  std::uint64_t full_tile_read_words{};
  std::uint64_t full_tile_read_wait_cycles{};
  std::uint64_t full_tile_stream_error_count{};
  std::uint64_t cross_tile_write_overlap_cycles{};
  std::size_t max_cross_tile_writes_inflight{};
};

struct SpineComputePorts {
  FixedAxiPort *vertex_state{};
  FixedAxiPort *active_out{};
  FixedAxiPort *active_bitmap{};
  FixedAxiPort *result{};
};

struct SpineOnChipMemoryProfile {
  std::size_t tiny_bram_read_latency{2};
  std::size_t vs_uram_read_latency{2};
  std::size_t active_bram_read_latency{2};
  std::size_t pipeline_capacity{4};
  std::size_t vs_bypass_depth{4};
};

class SpineSplitSsspCompute final : public Component {
 public:
  static constexpr std::uint32_t kInfinity = 0xffffffffU;
  static constexpr std::size_t kDefaultMemoryRequestWindow = 7;
  static constexpr std::size_t kDefaultWriteOnlyRequestWindow = 4;

  SpineSplitSsspCompute(std::string name, ClockId clock_id,
                        std::size_t vertices, std::uint32_t source,
                        std::size_t tiny_threshold, SpineComputePorts ports,
                        Fifo<PartConvWord> &edge_in,
                        Fifo<SourceValueWord> &value_out,
                        std::size_t memory_request_window =
                            kDefaultMemoryRequestWindow,
                        std::size_t writeonly_request_window =
                            kDefaultWriteOnlyRequestWindow,
                        SpineOnChipMemoryProfile on_chip_profile = {},
                        std::shared_ptr<const GraphAlgorithmPolicy>
                            algorithm_policy = nullptr,
                        std::optional<AlgorithmInitialState> initial_state =
                            std::nullopt,
                        SpineOwnerScheduler *owner_scheduler = nullptr);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] bool recoverable_host_handoff() const noexcept;
  [[nodiscard]] const std::vector<std::uint32_t> &values() const noexcept {
    return values_;
  }
  [[nodiscard]] const std::vector<std::uint32_t> &next_active() const noexcept {
    return next_active_;
  }
  [[nodiscard]] const SpineComputeCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] const GraphAlgorithmPolicy &algorithm_policy() const noexcept {
    return *algorithm_policy_;
  }
  void reset_round();
  void reset_after_host_handoff();
  void reset_for_full_recompute();

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  enum class MemoryPayloadKind {
    kNone,
    kSourceValue,
    kGatherVertex,
    kFullTile,
    kDeferredMergeWord,
    kDeferredSweepWord,
    kDeferredPublishVertex,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::vector<std::uint8_t> write_data;
    MemoryPayloadKind payload_kind{MemoryPayloadKind::kNone};
    std::size_t item_index{};
    std::uint64_t payload_value{};
    bool stream_read_beats{};
    std::size_t streamed_read_bytes{};
  };

  enum class TinyReadPurpose { kGather, kRelax };
  enum class VsReadPurpose { kRelax, kSparseStore, kActiveEmit };

  struct PendingTinyRead {
    std::uint64_t due_cycle{};
    std::size_t item_index{};
    TinyReadPurpose purpose{TinyReadPurpose::kGather};
    PartConvWord edge;
  };

  struct PendingVsRead {
    std::uint64_t due_cycle{};
    VsReadPurpose purpose{VsReadPurpose::kRelax};
    PartConvWord edge;
    std::uint32_t vertex{};
    std::uint32_t memory_value{kInfinity};
  };

  struct VsBypassEntry {
    std::uint32_t vertex{};
    std::uint32_t value{kInfinity};
  };

  enum class Phase {
    kReinitialize,
    kInput,
    kSourceRead,
    kSourceReply,
    kDeferredActiveClear,
    kGatherBegin,
    kGatherAdvance,
    kClearTileActive,
    kRelax,
    kFullLoad,
    kFullReplay,
    kFullReplayDrain,
    kFullStreamDrain,
    kSparseStoreScan,
    kSparseStoreBits,
    kStore,
    kEmitActiveScan,
    kEmitActiveBits,
    kEmitStore,
    kDeferredMergeScan,
    kDeferredMergeWait,
    kDeferredSweepRead,
    kDeferredSweepScan,
    kDeferredSweepBits,
    kDeferredSweepDrain,
    kDeferredFinalClear,
    kDeferredFinalDrain,
    kFinish,
  };

  enum class Action {
    kNone,
    kAdvance,
    kPopEdge,
    kPushValue,
  };

  void advance(const CycleContext &context);
  void handle_edge_word(const PartConvWord &word,
                        const CycleContext &context);
  void enqueue_memory(FixedAxiPort &port, MemoryOperation operation,
                      std::uint64_t address, std::uint64_t bytes,
                      std::vector<std::uint8_t> write_data = {},
                      MemoryPayloadKind payload_kind = MemoryPayloadKind::kNone,
                      std::size_t item_index = 0,
                      std::uint64_t payload_value = 0,
                      bool stream_read_beats = false);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  [[nodiscard]] bool memory_task_conflicts(const MemoryTask &task) const;
  [[nodiscard]] std::size_t
  inflight_memory_tasks_for_port(const FixedAxiPort *port) const noexcept;
  [[nodiscard]] std::size_t
  memory_request_window_for(const FixedAxiPort *port) const noexcept;
  [[nodiscard]] std::size_t active_memory_ports() const noexcept;
  [[nodiscard]] bool memory_work_is_write_only() const noexcept;
  [[nodiscard]] bool stage_memory_completions();
  [[nodiscard]] bool stage_full_tile_read_beat();
  void consume_full_tile_read_beat(const AxiReadBeatResponse &beat);
  void prepare_gather();
  void prepare_vertex_store();
  void enqueue_active_output(std::uint32_t vertex);
  void enqueue_active_output(std::uint32_t vertex, std::uint32_t value,
                             std::size_t output_index);
  void issue_tiny_read(std::size_t item_index, TinyReadPurpose purpose,
                       const CycleContext &context);
  void issue_vs_read(const PartConvWord &edge, VsReadPurpose purpose,
                     const CycleContext &context);
  void issue_vs_read(std::uint32_t vertex, VsReadPurpose purpose,
                     const CycleContext &context);
  void advance_on_chip_pipelines(const CycleContext &context);
  void complete_relax(const PendingVsRead &request);
  [[nodiscard]] std::uint32_t bypass_value(
      std::uint32_t vertex, std::uint32_t memory_value);
  void push_bypass(std::uint32_t vertex, std::uint32_t value);
  void reset_bypass();
  void count_on_chip_read_wait(std::uint64_t cycle);
  void count_on_chip_pipeline_stall(std::uint64_t cycle);
  [[nodiscard]] bool on_chip_pipelines_drained() const noexcept;
  void begin_tile_active_clear(Phase next_phase);
  void begin_sparse_store_scan();
  void begin_active_emit_scan();
  void begin_deferred_merge_scan();
  void begin_deferred_sweep();
  void finish_active_word_scan(Phase scan_phase);
  [[nodiscard]] std::optional<std::uint32_t> current_active_vertex() const;
  [[nodiscard]] bool controller_memory_overlap_phase() const noexcept;
  void sort_changed_vertices_for_emit();
  void begin_full_path(const PartConvWord &overflow_edge);
  void reset_tile();

  std::size_t vertices_{};
  std::uint32_t source_{};
  std::shared_ptr<const GraphAlgorithmPolicy> algorithm_policy_;
  std::size_t tiny_threshold_{};
  std::size_t memory_request_window_{};
  std::size_t writeonly_request_window_{};
  SpineOnChipMemoryProfile on_chip_profile_;
  SpineComputePorts ports_;
  Fifo<PartConvWord> &edge_in_;
  Fifo<SourceValueWord> &value_out_;
  SpineOwnerScheduler *owner_scheduler_{};
  SpineComputeCounters counters_;
  std::vector<std::uint32_t> values_;
  std::vector<std::uint32_t> next_active_;
  std::vector<PartConvWord> tile_edges_;
  std::vector<std::uint32_t> gather_vertices_;
  std::vector<std::uint32_t> changed_vertices_;
  std::vector<std::uint32_t> tile_values_;
  std::deque<MemoryTask> memory_tasks_;
  std::unordered_map<std::uint64_t, MemoryTask> inflight_memory_tasks_;
  std::unordered_map<std::uint32_t, std::uint32_t> gathered_values_;
  std::deque<PendingTinyRead> pending_tiny_reads_;
  std::deque<PendingVsRead> pending_vs_reads_;
  std::deque<VsBypassEntry> vs_bypass_;
  std::array<std::uint64_t, 1024> tile_active_words_{};
  std::array<std::uint64_t, 128> deferred_bitmap_chunk_{};
  Phase phase_{Phase::kInput};
  Action staged_action_{Action::kNone};
  PartConvWord staged_edge_word_;
  SourceValueWord staged_value_word_;
  std::vector<AxiResponse> staged_responses_;
  AxiReadBeatResponse staged_full_tile_read_beat_;
  std::uint32_t pending_source_{};
  std::uint32_t pending_source_value_{kInfinity};
  SourceValueWord::Kind pending_value_kind_{SourceValueWord::Kind::kSourceValue};
  std::uint32_t tile_base_{};
  std::size_t tile_size_{};
  std::size_t relax_index_{};
  std::size_t active_word_index_{};
  std::size_t active_bit_index_{};
  std::size_t active_output_base_{};
  std::size_t active_output_index_{};
  std::uint64_t active_scan_bits_{};
  std::uint64_t active_read_due_cycle_{};
  std::size_t deferred_active_word_index_{};
  std::size_t deferred_sweep_base_word_{};
  std::size_t deferred_sweep_chunk_words_{};
  std::size_t deferred_sweep_word_index_{};
  std::size_t deferred_sweep_bit_index_{};
  std::size_t deferred_sweep_reads_pending_{};
  std::uint64_t deferred_sweep_scan_bits_{};
  std::uint64_t deferred_sweep_next_issue_cycle_{};
  std::uint64_t deferred_sweep_next_bit_cycle_{};
  std::uint64_t last_on_chip_read_wait_cycle_{~std::uint64_t{0}};
  std::uint64_t last_on_chip_pipeline_stall_cycle_{~std::uint64_t{0}};
  Phase after_clear_phase_{Phase::kRelax};
  std::uint64_t next_transaction_id_{};
  bool staged_memory_issue_{};
  bool staged_full_tile_read_beat_valid_{};
  bool staged_owner_activation_{};
  bool active_read_pending_{};
  bool active_read_ready_{};
  bool source_reply_pending_{};
  bool source_count_seen_{};
  bool source_generation_seen_{};
  bool source_protocol_overflow_{};
  bool deferred_active_{};
  bool tile_open_{};
  bool full_path_{};
  bool overflow_edge_pending_{};
  PartConvWord overflow_edge_;
  bool done_{};
  bool failed_{};
};

}  // namespace spine::sim
