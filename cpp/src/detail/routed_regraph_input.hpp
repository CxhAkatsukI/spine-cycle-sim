#pragma once

#include "prefetch_compact/compactor.hpp"
#include "spine_sim/routed_regraph.hpp"

namespace spine::sim::detail {

// Explicit physical adapter masters. The experimental path resets the bounded
// datapath only after it drains; it never materializes a compact edge array.
class RoutedPmaInput final : public Component {
public:
  RoutedPmaInput(std::string, ClockId, const RoutedReGraphConfig&, FixedAxiPort&,
                 Fifo<ReGraphPmaPacket>&, FixedAxiPort* odd_memory = nullptr);
  void start_partition(ReGraphPmaPartition);
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] ReGraphPmaAdapterCounters counters() const;
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
private:
  FixedAxiPort& memory_;
  FixedAxiPort* odd_memory_;
  Fifo<ReGraphPmaPacket>& output_;
  const std::uint64_t read_delay_;
  const std::size_t pipeline_capacity_;
  Fifo<prefetch_compact::Segment> segments_;
  std::unique_ptr<ReGraphPmaAdapter> legacy_;
  std::unique_ptr<prefetch_compact::Reader> reader_;
  std::unique_ptr<prefetch_compact::Compactor> compactor_;
  ReGraphPmaAdapterCounters completed_;
};

}  // namespace spine::sim::detail
