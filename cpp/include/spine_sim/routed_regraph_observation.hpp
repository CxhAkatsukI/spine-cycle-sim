#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace spine::sim {

// Cumulative component observations. Overlapping waits must not be added into
// an exclusive stage breakdown or interpreted as FPGA performance counters.
struct RoutedFrontendObservation {
  std::uint64_t packets{}, emitted{}, source_waits{}, edge_waits{}, output_stalls{},
      pipeline_stalls{}, request_stalls{}, source_lines{};
  std::uint64_t gather_reset{}, gather_merge{}, gather_drain{}, gather_output_stalls{},
      gather_conflicts{}, gather_rows{};
  bool operator==(const RoutedFrontendObservation&) const = default;
};

struct RoutedSourceObservation {
  std::uint64_t blocks{}, lines{}, terminators{}, parents{}, completions{},
      output_stalls{}, issue_stalls{}, max_pending{};
  bool operator==(const RoutedSourceObservation&) const = default;
};

struct RoutedBackendObservation {
  std::uint64_t merger_output_stalls{}, apply_output_stalls{}, apply_read_stalls{},
      apply_pipeline_stalls{}, apply_write_stalls{}, writeback_pipeline_stalls{},
      writeback_write_stalls{}, apply_max_reads{}, apply_max_pipeline{},
      apply_max_writes{}, writeback_max_pipeline{}, writeback_max_writes{};
  bool operator==(const RoutedBackendObservation&) const = default;
};

struct RoutedReGraphObservation {
  std::array<RoutedFrontendObservation, 4> frontends;
  std::vector<RoutedSourceObservation> sources;
  RoutedBackendObservation backend;
  bool operator==(const RoutedReGraphObservation&) const = default;
};

}  // namespace spine::sim
