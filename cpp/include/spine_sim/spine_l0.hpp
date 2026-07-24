#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <string>
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
  std::vector<std::uint32_t> hot_vertices;
  std::uint64_t sorted_edges_base{};
  std::uint64_t persistent_directory_base{64ULL << 20};
  std::uint64_t persistent_dirty_bitmap_base{96ULL << 20};
  std::uint64_t persistent_dirty_list_base{128ULL << 20};
  std::uint64_t metadata_base{};
  std::uint64_t result_base{};
};

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
  std::uint64_t active_families{};
  std::uint64_t persisted_edges{};
  std::uint64_t persisted_rows{};
  std::uint64_t pages_stamped{};
  std::uint64_t memory_tasks{};
  std::uint64_t cold_input_edges{};
  std::uint64_t hot_input_edges{};
  std::uint64_t carry_level_payload_reads{};
  std::uint64_t carry_level_payload_read_bytes{};
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
    kDirtyPreflightBegin,
    kDirtyPreflightProcess,
    kDirtyUpdateBegin,
    kDirtyUpdateProcess,
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

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    TaskClass task_class{TaskClass::kSorted};
    std::vector<std::uint8_t> write_data;
    std::vector<std::uint32_t> carry_edge_sources;
  };

  enum class StagedAction { kNone, kAdvance, kIssue, kComplete };

  void advance(const CycleContext &context);
  void enqueue_task(FixedAxiPort &port, MemoryOperation operation,
                    std::uint64_t address, std::uint64_t bytes,
                    TaskClass task_class,
                    std::vector<std::uint8_t> write_data = {},
                    std::vector<std::uint32_t> carry_edge_sources = {});
  void begin_sorted_scan(Phase process_phase);
  void process_scan_edge(Phase next_phase);
  void consume_memory_response(const MemoryTask &task,
                               const AxiResponse &response);
  void enqueue_dirty_source_updates();
  void build_family_outputs();
  void enqueue_family_writes(bool hot, std::size_t family, std::size_t target);
  void enqueue_carry_reads(bool hot, std::size_t family, std::size_t target);
  void commit_level_state(bool hot, std::size_t target);
  [[nodiscard]] std::vector<SpineEdgeRecord> coalesce_family(
      bool hot, std::size_t family) const;
  [[nodiscard]] std::vector<SpineEdgeRecord> merge_family(
      bool hot, std::size_t family, std::size_t target) const;
  [[nodiscard]] std::vector<SpineEdgeRecord> merge_family_with_carry_payload(
      bool hot, std::size_t family) const;
  [[nodiscard]] std::size_t family_for(std::uint32_t dst) const;
  [[nodiscard]] std::size_t target_for(bool hot) const;
  [[nodiscard]] bool edge_is_hot(std::uint32_t dst) const;

  struct FamilyWriteTask {
    bool hot{};
    std::size_t family{};
    std::size_t target{};
  };

  SpineL0Config config_;
  SpineEdgeSlice workload_;
  SpineL0Ports ports_;
  SpineL0State &state_;
  SpineL0Counters counters_;
  std::vector<SpineEdgeRecord> sorted_scan_edges_;
  std::vector<SpineEdgeRecord> carry_payload_edges_;
  std::array<std::vector<SpineEdgeRecord>, 16> family_outputs_;
  std::array<std::vector<SpineEdgeRecord>, 16> hot_family_outputs_;
  std::vector<FamilyWriteTask> family_write_tasks_;
  std::deque<MemoryTask> tasks_;
  Phase phase_{Phase::kInitialize};
  std::size_t scan_index_{};
  std::size_t family_index_{};
  std::size_t active_family_index_{};
  std::size_t carry_steps_remaining_{};
  bool precount_hot_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_{};
  bool done_{};
  bool failed_{};
  std::string failure_;
  StagedAction staged_action_{StagedAction::kNone};
  AxiResponse staged_response_;
};

}  // namespace spine::sim
