#include "spine_sim/memory_backend.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

MemoryLocalityStats add_locality(const MemoryLocalityStats& left,
                                 const MemoryLocalityStats& right) noexcept {
  return MemoryLocalityStats{
      .requests = left.requests + right.requests,
      .bytes = left.bytes + right.bytes,
      .first_requests = left.first_requests + right.first_requests,
      .first_bytes = left.first_bytes + right.first_bytes,
      .contiguous_requests =
          left.contiguous_requests + right.contiguous_requests,
      .contiguous_bytes = left.contiguous_bytes + right.contiguous_bytes,
      .repeated_requests = left.repeated_requests + right.repeated_requests,
      .repeated_bytes = left.repeated_bytes + right.repeated_bytes,
      .discontinuous_requests =
          left.discontinuous_requests + right.discontinuous_requests,
      .discontinuous_bytes =
          left.discontinuous_bytes + right.discontinuous_bytes,
  };
}

MemoryLocalityStats subtract_locality(const MemoryLocalityStats& after,
                                      const MemoryLocalityStats& before) {
  const auto subtract = [](std::uint64_t later, std::uint64_t earlier) {
    if (later < earlier) {
      throw std::invalid_argument("memory traffic snapshots are not ordered");
    }
    return later - earlier;
  };
  return MemoryLocalityStats{
      .requests = subtract(after.requests, before.requests),
      .bytes = subtract(after.bytes, before.bytes),
      .first_requests =
          subtract(after.first_requests, before.first_requests),
      .first_bytes = subtract(after.first_bytes, before.first_bytes),
      .contiguous_requests =
          subtract(after.contiguous_requests, before.contiguous_requests),
      .contiguous_bytes =
          subtract(after.contiguous_bytes, before.contiguous_bytes),
      .repeated_requests =
          subtract(after.repeated_requests, before.repeated_requests),
      .repeated_bytes =
          subtract(after.repeated_bytes, before.repeated_bytes),
      .discontinuous_requests = subtract(after.discontinuous_requests,
                                          before.discontinuous_requests),
      .discontinuous_bytes =
          subtract(after.discontinuous_bytes, before.discontinuous_bytes),
  };
}

enum class LocalityClass { kFirst, kContiguous, kRepeated, kDiscontinuous };

void record_locality(MemoryLocalityStats& stats, LocalityClass locality,
                     std::uint32_t bytes) {
  ++stats.requests;
  stats.bytes += bytes;
  switch (locality) {
    case LocalityClass::kFirst:
      ++stats.first_requests;
      stats.first_bytes += bytes;
      break;
    case LocalityClass::kContiguous:
      ++stats.contiguous_requests;
      stats.contiguous_bytes += bytes;
      break;
    case LocalityClass::kRepeated:
      ++stats.repeated_requests;
      stats.repeated_bytes += bytes;
      break;
    case LocalityClass::kDiscontinuous:
      ++stats.discontinuous_requests;
      stats.discontinuous_bytes += bytes;
      break;
  }
}

}  // namespace

MemoryLocalityStats combine_memory_traffic(
    const MemoryTrafficStats& stats) noexcept {
  return add_locality(stats.reads, stats.writes);
}

MemoryTrafficStats subtract_memory_traffic(const MemoryTrafficStats& after,
                                           const MemoryTrafficStats& before) {
  return MemoryTrafficStats{
      .reads = subtract_locality(after.reads, before.reads),
      .writes = subtract_locality(after.writes, before.writes),
  };
}

void MemoryBackend::register_initiator(std::uint32_t initiator_id) {
  if (!initiators_.insert(initiator_id).second) {
    throw std::invalid_argument("memory initiator ID is already registered");
  }
}

bool MemoryBackend::initiator_registered(
    std::uint32_t initiator_id) const noexcept {
  return initiators_.contains(initiator_id);
}

void MemoryBackend::begin_traffic_epoch() noexcept {
  traffic_cursors_.clear();
}

