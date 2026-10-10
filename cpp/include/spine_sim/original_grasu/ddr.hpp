#pragma once

#include <deque>

#include "spine_sim/original_grasu/types.hpp"

namespace spine::sim::original_grasu {

class DdrCore final : public Component {
 public:
  DdrCore(std::string name, ClockId clock, unsigned subpath, std::array<Fifo<Update>*, 16> input,
          Port reads, Port writes, Timing timing = {});
  void begin(std::uint64_t address, std::uint32_t segments);
  bool finished() const noexcept { return started_ && done_; }
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  enum class Phase { kFree, kRead, kCompute, kWrite };
  struct Pending {
    Phase phase{Phase::kFree};
    Update update;
    Segment result;
    std::uint64_t transaction{}, ready{};
  };
  unsigned subpath_;
  std::array<Fifo<Update>*, 16> input_;
  Port reads_, writes_;
  Timing timing_;
  std::array<Pending, 16> pending_{};
  std::array<bool, 16> ended_{};
  std::deque<unsigned> write_order_;
  std::uint64_t address_{}, next_transaction_{1}, sweep_start_{};
  std::uint32_t segments_{};
  unsigned cursor_{};
  bool started_{}, done_{}, epoch_pending_{}, stage_epoch_{};
  bool stage_poll_{}, stage_end_{}, stage_read_{}, stage_write_{}, stage_restart_{};
  Update incoming_;
  std::optional<std::pair<unsigned, Segment>> read_ack_;
  std::optional<unsigned> write_ack_;
  Counters counters_;
};

}  // namespace spine::sim::original_grasu
