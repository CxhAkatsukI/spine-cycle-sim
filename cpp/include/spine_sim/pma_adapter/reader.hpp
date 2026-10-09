#pragma once

#include <deque>
#include <optional>

#include "spine_sim/original_regraph/frontend_types.hpp"
#include "spine_sim/pma_adapter/types.hpp"

namespace spine::sim::pma_adapter {

// Sharded destination-only PMA input. All row and PMA accesses share the
// supplied finite port; no edge array or unlimited metadata cache is used.
class Reader final : public Component {
 public:
  Reader(std::string name, ClockId clock, original_regraph::ReadPort memory,
         Fifo<original_regraph::EdgeBurst>& output, Timing timing = {});
  void begin_partition(Partition partition);
  bool finished() const noexcept;
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  enum class Phase { kIdle, kTotal, kRow, kSegments, kDone };
  struct Pending {
    std::uint64_t transaction{}, address{}, issue_cycle{}, ready_cycle{};
    std::uint32_t segment{};
    unsigned route{}, half{};
    std::optional<std::array<std::uint32_t, 16>> data;
  };
  Pending row_request(std::uint64_t cycle) const;
  Pending segment_request(std::uint64_t cycle) const;
  original_regraph::EdgeBurst edges(const Pending&) const;
  void accept_response(const AxiResponse&, std::uint64_t cycle);
  void accept_row(std::uint64_t cycle);
  void advance_source(std::uint64_t cycle);

  original_regraph::ReadPort memory_;
  Fifo<original_regraph::EdgeBurst>& output_;
  Timing timing_;
  Partition partition_;
  Phase phase_{Phase::kIdle};
  std::optional<Pending> row_;
  std::deque<Pending> segments_;
  std::uint64_t next_transaction_{1}, ready_cycle_{}, next_issue_cycle_{};
  std::uint32_t source_{}, total_slots_{}, previous_end_{}, begin_{}, end_{};
  std::uint32_t next_segment_{}, end_segment_{}, emitted_{};
  std::optional<Pending> staged_request_;
  std::optional<AxiResponse> staged_response_;
  bool staged_output_{}, staged_row_{};
  Counters counters_;
};

}  // namespace spine::sim::pma_adapter
