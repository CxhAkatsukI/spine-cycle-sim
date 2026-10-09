#include "spine_sim/original_regraph/big_requests.hpp"

#include <stdexcept>

namespace spine::sim::original_regraph {

BigEdgeFork::BigEdgeFork(std::string name, ClockId clock, Fifo<EdgeBurst>& input,
    Fifo<EdgeBurst>& scatter, Fifo<EdgeBurst>& source)
    : Component(std::move(name), clock), input_(input), scatter_(scatter), source_(source) {
  if (input.clock_id() != clock || scatter.clock_id() != clock || source.clock_id() != clock ||
      &input == &scatter || &input == &source || &scatter == &source) {
    throw std::invalid_argument("Big edge fork requires distinct same-clock ports");
  }
}
void BigEdgeFork::begin_partition(std::uint64_t bursts) {
  if (!finished() || !input_.empty() || !scatter_.empty() || !source_.empty()) {
    throw std::logic_error("Big edge fork restart requires drained ports");
  }
  remaining_ = bursts;
}
void BigEdgeFork::evaluate(const CycleContext&) {
  accepted_ = false;
  if (!remaining_ || input_.empty()) return;
  if (scatter_.full() || source_.full()) { ++output_stalls_; return; }
  EdgeBurst value;
  if (!input_.try_pop(value) || !scatter_.try_push(value) || !source_.try_push(value)) {
    throw std::logic_error("Big edge fork ownership mismatch");
  }
  accepted_ = true;
}
void BigEdgeFork::commit(const CycleContext&) { if (accepted_) --remaining_; }

BigRequestGenerator::BigRequestGenerator(std::string name, ClockId clock,
    Fifo<EdgeBurst>& input, Fifo<CachelineBatch>& output)
    : Component(std::move(name), clock), input_(input), output_(output) {
  if (input.clock_id() != clock || output.clock_id() != clock) throw std::invalid_argument("Big generator clock mismatch");
}
void BigRequestGenerator::begin_partition(std::uint64_t bursts) {
  if (!finished() || !input_.empty() || !output_.empty()) throw std::logic_error("Big generator restart requires drain");
  remaining_ = bursts;
  previous_line_ = previous_source_ = 0;
  end_sent_ = false;
}
void BigRequestGenerator::evaluate(const CycleContext&) {
  accepted_.reset(); stage_end_ = false;
  if (end_sent_) return;
  if (!remaining_) {
    if (output_.full()) { ++output_stalls_; return; }
    if (!output_.try_push({{}, 7, true})) throw std::logic_error("Big generator end ownership");
    stage_end_ = true;
    return;
  }
  if (input_.empty()) return;
  CachelineBatch batch{};
  std::uint32_t previous = previous_source_;
  for (unsigned lane = 0; lane < 8; ++lane) {
    const auto source = (*input_.front())[lane].source & 0x7fffffffu;
    if (source < previous || source >= (1u << 30)) {
      throw std::invalid_argument("Big source input must be sorted in the original 26-bit cacheline domain");
    }
    previous = source;
    batch.lines[lane] = source / 16;
  }
  if (batch.lines.back() != previous_line_) {
    while (batch.first < 8 && batch.lines[batch.first] == previous_line_) ++batch.first;
    if (output_.full()) { ++output_stalls_; return; }
    if (!output_.try_push(batch)) throw std::logic_error("Big generator output ownership");
  }
  EdgeBurst value;
  if (!input_.try_pop(value)) throw std::logic_error("Big generator input ownership");
  accepted_ = value;
}
void BigRequestGenerator::commit(const CycleContext&) {
  if (accepted_) {
    previous_source_ = accepted_->back().source & 0x7fffffffu;
    previous_line_ = previous_source_ / 16;
    --remaining_; ++bursts_;
  }
  if (stage_end_) end_sent_ = true;
}

BigCachelineSender::BigCachelineSender(std::string name, ClockId clock,
    Fifo<CachelineBatch>& input, Fifo<CachelineRequest>& output, std::size_t trace_limit)
    : Component(std::move(name), clock), input_(input), output_(output), trace_limit_(trace_limit) {
  if (input.clock_id() != clock || output.clock_id() != clock) throw std::invalid_argument("Big sender clock mismatch");
}
void BigCachelineSender::begin_partition() {
  if (!finished_ || batch_ || !input_.empty() || !output_.empty()) throw std::logic_error("Big sender restart requires drain");
  initial_ = true; finished_ = false;
}
void BigCachelineSender::evaluate(const CycleContext&) {
  loaded_.reset(); sent_.reset();
  if (finished_) return;
  if (!initial_ && !batch_ && !input_.empty()) {
    CachelineBatch batch;
    if (!input_.try_pop(batch)) throw std::logic_error("Big sender input ownership");
    if (batch.first > 7) throw std::invalid_argument("Big request batch has no lanes");
    loaded_ = batch;
  }
  if (output_.full() || (!initial_ && !batch_)) return;
  CachelineRequest request{};
  if (!initial_) request = {batch_->end ? 0u : batch_->lines[lane_], lane_, batch_->end};
  if (!output_.try_push(request)) throw std::logic_error("Big sender output ownership");
  sent_ = request;
}
void BigCachelineSender::commit(const CycleContext&) {
  if (loaded_) { batch_ = loaded_; lane_ = loaded_->first; }
  if (!sent_) return;
  if (trace_.size() < trace_limit_) trace_.push_back(*sent_); else ++trace_dropped_;
  if (initial_) initial_ = false;
  else if (sent_->end) { batch_.reset(); finished_ = true; }
  else if (++lane_ == 8) batch_.reset();
}

}  // namespace spine::sim::original_regraph
