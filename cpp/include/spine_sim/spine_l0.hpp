#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <string>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

struct SpineEdgeRecord {
  std::uint32_t src{};
  std::uint32_t dst{};
  std::uint16_t weight{1};
  std::int16_t diff{1};

  friend bool operator==(const SpineEdgeRecord&, const SpineEdgeRecord&) = default;
};

struct SpineEdgeSlice {
  std::size_t vertices{};
  std::vector<SpineEdgeRecord> edges;
  std::string case_name;
};

SpineEdgeSlice load_spine_edge_slice(const std::filesystem::path& path);

struct SpineL0Config {
  std::size_t partitions{16};
  std::size_t levels{11};
  std::uint32_t vertex_partition_size{1U << 20};
  std::uint32_t page_vertices{256};
  std::uint32_t max_vertices{1U << 24};
  std::uint64_t sorted_edges_base{};
  std::uint64_t persistent_directory_base{64ULL << 20};
  std::uint64_t persistent_dirty_bitmap_base{96ULL << 20};
  std::uint64_t persistent_dirty_list_base{128ULL << 20};
  std::uint64_t metadata_base{};
  std::uint64_t result_base{};
};

struct SpineL0State {
  std::array<std::array<std::vector<SpineEdgeRecord>, 11>, 16> cold_levels;
};

struct SpineL0Counters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint64_t sorted_scan_passes{};
  std::uint64_t sorted_edge_visits{};
  std::uint64_t sorted_read_bytes{};
  std::uint64_t persistent_read_bytes{};
  std::uint64_t persistent_write_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t metadata_write_bytes{};
  std::uint64_t graph_write_bytes{};
  std::uint64_t result_write_bytes{};
  std::uint64_t unique_sources{};
  std::uint64_t active_families{};
  std::uint64_t persisted_edges{};
  std::uint64_t persisted_rows{};
  std::uint64_t pages_stamped{};
  std::uint64_t memory_tasks{};
  std::array<std::uint64_t, 16> family_edges{};
  std::array<std::uint64_t, 16> family_rows{};
};

struct SpineL0Ports {
  std::array<FixedAxiPort*, 16> graph{};
  FixedAxiPort* sorted_edges{};
  FixedAxiPort* metadata{};
  FixedAxiPort* result{};
};

class SpineL0Maintenance final : public Component {
 public:
  SpineL0Maintenance(std::string name, ClockId clock_id, SpineL0Config config,
                     SpineEdgeSlice workload, SpineL0Ports ports,
                     SpineL0State& state);

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::string& failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineL0Counters& counters() const noexcept {
    return counters_;
  }

  void evaluate(const CycleContext& context) override;
  void commit(const CycleContext& context) override;

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
    kWriteSelect,
    kWriteBegin,
    kWriteProcess,
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
    FixedAxiPort* port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    TaskClass task_class{TaskClass::kSorted};
  };

  enum class StagedAction { kNone, kAdvance, kIssue, kComplete };

  void advance(const CycleContext& context);
  void enqueue_task(FixedAxiPort& port, MemoryOperation operation,
                    std::uint64_t address, std::uint64_t bytes,
                    TaskClass task_class);
  void begin_sorted_scan(Phase process_phase);
  void process_scan_edge(Phase next_phase);
  void enqueue_dirty_source_updates();
  void build_family_outputs();
  void enqueue_family_writes(std::size_t family);
  [[nodiscard]] std::vector<SpineEdgeRecord> coalesce_family(
      std::size_t family) const;
  [[nodiscard]] std::size_t family_for(std::uint32_t dst) const;

  SpineL0Config config_;
  SpineEdgeSlice workload_;
  SpineL0Ports ports_;
  SpineL0State& state_;
  SpineL0Counters counters_;
  std::array<std::vector<SpineEdgeRecord>, 16> family_outputs_;
  std::vector<std::size_t> active_families_;
  std::deque<MemoryTask> tasks_;
  Phase phase_{Phase::kInitialize};
  std::size_t scan_index_{};
  std::size_t family_index_{};
  std::size_t active_family_index_{};
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
