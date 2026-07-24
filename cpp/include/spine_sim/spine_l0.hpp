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
  // Coarse task overlap is an explicit architecture what-if until each HLS
  // pipelined loop has its own issue/retire model. One is source-faithful.
  std::size_t memory_request_window{1};
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
  std::uint64_t result_write_bytes{};
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
  std::size_t max_memory_requests_inflight{};
  std::uint64_t cold_input_edges{};
  std::uint64_t hot_input_edges{};
  std::uint64_t carry_level_payload_reads{};
  std::uint64_t carry_level_payload_read_bytes{};
  std::uint64_t carry_new_batch_reads{};
  std::uint64_t carry_new_batch_read_bytes{};
  std::uint64_t carry_refill_wait_cycles{};
  std::size_t carry_max_buffered_heads{};
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
    kPrecountBegin,
    kPrecountProcess,
    kBuildOutputs,
    kWriteSelect,
    kWriteBegin,
    kWriteProcess,
    kCarryPrepare,
    kCarryProcess,
    kWriteAdvance,
    kCommitMetadata,
    kWriteResult,
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
    kCarryNewBatchRead,
    kCarryLevelEdgeRead,
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
    bool stream_sorted_scan{};
    std::size_t streamed_read_beats_expected{};
    std::size_t streamed_read_beats_received{};
  };

  enum class StagedAction { kNone, kAdvance };

  struct FamilyWriteTask;

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
                    std::size_t carry_edge_index = 0);
  void begin_sorted_scan(Phase process_phase, ScanKind kind);
  [[nodiscard]] bool process_scan_edge(const CycleContext &context);
  [[nodiscard]] bool scan_process_phase() const noexcept;
  [[nodiscard]] bool scan_can_advance(const CycleContext &context);
  [[nodiscard]] std::size_t scan_initiation_interval() const noexcept;
  [[nodiscard]] std::size_t scan_tail_cycles() const noexcept;
  [[nodiscard]] bool stage_read_beat();
  void consume_read_beat(const AxiReadBeatResponse &beat);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  [[nodiscard]] bool memory_task_conflicts(const MemoryTask &task) const;
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
  void enqueue_committed_metadata();
  void build_family_outputs();
  void enqueue_family_writes(bool hot, std::size_t family, std::size_t target);
  void initialize_carry_engine(const FamilyWriteTask &task);
  void enqueue_carry_index_reads(const FamilyWriteTask &task);
  void enqueue_carry_stream_refill(std::size_t stream_index);
  void consume_carry_memory_response(const MemoryTask &task,
                                     const AxiResponse &response);
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

  struct CarryInputStream {
    bool new_batch{};
    std::size_t level{};
    std::vector<std::uint32_t> sources;
    std::size_t next_index{};
    std::deque<SpineEdgeRecord> buffered;
    bool request_pending{};
    bool exhausted{};
  };

  SpineL0Config config_;
  SpineEdgeSlice workload_;
  SpineL0Ports ports_;
  SpineL0State &state_;
  SpineL0Counters counters_;
  std::vector<SpineEdgeRecord> sorted_scan_edges_;
  std::vector<CarryInputStream> carry_streams_;
  std::vector<SpineEdgeRecord> carry_merge_inputs_;
  std::array<std::vector<SpineEdgeRecord>, 16> family_outputs_;
  std::array<std::vector<SpineEdgeRecord>, 16> hot_family_outputs_;
  std::array<std::array<std::uint32_t, kSpineLevelCount>, kSpineFamilyCount>
      slice_epochs_{};
  std::unordered_map<std::uint64_t, std::uint32_t> page_epochs_;
  std::vector<FamilyWriteTask> family_write_tasks_;
  std::deque<MemoryTask> tasks_;
  std::unordered_map<std::uint64_t, MemoryTask> inflight_tasks_;
  std::unordered_map<std::size_t, SpineEdgeRecord> scan_response_edges_;
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
  std::vector<std::uint8_t> dirty_bitmap_original_payload_;
  std::size_t family_index_{};
  std::size_t active_family_index_{};
  bool precount_hot_{};
  std::uint64_t next_transaction_id_{};
  bool done_{};
  bool failed_{};
  std::string failure_;
  StagedAction staged_action_{StagedAction::kNone};
  AxiResponse staged_response_;
  AxiReadBeatResponse staged_read_beat_response_;
  bool staged_memory_issue_{};
  bool staged_memory_completion_{};
  bool staged_read_beat_completion_{};
};

}  // namespace spine::sim