void MemoryBackend::record_accepted_request(const BackendRequest& request) {
  const std::size_t operation_index =
      request.operation == MemoryOperation::kRead ? 0 : 1;
  AccessCursor& cursor =
      traffic_cursors_[request.initiator_id].operations[operation_index];
  LocalityClass locality = LocalityClass::kFirst;
  if (cursor.valid) {
    const bool same_channel = cursor.channel == request.channel;
    if (same_channel && cursor.address == request.address) {
      locality = LocalityClass::kRepeated;
    } else if (same_channel && request.address >= cursor.address &&
               request.address - cursor.address == cursor.bytes) {
      locality = LocalityClass::kContiguous;
    } else {
      locality = LocalityClass::kDiscontinuous;
    }
  }

  MemoryLocalityStats& total = request.operation == MemoryOperation::kRead
                                   ? traffic_stats_.reads
                                   : traffic_stats_.writes;
  MemoryTrafficStats& initiator =
      traffic_stats_by_initiator_[request.initiator_id];
  MemoryLocalityStats& per_initiator =
      request.operation == MemoryOperation::kRead ? initiator.reads
                                                  : initiator.writes;
  record_locality(total, locality, request.bytes);
  record_locality(per_initiator, locality, request.bytes);
  cursor = AccessCursor{
      .valid = true,
      .channel = request.channel,
      .address = request.address,
      .bytes = request.bytes,
  };
}

void MemoryBackend::initialize_payload(
    std::size_t channel, std::uint64_t address,
    const std::vector<std::uint8_t>& data) {
  if (data.size() > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("memory payload initialization overflows address");
  }
  auto& storage = payload_storage_[channel];
  std::size_t index = 0;
  while (index < data.size()) {
    const std::uint64_t byte_address = address + index;
    const std::uint64_t page_number = byte_address / kPayloadPageBytes;
    const std::size_t page_offset =
        static_cast<std::size_t>(byte_address % kPayloadPageBytes);
    const std::size_t chunk =
        std::min(data.size() - index, kPayloadPageBytes - page_offset);
    PayloadPage& page = storage[page_number];
    std::copy_n(data.begin() + static_cast<std::ptrdiff_t>(index), chunk,
                page.bytes.begin() + static_cast<std::ptrdiff_t>(page_offset));
    for (std::size_t offset = page_offset; offset < page_offset + chunk;
         ++offset) {
      page.mark(offset);
    }
    index += chunk;
  }
}

void MemoryBackend::fill_payload(std::size_t channel, std::uint64_t address,
                                 std::uint64_t bytes, std::uint8_t value) {
  if (bytes == 0 || address > std::numeric_limits<std::uint64_t>::max() - bytes) {
    throw std::invalid_argument("invalid memory payload fill range");
  }
  payload_fills_[channel].push_back(
      FillRegion{.address = address, .bytes = bytes, .value = value});
}

