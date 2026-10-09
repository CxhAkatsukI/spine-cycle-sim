#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace spine::sim::pma_adapter {

struct Partition {
  std::array<std::uint64_t, 4> pma_addresses{};
  std::uint64_t row_address{};
  std::uint32_t vertices{}, slots{}, cache_segments{};
  std::uint32_t destination_offset{}, destination_vertices{65536};
};

// Schedule-informed, not a measured RTL/FPGA timing calibration. The read
// minimum replaces the HLS nominal memory wait; it is not added after it.
struct Timing {
  std::uint64_t minimum_read_cycles{71};
  std::uint64_t segment_issue_interval{2};
  std::uint64_t row_decode_cycles{2};
  std::uint64_t source_restart_cycles{1};
  std::uint64_t output_latency{1};
  std::size_t segment_capacity{38};
};

struct Counters {
  std::uint64_t tasks{}, parent_requests{}, acknowledgements{}, read_bytes{};
  std::uint64_t row_word_reads{}, row_bus_bytes{}, pma_bus_bytes{};
  std::array<std::uint64_t, 4> segment_reads{};
  std::uint64_t physical_edges{}, valid_edges{}, dummy_edges{}, final_bursts{};
  std::uint64_t request_stalls{}, output_stalls{}, capacity_stalls{}, interval_stalls{};
  std::size_t max_segments{};
};

}  // namespace spine::sim::pma_adapter
