#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "spine_sim/algorithm.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/grasu.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace spine::sim {

constexpr std::size_t kGraSuReGraphU55cGraphChannels = 23;
constexpr std::size_t kGraSuReGraphU55cChannelCapacityBytes = 512ULL << 20;
constexpr std::size_t kGraSuReGraphRuntimeAlignmentBytes = 4096;

struct GraSuReGraphBufferRegion {
  std::size_t shard{};
  std::string name;
  std::size_t logical_bytes{};
  std::size_t allocated_bytes{};
  std::size_t channel{};
  std::size_t channel_offset_bytes{};
  std::size_t channel_first{};
  std::size_t channel_last{};
};

struct GraSuReGraphShardRuntimePlan {
  std::uint32_t destination_base{};
  std::size_t destination_vertices{};
  std::size_t pma_slot_count{};
  std::array<std::size_t, 4> pma_words{};
  std::array<std::size_t, 4> update_counts{};
  std::array<std::size_t, 4> update_alloc_counts{};
  std::size_t row_words{};
  std::size_t binary_words{};
};

struct GraSuReGraphRuntimePlan {
  std::size_t max_cache_segments{};
  std::size_t channel_capacity_bytes{};
  std::vector<GraSuReGraphShardRuntimePlan> shards;
  std::vector<GraSuReGraphBufferRegion> regions;
  std::vector<std::size_t> channel_load_bytes;
  std::size_t total_allocated_bytes{};
};

// Exact lane-aware U55C placement contract used by the sharded-K4 HLS host.
// PMA/update lane N is restricted to its routed pseudo-channel range, while
// row and binary metadata use the least-loaded graph pseudo-channel. Placement
// is deterministic largest-first and rejects any per-channel overflow.
[[nodiscard]] GraSuReGraphRuntimePlan build_grasu_regraph_runtime_plan(
    const GraSuPartitionedPmaLayout &layout,
    const std::vector<std::size_t> &physical_updates_per_shard,
    std::size_t max_cache_segments,
    std::size_t channels = kGraSuReGraphU55cGraphChannels,
    std::size_t channel_capacity_bytes =
        kGraSuReGraphU55cChannelCapacityBytes);

[[nodiscard]] const GraSuReGraphBufferRegion &
find_grasu_regraph_runtime_region(const GraSuReGraphRuntimePlan &plan,
                                  std::size_t shard,
                                  const std::string &name);

