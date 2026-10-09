#include "spine_sim/original_regraph/little_merge.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {

LittleLocalMerge::LittleLocalMerge(std::string name, ClockId clock,
                                 GatherOutputs inputs,
                                 Fifo<VertexPair>& output, PipelineTiming timing)
    : Component(std::move(name), clock), inputs_(inputs), output_(output),
      pipeline_(timing) {
  if (output.clock_id() != clock) {
    throw std::invalid_argument("local merge output clock mismatch");
  }
  for (std::size_t lane = 0; lane < inputs.size(); ++lane) {
    if (!inputs[lane] || inputs[lane]->clock_id() != clock ||
        std::find(inputs.begin(), inputs.begin() + lane, inputs[lane]) !=
            inputs.begin() + lane) {
      throw std::invalid_argument("local merge requires distinct same-clock inputs");
    }
  }
}

void LittleLocalMerge::evaluate(const CycleContext& context) {
  if (const auto* pair = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*pair)) {
      pipeline_.stage_retire();
    } else {
      pipeline_.output_stall();
    }
  }
  if (std::any_of(inputs_.begin(), inputs_.end(),
                  [](const auto* queue) { return queue->empty(); }) ||
      !pipeline_.can_accept(context.domain_cycle)) {
    return;
  }
  VertexPair merged;
  for (auto* input : inputs_) {
    VertexPair pair;
    if (!input->try_pop(pair)) {
      throw std::logic_error("local merger lost exclusive input ownership");
    }
    merged.low += pair.low;
    merged.high += pair.high;
  }
  pipeline_.stage_accept(merged, context.domain_cycle);
}

void LittleLocalMerge::commit(const CycleContext& context) {
  pipeline_.commit(context.domain_cycle);
}

LittleGlobalMerge::LittleGlobalMerge(std::string name, ClockId clock,
                                   std::vector<Fifo<VertexPair>*> inputs,
                                   Fifo<PropertyLine>& output,
                                   PipelineTiming timing)
    : Component(std::move(name), clock), inputs_(std::move(inputs)),
      output_(output), held_(inputs_.size()), captured_(inputs_.size()),
      pipeline_(timing) {
  if (inputs_.empty() || inputs_.size() > 14 || output.clock_id() != clock) {
    throw std::invalid_argument("invalid Little merger topology or clock");
  }
  for (std::size_t index = 0; index < inputs_.size(); ++index) {
    if (!inputs_[index] || inputs_[index]->clock_id() != clock ||
        std::find(inputs_.begin(), inputs_.begin() + index, inputs_[index]) !=
            inputs_.begin() + index) {
      throw std::invalid_argument("global merge requires distinct same-clock inputs");
    }
  }
}

bool LittleGlobalMerge::drained() const noexcept {
  return pipeline_.drained() && packed_pairs_ == 0 &&
         std::none_of(held_.begin(), held_.end(),
                      [](const auto& entry) { return entry.has_value(); });
}

void LittleGlobalMerge::evaluate(const CycleContext& context) {
  retired_.reset();
  consumed_ = false;
  std::fill(captured_.begin(), captured_.end(), std::nullopt);
  if (const auto* pair = pipeline_.ready(context.domain_cycle)) {
    bool retire = true;
    if (packed_pairs_ == 7) {
      auto line = packing_;
      line[14] = pair->low;
      line[15] = pair->high;
      retire = output_.try_push(line);
      if (!retire) {
        pipeline_.output_stall();
      }
    }
    if (retire) {
      retired_ = *pair;
      pipeline_.stage_retire();
    }
  }

  bool all_present = true;
  VertexPair merged;
  for (std::size_t index = 0; index < inputs_.size(); ++index) {
    if (!held_[index]) {
      VertexPair pair;
      if (inputs_[index]->try_pop(pair)) {
        captured_[index] = pair;
      }
    }
    const auto& pair = held_[index] ? held_[index] : captured_[index];
    if (!pair) {
      all_present = false;
    } else {
      merged.low += pair->low;
      merged.high += pair->high;
    }
  }
  if (all_present && pipeline_.can_accept(context.domain_cycle)) {
    pipeline_.stage_accept(merged, context.domain_cycle);
    consumed_ = true;
  }
}

void LittleGlobalMerge::commit(const CycleContext& context) {
  if (retired_) {
    packing_[packed_pairs_ * 2] = retired_->low;
    packing_[packed_pairs_ * 2 + 1] = retired_->high;
    if (++packed_pairs_ == 8) {
      packed_pairs_ = 0;
      ++emitted_lines_;
    }
  }
  for (std::size_t index = 0; index < held_.size(); ++index) {
    if (consumed_) {
      held_[index].reset();
    } else if (captured_[index]) {
      held_[index] = captured_[index];
    }
  }
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
