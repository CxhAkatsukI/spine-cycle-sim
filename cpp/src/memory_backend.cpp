#include "spine_sim/memory_backend.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim {

MockMemoryBackend::MockMemoryBackend(std::string name, ClockId clock_id,
                                     MockMemoryConfig config)
    : MemoryBackend(std::move(name), clock_id), config_(config) {
  if (config_.channels == 0 || config_.latency_cycles == 0 ||
      config_.accepts_per_channel_per_cycle == 0 ||
      config_.max_outstanding_per_channel == 0 ||
      config_.response_queue_depth == 0) {
    throw std::invalid_argument("mock memory configuration values must be positive");
  }
}

std::size_t MockMemoryBackend::channel_outstanding(std::size_t channel) const {
  return static_cast<std::size_t>(std::count_if(
      pending_.begin(), pending_.end(), [channel](const Pending& pending) {
        return pending.channel == channel;
      }));
}

bool MockMemoryBackend::try_submit(const BackendRequest& request) {
  if (request.channel >= config_.channels || request.bytes == 0) {
    throw std::invalid_argument("invalid mock memory request");
  }
  const auto staged_for_channel = static_cast<std::size_t>(std::count_if(
      staged_submissions_.begin(), staged_submissions_.end(),
      [&request](const BackendRequest& staged) {
        return staged.channel == request.channel;
      }));
  if (staged_for_channel >= config_.accepts_per_channel_per_cycle ||
      channel_outstanding(request.channel) + staged_for_channel >=
          config_.max_outstanding_per_channel) {
    ++stats_.submit_stalls;
    return false;
  }
  staged_submissions_.push_back(request);
  return true;
}

std::size_t MockMemoryBackend::response_count() const noexcept {
  return responses_.size();
}

const BackendResponse& MockMemoryBackend::response_at(std::size_t index) const {
  if (index >= responses_.size()) {
    throw std::out_of_range("mock memory response index out of range");
  }
  return responses_[index];
}

bool MockMemoryBackend::stage_pop_responses(std::size_t count) {
  if (staged_response_pops_ != 0 || count > responses_.size()) {
    return false;
  }
  staged_response_pops_ = count;
  return true;
}

std::size_t MockMemoryBackend::outstanding() const noexcept {
  return pending_.size() + staged_submissions_.size();
}

void MockMemoryBackend::prepare(const CycleContext& context) {
  while (!pending_.empty() &&
         pending_.front().due_cycle <= context.domain_cycle) {
    if (responses_.size() >= config_.response_queue_depth) {
      ++stats_.response_queue_stalls;
      break;
    }
    responses_.push_back(pending_.front().response);
    pending_.pop_front();
  }
}

void MockMemoryBackend::commit(const CycleContext& context) {
  for (std::size_t index = 0; index < staged_response_pops_; ++index) {
    responses_.pop_front();
  }
  staged_response_pops_ = 0;
  for (const BackendRequest& request : staged_submissions_) {
    pending_.push_back(Pending{
        .response = BackendResponse{.request_id = request.request_id, .success = true},
        .channel = request.channel,
        .due_cycle = context.domain_cycle + config_.latency_cycles,
    });
    ++stats_.accepted;
  }
  staged_submissions_.clear();
  stats_.max_outstanding = std::max(stats_.max_outstanding, pending_.size());
}

}  // namespace spine::sim
