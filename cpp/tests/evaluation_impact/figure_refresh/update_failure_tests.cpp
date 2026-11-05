#include "update_failure.hpp"
#include <sstream>
#include <stdexcept>

int main() {
  spine::sim::SpineL0State state;
  const spine::sim::SpineL0Config config;
  state.cold_levels[0][0].resize(2);
  state.cold_levels[0][10].resize(7);
  state.hot_levels[15][3].resize(3);
  std::ostringstream first, second;
  figure_refresh::write_update_failure(first, state, config, 3, 410, 57);
  figure_refresh::write_update_failure(second, state, config, 3, 410, 57);
  const auto text = first.str();
  if (text != second.str() ||
      !text.starts_with("WARM_BATCH_FAILURE {\"batch_index\":3,\"updates\":410,\"batch_cycles\":57,") ||
      text.find("\"capacity_per_level\":[131072,16384,32768,") == std::string::npos ||
      text.find("\"physical_records_by_family_level\":[[2,0,0,0,0,0,0,0,0,0,7]") == std::string::npos ||
      text.find("[0,0,0,3,0,0,0,0,0,0,0]]}") == std::string::npos ||
      !text.ends_with("}\n") || state.cold_levels[0][0].size() != 2 ||
      state.hot_levels[15][3].size() != 3) {
    throw std::runtime_error("failure diagnostics changed state or lost batch/capacity evidence");
  }
}
