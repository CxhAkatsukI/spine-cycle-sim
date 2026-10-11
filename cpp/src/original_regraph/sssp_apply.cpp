#include "spine_sim/original_regraph/sssp_apply.hpp"

#include <algorithm>
#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"
#include "spine_sim/original_regraph/udf.hpp"

namespace spine::sim::original_regraph {

SsspApply::SsspApply(std::string name, ClockId clock, TransactionPort old_state,
                     Fifo<PropertyWrite>& input, Fifo<PropertyWrite>& output,
                     std::uint64_t address, std::uint64_t bytes,
                     PipelineTiming timing, std::size_t line_credits, bool response_anchored)
    : Component(std::move(name), clock), old_state_(old_state), input_(input), output_(output),
      address_(address), bytes_(bytes), line_credits_(line_credits),
      response_anchored_(response_anchored), pipeline_(timing) {
  if (old_state.requests.clock_id() != clock || old_state.responses.clock_id() != clock ||
      input.clock_id() != clock || output.clock_id() != clock || !line_credits ||
      address % 64 || !bytes || bytes % 64 || bytes > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("invalid SSSP Apply port, old-state extent or credits");
  }
}

void SsspApply::begin(std::uint32_t lines, std::optional<std::uint64_t> address) {
  if (active_ || !pending_.empty() || !pipeline_.drained() || !input_.empty() ||
      !output_.empty() || !old_state_.requests.empty() || !old_state_.responses.empty()) {
    throw std::logic_error("SSSP Apply restart requires drained queues");
  }
  if (address) {
    if (*address % 64 || bytes_ > std::numeric_limits<std::uint64_t>::max() - *address) {
      throw std::invalid_argument("invalid relocated SSSP Apply old-state allocation");
    }
    address_ = *address;
  }
  expected_ = lines;
  accepted_ = 0;
  input_ended_ = false;
  active_ = true;
}

void SsspApply::evaluate(const CycleContext& context) {
  staged_input_.reset();
  staged_response_.reset();
  staged_active_vertices_ = 0;
  stage_compute_ = stage_input_end_ = stage_output_end_ = false;
  if (!active_) return;
  if (input_ended_ && !input_.empty()) {
    throw std::logic_error("SSSP Apply input after terminator");
  }
  if (const auto* packet = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*packet)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (!old_state_.responses.empty()) {
    AxiResponse response;
    if (!old_state_.responses.try_pop(response)) throw std::logic_error("SSSP Apply response ownership");
    detail::require_read_ack(response, response.transaction_id, 64);
    const auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.transaction == response.transaction_id;
    });
    if (found == pending_.end() || found->old_state) {
      throw std::logic_error("unexpected SSSP Apply old-state response");
    }
    staged_response_ = {response.transaction_id, detail::property_line(response.read_data)};
  }
  const PropertyLine* old_state = nullptr;
  if (!pending_.empty()) {
    if (pending_.front().old_state) old_state = &*pending_.front().old_state;
    else if (response_anchored_ && staged_response_ &&
             staged_response_->first == pending_.front().transaction) {
      // Anchor to response acceptance, without bypassing ordered pending work.
      old_state = &staged_response_->second;
    }
  }
  if (old_state && pipeline_.can_accept(context.domain_cycle)) {
    const auto& job = pending_.front();
    PropertyWrite result{{}, job.packet.index, false};
    for (std::size_t word = 0; word < result.data.size(); ++word) {
      result.data[word] = apply_sssp_property(job.packet.data[word], (*old_state)[word]);
      staged_active_vertices_ += (result.data[word] & kSsspActive) != 0;
    }
    pipeline_.stage_accept(result, context.domain_cycle);
    stage_compute_ = true;
  }
  if (!input_ended_ && !input_.empty()) {
    const auto packet = *input_.front();
    if (packet.end) {
      if (accepted_ != expected_) throw std::logic_error("SSSP Apply input terminated before expected extent");
      PropertyWrite consumed;
      if (!input_.try_pop(consumed)) throw std::logic_error("SSSP Apply input ownership");
      stage_input_end_ = true;
    } else {
      if (accepted_ == expected_) throw std::logic_error("excess SSSP Apply data after expected extent");
      if (static_cast<std::uint64_t>(packet.index) >= bytes_ / 64) {
        throw std::out_of_range("SSSP Apply old-state index exceeds allocation");
      }
      const auto live = pending_.size() + pipeline_.counters().accepted - pipeline_.counters().completed;
      if (live >= line_credits_) ++counters_.credit_stalls;
      else if (old_state_.requests.try_push(AxiRequest{
          .transaction_id = next_transaction_, .operation = MemoryOperation::kRead,
          .address = address_ + static_cast<std::uint64_t>(packet.index) * 64,
          .bytes = 64, .stream_read_beats = false, .target_channel = std::nullopt, .write_data = {}})) {
        PropertyWrite consumed;
        if (!input_.try_pop(consumed)) throw std::logic_error("SSSP Apply input ownership");
        staged_input_ = Pending{next_transaction_, packet, std::nullopt};
      } else ++counters_.request_stalls;
    }
  }
  if (input_ended_ && pending_.empty() && pipeline_.drained() &&
      old_state_.requests.empty() && old_state_.responses.empty()) {
    stage_output_end_ = output_.try_push({{}, 0, true});
  }
}

void SsspApply::commit(const CycleContext& context) {
  if (staged_response_) {
    auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.transaction == staged_response_->first;
    });
    if (found == pending_.end()) throw std::logic_error("SSSP Apply response lost pending metadata");
    found->old_state = staged_response_->second;
    ++counters_.old_state_responses;
    counters_.old_state_bytes += 64;
  }
  if (stage_compute_) {
    pending_.pop_front();
    counters_.active_vertices += staged_active_vertices_;
  }
  if (staged_input_) {
    pending_.push_back(*staged_input_);
    ++next_transaction_;
    ++accepted_;
    ++counters_.lines;
  }
  if (stage_input_end_) { input_ended_ = true; ++counters_.input_terminators; }
  if (stage_output_end_) { active_ = false; ++counters_.output_terminators; }
  pipeline_.commit(context.domain_cycle);
  counters_.max_live_lines = std::max(counters_.max_live_lines, static_cast<std::size_t>(
      pending_.size() + pipeline_.counters().accepted - pipeline_.counters().completed));
}

}  // namespace spine::sim::original_regraph