struct GraSuReGraphConfig {
  std::size_t memory_channels{32};
  std::size_t compute_pipelines{1};
  bool shared_downstream{};
  std::size_t cache_segments_per_half{131072};
  std::size_t partition_vertices{65536};
  std::size_t source_buffer_vertices{4096};
  std::size_t source_cache_request_fifo_depth{8};
  std::size_t source_cache_response_fifo_depth{8};
  std::size_t edge_array_fifo_depth{8};
  std::size_t edge_lanes{8};
  std::size_t gather_banks{8};
  std::size_t gather_bypass_distance{6};
  std::size_t gather_pipeline_latency{9};
  std::size_t gather_vertices_per_reset_cycle{2};
  std::size_t gather_vertices_per_merge_cycle{2};
  std::size_t axis_fifo_depth{16};
  std::size_t gather_merger_fifo_depth{16};
  std::size_t merger_apply_fifo_depth{16};
  std::size_t apply_wrapper_fifo_depth{16};
  std::size_t reader_buffer_batches{32};
  std::size_t max_pending_requests{16};
  std::size_t max_outstanding_bursts{16};
  std::size_t response_beats_per_cycle{1};
  std::size_t apply_request_window{32};
  std::size_t apply_pipeline_latency{100};
  std::size_t apply_pipeline_capacity{100};
  std::size_t hbm_wrapper_pipeline_latency{71};
  std::size_t hbm_wrapper_pipeline_capacity{71};
  std::size_t pagerank_source_map_latency{1};
  bool pagerank_prepared_source{true};
  bool initialize_degree_payload{true};
  std::size_t max_supersteps{1024};
  std::uint64_t row_offset_base{0x1000'0000ULL};
  std::uint64_t pma_base{0x3000'0000ULL};
  std::uint64_t vertex_state_base{0x4000'0000ULL};
  std::uint64_t source_state_base{0x5000'0000ULL};
  std::uint64_t source_state_buffer_stride{0x0010'0000ULL};
  std::uint64_t degree_base{0x4100'0000ULL};
  std::uint64_t edge_array_base{0x6000'0000ULL};
  // A partition keeps the first partition's historical addresses and moves
  // subsequent row/PMA windows by this stride.
  std::uint64_t partition_address_stride{0x1'0000'0000ULL};
  bool packed_partition_addresses{};
  std::uint64_t partition_address_arena_base{0x0100'0000ULL};
  std::uint64_t partition_address_alignment{4096};
  std::size_t row_channel{0};
  std::size_t source_state_channel{1};
  std::size_t source_state_mirror_channel{3};
  std::size_t vertex_state_channel{30};
  std::size_t degree_channel{30};
  std::size_t edge_array_channel{0};
};

struct GraSuReGraphCounters {
  std::size_t state_bytes_per_vertex{};
  std::size_t destination_partitions{};
  std::size_t compute_pipelines{};
  std::size_t max_parallel_partitions{};
  std::size_t max_parallel_downstream_partitions{};
  std::uint64_t supersteps{};
  std::uint64_t partition_passes{};
  std::uint64_t pipeline_busy_cycles{};
  std::uint64_t downstream_busy_cycles{};
  std::uint64_t source_prepare_cycles{};
  std::uint64_t source_prepare_state_reads{};
  std::uint64_t source_prepare_state_read_bytes{};
  std::uint64_t source_prepare_degree_reads{};
  std::uint64_t source_prepare_writes{};
  std::uint64_t row_reads{};
  std::uint64_t source_state_reads{};
  std::uint64_t source_cache_requests{};
  std::uint64_t source_cache_request_markers{};
  std::uint64_t source_cache_lines{};
  std::uint64_t source_cache_lane_writes{};
  std::uint64_t source_cache_response_markers{};
  std::uint64_t source_cache_wait_cycles{};
  std::uint64_t source_cache_output_stall_cycles{};
  std::size_t source_cache_request_fifo_max_occupancy{};
  std::size_t source_cache_response_fifo_max_occupancy{};
  std::uint64_t source_state_writes{};
  std::uint64_t degree_reads{};
  std::uint64_t source_map_cycles{};
  std::uint64_t pma_segment_reads{};
  std::uint64_t edge_batches_scanned{};
  std::uint64_t pma_slots_scanned{};
  std::uint64_t live_edges_scanned{};
  std::uint64_t active_edges_mapped{};
  std::uint64_t gather_reset_cycles{};
  std::uint64_t gather_merge_cycles{};
  std::uint64_t gather_pipeline_drain_cycles{};
  std::uint64_t gather_output_stall_cycles{};
  std::uint64_t gather_bank_conflict_cycles{};
  std::uint64_t gather_bank_updates{};
  std::uint64_t gather_bypass_hits{};
  std::uint64_t gather_bypass_misses{};
  std::uint64_t gather_cross_bank_reductions{};
  std::uint64_t gather_rows_emitted{};
  std::uint64_t merger_rows_consumed{};
  std::uint64_t merger_bursts_emitted{};
  std::uint64_t merger_output_stall_cycles{};
  std::uint64_t apply_state_reads{};
  std::uint64_t apply_state_writes{};
  std::uint64_t apply_input_bursts{};
  std::uint64_t apply_output_stall_cycles{};
  std::uint64_t apply_read_window_stalls{};
  std::uint64_t apply_pipeline_capacity_stalls{};
  std::uint64_t apply_write_window_stalls{};
  std::size_t apply_max_reads_inflight{};
  std::size_t apply_max_pipeline_occupancy{};
  std::size_t apply_max_writes_inflight{};
  std::uint64_t hbm_wrapper_input_bursts{};
  std::uint64_t hbm_wrapper_pipeline_capacity_stalls{};
  std::uint64_t hbm_wrapper_write_window_stalls{};
  std::size_t hbm_wrapper_max_pipeline_occupancy{};
  std::size_t hbm_wrapper_max_writes_inflight{};
  std::size_t gather_merger_fifo_max_occupancy{};
  std::size_t merger_apply_fifo_max_occupancy{};
  std::size_t apply_wrapper_fifo_max_occupancy{};
  std::uint64_t activated_vertices{};
  std::uint64_t row_read_bytes{};
  std::uint64_t source_state_read_bytes{};
  std::uint64_t source_state_write_bytes{};
  std::uint64_t degree_read_bytes{};
  std::uint64_t pma_read_bytes{};
  std::uint64_t apply_read_bytes{};
  std::uint64_t apply_write_bytes{};
  std::uint64_t axi_beats_issued{};
  std::uint64_t axi_beats_completed{};
  std::uint64_t axi_request_fifo_stalls{};
  std::uint64_t axi_backend_submit_stalls{};
  std::uint64_t axis_push_stalls{};
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  float last_iteration_error{};
};

// Direct PMA-to-ReGraph compute path. Its normalized PMA word uses ReGraph's
// 19-bit local destination and 12-bit weight ABI. The partitioned overloads
// dispatch destination partitions across finite compute workers and synchronize
// at a superstep barrier. PageRank uses one global source-preparation pass and
// reduces worker-local active/error/dangling statistics at that barrier.
class GraSuReGraphSsspSystem {
public:
  GraSuReGraphSsspSystem(Scheduler &scheduler, ClockId clock_id,
                         MemoryBackend &backend, GraSuPmaLayout layout,
                         std::uint32_t source, GraSuReGraphConfig config = {});
  GraSuReGraphSsspSystem(Scheduler &scheduler, ClockId clock_id,
                         MemoryBackend &backend, GraSuPmaLayout layout,
                         GraphAlgorithmPolicy policy,
                         std::vector<std::uint32_t> out_degrees,
                         std::size_t fixed_rounds,
                         GraSuReGraphConfig config = {},
                         std::optional<AlgorithmInitialState> initial_state =
                             std::nullopt);
  GraSuReGraphSsspSystem(Scheduler &scheduler, ClockId clock_id,
                         MemoryBackend &backend,
                         GraSuPartitionedPmaLayout layout,
                         std::uint32_t source,
                         GraSuReGraphConfig config = {});
  GraSuReGraphSsspSystem(Scheduler &scheduler, ClockId clock_id,
                         MemoryBackend &backend,
                         GraSuPartitionedPmaLayout layout,
                         GraphAlgorithmPolicy policy,
                         std::vector<std::uint32_t> out_degrees,
                         std::size_t fixed_rounds,
                         GraSuReGraphConfig config = {},
                         std::optional<AlgorithmInitialState> initial_state =
                             std::nullopt);
  ~GraSuReGraphSsspSystem();

  GraSuReGraphSsspSystem(const GraSuReGraphSsspSystem &) = delete;
  GraSuReGraphSsspSystem &operator=(const GraSuReGraphSsspSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuReGraphCounters counters() const noexcept;
  [[nodiscard]] std::vector<std::size_t> frontier_out_sizes() const;
  [[nodiscard]] std::vector<std::uint32_t> distances() const;
  [[nodiscard]] std::vector<std::uint32_t> state_words() const;
  [[nodiscard]] std::vector<std::uint32_t> auxiliary_state_words() const;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

class GraSuReGraphPageRankSystem {
public:
  GraSuReGraphPageRankSystem(Scheduler &scheduler, ClockId clock_id,
                             MemoryBackend &backend, GraSuPmaLayout layout,
                             std::vector<std::uint32_t> out_degrees,
                             std::size_t iterations, float damping = 0.85F,
                             GraSuReGraphConfig config = {});
  GraSuReGraphPageRankSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      GraSuPartitionedPmaLayout layout,
      std::vector<std::uint32_t> out_degrees, std::size_t iterations,
      float damping = 0.85F, GraSuReGraphConfig config = {});
  ~GraSuReGraphPageRankSystem();

  GraSuReGraphPageRankSystem(const GraSuReGraphPageRankSystem &) = delete;
  GraSuReGraphPageRankSystem &
  operator=(const GraSuReGraphPageRankSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuReGraphCounters counters() const noexcept;
  [[nodiscard]] std::vector<float> ranks() const;

private:
  std::unique_ptr<GraSuReGraphSsspSystem> engine_;
};

class GraSuReGraphResidualPageRankSystem {
public:
  GraSuReGraphResidualPageRankSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      GraSuPmaLayout layout, std::vector<std::uint32_t> out_degrees,
      std::size_t max_iterations, float damping = 0.85F,
      float epsilon = 1.0e-6F, GraSuReGraphConfig config = {},
      ResidualPageRankContract residual_contract =
          ResidualPageRankContract::kGenericDanglingL1Cold,
      std::optional<AlgorithmInitialState> initial_state = std::nullopt);
  GraSuReGraphResidualPageRankSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      GraSuPartitionedPmaLayout layout,
      std::vector<std::uint32_t> out_degrees,
      std::size_t max_iterations, float damping = 0.85F,
      float epsilon = 1.0e-6F, GraSuReGraphConfig config = {},
      ResidualPageRankContract residual_contract =
          ResidualPageRankContract::kGenericDanglingL1Cold,
      std::optional<AlgorithmInitialState> initial_state = std::nullopt);
  ~GraSuReGraphResidualPageRankSystem();

  GraSuReGraphResidualPageRankSystem(
      const GraSuReGraphResidualPageRankSystem &) = delete;
  GraSuReGraphResidualPageRankSystem &
  operator=(const GraSuReGraphResidualPageRankSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuReGraphCounters counters() const noexcept;
  [[nodiscard]] std::vector<float> ranks() const;
  [[nodiscard]] std::vector<float> residuals() const;
  [[nodiscard]] std::vector<std::size_t> frontier_out_sizes() const;

private:
  std::unique_ptr<GraSuReGraphSsspSystem> engine_;
};

class GraSuReGraphConnectedComponentsSystem {
public:
  GraSuReGraphConnectedComponentsSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      GraSuPmaLayout layout, std::size_t max_iterations,
      GraSuReGraphConfig config = {},
      std::optional<AlgorithmInitialState> initial_state = std::nullopt);
  GraSuReGraphConnectedComponentsSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      GraSuPartitionedPmaLayout layout, std::size_t max_iterations,
      GraSuReGraphConfig config = {},
      std::optional<AlgorithmInitialState> initial_state = std::nullopt);
  ~GraSuReGraphConnectedComponentsSystem();

  GraSuReGraphConnectedComponentsSystem(
      const GraSuReGraphConnectedComponentsSystem &) = delete;
  GraSuReGraphConnectedComponentsSystem &
  operator=(const GraSuReGraphConnectedComponentsSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuReGraphCounters counters() const noexcept;
  [[nodiscard]] std::vector<std::uint32_t> labels() const;
  [[nodiscard]] std::vector<std::size_t> frontier_out_sizes() const;

private:
  std::unique_ptr<GraSuReGraphSsspSystem> engine_;
};

} // namespace spine::sim
