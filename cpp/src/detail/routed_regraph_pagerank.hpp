#pragma once

#include "spine_sim/axi_endpoint.hpp"
#include "spine_sim/routed_regraph.hpp"

namespace spine::sim::detail {

struct RoutedPageRankPreparePorts {
  AxiEndpoint state, degree, degree_write, primary, mirror;
};

struct RoutedPageRankPrepareCounters {
  std::uint64_t state_reads{}, degree_reads{}, degree_writes{}, source_writes{};
  std::uint64_t start{}, end{};
};

// Runs once before correction: update the resident degrees, then map old rank
// to the new graph's source payload. All accesses use the shared finite ports.
class RoutedPageRankPrepare final : public Component {
public:
  RoutedPageRankPrepare(ClockId, std::size_t vertices, GraphAlgorithmPolicy,
                       GraSuReGraphConfig, std::vector<std::int32_t> degree_deltas,
                       RoutedPageRankPreparePorts);
  ~RoutedPageRankPrepare() override;
  void start(std::uint64_t cycle);
  [[nodiscard]] bool done() const;
  [[nodiscard]] std::uint32_t dangling_share() const;
  [[nodiscard]] RoutedPageRankPrepareCounters counters() const;
  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace spine::sim::detail
