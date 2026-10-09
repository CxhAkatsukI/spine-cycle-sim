#include "spine_sim/original_regraph/pr_apply.hpp"

#include <algorithm>
#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"

namespace spine::sim::original_regraph {

std::uint32_t apply_pr_property(std::uint32_t sum, std::uint32_t degree,
                                std::uint32_t argument) {
  constexpr auto limit = static_cast<std::uint64_t>(std::numeric_limits<std::int32_t>::max());
  const auto damped = static_cast<std::uint64_t>(sum) * 108;
  const auto score = static_cast<std::uint64_t>(argument) + (damped >> 7);
  const auto inverse = degree ? 65536u / degree : 0;
  const auto product = score * inverse;
  if (damped > limit || score > limit || product > limit || degree > limit) {
    throw std::out_of_range("PR source-functional domain excludes signed-int overflow");
  }
  return static_cast<std::uint32_t>(product >> 16);
}

PrApply::PrApply(std::string name, ClockId clock, TransactionPort degree,
                 Fifo<PropertyWrite>& input, Fifo<PropertyWrite>& output,
                 std::uint64_t address, std::uint64_t bytes, PipelineTiming timing,
                 std::size_t line_credits)
    : Component(std::move(name), clock), degree_(degree), input_(input), output_(output),
      address_(address), bytes_(bytes), line_credits_(line_credits), pipeline_(timing) {
  if (degree.requests.clock_id() != clock || degree.responses.clock_id() != clock ||
      input.clock_id() != clock || output.clock_id() != clock || !line_credits ||
      address % 64 || !bytes || bytes % 64 || bytes > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("invalid Apply port, degree extent or credits");
  }
}

void PrApply::begin(std::uint32_t lines, std::uint32_t argument) {
  if (active_ || !pending_.empty() || !pipeline_.drained() || !input_.empty() ||
      !output_.empty() || !degree_.requests.empty() || !degree_.responses.empty()) {
    throw std::logic_error("Apply restart requires drained queues");
  }
  expected_ = lines;
  accepted_ = 0;
  argument_ = argument;
  input_ended_ = false;
  active_ = true;
}

void PrApply::evaluate(const CycleContext& context) {
  staged_input_.reset();
  staged_response_.reset();
  stage_compute_ = stage_input_end_ = stage_output_end_ = false;
  if (!active_) return;
  if (const auto* packet = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*packet)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (!degree_.responses.empty()) {
    AxiResponse response;
    if (!degree_.responses.try_pop(response)) throw std::logic_error("Apply response ownership");
    detail::require_read_ack(response, response.transaction_id, 64);
    const auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.transaction == response.transaction_id;
    });
    if (found == pending_.end() || found->degree) throw std::logic_error("unexpected Apply degree response");
    staged_response_ = {response.transaction_id, detail::property_line(response.read_data)};
  }
  if (!pending_.empty() && pending_.front().degree && pipeline_.can_accept(context.domain_cycle)) {
    const auto& job = pending_.front();
    PropertyWrite result{{}, job.packet.index, false};
    for (std::size_t word = 0; word < result.data.size(); ++word) {
      const auto degree = (*job.degree)[word];
      result.data[word] = apply_pr_property(job.packet.data[word], degree, argument_);
      counters_.zero_degree_vertices += degree == 0;
    }
    pipeline_.stage_accept(result, context.domain_cycle);
    stage_compute_ = true;
  }
  if (!input_ended_ && !input_.empty()) {
    const auto packet = *input_.front();
    if (packet.end) {
      if (accepted_ != expected_) throw std::logic_error("Apply input terminated before expected extent");
      PropertyWrite consumed;
      if (!input_.try_pop(consumed)) throw std::logic_error("Apply input ownership");
      stage_input_end_ = true;
    } else {
      if (accepted_ == expected_) throw std::logic_error("excess Apply data after expected extent");
      if (static_cast<std::uint64_t>(packet.index) >= bytes_ / 64) {
        throw std::out_of_range("Apply degree index exceeds allocation");
      }
      const auto live = pending_.size() + pipeline_.counters().accepted - pipeline_.counters().completed;
      if (live >= line_credits_) ++counters_.credit_stalls;
      else if (degree_.requests.try_push(AxiRequest{
          .transaction_id = next_transaction_, .operation = MemoryOperation::kRead,
          .address = address_ + static_cast<std::uint64_t>(packet.index) * 64,
          .bytes = 64, .stream_read_beats = false, .target_channel = std::nullopt, .write_data = {}})) {
        PropertyWrite consumed;
        if (!input_.try_pop(consumed)) throw std::logic_error("Apply input ownership");
        staged_input_ = Pending{next_transaction_, packet, std::nullopt};
      } else ++counters_.request_stalls;
    }
  }
  if (input_ended_ && pending_.empty() && pipeline_.drained()) {
    stage_output_end_ = output_.try_push({{}, 0, true});
  }
}

void PrApply::commit(const CycleContext& context) {
  if (staged_response_) {
    auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& item) {
      return item.transaction == staged_response_->first;
    });
    if (found == pending_.end()) throw std::logic_error("Apply response lost pending metadata");
    found->degree = staged_response_->second;
    ++counters_.degree_responses;
    counters_.degree_bytes += 64;
  }
  if (stage_compute_) pending_.pop_front();
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
