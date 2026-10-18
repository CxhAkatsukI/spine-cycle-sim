#include "spine_sim/routed_regraph_profile.hpp"

#include <stdexcept>

namespace spine::sim {

RoutedReGraphConfig routed_regraph_profile_config(const RoutedReGraphProfileSelection &s) {
  const auto expected = s.bank_stream_model ? "grasu_regraph_bank_stream_sssp_compute_v1" :
      s.cross_row_model ? "grasu_regraph_cross_row_sssp_compute_v1" :
      s.row_line_model ? "grasu_regraph_row_line_sssp_compute_v1" :
      s.routed_empty_exit ? "grasu_regraph_routed_sssp_compute_v4" :
      s.routed_stream_depths ? "grasu_regraph_routed_sssp_compute_v3" :
      s.independent_read_write ? "grasu_regraph_routed_sssp_compute_v2" :
      "grasu_regraph_routed_sssp_compute_v1";
  const bool bank = s.bank_stream_model;
  if (s.profile_id != expected || (s.routed_stream_depths && !s.independent_read_write) ||
      (s.routed_empty_exit && !s.routed_stream_depths) ||
      (s.row_line_read && !s.row_line_model && !s.cross_row_model && !bank) ||
      ((s.row_line_model || s.cross_row_model || bank) &&
       (!s.routed_stream_depths || !s.prefetch_rows || !s.stop_after_last || s.routed_empty_exit)) ||
      (s.cross_row_pipeline && !s.cross_row_model && !bank) ||
      (s.cross_row_model && (s.row_line_model || !s.row_line_read)) ||
      (bank && (s.row_line_model || s.cross_row_model || !s.row_line_read || !s.cross_row_pipeline)))
    throw std::invalid_argument("routed profile, AXI channels and stream depths disagree");

  RoutedReGraphConfig config;
  config.adapter.prefetch_rows = s.prefetch_rows;
  config.adapter.stop_after_last = s.stop_after_last;
  config.adapter.row_line_reads = s.row_line_read;
  config.adapter.cross_row_pipeline = s.cross_row_pipeline;
  if (s.routed_empty_exit) config.adapter.empty_segment_exit_cycles = 73;
  config.compute.max_supersteps = 256;
  config.compute.apply_request_window = 16;
  config.independent_read_write = s.independent_read_write;
  if (s.routed_stream_depths) {
    config.adapter_stream_depth = 32;
    config.gather_stream_depth = 32;
    config.mux_stream_depth = 32;
  }
  if (bank) {
    config.source_topology = RoutedSourceTopology::kTwoPairwise;
    auto &schedule = config.adapter.cross_row;
    schedule.reader_pipeline_capacity = 2;
    schedule.block_drain_cycles = 2;
    schedule.directory_cache_rows = 1024;
    schedule.packet_pipeline = true;
    schedule.bank_stream = true;
    schedule.bank_read_beats = true;
    schedule.bank_fifo_lines = 256;
  }
  return config;
}

} // namespace spine::sim
