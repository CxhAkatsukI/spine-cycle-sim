#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <span>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

struct SpineEdgeRecord {
  std::uint32_t src{};
  std::uint32_t dst{};
  std::uint16_t weight{1};
  std::int16_t diff{1};

  friend bool operator==(const SpineEdgeRecord &,
                         const SpineEdgeRecord &) = default;
};

struct SpineEdgeSlice {
  std::size_t vertices{};
  std::vector<SpineEdgeRecord> edges;
  std::string case_name;
};

SpineEdgeSlice load_spine_edge_slice(const std::filesystem::path &path);
inline constexpr std::uint64_t kSpineSortWordBytes = 16;
inline constexpr std::uint64_t kSpineGraphWordBytes = 8;
inline constexpr std::uint64_t kSpineMetadataWordBytes = 8;
inline constexpr std::uint64_t kSpineActiveRecordBytes = 32;
inline constexpr std::size_t kSpineFamilyCount = 32;
inline constexpr std::size_t kSpineLevelCount = 11;
inline constexpr std::size_t kSpineMaintenanceResultWords = 96;
inline constexpr std::size_t kSpineMaintenanceResultBytes =
    kSpineMaintenanceResultWords * sizeof(std::int32_t);
[[nodiscard]] std::vector<std::uint8_t> encode_spine_sort_edge(
    const SpineEdgeRecord &edge);
[[nodiscard]] SpineEdgeRecord decode_spine_sort_edge(
    const std::vector<std::uint8_t> &data);
[[nodiscard]] std::vector<std::uint8_t> encode_spine_sort_edges(
    const std::vector<SpineEdgeRecord> &edges);
[[nodiscard]] std::vector<SpineEdgeRecord> decode_spine_sort_edges(
    const std::vector<std::uint8_t> &data);
[[nodiscard]] std::vector<std::uint8_t> encode_spine_level_edge(
    const SpineEdgeRecord &edge);
[[nodiscard]] SpineEdgeRecord decode_spine_level_edge(
    const std::vector<std::uint8_t> &data, std::uint32_t source);

enum class SpineMaintenancePath : std::int32_t {
  kNone = 0,
  kStoreL0 = 2,
  kCascade = 3,
  kOverflow = 5,
};

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

struct SpineMaintenanceResult {
  static constexpr std::size_t kInputEdges = 0;
  static constexpr std::size_t kOverflow = 1;
  static constexpr std::size_t kLevels = 2;
  static constexpr std::size_t kPartitions = 3;
  static constexpr std::size_t kMaxSort = 4;
  static constexpr std::size_t kTargetLevel = 5;
  static constexpr std::size_t kConsumedLevelMask = 6;
  static constexpr std::size_t kPersistedEdges = 7;
  static constexpr std::size_t kPath = 8;
  static constexpr std::size_t kUnsupported = 9;
  static constexpr std::size_t kNonemptyPartitions = 10;
  static constexpr std::size_t kPartitionEdgeCountBase = 16;
  static constexpr std::size_t kEpochPartitionsWritten = 32;
  static constexpr std::size_t kEpochPagesStamped = 33;
  static constexpr std::size_t kEpochFullClearFallbacks = 34;
  static constexpr std::size_t kEpochWrapEvents = 35;
  static constexpr std::size_t kEpochCommitFailures = 36;
  static constexpr std::size_t kHotEdges = 37;
  static constexpr std::size_t kColdEdges = 38;
  static constexpr std::size_t kCarryColdBase = 39;
  static constexpr std::size_t kCarryHotBase = 57;
  static constexpr std::size_t kLayoutVersion = 75;
  static constexpr std::size_t kMetadataFormatVersion = 76;
  static constexpr std::size_t kDirtyMode = 80;
  static constexpr std::size_t kDirtyStatus = 81;
  static constexpr std::size_t kDirtyCount = 82;
  static constexpr std::size_t kDirtyGeneration = 83;
  static constexpr std::size_t kDirtyHashSumLow = 84;
  static constexpr std::size_t kDirtyHashSumHigh = 85;
  static constexpr std::size_t kDirtyHashXorLow = 86;
  static constexpr std::size_t kDirtyHashXorHigh = 87;
  static constexpr std::size_t kDirtyUniqueInputSources = 88;
  static constexpr std::size_t kDirtyBitmapReads = 89;
  static constexpr std::size_t kDirtyBitmapWrites = 90;
  static constexpr std::size_t kDirtyListAppends = 91;
  static constexpr std::size_t kDirtyDuplicatesSuppressed = 92;
  static constexpr std::size_t kDirtyGenerationAdvances = 93;
  static constexpr std::size_t kDirtyConservativeSources = 94;
  static constexpr std::size_t kDirtyAux = 95;

  std::array<std::int32_t, kSpineMaintenanceResultWords> words{};

