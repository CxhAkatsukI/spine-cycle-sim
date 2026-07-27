#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace spine::sim {

constexpr std::uint32_t kGraSuPmaEmpty = 0x8000'0000U;
constexpr std::uint32_t kGraSuPmaDestinationMask = 0x0007'ffffU;
constexpr std::uint32_t kGraSuPmaWeightMask = 0x0000'0fffU;
constexpr std::size_t kGraSuPmaWeightShift = 19;
constexpr std::size_t kGraSuPmaLocalVertexCapacity =
    static_cast<std::size_t>(kGraSuPmaDestinationMask) + 1;
constexpr std::size_t kGraSuSegmentSlots = 16;
constexpr std::size_t kGraSuSegmentBytes = 64;

enum class GraSuPmaWordAbi {
  // Simulator-native deep integration: local destination plus 12-bit weight.
  // Search, reservation, and replacement are keyed by destination.
  kNormalizedWeighted,
  // ff13a67 weighted HLS: the complete encoded destination-and-weight word is
  // the PMA search and reservation key. Weight changes must be lowered to an
  // exact delete followed by an insert.
  kWeightedFullWord,
  // Existing GraSU HLS ABI: bit 31 is empty and bits 30:0 are raw dst.
  kNativeRawDestination,
};

[[nodiscard]] std::uint32_t encode_grasu_pma_edge(std::uint32_t destination,
                                                  std::uint16_t weight);
[[nodiscard]] std::uint32_t
decode_grasu_pma_destination(std::uint32_t encoded);
[[nodiscard]] std::uint16_t decode_grasu_pma_weight(std::uint32_t encoded);
[[nodiscard]] bool is_grasu_pma_empty(std::uint32_t encoded) noexcept;

struct GraSuEdge {
  std::uint32_t source{};
  std::uint32_t destination{};
  std::uint16_t weight{1};
  bool delete_op{};

  friend bool operator==(const GraSuEdge &, const GraSuEdge &) = default;
};

// Exact host-side vertex numbering used by the current GraSU HLS integration.
// The native profile applies this before PMA construction; normalized profiles
// intentionally retain the workload's external numbering.
struct GraSuNativeReorderedGraph {
  std::vector<std::uint32_t> external_to_internal;
  std::vector<GraSuEdge> initial_edges;
  std::vector<GraSuEdge> updates;
};

[[nodiscard]] GraSuNativeReorderedGraph reorder_grasu_native_graph(
    std::size_t vertices, const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &updates);

// Exact host preprocessing used by the ff13a67 weighted-PMA HLS path.
// Logical weight changes become two physical PMA operations before the
// deterministic update-density vertex reorder is computed.
struct GraSuWeightedFullWordGraph {
  std::vector<std::uint32_t> external_to_internal;
  std::vector<std::uint32_t> internal_to_external;
  std::vector<GraSuEdge> initial_edges;
  std::vector<GraSuEdge> physical_updates;
  std::vector<GraSuEdge> final_edges;
  std::size_t logical_updates{};
};

[[nodiscard]] GraSuWeightedFullWordGraph prepare_grasu_weighted_full_word_graph(
    std::size_t vertices, const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &logical_updates);

struct GraSuPmaLayout {
  // Source rows remain globally indexed. Destinations are encoded relative to
  // this layout's destination window so the PMA word keeps ReGraph's 19-bit
  // local-destination ABI.
  std::size_t vertices{};
  std::uint32_t destination_base{};
  std::size_t destination_vertices{};
  GraSuPmaWordAbi pma_word_abi{GraSuPmaWordAbi::kNormalizedWeighted};
  std::vector<std::pair<std::uint32_t, std::uint32_t>> row_slot_bounds;
  std::vector<std::uint64_t> binary_heads;
  std::vector<std::array<std::uint32_t, kGraSuSegmentSlots>> segments;
  std::vector<std::array<std::uint32_t, kGraSuSegmentSlots>>
      reserved_segments;

  [[nodiscard]] static GraSuPmaLayout
  build(std::size_t vertices, const std::vector<GraSuEdge> &initial_edges,
        const std::vector<GraSuEdge> &reserved_updates,
        GraSuPmaWordAbi pma_word_abi = GraSuPmaWordAbi::kNormalizedWeighted);
  [[nodiscard]] static GraSuPmaLayout build_partition(
      std::size_t source_vertices, std::uint32_t destination_base,
      std::size_t destination_vertices,
      const std::vector<GraSuEdge> &initial_edges,
      const std::vector<GraSuEdge> &reserved_updates,
      GraSuPmaWordAbi pma_word_abi = GraSuPmaWordAbi::kNormalizedWeighted);
  [[nodiscard]] std::vector<GraSuEdge> live_edges() const;
  [[nodiscard]] std::size_t segment_for(const GraSuEdge &edge) const;
  [[nodiscard]] bool contains_destination(
      std::uint32_t destination) const noexcept;
  [[nodiscard]] std::uint32_t
  local_destination(std::uint32_t destination) const;
};

