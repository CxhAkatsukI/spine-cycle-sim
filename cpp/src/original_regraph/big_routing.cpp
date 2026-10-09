#include "spine_sim/original_regraph/big_routing.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {
namespace {
template <std::size_t N>
void ports(const std::array<Fifo<RoutedUpdate>*, N>& values, ClockId clock) {
  for (std::size_t index = 0; index < N; ++index) {
    if (!values[index] || values[index]->clock_id() != clock ||
        std::find(values.begin(), values.begin() + index, values[index]) != values.begin() + index) {
      throw std::invalid_argument("Big routing requires distinct same-clock SPSC ports");
    }
  }
}
template <typename Range>
bool all(const Range& flags) { return std::all_of(flags.begin(), flags.end(), [](bool flag) { return flag; }); }
}  // namespace

BigDispatch::BigDispatch(std::string name, ClockId clock, Fifo<UpdateBurst>& input,
                         RoutedPorts outputs)
    : Component(std::move(name), clock), input_(input), outputs_(outputs) {
  ports(outputs_, clock);
  if (input.clock_id() != clock) throw std::invalid_argument("Big dispatch input clock mismatch");
}

void BigDispatch::begin_partition(std::uint64_t bursts) {
  if (!finished_ || !input_.empty() || std::any_of(outputs_.begin(), outputs_.end(),
      [](const auto* queue) { return !queue->empty(); })) {
    throw std::logic_error("Big dispatch restart requires drained ports");
  }
  remaining_ = bursts;
  finished_ = false;
}

void BigDispatch::evaluate(const CycleContext&) {
  accepted_ = end_sent_ = false;
  if (finished_) return;
  if (remaining_ && input_.empty()) return;
  if (std::any_of(outputs_.begin(), outputs_.end(), [](const auto* queue) { return queue->full(); })) {
    ++output_stalls_;
    return;
  }
  UpdateBurst burst{};
  if (remaining_) {
    if (!input_.try_pop(burst)) throw std::logic_error("Big dispatch input ownership");
    accepted_ = true;
  } else {
    end_sent_ = true;
  }
  // Original PR IS_ACTIVE_VERTEX is always true, including zero/dummy tuples.
  for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
    if (!outputs_[lane]->try_push({burst[lane], end_sent_})) {
      throw std::logic_error("Big dispatch output ownership");
    }
  }
}

void BigDispatch::commit(const CycleContext&) {
  if (accepted_) { --remaining_; ++bursts_; }
  if (end_sent_) finished_ = true;
}

BigOmegaSwitch::BigOmegaSwitch(std::string name, ClockId clock, unsigned bit,
    std::array<Fifo<RoutedUpdate>*, 2> inputs,
    std::array<Fifo<RoutedUpdate>*, 2> outputs, std::size_t depth)
    : Component(name, clock), bit_(bit), inputs_(inputs), outputs_(outputs) {
  if (bit > 2) throw std::invalid_argument("Big omega destination bit must be 0..2");
  ports(inputs_, clock);
  ports(outputs_, clock);
  for (const auto* input : inputs_) {
    if (std::find(outputs_.begin(), outputs_.end(), input) != outputs_.end()) {
      throw std::invalid_argument("Big omega cannot alias input and output");
    }
  }
  for (std::size_t index = 0; index < routes_.size(); ++index) {
    routes_[index] = std::make_unique<Fifo<RoutedUpdate>>(name + ".route" + std::to_string(index), clock, depth);
  }
}

bool BigOmegaSwitch::drained() const noexcept {
  return finished() && std::all_of(routes_.begin(), routes_.end(), [](const auto& queue) { return queue->empty(); });
}

void BigOmegaSwitch::begin_partition() {
  if (!drained() || std::any_of(inputs_.begin(), inputs_.end(), [](auto* q) { return !q->empty(); }) ||
      std::any_of(outputs_.begin(), outputs_.end(), [](auto* q) { return !q->empty(); })) {
    throw std::logic_error("Big omega restart requires drained queues");
  }
  input_ends_ = {};
  route_ends_ = {};
  sender_done_ = receiver_done_ = false;
}

void BigOmegaSwitch::evaluate(const CycleContext&) {
  next_input_ends_ = input_ends_;
  next_route_ends_ = route_ends_;
  end_sent_ = end_received_ = false;
  if (!sender_done_) {
    if (all(input_ends_)) {
      if (std::any_of(routes_.begin(), routes_.end(), [](const auto& q) { return q->full(); })) {
        ++counters_.sender_stalls;
      } else {
        for (auto& queue : routes_) {
          if (!queue->try_push({{}, true})) throw std::logic_error("Big omega sender end ownership");
        }
        end_sent_ = true;
      }
    } else {
      for (std::size_t lane = 0; lane < 2; ++lane) {
        if (input_ends_[lane] || inputs_[lane]->empty()) continue;
        const auto& value = *inputs_[lane]->front();
        const auto route = lane * 2 + ((value.update.destination >> bit_) & 1u);
        if (!value.end && routes_[route]->full()) { ++counters_.sender_stalls; break; }
        RoutedUpdate consumed;
        if (!inputs_[lane]->try_pop(consumed)) throw std::logic_error("Big omega sender input ownership");
        if (consumed.end) {
          next_input_ends_[lane] = true;
          ++counters_.sender_ends;
        } else {
          if (!routes_[route]->try_push(consumed)) throw std::logic_error("Big omega route ownership");
          ++counters_.sender_tuples;
        }
      }
    }
  }
  if (receiver_done_) return;
  if (all(route_ends_)) {
    if (outputs_[0]->full() || outputs_[1]->full()) { ++counters_.receiver_stalls; return; }
    for (auto* output : outputs_) {
      if (!output->try_push({{}, true})) throw std::logic_error("Big omega receiver end ownership");
    }
    end_received_ = true;
    return;
  }
  for (std::size_t lane = 0; lane < 2; ++lane) {
    auto route = lane;
    if (routes_[route]->empty()) route += 2;
    if (routes_[route]->empty()) continue;
    const auto& value = *routes_[route]->front();
    if (!value.end && outputs_[lane]->full()) { ++counters_.receiver_stalls; break; }
    RoutedUpdate consumed;
    if (!routes_[route]->try_pop(consumed)) throw std::logic_error("Big omega receiver input ownership");
    if (consumed.end) {
      next_route_ends_[route] = true;
      ++counters_.receiver_ends;
    } else {
      if (!outputs_[lane]->try_push(consumed)) throw std::logic_error("Big omega output ownership");
      ++counters_.receiver_tuples;
    }
  }
}

void BigOmegaSwitch::commit(const CycleContext& context) {
  for (auto& queue : routes_) queue->commit(context);
  input_ends_ = next_input_ends_;
  route_ends_ = next_route_ends_;
  if (end_sent_) sender_done_ = true;
  if (end_received_) receiver_done_ = true;
}

}  // namespace spine::sim::original_regraph
