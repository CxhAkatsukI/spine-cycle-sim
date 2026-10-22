#pragma once

namespace spine::sim {

enum class RoutedSourceLoading {
  kEdgeCoupled,
  // Separate finite cache-write pipeline; unchanged two banks and AXI service.
  // Simulator architecture candidate, not a routed-hardware timing claim.
  kIndependentExperimental,
};

}  // namespace spine::sim
