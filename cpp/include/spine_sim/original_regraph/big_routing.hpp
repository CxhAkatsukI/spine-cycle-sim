#pragma once

#include <memory>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/original_regraph/big_types.hpp"

namespace spine::sim::original_regraph {

using RoutedPorts = std::array<Fifo<RoutedUpdate>*, kGatherLanes>;

class BigDispatch final : public Component {
 public:
  BigDispatch(std::string name, ClockId clock, Fifo<UpdateBurst>& input,
              RoutedPorts outputs);
  void begin_partition(std::uint64_t bursts);
  bool finished() const noexcept { return finished_; }
  std::uint64_t bursts() const noexcept { return bursts_; }
  std::uint64_t output_stalls() const noexcept { return output_stalls_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  Fifo<UpdateBurst>& input_;
  RoutedPorts outputs_;
  std::uint64_t remaining_{};
  std::uint64_t bursts_{};
  std::uint64_t output_stalls_{};
  bool finished_{true};
  bool accepted_{};
  bool end_sent_{};
};

struct SwitchCounters {
  std::uint64_t sender_tuples{};
  std::uint64_t receiver_tuples{};
  std::uint64_t sender_ends{};
  std::uint64_t receiver_ends{};
  std::uint64_t sender_stalls{};
  std::uint64_t receiver_stalls{};
};

// Each switch retains the author's four separate sender/receiver FIFOs and
// fixed receiver priority. Transfers reserve registered outputs before pop;
// this is not a claim of exact blocking-write/global-stall HLS scheduling.
class BigOmegaSwitch final : public Component {
 public:
  BigOmegaSwitch(std::string name, ClockId clock, unsigned destination_bit,
                 std::array<Fifo<RoutedUpdate>*, 2> inputs,
                 std::array<Fifo<RoutedUpdate>*, 2> outputs,
                 std::size_t internal_depth = 2);
  void begin_partition();
  bool finished() const noexcept { return sender_done_ && receiver_done_; }
  bool drained() const noexcept;
  const SwitchCounters& counters() const noexcept { return counters_; }
  const Fifo<RoutedUpdate>& route(std::size_t index) const { return *routes_.at(index); }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  unsigned bit_;
  std::array<Fifo<RoutedUpdate>*, 2> inputs_;
  std::array<Fifo<RoutedUpdate>*, 2> outputs_;
  std::array<std::unique_ptr<Fifo<RoutedUpdate>>, 4> routes_;
  std::array<bool, 2> input_ends_{};
  std::array<bool, 4> route_ends_{};
  std::array<bool, 2> next_input_ends_{};
  std::array<bool, 4> next_route_ends_{};
  bool sender_done_{true};
  bool receiver_done_{true};
  bool end_sent_{};
  bool end_received_{};
  SwitchCounters counters_;
};

}  // namespace spine::sim::original_regraph
