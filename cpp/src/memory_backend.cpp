#include "spine_sim/memory_backend.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim {

void MemoryBackend::register_initiator(std::uint32_t initiator_id) {
  if (!initiators_.insert(initiator_id).second) {
    throw std::invalid_argument("memory initiator ID is already registered");
  }
}

bool MemoryBackend::initiator_registered(
    std::uint32_t initiator_id) const noexcept {
  return initiators_.contains(initiator_id);
}

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
  if (!initiator_registered(request.initiator_id) ||
      request.channel >= config_.channels || request.bytes == 0) {
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

std::size_t MockMemoryBackend::response_count(
    std::uint32_t initiator_id) const noexcept {
  const auto found = responses_.find(initiator_id);
  return found == responses_.end() ? 0 : found->second.size();
}

const BackendResponse& MockMemoryBackend::response_at(
    std::uint32_t initiator_id, std::size_t index) const {
  const auto found = responses_.find(initiator_id);
  if (found == responses_.end() || index >= found->second.size()) {
    throw std::out_of_range("mock memory response index out of range");
  }
  return found->second[index];
}

bool MockMemoryBackend::stage_pop_responses(std::uint32_t initiator_id,
                                            std::size_t count) {
  const std::size_t staged = staged_response_pops_[initiator_id];
  if (staged != 0 || count > response_count(initiator_id)) {
    return false;
  }
  staged_response_pops_[initiator_id] = count;
  return true;
}

std::size_t MockMemoryBackend::outstanding() const noexcept {
  return pending_.size() + staged_submissions_.size();
}

std::size_t MockMemoryBackend::outstanding_for(
    std::uint32_t initiator_id) const noexcept {
  const auto pending = static_cast<std::size_t>(std::count_if(
      pending_.begin(), pending_.end(),
      [initiator_id](const Pending& item) {
        return item.response.initiator_id == initiator_id;
      }));
  const auto staged = static_cast<std::size_t>(std::count_if(
      staged_submissions_.begin(), staged_submissions_.end(),
      [initiator_id](const BackendRequest& request) {
        return request.initiator_id == initiator_id;
      }));
  return pending + staged;
}

void MockMemoryBackend::prepare(const CycleContext& context) {
  for (auto iterator = pending_.begin(); iterator != pending_.end();) {
    if (iterator->due_cycle > context.domain_cycle) {
      ++iterator;
      continue;
    }
    auto& queue = responses_[iterator->response.initiator_id];
    if (queue.size() >= config_.response_queue_depth) {
      ++stats_.response_queue_stalls;
      ++iterator;
      continue;
    }
    queue.push_back(iterator->response);
    iterator = pending_.erase(iterator);
  }
}

void MockMemoryBackend::commit(const CycleContext& context) {
  for (const auto& [initiator_id, count] : staged_response_pops_) {
    auto& queue = responses_[initiator_id];
    for (std::size_t index = 0; index < count; ++index) {
      queue.pop_front();
    }
  }
  staged_response_pops_.clear();
  for (const BackendRequest& request : staged_submissions_) {
    pending_.push_back(Pending{
        .response = BackendResponse{
            .initiator_id = request.initiator_id,
            .request_id = request.request_id,
            .success = true,
        },
        .channel = request.channel,
        .due_cycle = context.domain_cycle + config_.latency_cycles,
    });
    ++stats_.accepted;
  }
  staged_submissions_.clear();
  stats_.max_outstanding = std::max(stats_.max_outstanding, pending_.size());
}

}  // namespace spine::sim
