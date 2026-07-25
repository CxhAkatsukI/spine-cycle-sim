#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "spine_sim/grasu.hpp"
#include "spine_sim/grasu_regraph.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace spine::sim {

struct GraSuNativeCompactorConfig {
  std::size_t memory_channels{32};
  std::size_t cache_segments_per_half{131072};
  std::size_t completion_tokens{4};
  // Vitis HLS 2024.1 reports iteration latency 72, II=1, trip count 16.
  std::size_t lane_pipeline_latency{72};
  std::size_t max_pending_requests{16};
  std::size_t max_outstanding_bursts{16};
  std::size_t response_beats_per_cycle{1};
  std::uint64_t row_offset_base{0x1000'0000ULL};
  std::uint64_t pma_base{0x3000'0000ULL};
  std::uint64_t edge_array_base{0x6000'0000ULL};
  std::size_t row_channel{0};
  std::size_t edge_array_channel{0};
};

struct GraSuNativeCompactorCounters {
  std::uint64_t completion_token_reads{};
  std::uint64_t barrier_cycles{};
  std::uint64_t row_reads{};
  std::uint64_t pma_segment_reads{};
  std::uint64_t pma_slots_scanned{};
  std::uint64_t lane_pipeline_cycles{};
  std::uint64_t valid_edges_seen{};
  std::uint64_t emitted_edge_slots{};
  std::uint64_t dummy_edge_slots{};
  std::uint64_t edge_array_writes{};
  std::uint64_t row_read_bytes{};
  std::uint64_t pma_read_bytes{};
  std::uint64_t edge_array_write_bytes{};
  std::uint64_t axi_backend_submit_stalls{};
  std::uint64_t output_issue_stall_cycles{};
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
};

// Existing HLS conversion path: completion barrier, capacity-wide raw-PMA
// scan, then a padded 64-bit ReGraph edge array. It consumes payloads produced
// by GraSuPmaUpdateSystem with kNativeRawDestination and does not initialize or
// rewrite PMA state on the host.
class GraSuNativeCompactorSystem {
public:
  GraSuNativeCompactorSystem(Scheduler &scheduler, ClockId clock_id,
                             MemoryBackend &backend, GraSuPmaLayout layout,
                             std::size_t compact_edge_slots,
                             GraSuNativeCompactorConfig config = {});
  ~GraSuNativeCompactorSystem();

  GraSuNativeCompactorSystem(const GraSuNativeCompactorSystem &) = delete;
  GraSuNativeCompactorSystem &
  operator=(const GraSuNativeCompactorSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuNativeCompactorCounters counters() const noexcept;
  [[nodiscard]] std::vector<GraSuEdge> compacted_live_edges() const;
  [[nodiscard]] std::vector<std::uint8_t> edge_array_payload() const;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

struct GraSuNativeReGraphCounters {
  GraSuReGraphCounters pipeline;
  std::uint64_t edge_array_requests{};
  std::uint64_t edge_array_bursts{};
  std::uint64_t edge_array_slots_scanned{};
  std::uint64_t edge_array_read_bytes{};
  std::uint64_t edge_array_output_stall_cycles{};
  std::uint64_t cross_source_round_bursts{};
};

// Existing ReGraph little-GS unit-weight SSSP path. It reads the padded edge
// array produced by GraSuNativeCompactorSystem on every fixed superstep.
class GraSuNativeReGraphSsspSystem {
public:
  GraSuNativeReGraphSsspSystem(
      Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
      std::size_t vertices, std::size_t compact_edge_slots,
      std::uint32_t source, std::size_t supersteps,
      GraSuReGraphConfig config = {});
  ~GraSuNativeReGraphSsspSystem();

  GraSuNativeReGraphSsspSystem(const GraSuNativeReGraphSsspSystem &) = delete;
  GraSuNativeReGraphSsspSystem &
  operator=(const GraSuNativeReGraphSsspSystem &) = delete;

  void register_components();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] GraSuNativeReGraphCounters counters() const noexcept;
  [[nodiscard]] std::vector<std::uint32_t> distances() const;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace spine::sim
