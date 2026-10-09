#include "spine_sim/original_regraph/little_gather.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_regraph {

LittleGather::LittleGather(std::string name, ClockId clock,
                           Fifo<UpdateBurst>& input, GatherOutputs outputs,
                           LittleTiming timing)
    : Component(std::move(name), clock), input_(input), outputs_(outputs),
      updates_(timing.gather), drain_(timing.drain) {
  if (input.clock_id() != clock) {
    throw std::invalid_argument("gather input clock mismatch");
  }
  for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
    if (!outputs[lane] || outputs[lane]->clock_id() != clock) {
      throw std::invalid_argument("gather output clock mismatch");
    }
    if (std::find(outputs.begin(), outputs.begin() + lane, outputs[lane]) !=
        outputs.begin() + lane) {
      throw std::invalid_argument("gather outputs must be distinct SPSC queues");
    }
    memory_[lane].resize(kLittleRows);
  }
}

void LittleGather::begin_partition(std::uint64_t bursts) {
  if (!finished() || !input_.empty() ||
      std::any_of(outputs_.begin(), outputs_.end(),
                  [](const auto* queue) { return !queue->empty(); })) {
    throw std::logic_error("gather restart requires drained boundary queues");
  }
  forwarding_ = {};
  expected_ = bursts;
  accepted_count_ = 0;
  next_row_ = 0;
  phase_ = bursts ? Phase::kGather : Phase::kDrain;
}

bool LittleGather::finished() const noexcept {
  return phase_ == Phase::kFinished;
}

void LittleGather::evaluate(const CycleContext& context) {
  accepted_.reset();
  retired_writes_.reset();
  issued_row_.reset();
  if (const auto* writes = writes_.ready(context.domain_cycle)) {
    retired_writes_ = *writes;
    writes_.stage_retire();
  }
  if (updates_.ready(context.domain_cycle)) {
    updates_.stage_retire();
  }
  if (phase_ == Phase::kGather && accepted_count_ < expected_) {
    if (input_.empty()) {
      ++counters_.input_wait_cycles;
    } else if (updates_.can_accept(context.domain_cycle) &&
               writes_.can_accept(context.domain_cycle)) {
      UpdateBurst burst;
      if (input_.try_pop(burst)) {
        accepted_ = burst;
        updates_.stage_accept(burst, context.domain_cycle);
      }
    }
  }
  if (phase_ != Phase::kDrain) {
    return;
  }
  if (const auto* rows = drain_.ready(context.domain_cycle)) {
    if (std::any_of(outputs_.begin(), outputs_.end(),
                    [](const auto* queue) { return queue->full(); })) {
      drain_.output_stall();
    } else {
      for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
        if (!outputs_[lane]->try_push((*rows)[lane])) {
          throw std::logic_error("gather lost exclusive output ownership");
        }
      }
      drain_.stage_retire();
    }
  }
  if (next_row_ < kLittleRows && drain_.can_accept(context.domain_cycle)) {
    LanePairs rows;
    for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
      rows[lane] = memory_[lane][next_row_];
    }
    drain_.stage_accept(rows, context.domain_cycle);
    issued_row_ = next_row_;
  }
}

LittleGather::Writes LittleGather::map_updates(const UpdateBurst& burst) {
  Writes result{};
  for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
    const auto update = burst[lane];
    if (update.destination & kDummyDestination) {
      ++counters_.dummy_updates;
      continue;
    }
    // Original Little masks to the partition size after testing dummy bit 19.
    const auto destination = update.destination & (kLittleVertices - 1);
    const auto row = destination / 2;
    auto value = memory_[lane][row];
    ++counters_.uram_reads;
    bool forwarded = false;
    for (const auto& entry : forwarding_[lane]) {
      if (entry.valid && entry.row == row) {
        value = entry.value;
        forwarded = true;
      }
    }
    counters_.forwarded_reads += forwarded;
    if (destination & 1u) {
      value.high += update.value;
    } else {
      value.low += update.value;
    }
    auto& history = forwarding_[lane];
    std::move(history.begin() + 1, history.end(), history.begin());
    history.back() = Write{row, value, true};
    result[lane] = history.back();
    ++counters_.valid_updates;
  }
  return result;
}

void LittleGather::commit(const CycleContext& context) {
  if (retired_writes_) {
    for (std::size_t lane = 0; lane < kGatherLanes; ++lane) {
      const auto& write = (*retired_writes_)[lane];
      if (write.valid) {
        memory_[lane][write.row] = write.value;
        ++counters_.uram_writes;
      }
    }
  }
  if (accepted_) {
    writes_.stage_accept(map_updates(*accepted_), context.domain_cycle);
    ++accepted_count_;
    ++counters_.bursts;
  }
  if (issued_row_) {
    for (auto& lane : memory_) {
      lane[*issued_row_] = {};
    }
    ++next_row_;
    counters_.drain_read_pairs += kGatherLanes;
    counters_.drain_clear_pairs += kGatherLanes;
  }
  updates_.commit(context.domain_cycle);
  writes_.commit(context.domain_cycle);
  drain_.commit(context.domain_cycle);
  if (phase_ == Phase::kGather && accepted_count_ == expected_ &&
      updates_.drained() && writes_.drained()) {
    phase_ = Phase::kDrain;
  } else if (phase_ == Phase::kDrain && next_row_ == kLittleRows &&
             drain_.drained()) {
    phase_ = Phase::kFinished;
    ++counters_.partitions;
  }
}

}  // namespace spine::sim::original_regraph