std::vector<std::uint8_t> MemoryBackend::inspect_payload(
    std::size_t channel, std::uint64_t address, std::size_t bytes) const {
  if (bytes > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("memory payload inspection overflows address");
  }
  std::vector<std::uint8_t> result(bytes, 0);
  const auto channel_storage = payload_storage_.find(channel);
  const auto channel_fills = payload_fills_.find(channel);
  std::size_t index = 0;
  while (index < bytes) {
    const std::uint64_t byte_address = address + index;
    const std::uint64_t page_number = byte_address / kPayloadPageBytes;
    const std::size_t page_offset =
        static_cast<std::size_t>(byte_address % kPayloadPageBytes);
    const std::size_t chunk =
        std::min(bytes - index, kPayloadPageBytes - page_offset);
    const PayloadPage* page = nullptr;
    if (channel_storage != payload_storage_.end()) {
      const auto found = channel_storage->second.find(page_number);
      if (found != channel_storage->second.end()) {
        page = &found->second;
      }
    }
    for (std::size_t within = 0; within < chunk; ++within) {
      const std::size_t offset = page_offset + within;
      if (page != nullptr && page->contains(offset)) {
        result[index + within] = page->bytes[offset];
        continue;
      }
      if (channel_fills == payload_fills_.end()) {
        continue;
      }
      const std::uint64_t current_address = byte_address + within;
      for (auto fill = channel_fills->second.rbegin();
           fill != channel_fills->second.rend(); ++fill) {
        if (current_address >= fill->address &&
            current_address - fill->address < fill->bytes) {
          result[index + within] = fill->value;
          break;
        }
      }
    }
    index += chunk;
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

RegisteredChannelArbiter::RegisteredChannelArbiter(
    std::size_t channels, std::size_t grants_per_channel_per_cycle)
    : channels_(channels),
      grants_per_channel_per_cycle_(grants_per_channel_per_cycle),
      intents_(channels),
      grants_(channels),
      next_initiator_(channels, 0) {
  if (channels_ == 0 || grants_per_channel_per_cycle_ == 0) {
    throw std::invalid_argument(
        "registered channel arbiter configuration must be positive");
  }
}

bool RegisteredChannelArbiter::try_acquire(const BackendRequest& request) {
  if (request.channel >= channels_) {
    throw std::invalid_argument("arbiter request targets an invalid channel");
  }
  auto& channel_grants = grants_[request.channel];
  const auto granted = channel_grants.find(request.initiator_id);
  if (granted != channel_grants.end()) {
    channel_grants.erase(granted);
    ++stats_.consumed_grants;
    return true;
  }

  auto& channel_intents = intents_[request.channel];
  const auto [pending, inserted] =
      channel_intents.emplace(request.initiator_id, request);
  (void)pending;
  stats_.unique_intents += inserted ? 1 : 0;
  ++stats_.request_waits;
  return false;
}

void RegisteredChannelArbiter::arbitrate(
    std::span<const std::size_t> channel_outstanding,
    std::size_t max_outstanding_per_channel) {
  if (channel_outstanding.size() != channels_ ||
      max_outstanding_per_channel == 0) {
    throw std::invalid_argument("invalid arbiter outstanding snapshot");
  }
  for (std::size_t channel = 0; channel < channels_; ++channel) {
    auto& intents = intents_[channel];
    auto& grants = grants_[channel];
    stats_.max_contenders = std::max(stats_.max_contenders, intents.size());
    if (intents.empty()) {
      continue;
    }
    const std::size_t occupied = channel_outstanding[channel] + grants.size();
    const std::size_t capacity =
        occupied < max_outstanding_per_channel
            ? max_outstanding_per_channel - occupied
            : 0;
    const std::size_t slots =
        std::min(grants_per_channel_per_cycle_, capacity);
    if (slots == 0) {
      ++stats_.capacity_blocked_cycles;
      stats_.contention_losers += intents.size();
      continue;
    }
    if (intents.size() > slots) {
      ++stats_.contended_cycles;
      stats_.contention_losers += intents.size() - slots;
    }

    for (std::size_t slot = 0; slot < slots && !intents.empty(); ++slot) {
      auto selected = intents.lower_bound(next_initiator_[channel]);
      if (selected == intents.end()) {
        selected = intents.begin();
      }
      const std::uint32_t initiator = selected->first;
      if (!grants.emplace(initiator, std::move(selected->second)).second) {
        throw std::logic_error("arbiter issued a duplicate initiator grant");
      }
      intents.erase(selected);
      next_initiator_[channel] = initiator + 1;
      ++stats_.grants;
    }
  }
  stats_.max_pending_grants =
      std::max(stats_.max_pending_grants, pending_grants());
}

std::size_t RegisteredChannelArbiter::pending_grants() const noexcept {
  std::size_t count = 0;
  for (const auto& grants : grants_) {
    count += grants.size();
  }
  return count;
}

std::size_t RegisteredChannelArbiter::pending_intents() const noexcept {
  std::size_t count = 0;
  for (const auto& intents : intents_) {
    count += intents.size();
  }
  return count;
}

std::size_t RegisteredChannelArbiter::pending_grants_for(
    std::uint32_t initiator_id) const noexcept {
  std::size_t count = 0;
  for (const auto& grants : grants_) {
    count += grants.contains(initiator_id) ? 1 : 0;
  }
  return count;
}

MockMemoryBackend::MockMemoryBackend(std::string name, ClockId clock_id,
                                     MockMemoryConfig config)
    : MemoryBackend(std::move(name), clock_id), config_(config),
      arbiter_(config.registered_round_robin_arbitration
                   ? std::make_unique<RegisteredChannelArbiter>(
                         config.channels,
                         config.accepts_per_channel_per_cycle)
                   : nullptr) {
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
  if (arbiter_ != nullptr && !arbiter_->try_acquire(request)) {
    ++stats_.submit_stalls;
    return false;
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
  return pending_.size() + staged_submissions_.size() +
         (arbiter_ == nullptr ? 0 : arbiter_->pending_grants());
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
  return pending + staged +
         (arbiter_ == nullptr ? 0
                              : arbiter_->pending_grants_for(initiator_id));
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
    record_accepted_request(request);
    ++stats_.accepted;
  }
  staged_submissions_.clear();
  if (arbiter_ != nullptr) {
    std::vector<std::size_t> outstanding(config_.channels, 0);
    for (const Pending& item : pending_) {
      if (!item.completed) {
        ++outstanding[item.channel];
      }
    }
    arbiter_->arbitrate(outstanding, config_.max_outstanding_per_channel);
  }
  stats_.max_outstanding = std::max(stats_.max_outstanding, pending_.size());
}

}  // namespace spine::sim
