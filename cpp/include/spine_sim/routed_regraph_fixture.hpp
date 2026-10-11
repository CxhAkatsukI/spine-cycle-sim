#pragma once

#include "spine_sim/routed_regraph.hpp"

namespace spine::sim {

// Versioned, little-endian u32 fixture exported from the owning HLS host's
// PMA builder and update reference. Input preparation is outside device time.
struct RoutedReGraphFixture {
  GraSuPartitionedPmaLayout layout;
  AlgorithmInitialState initial;
  std::vector<std::uint32_t> internal_to_external, expected;
  std::vector<std::size_t> physical_updates;
  std::size_t cache_segments{}, expected_rounds{};
};

[[nodiscard]] RoutedReGraphFixture load_routed_regraph_fixture(const std::string &path);

} // namespace spine::sim