  [[nodiscard]] std::int32_t operator[](std::size_t index) const {
    return words.at(index);
  }
};

[[nodiscard]] std::vector<std::uint8_t> encode_spine_maintenance_result(
    const SpineMaintenanceResult &result);
[[nodiscard]] SpineMaintenanceResult decode_spine_maintenance_result(
    std::span<const std::uint8_t> data);

struct SpineL0Config {
  std::size_t partitions{16};
  std::size_t levels{11};
  std::uint32_t vertex_partition_size{1U << 20};
  std::uint32_t page_vertices{256};
  std::uint32_t max_vertices{1U << 24};
  std::uint32_t max_sort_edges{131'072};
  // Production defaults mirror the fixed capacities in
  // spine_partitioned.hpp. Smaller values exercise the otherwise very large
  // fallback boundaries in cycle-level tests.
  std::size_t device_dirty_source_limit{4'096};
  std::size_t range_task_active_gate{16'384};
  std::size_t range_task_capacity{65'536};
  std::uint64_t range_task_payload_budget{1'048'576};
  std::uint64_t fallback_replay_threshold{65'536};
  // Logical parent-request window per independent m_axi initiator. A value of
  // one keeps each bundle ordered while allowing different HLS bundles to
  // overlap. Values above one remain an explicit same-bundle overlap what-if
  // until every enclosing HLS loop has its own issue/retire model.
  std::size_t memory_request_window{1};
  // The target selector's metadata loop reaches II=2 because each family
  // iteration performs two reads on gmem_meta. The accepted synthesis report
  // has an iteration latency of 16 cycles, so 16 parent reads cover its
  // maximum source-visible overlap without applying the coarse global window.
  std::size_t maintenance_target_select_request_window{16};
  std::size_t maintenance_result_request_window{16};
  std::size_t maintenance_cold_target_select_min_cycles{562};
  std::size_t maintenance_hot_target_select_min_cycles{551};
  // Accepted hot-classification loops issue one gmem_meta bitmap read per
  // edge and overlap up to the default HLS m_axi read-outstanding depth.
  std::size_t maintenance_hot_bitmap_request_window{16};
  // The HLS edge loops achieve II=1. Two outstanding 16-beat reads provide 32
  // edge-word credits in the accepted synthesis report.
  std::size_t reader_edge_pipeline_depth{32};
  std::size_t reader_edge_response_capacity{32};
  // Accepted HLS loop reports: count/precount latency is N+19 cycles;
  // L0 write latency is 24*(N-1)+43 cycles.
  std::size_t maintenance_count_scan_ii{1};
  std::size_t maintenance_count_scan_tail_cycles{19};
  std::size_t maintenance_l0_write_scan_ii{24};
  std::size_t maintenance_l0_write_scan_tail_cycles{42};
  std::size_t maintenance_scan_response_capacity{32};
  std::vector<std::uint32_t> hot_vertices;
  std::uint64_t sorted_edges_base{};
  // HBM16 is shared by sorted input/range-task scratch and the persistent
  // dirty frontier. These defaults match the production HLS ABI.
  std::uint64_t persistent_dirty_bitmap_base{2ULL << 20};
  std::uint64_t persistent_dirty_list_base{4ULL << 20};
  std::uint64_t metadata_base{};
  std::uint64_t result_base{};
};

struct SpineMetadataLayout {
  std::uint64_t page_count{};
  std::uint64_t slice_count{};
  std::uint64_t slice_words{};
  std::uint64_t active_bin_offset_base{};
  std::uint64_t active_bin_count_base{};
  std::uint64_t slice_epoch_base{};
  std::uint64_t page_epoch_base{};
  std::uint64_t hot_bitmap_base{};
  std::uint64_t hot_bitmap_words{};
  std::uint64_t hot_enabled_word{};
  std::uint64_t page_list_count_base{};
  std::uint64_t page_list_base{};
  std::uint64_t page_list_words_per_slice{};
  std::uint64_t dirty_base{};
  std::uint64_t dirty_count_word{};
  std::uint64_t dirty_generation_word{};
  std::uint64_t dirty_hash_sum_word{};
  std::uint64_t dirty_hash_xor_word{};
  std::uint64_t dirty_candidate_generation_word{};
  std::uint64_t dirty_candidate_count_word{};
  std::uint64_t dirty_candidate_hash_sum_word{};
  std::uint64_t dirty_candidate_hash_xor_word{};
  std::uint64_t dirty_candidate_valid_word{};
  std::uint64_t dirty_host_generation_word{};
  std::uint64_t dirty_host_count_word{};
  std::uint64_t dirty_host_hash_sum_word{};
  std::uint64_t dirty_host_hash_xor_word{};
  std::uint64_t dirty_host_valid_word{};
  std::uint64_t dirty_last_mode_word{};
  std::uint64_t dirty_last_status_word{};
  std::uint64_t total_words{};
};

struct SpineActiveRecord {
  std::uint32_t source{};
  std::uint32_t source_value{};
  std::array<std::uint16_t, kSpineLevelCount> level_masks{};
  std::uint16_t hot_shard_mask{};

  friend bool operator==(const SpineActiveRecord &,
                         const SpineActiveRecord &) = default;
};

struct SpineActiveBins {
  std::array<std::vector<SpineActiveRecord>, 16> bins;

  [[nodiscard]] std::size_t size() const noexcept {
    std::size_t total = 0;
    for (const auto &bin : bins) {
      total += bin.size();
    }
    return total;
  }
};

struct SpineDirtyIdentity {
  std::uint32_t generation{};
  std::uint64_t count{};
  std::uint64_t hash_sum{};
  std::uint64_t hash_xor{};

  friend bool operator==(const SpineDirtyIdentity &,
                         const SpineDirtyIdentity &) = default;
};

[[nodiscard]] SpineMetadataLayout spine_metadata_layout(
    const SpineL0Config &config);
[[nodiscard]] std::uint64_t spine_metadata_control_word(bool hot_enabled);
[[nodiscard]] bool spine_metadata_control_valid(std::uint64_t control) noexcept;
[[nodiscard]] std::uint64_t spine_dirty_hash_sum_term(
    std::uint32_t source) noexcept;
[[nodiscard]] std::uint64_t spine_dirty_hash_xor_term(
    std::uint32_t source) noexcept;
[[nodiscard]] SpineDirtyIdentity spine_dirty_identity(
    std::uint32_t generation, std::span<const std::uint32_t> sources);
[[nodiscard]] std::vector<std::uint8_t> encode_spine_active_record(
    const SpineActiveRecord &record);
[[nodiscard]] SpineActiveRecord decode_spine_active_record(
    std::span<const std::uint8_t> data);

struct SpineLevelLayout {
  std::uint64_t bitmap_offset_words{};
  std::uint64_t page_base_offset_words{};
  std::uint64_t row_offset_offset_words{};
  std::uint64_t mask_offset_words{};
  std::uint64_t edge_offset_words{};
  std::uint64_t edge_capacity{};
  std::uint64_t row_capacity_words{};
  std::uint64_t mask_capacity_words{};
};

[[nodiscard]] std::uint32_t spine_hot_dst_hash(std::uint32_t dst) noexcept;
[[nodiscard]] std::size_t spine_hot_shard(std::uint32_t dst) noexcept;
[[nodiscard]] SpineLevelLayout spine_level_layout(const SpineL0Config &config,
                                                  bool hot, std::size_t level);
[[nodiscard]] SpineLevelLayout spine_slice_layout(
    const SpineL0Config &config, bool hot, std::size_t level,
    std::uint64_t row_count);

struct SpineL0State {
  std::array<std::array<std::vector<SpineEdgeRecord>, 11>, 16> cold_levels;
  std::array<std::array<std::vector<SpineEdgeRecord>, 11>, 16> hot_levels;
  std::unordered_set<std::uint32_t> hot_vertices;
  bool hot_enabled{};
};

struct SpineL0Counters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t sorted_scan_passes{};
  std::uint64_t sorted_edge_visits{};
  std::uint64_t sorted_read_bytes{};
  std::uint64_t sorted_payload_read_bytes{};
  std::uint64_t sorted_read_beats_received{};
  std::uint64_t sorted_scan_response_stall_cycles{};
  std::uint64_t sorted_scan_reorder_full_stall_cycles{};
  std::uint64_t sorted_scan_ii_stall_cycles{};
  std::uint64_t sorted_scan_tail_cycles{};
  std::size_t max_sorted_scan_buffered_edges{};
  std::uint64_t dirty_validate_edge_visits{};
  std::uint64_t dirty_mark_edge_visits{};
  std::uint64_t hot_cold_count_edge_visits{};
  std::uint64_t family_precount_edge_visits{};
  std::uint64_t l0_write_edge_visits{};
  std::uint64_t persistent_read_bytes{};
  std::uint64_t persistent_write_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t metadata_write_bytes{};
  std::uint64_t graph_read_bytes{};
  std::uint64_t graph_write_bytes{};
  std::uint64_t graph_index_payload_write_bytes{};
  std::uint64_t graph_edge_payload_write_bytes{};
  std::uint64_t page_list_payload_write_bytes{};
  std::uint64_t page_list_count_write_bytes{};
  std::uint64_t result_write_bytes{};
  std::uint64_t result_payload_write_bytes{};
  std::uint64_t result_write_responses{};
  std::uint64_t result_metadata_reads{};
  std::uint64_t result_metadata_responses{};
  std::uint64_t result_metadata_payload_read_bytes{};
  std::size_t result_metadata_max_inflight{};
  std::uint64_t result_validation_failures{};
  std::uint64_t logical_overflow_events{};
  std::uint64_t slice_epoch_reads{};
  std::uint64_t slice_epoch_responses{};
  std::uint64_t slice_epoch_payload_read_bytes{};
  std::uint64_t slice_epoch_validation_failures{};
  std::uint64_t epoch_full_clear_fallbacks{};
  std::uint64_t epoch_wrap_events{};
  std::uint64_t epoch_commit_failures{};
  std::uint64_t epoch_clear_parent_writes{};
  std::uint64_t epoch_clear_word_writes{};
  std::uint64_t epoch_clear_payload_write_bytes{};
  std::uint64_t epoch_clear_write_responses{};
  std::uint64_t epoch_clear_wait_cycles{};
  std::uint64_t epoch_retire_writes{};
  std::uint64_t epoch_retire_write_responses{};
  std::uint64_t unique_sources{};
  std::uint64_t dirty_bitmap_reads{};
  std::uint64_t dirty_bitmap_writes{};
  std::uint64_t dirty_list_reads{};
  std::uint64_t dirty_list_appends{};
  std::uint64_t dirty_duplicates_suppressed{};
  std::uint64_t dirty_generation_advances{};
  std::uint32_t dirty_count{};
  std::uint32_t dirty_generation{};
  std::uint64_t dirty_hash_sum{};
  std::uint64_t dirty_hash_xor{};
  std::uint64_t active_families{};
  std::uint64_t persisted_edges{};
  std::uint64_t persisted_rows{};
  std::uint64_t pages_stamped{};
  std::uint64_t memory_tasks{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t memory_window_stall_cycles{};
  std::uint64_t memory_dependency_stall_cycles{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::size_t max_memory_requests_issued_per_cycle{};
  std::size_t max_memory_responses_completed_per_cycle{};
  std::uint64_t multi_port_issue_cycles{};
  std::uint64_t multi_port_response_cycles{};
  std::size_t max_memory_requests_inflight{};
  std::size_t max_memory_requests_inflight_per_port{};
  std::size_t max_non_target_memory_requests_inflight_per_port{};
  std::size_t max_active_memory_ports{};
  std::uint64_t memory_cross_port_overlap_cycles{};
  std::uint64_t target_selector_invocations{};
  std::uint64_t target_selector_levels_scanned{};
  std::uint64_t target_selector_family_iterations{};
  std::uint64_t target_selector_metadata_reads{};
  std::uint64_t target_selector_payload_read_bytes{};
  std::uint64_t target_selector_responses{};
  std::uint64_t target_selector_cycles{};
  std::uint64_t target_selector_min_padding_cycles{};
  std::uint64_t target_selector_validation_failures{};
  std::size_t target_selector_max_inflight{};
  std::uint64_t metadata_control_reads{};
  std::uint64_t metadata_control_payload_read_bytes{};
  std::uint64_t hot_bitmap_reads{};
  std::uint64_t hot_bitmap_scan_reads{};
  std::uint64_t hot_bitmap_carry_reads{};
  std::uint64_t hot_bitmap_responses{};
  std::uint64_t hot_bitmap_payload_read_bytes{};
  std::uint64_t hot_bitmap_scan_wait_cycles{};
  std::uint64_t hot_bitmap_validation_failures{};
  std::size_t hot_bitmap_max_inflight{};
  std::uint64_t cold_input_edges{};
  std::uint64_t hot_input_edges{};
  std::uint64_t carry_level_payload_reads{};
  std::uint64_t carry_level_payload_read_bytes{};
  std::uint64_t carry_new_batch_reads{};
  std::uint64_t carry_new_batch_read_bytes{};
  std::uint64_t carry_refill_wait_cycles{};
  std::size_t carry_max_buffered_heads{};
  std::uint64_t carry_cursor_metadata_read_bytes{};
  std::uint64_t carry_cursor_page_ids{};
  std::uint64_t carry_cursor_pages_visited{};
  std::uint64_t carry_cursor_bitmap_words{};
  std::uint64_t carry_cursor_bits_inspected{};
  std::uint64_t carry_cursor_refill_cycles{};
  std::uint64_t carry_cursor_rows_entered{};
  std::uint64_t carry_cursor_row_offset_reads{};
  std::uint64_t carry_cursor_validation_failures{};
  std::uint64_t carry_writer_groups_seen{};
  std::uint64_t carry_writer_groups_emitted{};
  std::uint64_t carry_writer_groups_cancelled{};
  std::uint64_t carry_writer_edge_word_writes{};
  std::uint64_t carry_writer_row_word_writes{};
  std::uint64_t carry_writer_mask_word_writes{};
  std::uint64_t carry_writer_page_base_word_writes{};
  std::uint64_t carry_writer_bitmap_page_writes{};
  std::uint64_t carry_writer_page_list_word_writes{};
  std::uint64_t carry_writer_page_epoch_word_writes{};
  std::uint64_t carry_writer_memory_wait_cycles{};
  std::uint64_t l0_writer_groups_seen{};
  std::uint64_t l0_writer_groups_emitted{};
  std::uint64_t l0_writer_groups_cancelled{};
  std::uint64_t l0_writer_edge_word_writes{};
  std::uint64_t l0_writer_row_word_writes{};
  std::uint64_t l0_writer_mask_word_writes{};
  std::uint64_t l0_writer_page_base_word_writes{};
  std::uint64_t l0_writer_bitmap_page_writes{};
  std::uint64_t l0_writer_page_list_word_writes{};
  std::uint64_t l0_writer_page_epoch_word_writes{};
  std::uint64_t l0_writer_memory_wait_cycles{};
  std::uint64_t l0_writer_memory_overlap_cycles{};
  std::uint64_t l0_writer_backpressure_stall_cycles{};
  std::uint64_t l0_writer_validation_failures{};
  std::size_t l0_writer_max_pending_tasks{};
  std::size_t l0_writer_max_pending_tasks_per_port{};
  std::uint64_t carry_merge_inputs{};
  std::uint64_t carry_outputs{};
  std::int32_t target_level{-1};
  std::int32_t hot_target_level{-1};
  bool hot_enabled{};
  std::array<std::uint64_t, 16> family_edges{};
  std::array<std::uint64_t, 16> family_rows{};
  std::array<std::uint64_t, 16> hot_family_edges{};
  std::array<std::uint64_t, 16> hot_family_rows{};
};

struct SpineL0Ports {
  std::array<FixedAxiPort *, 16> graph{};
  FixedAxiPort *sorted_edges{};
  FixedAxiPort *metadata{};
  FixedAxiPort *result{};
};

class SpineL0Maintenance final : public Component {
 public:
  SpineL0Maintenance(std::string name, ClockId clock_id, SpineL0Config config,
                     SpineEdgeSlice workload, SpineL0Ports ports,
                     SpineL0State &state);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineL0Counters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] const SpineL0Config &config() const noexcept { return config_; }
  [[nodiscard]] std::size_t vertices() const noexcept {
    return workload_.vertices;
  }

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

 private:
  enum class Phase {
    kInitialize,
    kDirtyMetadataLoad,
    kDirtyPreflightBegin,
    kDirtyPreflightProcess,
    kDirtyGenerationPrepare,
    kDirtyUpdateBegin,
    kDirtyUpdateProcess,
    kDirtyFinalize,
    kHotColdCountBegin,
    kHotColdCountProcess,
    kTargetSelect,
    kTargetSelectLevelWait,
    kTargetSelectPadding,
    kPrecountBegin,
    kPrecountProcess,
    kBuildOutputs,
    kWriteSelect,
    kWriteEpochResolve,
    kWriteEpochClear,
    kWriteProcess,
    kCarryProcess,
    kWriteAdvance,
    kCommitMetadata,
    kWriteResult,
    kRetireEpochs,
    kCollectResult,
    kFinish,
  };

  enum class TaskClass {
    kSorted,
    kPersistent,
    kMetadata,
    kGraph,
    kResult,
  };

  enum class TaskPurpose {
    kGeneric,
    kDirtyMetadataLoad,
    kDirtyMarkEdge,
    kDirtyBitmapRead,
    kDirtyBitmapWrite,
    kDirtyBitmapOverflowSet,
    kDirtyBitmapOverflowClear,
    kDirtyListRead,
    kDirtyListWrite,
    kMetadataControl,
    kScanHotBitmap,
    kTargetMetadataOccupied,
    kTargetMetadataEdgeCount,
    kResultColdEdgeCount,
    kResultHotEdgeCount,
    kMaintenanceResultWrite,
    kLevelWriterSliceEpochRead,
    kLevelWriterEpochClear,
    kEpochRetireWrite,
    kCarryNewBatchRead,
    kCarryNewBatchHotBitmap,
    kCarryCursorSliceMetadata,
    kCarryCursorSliceEpoch,
    kCarryCursorPageCount,
    kCarryCursorPageList,
    kCarryCursorPageEpoch,
    kCarryCursorPageBase,
    kCarryCursorBitmap,
    kCarryCursorRowOffsets,
    kCarryLevelEdgeRead,
    kLevelWriterGraphWrite,
    kLevelWriterMetadataWrite,
  };

  enum class ScanKind {
    kDirtyValidate,
    kDirtyMark,
    kHotColdCount,
    kFamilyPrecount,
    kL0Write,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    TaskClass task_class{TaskClass::kSorted};
    std::vector<std::uint8_t> write_data;
    std::vector<std::uint32_t> carry_edge_sources;
    TaskPurpose purpose{TaskPurpose::kGeneric};
    std::uint32_t source{};
    std::size_t carry_stream{};
    std::size_t carry_edge_index{};
    std::size_t metadata_family{};
    std::size_t metadata_level{};
    bool stream_sorted_scan{};
    std::size_t streamed_read_beats_expected{};
    std::size_t streamed_read_beats_received{};
  };

  struct StagedMemoryIssue {
    std::size_t task_index{};
    std::uint64_t transaction_id{};
  };

  enum class StagedAction { kNone, kAdvance };

  struct FamilyWriteTask;
  struct LevelPendingWord;

  void advance(const CycleContext &context);
  void enqueue_task(FixedAxiPort &port, MemoryOperation operation,
                    std::uint64_t address, std::uint64_t bytes,
                    TaskClass task_class,
                    std::vector<std::uint8_t> write_data = {},
                    std::vector<std::uint32_t> carry_edge_sources = {},
                    bool stream_sorted_scan = false,
                    TaskPurpose purpose = TaskPurpose::kGeneric,
                    std::uint32_t source = 0,
                    std::size_t carry_stream = 0,
                    std::size_t carry_edge_index = 0,
                    std::size_t metadata_family = 0,
                    std::size_t metadata_level = 0);
  void begin_sorted_scan(Phase process_phase, ScanKind kind);
  [[nodiscard]] bool process_scan_edge(const CycleContext &context);
  [[nodiscard]] bool scan_process_phase() const noexcept;
  [[nodiscard]] bool scan_can_advance(const CycleContext &context);
  [[nodiscard]] std::size_t scan_initiation_interval() const noexcept;
  [[nodiscard]] std::size_t scan_tail_cycles() const noexcept;
  [[nodiscard]] bool scan_requires_hot_bitmap() const noexcept;
  void enqueue_scan_hot_bitmap_read(std::size_t index,
                                    std::uint32_t destination);
  void enqueue_carry_hot_bitmap_read(std::size_t stream_index,
                                     const SpineEdgeRecord &edge);
  [[nodiscard]] bool stage_read_beat();
  void consume_read_beat(const AxiReadBeatResponse &beat);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  [[nodiscard]] bool memory_task_conflicts(const MemoryTask &task) const;
  [[nodiscard]] std::size_t
  inflight_memory_tasks_for_port(const FixedAxiPort *port) const noexcept;
  [[nodiscard]] std::size_t active_memory_ports() const noexcept;
  void update_memory_concurrency_counters(const FixedAxiPort *issued_port);
  void stage_memory_issues();
  [[nodiscard]] bool stage_memory_completion();
  void enqueue_dirty_metadata_load();
  void enqueue_dirty_generation_prepare();
  void enqueue_dirty_mark_edge_read();
  void enqueue_dirty_bitmap_read(std::uint32_t source);
  void enqueue_dirty_final_metadata();
  void finish_dirty_source_update();
  void consume_dirty_memory_response(const MemoryTask &task,
                                     const AxiResponse &response);
  void initialize_metadata_payload();
  void initialize_target_selector(bool hot, const CycleContext &context);
  void enqueue_target_selector_level();
  void resolve_target_selector_level(const CycleContext &context);
  void finish_target_selector(const CycleContext &context);
  void consume_target_selector_response(const MemoryTask &task,
                                        const AxiResponse &response);
  void consume_metadata_control_response(const AxiResponse &response);
  void consume_hot_bitmap_response(const MemoryTask &task,
                                   const AxiResponse &response);
  void enqueue_result_metadata_reads();
  void consume_result_metadata_response(const MemoryTask &task,
                                        const AxiResponse &response);
  [[nodiscard]] SpineMaintenanceResult build_maintenance_result() const;
  void enqueue_maintenance_result();
  void begin_logical_overflow(std::string failure,
                              SpineDirtyStatus dirty_status);
  void enqueue_active_writer_epoch_read();
  void consume_active_writer_epoch_response(const MemoryTask &task,
                                            const AxiResponse &response);
  void prepare_active_writer_epoch();
  void enqueue_epoch_full_clear(const FamilyWriteTask &task);
  void begin_active_family_write();
  [[nodiscard]] bool enqueue_retired_writer_epochs();
  [[nodiscard]] bool target_selector_phase() const noexcept;
  [[nodiscard]] std::size_t
  memory_request_window_for(const MemoryTask &task) const noexcept;
  void enqueue_committed_metadata();
  void build_family_outputs();
  void initialize_carry_engine(const FamilyWriteTask &task);
  void enqueue_carry_cursor_metadata(std::size_t stream_index);
  void maybe_enqueue_carry_page_list(std::size_t stream_index);
  void enqueue_carry_page_indexes(std::size_t stream_index);
  void finalize_carry_page_indexes(std::size_t stream_index);
  void enqueue_carry_stream_refill(std::size_t stream_index);
  void consume_carry_memory_response(const MemoryTask &task,
                                     const AxiResponse &response);
  void initialize_l0_level_writer(const FamilyWriteTask &task);
  void initialize_carry_level_writer(const FamilyWriteTask &task);
  void accumulate_level_writer(const SpineEdgeRecord &entry);
  void emit_level_writer_group(const FamilyWriteTask &task);
  void finalize_level_writer(const FamilyWriteTask &task);
  void level_writer_write_u32(std::uint64_t base_word,
                              std::uint32_t index, std::uint32_t value,
                              LevelPendingWord &pending,
                              std::uint64_t &counter);
  void level_writer_write_u16(std::uint64_t base_word,
                              std::uint32_t index, std::uint16_t value,
                              LevelPendingWord &pending,
                              std::uint64_t &counter);
  void level_writer_flush_graph_word(std::uint64_t base_word,
                                     LevelPendingWord &pending,
                                     std::uint64_t &counter);
  void level_writer_flush_bitmap();
  void level_writer_append_page(std::uint32_t page);
  void level_writer_flush_page_list();
  [[nodiscard]] std::size_t queued_level_writer_tasks_for_port(
      const FixedAxiPort *port) const noexcept;
  [[nodiscard]] bool l0_writer_has_queue_headroom() const noexcept;
  [[nodiscard]] bool advance_carry_merge();
  void finish_carry_merge(const FamilyWriteTask &task);
  void commit_level_state(bool hot, std::size_t target);
  [[nodiscard]] std::vector<SpineEdgeRecord> coalesce_family(
      bool hot, std::size_t family) const;
  [[nodiscard]] std::vector<SpineEdgeRecord> merge_family(
      bool hot, std::size_t family, std::size_t target) const;
  [[nodiscard]] std::size_t family_for(std::uint32_t dst) const;
  [[nodiscard]] std::size_t target_for(bool hot) const;
  [[nodiscard]] bool edge_is_hot(std::uint32_t dst) const;

  struct FamilyWriteTask {
    bool hot{};
    std::size_t family{};
    std::size_t target{};
  };

  struct LevelPendingWord {
    std::uint64_t value{};
    std::uint32_t index{};
    bool valid{};
  };

  struct LevelWriterStats {
    std::uint64_t groups_seen{};
    std::uint64_t groups_emitted{};
    std::uint64_t groups_cancelled{};
    std::uint64_t edge_word_writes{};
    std::uint64_t row_word_writes{};
    std::uint64_t mask_word_writes{};
    std::uint64_t page_base_word_writes{};
    std::uint64_t bitmap_page_writes{};
    std::uint64_t page_list_word_writes{};
    std::uint64_t page_epoch_word_writes{};
  };

  struct CarryResultCounters {
    std::uint64_t page_ids_written{};
    std::uint64_t validation_failures{};
    std::uint64_t pages_visited{};
    std::uint64_t bits_inspected{};
    std::uint64_t rows_entered{};
    std::uint64_t payload_reads{};
    std::uint64_t refill_stalls{};
    std::uint64_t merge_inputs{};
    std::uint64_t outputs{};
  };

  [[nodiscard]] CarryResultCounters &active_carry_result_counters();

  struct LevelWriterState {
    SpineLevelLayout layout;
    LevelWriterStats stats;
    LevelPendingWord row;
    LevelPendingWord mask;
    LevelPendingWord page_base;
    LevelPendingWord page_list;
    std::array<std::uint64_t, 4> bitmap{};
    SpineEdgeRecord group;
    std::int64_t group_diff{};
    std::uint32_t epoch{};
    std::uint32_t row_index{};
    std::uint32_t edge_index{};
    std::uint32_t last_source{};
    std::uint32_t last_page{};
    std::uint32_t current_mask_index{};
    std::uint32_t bitmap_page{};
    std::uint32_t page_list_count{};
    std::uint32_t expected_rows{};
    std::uint32_t expected_edges{};
    std::uint16_t current_mask{};
    bool initialized{};
    bool group_valid{};
    bool have_last_source{};
    bool have_last_page{};
    bool bitmap_valid{};
    bool finalized{};
    bool was_active{};
    bool l0_mode{};
  };

  struct CarryInputStream {
    bool new_batch{};
    std::size_t level{};
    std::vector<std::uint32_t> sources;
    std::uint64_t bitmap_offset_words{};
    std::uint64_t page_base_offset_words{};
    std::uint64_t row_offset_offset_words{};
    std::uint64_t edge_offset_words{};
    std::uint32_t slice_epoch{};
    std::uint32_t page_count{};
    std::uint32_t row_count{};
    std::uint32_t edge_count{};
    std::vector<std::uint32_t> pages;
    std::vector<std::uint32_t> page_epochs;
    std::vector<std::uint32_t> page_bases;
    std::vector<std::array<std::uint64_t, 4>> page_bitmaps;
    std::size_t page_index_responses_pending{};
    std::size_t next_index{};
    std::deque<SpineEdgeRecord> buffered;
    SpineEdgeRecord pending_hot_edge;
    bool slice_epoch_ready{};
    bool page_count_ready{};
    bool page_list_requested{};
    bool cursor_ready{};
    bool request_pending{};
    bool pending_hot_edge_valid{};
    bool exhausted{};
  };

  SpineL0Config config_;
  SpineEdgeSlice workload_;
  SpineL0Ports ports_;
  SpineL0State &state_;
  SpineL0Counters counters_;
  std::vector<SpineEdgeRecord> sorted_scan_edges_;
  std::vector<CarryInputStream> carry_streams_;
  std::uint64_t carry_cursor_refill_cycles_remaining_{};
  LevelWriterState level_writer_;
  std::array<std::vector<SpineEdgeRecord>, 16> family_outputs_;
  std::array<std::vector<SpineEdgeRecord>, 16> hot_family_outputs_;
  std::array<std::array<std::uint32_t, kSpineLevelCount>, kSpineFamilyCount>
      slice_epochs_{};
  std::array<std::array<std::uint32_t, kSpineLevelCount>, kSpineFamilyCount>
      staged_writer_epochs_{};
  std::array<std::array<std::uint32_t, kSpineLevelCount>, kSpineFamilyCount>
      page_list_counts_{};
  std::unordered_map<std::uint64_t, std::uint32_t> page_epochs_;
  std::array<std::array<std::uint64_t, kSpineLevelCount>, kSpineFamilyCount>
      target_edge_counts_{};
  std::array<std::array<std::uint64_t, kSpineLevelCount>, kSpineFamilyCount>
      target_occupied_{};
  std::array<std::array<std::uint8_t, kSpineLevelCount>, kSpineFamilyCount>
      target_metadata_ready_{};
  std::array<std::uint64_t, 16> result_cold_edge_counts_{};
  std::array<std::uint64_t, 16> result_hot_edge_counts_{};
  std::array<bool, 16> result_cold_edge_counts_ready_{};
  std::array<bool, 16> result_hot_edge_counts_ready_{};
  std::array<CarryResultCounters, 2> carry_result_counters_{};
  std::vector<FamilyWriteTask> family_write_tasks_;
  std::deque<MemoryTask> tasks_;
  std::unordered_map<std::uint64_t, MemoryTask> inflight_tasks_;
  std::unordered_map<std::size_t, SpineEdgeRecord> scan_response_edges_;
  std::unordered_map<std::size_t, bool> scan_hot_results_;
  std::unordered_set<std::size_t> scan_hot_requests_pending_;
  std::unordered_map<std::uint32_t, bool> hot_classification_by_vertex_;
  Phase phase_{Phase::kInitialize};
  ScanKind scan_kind_{ScanKind::kDirtyValidate};
  std::size_t scan_index_{};
  std::size_t scan_tail_remaining_{};
  std::uint64_t next_scan_consume_cycle_{};
  std::uint64_t scan_transaction_id_{};
  bool scan_transaction_valid_{};
  bool streaming_scan_{};
  bool edge_by_edge_scan_{};
  bool scan_have_last_source_{};
  std::uint32_t scan_last_source_{};
  bool dirty_source_pending_{};
  std::uint32_t dirty_pending_source_{};
  std::uint32_t dirty_count_{};
  std::uint32_t dirty_generation_{};
  std::uint64_t dirty_hash_sum_{};
  std::uint64_t dirty_hash_xor_{};
  SpineDirtyStatus dirty_status_{SpineDirtyStatus::kOk};
  std::vector<std::uint8_t> dirty_bitmap_original_payload_;
  std::size_t family_index_{};
  std::size_t active_family_index_{};
  bool precount_hot_{};
  bool metadata_control_ready_{};
  bool metadata_hot_enabled_{};
  bool target_scan_hot_{};
  std::size_t target_scan_level_{};
  std::int32_t target_scan_candidate_{-1};
  std::uint64_t target_scan_start_cycle_{};
  std::uint64_t target_scan_min_finish_cycle_{};
  std::uint32_t active_writer_current_epoch_{};
  std::uint32_t active_writer_next_epoch_{};
  std::uint64_t next_transaction_id_{};
  bool active_writer_epoch_ready_{};
  bool active_writer_epoch_wrapped_{};
  bool logical_overflow_{};
  bool done_{};
  bool failed_{};
  std::string failure_;
  StagedAction staged_action_{StagedAction::kNone};
  std::vector<StagedMemoryIssue> staged_memory_issues_;
  std::vector<AxiResponse> staged_responses_;
  AxiReadBeatResponse staged_read_beat_response_;
  bool staged_memory_completion_{};
  bool staged_read_beat_completion_{};
};

}  // namespace spine::sim
