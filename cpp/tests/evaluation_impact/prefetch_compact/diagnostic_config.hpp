#pragma once

#include "../k4_config.hpp"

namespace evaluation_impact::prefetch_compact {
struct DiagnosticConfig {
  bool dual{}, full_burst{}, elastic{}, current{};
  std::size_t directory_tiles{1}, bank_lines{256};
  std::size_t capacity() const { return elastic ? 3 : 2; }
  std::size_t ports() const { return current ? 3 : dual ? 2 : 1; }

  static DiagnosticConfig from_mode(const std::string& mode) {
    if (mode == "current-input") {
      // Obtain resource settings from the exact complete-R arm, not a second
      // set of hand-picked reader parameters. Compute is absent in this probe.
      const auto config = k4_configuration(control("prefetch_sssp_write_issue"));
      if (config.input_path != spine::sim::RoutedInputPath::kTriplePrefetchElasticExperimental ||
          config.compute.max_pending_requests != 16 || config.adapter.read_pipeline_cycles != 71)
        throw std::logic_error("current input control requires topology review");
      return {true, config.experimental_full_burst_refill, true, true,
              config.experimental_directory_tiles, config.experimental_prefetch_bank_lines};
    }
    if (!(mode.empty() || mode == "dual-port" || mode == "full-burst" ||
          mode == "dual-port-full-burst" || mode == "elastic" || mode == "dual-port-elastic"))
      throw std::invalid_argument("unknown candidate reader topology/policy");
    return {mode == "dual-port" || mode == "dual-port-full-burst" || mode == "dual-port-elastic",
            mode == "full-burst" || mode == "dual-port-full-burst",
            mode == "elastic" || mode == "dual-port-elastic", false, 1, 256};
  }
};
}  // namespace evaluation_impact::prefetch_compact
