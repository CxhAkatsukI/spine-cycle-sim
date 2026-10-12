#include "state.hpp"

#include <stdexcept>

namespace spine::sim::detail {

void CrossRowPmaAdapter::evaluate_packet_pipeline(const CycleContext &context) {
  staged_formed_.reset();
  if (!packet_pipeline_.empty() && packet_pipeline_.front().ready <= context.domain_cycle) {
    if (output_.try_push(packet_pipeline_.front().value)) staged_packet_ = packet_pipeline_.front().value;
    else staged_stall_ = true;
  }
  // Two in-flight packets implement the synthesized depth-2, II=1 loop.
  const bool space = packet_pipeline_.size() < 2 || staged_packet_.has_value();
  if (publishing_ && space) {
    auto value = packet();
    value.last = formed_slots_ + 8 >= total_slots_;
    staged_formed_ = PendingPacket{value, context.domain_cycle + 2};
  }
  if (!publisher_closed_ && (!publishing_ || (staged_formed_ && half_ == 1))) {
    Loaded next;
    if (loaded_.try_pop(next)) staged_loaded_ = std::move(next);
  }
}

void CrossRowPmaAdapter::commit_packet_pipeline(const CycleContext &) {
  if (staged_packet_) packet_pipeline_.pop_front();
  if (staged_formed_) {
    packet_pipeline_.push_back(std::move(*staged_formed_));
    formed_slots_ += 8;
    if (++half_ == 2) publishing_.reset();
  }
  if (staged_loaded_) {
    if (staged_loaded_->task.terminal) {
      if (!pending_.empty() || !inflight_.empty() || !returned_.empty() || formed_slots_ != total_slots_)
        throw std::logic_error("pipelined publisher terminal violates conservation");
      publisher_closed_ = true;
    } else {
      publishing_ = std::move(*staged_loaded_);
      half_ = 0;
    }
  }
  if (publisher_closed_ && packet_pipeline_.empty()) {
    phase_ = Phase::kDone;
    stream_complete_ = true;
  }
}

} // namespace spine::sim::detail
