#include "spine_sim/original_grasu/routing.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_grasu {

Dispatch::Dispatch(std::string name, ClockId clock, std::array<Fifo<Update>*, 4> input,
                   std::array<Fifo<Update>*, 4> output)
    : Component(std::move(name), clock), input_(input), output_(output) {
  for (auto* queue : input_) if (!queue || queue->clock_id() != clock) throw std::invalid_argument("G dispatch input clock");
  for (auto* queue : output_) if (!queue || queue->clock_id() != clock) throw std::invalid_argument("G dispatch output clock");
}

void Dispatch::begin(std::uint64_t updates) {
  if (started_ && !finished()) throw std::logic_error("G dispatch restart while active");
  count_ = updates; cursor_ = ends_ = 0; started_ = true;
}

void Dispatch::evaluate(const CycleContext&) {
  stage_update_ = stage_end_ = false;
  if (!started_ || finished()) return;
  if (cursor_ < count_) {
    auto& input = *input_[cursor_ % 4];
    if (input.empty()) { ++counters_.input_stalls; return; }
    const auto item = *input.front();
    if (item.end || item.slot % 16) throw std::logic_error("G dispatch invalid search packet");
    const unsigned route = ((item.slot >> 4) & 1) * 2 + ((item.slot >> 5) >= kHotSegments);
    if (!output_[route]->try_push(item)) { ++counters_.output_stalls; return; }
    Update consumed; if (!input.try_pop(consumed)) throw std::logic_error("G dispatch input ownership");
    stage_update_ = true;
  } else if (output_[ends_]->try_push(Update{.end = true})) stage_end_ = true;
}

void Dispatch::commit(const CycleContext&) {
  if (stage_update_) { ++cursor_; ++counters_.updates; }
  if (stage_end_) { ++ends_; ++counters_.ends; }
}

PeDispatch::PeDispatch(std::string name, ClockId clock, Fifo<Update>& input,
                       std::vector<Fifo<Update>*> output)
    : Component(std::move(name), clock), input_(input), output_(std::move(output)) {
  if ((output_.size() != 16 && output_.size() != 32) || input.clock_id() != clock ||
      std::any_of(output_.begin(), output_.end(), [clock](auto* queue) { return !queue || queue->clock_id() != clock; }))
    throw std::invalid_argument("G PE dispatch requires sixteen or thirty-two queues");
}

void PeDispatch::begin() {
  if (started_ && !finished()) throw std::logic_error("G PE dispatch restart while active");
  started_ = true; ended_ = false; ends_ = 0;
  sent_.assign(output_.size(), false); stage_sent_.assign(output_.size(), false);
}

void PeDispatch::evaluate(const CycleContext&) {
  stage_update_ = stage_end_ = stage_sentinel_ = false;
  std::fill(stage_sent_.begin(), stage_sent_.end(), false);
  if (!started_ || finished()) return;
  if (ended_) {
    if (output_.size() == 16) stage_end_ = output_[ends_]->try_push(Update{.end = true});
    else for (std::size_t index = 0; index < output_.size(); ++index)
      if (!sent_[index]) stage_sent_[index] = output_[index]->try_push(Update{.end = true});
    return;
  }
  if (input_.empty()) return;
  const auto item = *input_.front();
  if (item.end) stage_sentinel_ = true;
  else {
    if (!output_[(item.slot >> 5) % output_.size()]->try_push(item)) { ++counters_.output_stalls; return; }
    stage_update_ = true;
  }
  Update consumed; if (!input_.try_pop(consumed)) throw std::logic_error("G PE dispatch input ownership");
}

void PeDispatch::commit(const CycleContext&) {
  if (stage_sentinel_) ended_ = true;
  if (stage_update_) ++counters_.updates;
  if (stage_end_) { ++ends_; ++counters_.ends; }
  for (std::size_t index = 0; index < stage_sent_.size(); ++index) if (stage_sent_[index]) {
    sent_[index] = true; ++ends_; ++counters_.ends;
  }
}

}  // namespace spine::sim::original_grasu
