#include "spine_sim/original_regraph/big_gather.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {

BigGatherBank::BigGatherBank(std::string name, ClockId clock, unsigned bank,
    Fifo<RoutedUpdate>& input, Fifo<VertexPair>& output, BigTiming timing)
    : Component(std::move(name), clock), bank_(bank), input_(input), output_(output),
      memory_(kBigBankRows), updates_(timing.gather), drain_(timing.drain) {
  if (bank >= kGatherLanes || input.clock_id() != clock || output.clock_id() != clock) {
    throw std::invalid_argument("invalid Big bank index or port clock");
  }
}

void BigGatherBank::begin_partition() {
  if (!finished() || !input_.empty() || !output_.empty()) {
    throw std::logic_error("Big bank restart requires drained queues");
  }
  forwarding_ = {};
  next_row_ = 0;
  phase_ = Phase::kGather;
}

void BigGatherBank::evaluate(const CycleContext& context) {
  accepted_.reset(); retired_.reset(); issued_row_.reset();
  const auto cycle = context.domain_cycle;
  if (const auto* write = writes_.ready(cycle)) { retired_ = *write; writes_.stage_retire(); }
  if (updates_.ready(cycle)) updates_.stage_retire();
  if (phase_ == Phase::kGather && !input_.empty()) {
    const auto& value = *input_.front();
    if (value.end || (updates_.can_accept(cycle) && writes_.can_accept(cycle))) {
      RoutedUpdate consumed;
      if (!input_.try_pop(consumed)) throw std::logic_error("Big bank input ownership");
      accepted_ = consumed;
      if (!consumed.end) updates_.stage_accept(consumed.update, cycle);
    }
  }
  if (phase_ != Phase::kDrain) return;
  if (const auto* value = drain_.ready(cycle)) {
    if (output_.full()) { drain_.output_stall(); }
    else {
      if (!output_.try_push(*value)) throw std::logic_error("Big bank output ownership");
      drain_.stage_retire();
    }
  }
  if (next_row_ < kBigBankRows && drain_.can_accept(cycle)) {
    drain_.stage_accept(memory_[next_row_], cycle);
    issued_row_ = next_row_;
  }
}

BigGatherBank::Write BigGatherBank::accumulate(Update update) {
  if (update.destination >= (kBigVertices * 2)) throw std::invalid_argument("Big local destination exceeds 20 bits");
  if (update.destination & kDummyDestination) { ++counters_.dummy_updates; return {}; }
  if ((update.destination & 7u) != bank_) throw std::invalid_argument("Big omega routed tuple to wrong bank");
  const auto row = update.destination / 16;
  auto value = memory_[row];
  ++counters_.uram_reads;
  bool forwarded = false;
  for (const auto& entry : forwarding_) {
    if (entry.valid && entry.row == row) { value = entry.value; forwarded = true; }
  }
  counters_.forwarded_reads += forwarded;
  if (update.destination & 8u) value.high += update.value;
  else value.low += update.value;
  std::move(forwarding_.begin() + 1, forwarding_.end(), forwarding_.begin());
  forwarding_.back() = {row, value, true};
  ++counters_.valid_updates;
  return forwarding_.back();
}

void BigGatherBank::commit(const CycleContext& context) {
  const auto cycle = context.domain_cycle;
  if (retired_ && retired_->valid) { memory_[retired_->row] = retired_->value; ++counters_.uram_writes; }
  if (accepted_) {
    if (accepted_->end) { phase_ = Phase::kFlush; ++counters_.ends; }
    else writes_.stage_accept(accumulate(accepted_->update), cycle);
  }
  if (issued_row_) {
    memory_[*issued_row_] = {};
    ++next_row_;
    ++counters_.drain_read_pairs;
    ++counters_.drain_clear_pairs;
  }
  updates_.commit(cycle); writes_.commit(cycle); drain_.commit(cycle);
  if (phase_ == Phase::kFlush && updates_.drained() && writes_.drained()) phase_ = Phase::kDrain;
  else if (phase_ == Phase::kDrain && next_row_ == kBigBankRows && drain_.drained()) {
    phase_ = Phase::kFinished;
    ++counters_.partitions;
  }
}

}  // namespace spine::sim::original_regraph
