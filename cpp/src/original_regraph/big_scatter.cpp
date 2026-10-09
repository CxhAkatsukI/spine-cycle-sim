#include "spine_sim/original_regraph/big_scatter.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {
namespace {
void validate(LanePropertyPorts ports, ClockId clock) {
  for (std::size_t lane = 0; lane < ports.size(); ++lane) {
    if (!ports[lane] || ports[lane]->clock_id() != clock ||
        std::find(ports.begin(), ports.begin() + lane, ports[lane]) != ports.begin() + lane) {
      throw std::invalid_argument("Big properties require distinct same-clock ports");
    }
  }
}
}  // namespace

BigResponseRouter::BigResponseRouter(std::string name, ClockId clock,
    Fifo<CachelineResponse>& input, LanePropertyPorts outputs)
    : Component(std::move(name), clock), input_(input), outputs_(outputs) {
  validate(outputs_, clock);
  if (input.clock_id() != clock) throw std::invalid_argument("Big response router clock mismatch");
}
void BigResponseRouter::begin_partition() {
  if (!finished_ || !input_.empty() || std::any_of(outputs_.begin(), outputs_.end(), [](auto* q) { return !q->empty(); })) {
    throw std::logic_error("Big response router restart requires drain");
  }
  initial_ = true; finished_ = false;
}
void BigResponseRouter::evaluate(const CycleContext&) {
  accepted_.reset();
  if (finished_ || input_.empty()) return;
  const auto& value = *input_.front();
  if (initial_ && (value.end || value.line != 0)) throw std::logic_error("Big first response must broadcast line zero");
  if (!initial_ && !value.end && value.lane >= 8) throw std::invalid_argument("Big response lane exceeds eight");
  if ((initial_ && std::any_of(outputs_.begin(), outputs_.end(), [](auto* q) { return q->full(); })) ||
      (!initial_ && !value.end && outputs_[value.lane]->full())) { ++output_stalls_; return; }
  CachelineResponse consumed;
  if (!input_.try_pop(consumed)) throw std::logic_error("Big response router input ownership");
  if (initial_) {
    for (auto* queue : outputs_) {
      if (!queue->try_push({consumed.data, consumed.line})) throw std::logic_error("Big broadcast ownership");
    }
  } else if (!consumed.end && !outputs_[consumed.lane]->try_push({consumed.data, consumed.line})) {
    throw std::logic_error("Big lane response ownership");
  }
  accepted_ = consumed;
}
void BigResponseRouter::commit(const CycleContext&) {
  if (accepted_) {
    if (accepted_->end) finished_ = true;
    else ++responses_;
    initial_ = false;
  }
}

BigScatter::BigScatter(std::string name, ClockId clock, Fifo<EdgeBurst>& input,
    LanePropertyPorts properties, Fifo<UpdateBurst>& output, PipelineTiming timing)
    : Component(std::move(name), clock), input_(input), properties_(properties), output_(output), pipeline_(timing) {
  validate(properties_, clock);
  if (input.clock_id() != clock || output.clock_id() != clock) throw std::invalid_argument("Big scatter clock mismatch");
}
void BigScatter::begin_partition(std::uint64_t bursts) {
  if (!finished() || !input_.empty() || !output_.empty() ||
      std::any_of(properties_.begin(), properties_.end(), [](auto* q) { return !q->empty(); })) {
    throw std::logic_error("Big scatter restart requires drain");
  }
  remaining_ = bursts; initialized_ = false; last_line_ = 0; last_ = {};
}
void BigScatter::evaluate(const CycleContext& context) {
  stage_initial_ = stage_burst_ = false;
  if (const auto* value = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*value)) pipeline_.stage_retire(); else pipeline_.output_stall();
  }
  if (!initialized_) {
    if (std::any_of(properties_.begin(), properties_.end(), [](auto* q) { return q->empty(); })) {
      ++counters_.source_wait_cycles; return;
    }
    for (unsigned lane = 0; lane < 8; ++lane) {
      LaneProperty value;
      if (!properties_[lane]->try_pop(value)) throw std::logic_error("Big initial property ownership");
      if (value.line != 0 || (lane && value.data != next_last_)) throw std::logic_error("Big broadcast data mismatch");
      next_last_ = value.data;
    }
    stage_initial_ = true;
    return;
  }
  if (!remaining_ || input_.empty() || !pipeline_.can_accept(context.domain_cycle)) return;
  const auto edge = *input_.front();
  for (unsigned lane = 0; lane < 8; ++lane) {
    const auto line = (edge[lane].source & 0x7fffffffu) / 16;
    if (line != last_line_ && properties_[lane]->empty()) { ++counters_.source_wait_cycles; return; }
  }
  UpdateBurst result;
  for (unsigned lane = 0; lane < 8; ++lane) {
    const auto source = edge[lane].source & 0x7fffffffu;
    PropertyLine data = last_;
    if (source / 16 != last_line_) {
      LaneProperty value;
      if (!properties_[lane]->try_pop(value)) throw std::logic_error("Big scatter property ownership");
      if (value.line != source / 16) throw std::logic_error("Big lane property line mismatch");
      data = value.data; ++counters_.lane_lines;
    }
    result[lane] = {edge[lane].destination, data[source & 15u]};
    if (lane == 7) { next_last_ = data; next_line_ = source / 16; }
  }
  EdgeBurst consumed;
  if (!input_.try_pop(consumed)) throw std::logic_error("Big scatter edge ownership");
  pipeline_.stage_accept(result, context.domain_cycle);
  stage_burst_ = true;
}
void BigScatter::commit(const CycleContext& context) {
  if (stage_initial_) { initialized_ = true; last_ = next_last_; counters_.initial_lines += 8; }
  if (stage_burst_) { last_ = next_last_; last_line_ = next_line_; --remaining_; ++counters_.bursts; counters_.source_lookups += 8; }
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
