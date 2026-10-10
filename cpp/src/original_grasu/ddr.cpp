#include "spine_sim/original_grasu/ddr.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_grasu {

DdrCore::DdrCore(std::string name, ClockId clock, unsigned subpath,
                 std::array<Fifo<Update>*, 16> input, Port reads, Port writes, Timing timing)
    : Component(std::move(name), clock), subpath_(subpath), input_(input), reads_(reads), writes_(writes), timing_(timing) {
  if (subpath > 1 || !timing.ddr_compute || !timing.ddr_sweep_minimum || !timing.ddr_restart)
    throw std::invalid_argument("G DDR subpath/timing");
}

void DdrCore::begin(std::uint64_t address, std::uint32_t segments) {
  if (started_ && !finished()) throw std::logic_error("G DDR restart before drain");
  if (address % 64 || segments <= kHotSegments) throw std::invalid_argument("G DDR admitted extent");
  address_ = address; segments_ = segments; cursor_ = 0; ended_ = {}; done_ = false;
  epoch_pending_ = true; started_ = true;
}

void DdrCore::evaluate(const CycleContext& context) {
  stage_poll_ = stage_end_ = stage_read_ = stage_write_ = stage_restart_ = false;
  stage_epoch_ = false;
  read_ack_.reset(); write_ack_.reset();
  if (!started_ || done_) return;
  if (epoch_pending_) { stage_epoch_ = true; return; }
  if (!reads_.responses.empty()) {
    AxiResponse response; reads_.responses.try_pop(response);
    const auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.phase == Phase::kRead && item.transaction == response.transaction_id;
    });
    if (found == pending_.end()) throw std::logic_error("G DDR unexpected read response");
    require_ack(response, found->transaction, MemoryOperation::kRead, 64);
    read_ack_ = {{static_cast<unsigned>(found - pending_.begin()), apply_update(decode_segment(response.read_data), found->update)}};
  }
  if (!writes_.responses.empty()) {
    AxiResponse response; writes_.responses.try_pop(response);
    const auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.phase == Phase::kWrite && item.transaction == response.transaction_id;
    });
    if (found == pending_.end()) throw std::logic_error("G DDR unexpected write response");
    require_ack(response, found->transaction, MemoryOperation::kWrite, 0);
    write_ack_ = static_cast<unsigned>(found - pending_.begin());
  }
  if (!write_order_.empty()) {
    const auto& item = pending_[write_order_.front()];
    if (item.phase == Phase::kCompute && item.ready <= context.domain_cycle)
      stage_write_ = writes_.requests.try_push(AxiRequest{.transaction_id = item.transaction,
          .operation = MemoryOperation::kWrite, .address = address_ + (item.update.slot >> 5) * 64ull,
          .bytes = 64, .stream_read_beats = false, .target_channel = std::nullopt,
          .write_data = encode_segments(std::span<const Segment>(&item.result, 1))});
  }
  if (context.domain_cycle < sweep_start_) return;
  if (cursor_ == 16) {
    stage_restart_ = context.domain_cycle >= sweep_start_ + timing_.ddr_sweep_minimum &&
        std::all_of(pending_.begin(), pending_.end(), [](const auto& item) { return item.phase == Phase::kFree; });
    return;
  }
  if (input_[cursor_]->empty()) { stage_poll_ = true; return; }
  incoming_ = *input_[cursor_]->front();
  if (ended_[cursor_]) throw std::logic_error("G DDR data after lane end");
  if (incoming_.end) stage_end_ = true;
  else {
    const auto index = incoming_.slot >> 5;
    if (index < kHotSegments || index >= segments_ || index % 2 != subpath_ || (index / 2) % 16 != cursor_)
      throw std::logic_error("G DDR bank/address/extent route");
    stage_read_ = reads_.requests.try_push(AxiRequest{.transaction_id = next_transaction_,
        .operation = MemoryOperation::kRead, .address = address_ + index * 64ull, .bytes = 64,
        .stream_read_beats = false, .target_channel = std::nullopt, .write_data = {}});
    if (!stage_read_) { ++counters_.output_stalls; return; }
  }
  Update consumed; input_[cursor_]->try_pop(consumed); stage_poll_ = true;
}

void DdrCore::commit(const CycleContext& context) {
  if (stage_epoch_) { epoch_pending_ = false; sweep_start_ = context.domain_cycle + 1; }
  if (read_ack_) {
    auto& item = pending_[read_ack_->first]; item.result = read_ack_->second;
    item.phase = Phase::kCompute; item.ready = context.domain_cycle + timing_.ddr_compute;
    ++counters_.acknowledgements;
  }
  if (write_ack_) { pending_[*write_ack_].phase = Phase::kFree; ++counters_.acknowledgements; }
  if (stage_write_) { pending_[write_order_.front()].phase = Phase::kWrite; write_order_.pop_front(); ++counters_.writes; }
  if (stage_read_) {
    auto& item = pending_[cursor_]; item.phase = Phase::kRead; item.update = incoming_;
    item.transaction = next_transaction_++; write_order_.push_back(cursor_);
    ++counters_.reads; ++counters_.updates;
  }
  if (stage_end_) { ended_[cursor_] = true; ++counters_.ends; }
  if (stage_poll_) ++cursor_;
  if (stage_restart_) {
    done_ = std::all_of(ended_.begin(), ended_.end(), [](auto value) { return value; });
    cursor_ = 0; sweep_start_ = context.domain_cycle + timing_.ddr_restart;
  }
}

}  // namespace spine::sim::original_grasu
