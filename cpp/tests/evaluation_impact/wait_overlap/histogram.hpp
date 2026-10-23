#pragma once

#include <array>
#include <filesystem>
#include <fstream>
#include <stdexcept>

#include "spine_sim/routed_regraph_observation.hpp"

namespace evaluation_impact::wait_overlap {
using spine::sim::RoutedReGraphObservation;

class Histogram {
public:
  void observe(const RoutedReGraphObservation& current) {
    const auto before = backend(previous_), after = backend(current);
    unsigned mask = 0;
    for (std::size_t bit = 0; bit < before.size(); ++bit) {
      if (after[bit] < before[bit] || after[bit] - before[bit] > 1)
        throw std::runtime_error("backend wait is not a per-cycle observation");
      if (after[bit] != before[bit]) mask |= 1U << bit;
    }
    for (std::size_t worker = 0; worker < current.frontends.size(); ++worker) {
      const auto& prior = previous_.frontends[worker];
      const auto& next = current.frontends[worker];
      const std::array a{prior.output_stalls, prior.edge_waits};
      const std::array b{next.output_stalls, next.edge_waits};
      for (std::size_t bit = 0; bit < a.size(); ++bit) {
        if (b[bit] < a[bit] || b[bit] - a[bit] > 1)
          throw std::runtime_error("frontend wait is not a per-cycle observation");
        if (b[bit] != a[bit]) mask |= 1U << (6 + bit);
      }
    }
    ++counts_[mask];
    previous_ = current;
  }

  void write(const std::filesystem::path& path) const {
    std::ofstream output(path);
    output.exceptions(std::ios::failbit | std::ios::badbit);
    output << "mask,cycles\n";
    for (std::size_t mask = 0; mask < counts_.size(); ++mask)
      if (counts_[mask]) output << mask << ',' << counts_[mask] << '\n';
    output.close();
  }

private:
  static std::array<std::uint64_t, 6> backend(const RoutedReGraphObservation& value) {
    const auto& b = value.backend;
    // Merger/Gather backfill suspended waits; their deltas cannot locate a wait in time.
    return std::array{b.apply_output_stalls, b.apply_read_stalls,
        b.apply_pipeline_stalls, b.apply_write_stalls, b.writeback_pipeline_stalls,
        b.writeback_write_stalls};
  }
  RoutedReGraphObservation previous_{};
  std::array<std::uint64_t, 256> counts_{};
};
}  // namespace evaluation_impact::wait_overlap
