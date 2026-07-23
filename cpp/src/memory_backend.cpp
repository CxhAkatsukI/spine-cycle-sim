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

void MemoryBackend::initialize_payload(
    std::size_t channel, std::uint64_t address,
    const std::vector<std::uint8_t>& data) {
  auto& storage = payload_storage_[channel];
  for (std::size_t index = 0; index < data.size(); ++index) {
    storage[address + index] = data[index];
  }
}

std::vector<std::uint8_t> MemoryBackend::inspect_payload(
    std::size_t channel, std::uint64_t address, std::size_t bytes) const {
  std::vector<std::uint8_t> result(bytes, 0);
  const auto channel_storage = payload_storage_.find(channel);
  if (channel_storage == payload_storage_.end()) {
    return result;
  }
  for (std::size_t index = 0; index < bytes; ++index) {
    const auto found = channel_storage->second.find(address + index);
    if (found != channel_storage->second.end()) {
      result[index] = found->second;
    }
  }
  return result;
}

void MemoryBackend::commit_write_payload(const BackendRequest& request) {
  if (request.operation != MemoryOperation::kWrite ||
      request.write_data.size() != request.bytes) {
    throw std::invalid_argument("invalid completed memory write payload");
  }
  initialize_payload(request.channel, request.address, request.write_data);
}

std::vector<std::uint8_t> MemoryBackend::complete_read_payload(
    const BackendRequest& request) const {
  if (request.operation != MemoryOperation::kRead ||
      !request.write_data.empty()) {
    throw std::invalid_argument("invalid completed memory read payload");
  }
  return inspect_payload(request.channel, request.address, request.bytes);
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
        return pending.channel == channel && !pending.completed;
      }));
}

bool MockMemoryBackend::try_submit(const BackendRequest& request) {
  if (!initiator_registered(request.initiator_id) ||
      request.channel >= config_.channels || request.bytes == 0) {
    throw std::invalid_argument("invalid mock memory request");
  }
  if ((request.operation == MemoryOperation::kRead &&
       !request.write_data.empty()) ||
      (request.operation == MemoryOperation::kWrite &&
       request.write_data.size() != request.bytes)) {
    throw std::invalid_argument("invalid mock memory request payload");
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
        return !item.completed && item.request.initiator_id == initiator_id;
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
    if (!iterator->completed) {
      if (iterator->request.operation == MemoryOperation::kWrite) {
        commit_write_payload(iterator->request);
      }
      iterator->completed = true;
    }
    auto& queue = responses_[iterator->request.initiator_id];
    if (queue.size() >= config_.response_queue_depth) {
      ++stats_.response_queue_stalls;
      ++iterator;
      continue;
    }
    queue.push_back(BackendResponse{
        .initiator_id = iterator->request.initiator_id,
        .request_id = iterator->request.request_id,
        .success = true,
        .read_data = iterator->request.operation == MemoryOperation::kRead
                         ? complete_read_payload(iterator->request)
                         : std::vector<std::uint8_t>{},
    });
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
        .request = request,
        .channel = request.channel,
        .due_cycle = context.domain_cycle + config_.latency_cycles,
        .completed = false,
    });
    ++stats_.accepted;
  }
  staged_submissions_.clear();
  stats_.max_outstanding = std::max(stats_.max_outstanding, pending_.size());
}

}  // namespace spine::sim