// Host-visible destination partitioning used by ReGraph. Every partition has
// global source rows but an independent PMA containing local destinations.
struct GraSuPartitionedPmaLayout {
  std::size_t vertices{};
  std::size_t partition_vertices{};
  std::vector<GraSuPmaLayout> partitions;

  [[nodiscard]] static GraSuPartitionedPmaLayout
  build(std::size_t vertices, std::size_t partition_vertices,
        const std::vector<GraSuEdge> &initial_edges,
        const std::vector<GraSuEdge> &reserved_updates,
        GraSuPmaWordAbi pma_word_abi = GraSuPmaWordAbi::kNormalizedWeighted);
  [[nodiscard]] std::size_t
  partition_for_destination(std::uint32_t destination) const;
  [[nodiscard]] const GraSuPmaLayout &partition_for(const GraSuEdge &edge) const;
  [[nodiscard]] std::vector<GraSuEdge> live_edges() const;
};

struct GraSuNativeConfig {
  GraSuPmaWordAbi pma_word_abi{GraSuPmaWordAbi::kNormalizedWeighted};
  std::size_t memory_channels{32};
  std::size_t cache_segments_per_half{131072};
  std::size_t axis_fifo_depth{16};
  std::size_t lane_fifo_depth{8};
  std::size_t max_pending_requests{16};
  std::size_t max_outstanding_bursts{16};
  std::size_t response_beats_per_cycle{1};
  std::uint64_t update_base{0x0000'0000ULL};
  std::uint64_t row_offset_base{0x1000'0000ULL};
  std::uint64_t binary_base{0x2000'0000ULL};
  std::uint64_t pma_base{0x3000'0000ULL};
  std::uint64_t partition_address_stride{0x1'0000'0000ULL};
  bool maintain_out_degree{};
  std::uint64_t degree_base{0x4100'0000ULL};
  std::size_t degree_channel{30};
  std::size_t degree_fifo_depth{16};
  std::size_t degree_reorder_entries{4096};
};

struct GraSuUpdateCounters {
  std::uint64_t updates{};
  std::size_t update_record_bytes{};
  std::size_t destination_partitions_touched{};
  std::uint64_t partition_routes{};
  std::uint64_t inserts{};
  std::uint64_t deletes{};
  std::uint64_t weight_decreases{};
  std::uint64_t weight_increases{};
  std::uint64_t row_reads{};
  std::uint64_t binary_probes{};
  std::uint64_t cache_updates{};
  std::uint64_t ddr_updates{};
  std::uint64_t pma_reads{};
  std::uint64_t pma_writes{};
  std::uint64_t degree_reads{};
  std::uint64_t degree_writes{};
  std::uint64_t update_read_bytes{};
  std::uint64_t row_read_bytes{};
  std::uint64_t binary_read_bytes{};
  std::uint64_t pma_read_bytes{};
  std::uint64_t pma_write_bytes{};
  std::uint64_t degree_read_bytes{};
  std::uint64_t degree_write_bytes{};
  std::uint64_t degree_fifo_stalls{};
  std::size_t degree_fifo_max_occupancy{};
  std::size_t degree_reorder_max_occupancy{};
  std::uint64_t axi_request_fifo_stalls{};
  std::uint64_t axi_backend_submit_stalls{};
  std::uint64_t axis_push_stalls{};
  std::uint64_t lane_queue_stalls{};
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
};

// Host-side initialization is outside the measured update kernel window. It
// writes one destination partition's row, binary-head, and PMA payloads without
// registering AXI initiators.
void initialize_grasu_pma_layout_payloads(MemoryBackend &backend,
                                          const GraSuPmaLayout &layout,
                                          const GraSuNativeConfig &config);

class GraSuPmaUpdateSystem {
 public:
  GraSuPmaUpdateSystem(Scheduler &scheduler, ClockId clock_id,
                       MemoryBackend &backend, GraSuPmaLayout layout,
                       std::vector<GraSuEdge> updates,
                       GraSuNativeConfig config = {});
  GraSuPmaUpdateSystem(Scheduler &scheduler, ClockId clock_id,
                       MemoryBackend &backend,
                       GraSuPartitionedPmaLayout layout,
                       std::vector<GraSuEdge> updates,
                       GraSuNativeConfig config = {});
  ~GraSuPmaUpdateSystem();

  GraSuPmaUpdateSystem(const GraSuPmaUpdateSystem &) = delete;
  GraSuPmaUpdateSystem &operator=(const GraSuPmaUpdateSystem &) = delete;

  void register_components();
  void unregister_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuUpdateCounters counters() const;
  [[nodiscard]] std::vector<GraSuEdge> live_edges() const;
  [[nodiscard]] std::array<std::uint32_t, kGraSuSegmentSlots>
  inspect_segment(std::size_t global_segment) const;
  [[nodiscard]] std::array<std::uint32_t, kGraSuSegmentSlots>
  inspect_segment(std::size_t partition, std::size_t local_segment) const;
  [[nodiscard]] const GraSuPmaLayout &initial_layout() const noexcept;
  [[nodiscard]] const GraSuPartitionedPmaLayout &
  initial_partitioned_layout() const noexcept;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace spine::sim
