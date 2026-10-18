#include "spine_sim/routed_regraph_profile.hpp"

#include <iostream>
#include <stdexcept>

namespace {
using namespace spine::sim;
void require(bool value) {
  if (!value) throw std::runtime_error("profile selection differs");
}
void reject(RoutedReGraphProfileSelection s) {
  bool rejected = false;
  try { (void)routed_regraph_profile_config(s); }
  catch (const std::invalid_argument &) { rejected = true; }
  require(rejected);
}
}

int main() {
  try {
    RoutedReGraphProfileSelection selection;
    for (unsigned version = 1; version <= 4; ++version) {
      selection.profile_id = "grasu_regraph_routed_sssp_compute_v" + std::to_string(version);
      selection.independent_read_write = version >= 2;
      selection.routed_stream_depths = version >= 3;
      selection.routed_empty_exit = version == 4;
      const auto c = routed_regraph_profile_config(selection);
      require(c.source_topology == RoutedSourceTopology::kFourDedicated &&
              c.independent_read_write == (version >= 2) &&
              c.adapter_stream_depth == (version >= 3 ? 32U : 16U) &&
              c.adapter.empty_segment_exit_cycles == (version == 4 ? 73U : 0U) &&
              !c.adapter.cross_row.bank_stream && c.compute.max_supersteps == 256 &&
              c.compute.apply_request_window == 16);
    }
    selection.profile_id = "grasu_regraph_bank_stream_sssp_compute_v1";
    selection.routed_empty_exit = false;
    selection.bank_stream_model = selection.row_line_read = selection.cross_row_pipeline = true;
    const auto c = routed_regraph_profile_config(selection);
    require(c.source_topology == RoutedSourceTopology::kTwoPairwise &&
            c.adapter.cross_row.bank_stream && c.adapter.cross_row.bank_read_beats &&
            c.adapter.cross_row.packet_pipeline && c.adapter.cross_row.bank_fifo_lines == 256 &&
            c.adapter.cross_row.directory_cache_rows == 1024 &&
            c.adapter.cross_row.reader_pipeline_capacity == 2 && c.adapter.cross_row.block_drain_cycles == 2 &&
            c.adapter.cross_row.publisher_pipeline_cycles == 2 && !c.adapter.cross_row.continuous_directory);
    for (auto flag : {&RoutedReGraphProfileSelection::bank_stream_model,
                      &RoutedReGraphProfileSelection::row_line_read,
                      &RoutedReGraphProfileSelection::cross_row_pipeline,
                      &RoutedReGraphProfileSelection::routed_stream_depths,
                      &RoutedReGraphProfileSelection::independent_read_write,
                      &RoutedReGraphProfileSelection::prefetch_rows,
                      &RoutedReGraphProfileSelection::stop_after_last}) {
      auto invalid = selection;
      invalid.*flag = false;
      reject(invalid);
    }
    for (auto flag : {&RoutedReGraphProfileSelection::row_line_model,
                      &RoutedReGraphProfileSelection::cross_row_model,
                      &RoutedReGraphProfileSelection::routed_empty_exit}) {
      auto invalid = selection;
      invalid.*flag = true;
      reject(invalid);
    }
    selection.profile_id = "grasu_regraph_routed_sssp_compute_v3";
    reject(selection);
    std::cout << "PASS: legacy defaults, bank-stream topology/schedule and 11 mixed-profile rejections\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
