#include "spine_sim/original_regraph/big_merge.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {
namespace {
template <typename Range>
void check_inputs(const Range& inputs, ClockId clock) {
  for (auto iterator = inputs.begin(); iterator != inputs.end(); ++iterator) {
    if (!*iterator || (*iterator)->clock_id() != clock ||
        std::find(inputs.begin(), iterator, *iterator) != iterator) {
      throw std::invalid_argument("Big merger requires distinct same-clock inputs");
    }
  }
}
template <typename Pipe>
void retire(Pipe& pipe, Fifo<PropertyLine>& output, std::uint64_t cycle) {
  if (const auto* value = pipe.ready(cycle)) {
    if (output.full()) { pipe.output_stall(); }
    else {
      if (!output.try_push(*value)) throw std::logic_error("Big merger output ownership");
      pipe.stage_retire();
    }
  }
}
template <typename Range>
void restart(bool finished, const Range& inputs, const Fifo<PropertyLine>& output) {
  if (!finished || !output.empty() || std::any_of(inputs.begin(), inputs.end(), [](auto* q) { return !q->empty(); })) {
    throw std::logic_error("Big merger restart requires drained queues");
  }
}
}  // namespace

BigResultPacker::BigResultPacker(std::string name, ClockId clock,
    std::array<Fifo<VertexPair>*, kGatherLanes> inputs, Fifo<PropertyLine>& output, PipelineTiming timing)
    : Component(std::move(name), clock), inputs_(inputs), output_(output), pipeline_(timing) {
  check_inputs(inputs_, clock);
  if (output.clock_id() != clock) throw std::invalid_argument("Big packer output clock mismatch");
}
void BigResultPacker::begin_partition() {
  restart(finished(), inputs_, output_);
  remaining_ = kBigBankRows;
}
void BigResultPacker::evaluate(const CycleContext& context) {
  accepted_ = false;
  retire(pipeline_, output_, context.domain_cycle);
  if (!remaining_ || std::any_of(inputs_.begin(), inputs_.end(), [](auto* q) { return q->empty(); }) ||
      !pipeline_.can_accept(context.domain_cycle)) return;
  PropertyLine line{};
  for (std::size_t bank = 0; bank < kGatherLanes; ++bank) {
    VertexPair pair;
    if (!inputs_[bank]->try_pop(pair)) throw std::logic_error("Big packer input ownership");
    line[bank] = pair.low;
    line[bank + 8] = pair.high;
  }
  pipeline_.stage_accept(line, context.domain_cycle);
  accepted_ = true;
}
void BigResultPacker::commit(const CycleContext& context) {
  if (accepted_) --remaining_;
  pipeline_.commit(context.domain_cycle);
}

BigGlobalMerge::BigGlobalMerge(std::string name, ClockId clock,
    std::vector<Fifo<PropertyLine>*> inputs, Fifo<PropertyLine>& output, PipelineTiming timing)
    : Component(std::move(name), clock), inputs_(std::move(inputs)), output_(output), pipeline_(timing) {
  if (inputs_.empty() || inputs_.size() > 14) throw std::invalid_argument("Big merger input count must be 1..14");
  check_inputs(inputs_, clock);
  if (output.clock_id() != clock || std::find(inputs_.begin(), inputs_.end(), &output) != inputs_.end()) {
    throw std::invalid_argument("Big merger output clock or SPSC alias");
  }
}
void BigGlobalMerge::begin_partition() {
  restart(finished(), inputs_, output_);
  remaining_ = kBigBankRows;
}
void BigGlobalMerge::evaluate(const CycleContext& context) {
  accepted_ = false;
  retire(pipeline_, output_, context.domain_cycle);
  if (!remaining_ || std::any_of(inputs_.begin(), inputs_.end(), [](auto* q) { return q->empty(); }) ||
      !pipeline_.can_accept(context.domain_cycle)) return;
  PropertyLine result{};
  for (auto* input : inputs_) {
    PropertyLine line;
    if (!input->try_pop(line)) throw std::logic_error("Big merger input ownership");
    for (std::size_t word = 0; word < result.size(); ++word) result[word] += line[word];
  }
  pipeline_.stage_accept(result, context.domain_cycle);
  accepted_ = true;
}
void BigGlobalMerge::commit(const CycleContext& context) {
  if (accepted_) --remaining_;
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
