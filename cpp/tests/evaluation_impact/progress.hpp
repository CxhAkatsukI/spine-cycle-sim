#pragma once

#include <fstream>
#include <filesystem>
#include <iostream>
#include <stdexcept>

#include "spine_sim/routed_regraph.hpp"
#include "wait_observations.hpp"

namespace evaluation_impact {
inline void write_dense_directory(const spine::sim::RoutedReGraphCounters& counters,
                                  std::size_t vertices) {
  if (counters.row_reads != counters.extent_reads * ((vertices + 7) / 8))
    throw std::logic_error("dense directory byte ledger mismatch");
  std::cout << "DENSE_DIRECTORY {\"vertices\":" << vertices
            << ",\"extent_beats\":" << counters.extent_reads
            << ",\"directory_beats\":" << counters.row_reads
            << ",\"slot_beats\":" << counters.segment_reads << "}" << std::endl;
}

// Serialize existing completion records only after the scheduler is drained.
inline void write_progress(const spine::sim::RoutedReGraphSystem& system,
                           const std::filesystem::path& directory) {
  std::ofstream rounds(directory / "rounds.csv");
  std::ofstream invocations(directory / "invocations.csv");
  rounds.exceptions(std::ios::failbit | std::ios::badbit);
  invocations.exceptions(std::ios::failbit | std::ios::badbit);
  rounds << "round,start,apply_done,writeback_done,status_done,end,active\n";
  for (std::size_t i = 0; i < system.rounds().size(); ++i) {
    const auto& r = system.rounds()[i];
    rounds << i << ',' << r.start << ',' << r.apply_done << ',' << r.writeback_done
           << ',' << r.status_done << ',' << r.end << ',' << r.active_vertices << '\n';
  }
  invocations << "round,partition,worker,adapter,start,end\n";
  for (const auto& r : system.invocations()) {
    // Internal invocation rounds are one-based; exported rounds match DEMO_ROUND.
    invocations << r.round - 1 << ',' << r.partition << ',' << r.worker << ','
                << r.adapter << ',' << r.start << ',' << r.end << '\n';
  }
  rounds.close();
  invocations.close();
  write_wait_observations(system, directory);
}
}  // namespace evaluation_impact
