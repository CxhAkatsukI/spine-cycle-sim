#pragma once

#include "spine_sim/original_grasu/types.hpp"

namespace spine::sim::original_grasu {

class Dispatch final : public Component {
 public:
  Dispatch(std::string name, ClockId clock, std::array<Fifo<Update>*, 4> input,
           std::array<Fifo<Update>*, 4> output);
  void begin(std::uint64_t updates);
  bool finished() const noexcept { return started_ && cursor_ == count_ && ends_ == 4; }
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  std::array<Fifo<Update>*, 4> input_, output_;
  std::uint64_t count_{}, cursor_{};
  unsigned ends_{};
  bool started_{}, stage_update_{}, stage_end_{};
  Counters counters_;
};

// Original cache routes half-segment bits [3:0]; DDR routes [4:0].
class PeDispatch final : public Component {
 public:
  PeDispatch(std::string name, ClockId clock, Fifo<Update>& input,
             std::vector<Fifo<Update>*> output);
  void begin();
  bool finished() const noexcept { return started_ && ended_ && ends_ == output_.size(); }
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<Update>& input_;
  std::vector<Fifo<Update>*> output_;
  std::size_t ends_{};
  std::vector<bool> sent_, stage_sent_;
  bool started_{}, ended_{}, stage_update_{}, stage_end_{}, stage_sentinel_{};
  Counters counters_;
};

}  // namespace spine::sim::original_grasu
