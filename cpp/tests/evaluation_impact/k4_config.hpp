#pragma once

#include "control.hpp"
#include "spine_sim/routed_regraph_profile.hpp"

namespace evaluation_impact {
inline spine::sim::RoutedReGraphConfig k4_configuration(const Control& selected) {
  using namespace spine::sim;
  RoutedReGraphConfig config;
  if (selected.bank_stream) {
    RoutedReGraphProfileSelection profile;
    profile.profile_id = "grasu_regraph_bank_stream_sssp_compute_v1";
    profile.independent_read_write = profile.routed_stream_depths = true;
    profile.row_line_read = profile.cross_row_pipeline = profile.bank_stream_model = true;
    config = routed_regraph_profile_config(profile);
  } else {
    // Preserve the seven historical controls, including four source masters.
    config.independent_read_write = true;
    config.adapter.empty_segment_exit_cycles = 0;
    config.adapter.row_line_reads = config.adapter.cross_row_pipeline = true;
    auto& cross = config.adapter.cross_row;
    cross.directory_cache_rows = selected.candidate ? 1024 : 8;
    cross.packet_pipeline = cross.bank_stream = cross.bank_read_beats = selected.candidate;
    if (selected.candidate) {
      cross.bank_fifo_lines = 256;
      cross.reader_pipeline_capacity = 2;
      cross.block_drain_cycles = 2;
    }
    config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
  }
  config.compute.max_pending_requests = selected.k4_parents;
  config.compute.apply_request_window = selected.k4_apply_window;
  if (selected.prefetch_compact)
    config.input_path = RoutedInputPath::kPrefetchCompactedExperimental;
  return config;
}
}  // namespace evaluation_impact
