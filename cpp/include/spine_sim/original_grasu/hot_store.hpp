#pragma once

#include <deque>

#include "spine_sim/original_grasu/types.hpp"

namespace spine::sim::original_grasu {

class CachePe;
class HotStore final : public Component {
 public:
  HotStore(std::string name, ClockId clock, StreamPort memory);
  void connect(std::array<CachePe*, 16> lanes);
  void begin(std::uint64_t address = 0);
  bool loaded() const noexcept { return phase_ == Phase::kProcess; }
  bool finished() const noexcept { return phase_ == Phase::kDone; }
  Segment& segment(std::uint32_t index) { return data_.at(index); }
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  enum class Phase { kIdle, kLoad, kProcess, kStore, kDone };
  StreamPort memory_;
  std::array<CachePe*, 16> lanes_{};
  std::vector<Segment> data_;
  std::vector<std::uint8_t> write_data_;
  Phase phase_{Phase::kIdle};
  std::uint64_t address_{}, transaction_{}, next_transaction_{1};
  std::uint32_t received_{};
  bool issued_{}, acknowledged_{}, stage_issue_{}, stage_ack_{}, stage_beat_{}, stage_store_{};
  Segment incoming_{};
  Counters counters_;
};

class CachePe final : public Component {
 public:
  CachePe(std::string name, ClockId clock, unsigned bank, HotStore& store,
          Fifo<Update>& input, Timing timing = {});
  void begin();
  bool finished() const noexcept { return ended_ && pending_.empty(); }
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  struct Pending { std::uint64_t ready; std::uint32_t index; Segment value; };
  unsigned bank_;
  HotStore& store_;
  Fifo<Update>& input_;
  Timing timing_;
  std::deque<Pending> pending_;
  std::optional<Pending> staged_;
  std::uint64_t next_accept_{};
  bool started_{}, ended_{}, stage_end_{}, stage_retire_{};
  Counters counters_;
};

}  // namespace spine::sim::original_grasu
