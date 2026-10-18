#pragma once

#include "spine_sim/routed_regraph.hpp"

#include <string>

namespace spine::sim {

// Explicit SST model selection. Old profiles retain their four-reader defaults.
struct RoutedReGraphProfileSelection {
  std::string profile_id{"grasu_regraph_routed_sssp_compute_v1"};
  bool prefetch_rows{true}, stop_after_last{true};
  bool independent_read_write{}, routed_stream_depths{}, routed_empty_exit{};
  bool row_line_model{}, row_line_read{}, cross_row_model{}, cross_row_pipeline{};
  bool bank_stream_model{};
};

RoutedReGraphConfig routed_regraph_profile_config(const RoutedReGraphProfileSelection &);

} // namespace spine::sim
