#pragma once

#include "spine_sim/spine_l0.hpp"
#include <ostream>

namespace figure_refresh {
// Failure-only observation: do not change placement or retry a failed batch.
inline void write_update_failure(std::ostream& output,
    const spine::sim::SpineL0State& state,
    const spine::sim::SpineL0Config& config,
    std::size_t batch_index, std::size_t updates, std::uint64_t cycles) {
  output << "WARM_BATCH_FAILURE {\"batch_index\":" << batch_index
         << ",\"updates\":" << updates << ",\"batch_cycles\":" << cycles;
  for (const bool hot : {false, true}) {
    const auto& families = hot ? state.hot_levels : state.cold_levels;
    output << (hot ? ",\"hot\":{" : ",\"cold\":{") << "\"capacity_per_level\":[";
    for (std::size_t level = 0; level < config.levels; ++level) {
      if (level) output << ',';
      output << spine::sim::spine_level_layout(config, hot, level).edge_capacity;
    }
    output << "],\"physical_records_by_family_level\":[";
    for (std::size_t family = 0; family < config.partitions; ++family) {
      if (family) output << ',';
      output << '[';
      for (std::size_t level = 0; level < config.levels; ++level) {
        if (level) output << ',';
        output << families.at(family).at(level).size();
      }
      output << ']';
    }
    output << "]}";
  }
  output << "}\n";
}
} // namespace figure_refresh
