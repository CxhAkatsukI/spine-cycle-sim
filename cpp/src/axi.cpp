#include "spine_sim/axi.hpp"

#include <algorithm>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace spine::sim {

namespace {
constexpr std::uint64_t kAxiBoundaryBytes = 4096;
}

AxiMaster::AxiMaster(std::string name, ClockId clock_id, AxiConfig config,
                     Fifo<AxiRequest>& requests, Fifo<AxiResponse>& responses,
                     MemoryBackend& backend)
    : Component(std::move(name), clock_id),
      config_(config),
      requests_(requests),
      responses_(responses),
      backend_(backend) {
  if (config_.data_width_bytes == 0 || config_.max_burst_beats == 0 ||
      config_.channels == 0 || config_.channel_interleave_bytes == 0 ||
      config_.max_pending_requests == 0 ||
      config_.max_outstanding_bursts == 0 ||
      config_.address_accepts_per_cycle == 0 ||
      config_.beat_issues_per_cycle == 0 ||
      config_.response_beats_per_cycle == 0) {
    throw std::invalid_argument("AXI configuration values must be positive");
  }
  if (config_.fixed_channel.has_value() &&
      *config_.fixed_channel >= config_.channels) {
    throw std::invalid_argument("AXI fixed channel is outside memory geometry");
  }
  if (requests_.clock_id() != clock_id || responses_.clock_id() != clock_id ||
      backend_.clock_id() != clock_id) {
    throw std::invalid_argument("AXI master, links, and backend must share a clock");
  }
  backend_.register_initiator(config_.initiator_id);
}

std::size_t AxiMaster::pending_requests() const noexcept {
  return parents_.size() + (staged_input_.has_value() ? 1 : 0);
}

bool AxiMaster::idle() const noexcept {
  return parents_.empty() && pending_address_.empty() && active_bursts_.empty() &&
      ready_responses_.empty() &&
      backend_.outstanding_for(config_.initiator_id) == 0;
}

std::size_t AxiMaster::channel_for(std::uint64_t address) const {
  if (config_.fixed_channel.has_value()) {
    return *config_.fixed_channel;
  }
  return static_cast<std::size_t>(
      (address / config_.channel_interleave_bytes) % config_.channels);
}

std::vector<AxiMaster::Burst> AxiMaster::split_request(
    std::uint64_t parent_id, const AxiRequest& request) {
  if (request.bytes == 0) {
    throw std::invalid_argument("AXI request byte count must be positive");
  }
  std::vector<Burst> bursts;
  std::uint64_t address = request.address;
  std::uint64_t remaining = request.bytes;
  const std::uint64_t max_burst_bytes =
      static_cast<std::uint64_t>(config_.data_width_bytes) * config_.max_burst_beats;
  while (remaining != 0) {
    const std::uint64_t boundary_remaining =
        kAxiBoundaryBytes - (address % kAxiBoundaryBytes);
    const std::uint64_t bytes = std::min({remaining, max_burst_bytes,
                                          boundary_remaining});
    const std::size_t beats = static_cast<std::size_t>(
        (bytes + config_.data_width_bytes - 1) / config_.data_width_bytes);
    bursts.push_back(Burst{
        .burst_id = next_burst_id_ + bursts.size(),
        .parent_id = parent_id,
        .operation = request.operation,
        .address = address,
        .bytes = bytes,
        .beats_total = beats,
        .beats_issued = 0,
        .beats_completed = 0,
    });
    if (bytes == boundary_remaining && remaining > bytes) {
      ++stats_.four_kib_splits;
    }
    address += bytes;
    remaining -= bytes;
  }
  return bursts;
}

AxiMaster::Burst* AxiMaster::find_active(std::uint64_t burst_id) {
  const auto found = std::find_if(
      active_bursts_.begin(), active_bursts_.end(),
      [burst_id](const Burst& burst) { return burst.burst_id == burst_id; });
  return found == active_bursts_.end() ? nullptr : &*found;
}

void AxiMaster::reset_staging() {
  staged_input_.reset();
  staged_new_bursts_.clear();
  staged_address_bursts_.clear();
  staged_beats_.clear();
  staged_backend_responses_.clear();
  staged_output_ = false;
}

void AxiMaster::evaluate_output() {
  if (!ready_responses_.empty()) {
    if (responses_.try_push(ready_responses_.front().response)) {
      staged_output_ = true;
    } else {
      ++stats_.response_queue_stalls;
    }
  }
}

void AxiMaster::evaluate_backend_responses() {
  const std::size_t count = std::min(config_.response_beats_per_cycle,
                                     backend_.response_count(config_.initiator_id));
  if (count == 0) {
    return;
  }
  staged_backend_responses_.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    staged_backend_responses_.push_back(
        backend_.response_at(config_.initiator_id, index));
  }
  if (!backend_.stage_pop_responses(config_.initiator_id, count)) {
    throw std::logic_error("memory backend rejected a valid response pop");
  }
}

void AxiMaster::evaluate_request_input() {
  if (parents_.size() >= config_.max_pending_requests) {
    if (requests_.front() != nullptr) {
      ++stats_.request_queue_stalls;
    }
    return;
  }
  AxiRequest request;
  if (!requests_.try_pop(request)) {
    return;
  }
  staged_parent_id_ = next_parent_id_;
  staged_input_ = request;
  staged_new_bursts_ = split_request(staged_parent_id_, request);
}

void AxiMaster::evaluate_address_channel() {
  const std::size_t free_slots = config_.max_outstanding_bursts > active_bursts_.size()
      ? config_.max_outstanding_bursts - active_bursts_.size()
      : 0;
  const std::size_t count = std::min(
      {config_.address_accepts_per_cycle, free_slots, pending_address_.size()});
  for (std::size_t index = 0; index < count; ++index) {
    staged_address_bursts_.push_back(pending_address_[index].burst_id);
  }
}

void AxiMaster::evaluate_data_channel() {
  if (active_bursts_.empty()) {
    return;
  }
  std::unordered_map<std::uint64_t, std::size_t> additional_issued;
  std::size_t inspected_without_issue = 0;
  std::size_t cursor = issue_round_robin_ % active_bursts_.size();
  while (staged_beats_.size() < config_.beat_issues_per_cycle &&
         inspected_without_issue < active_bursts_.size()) {
    const Burst& burst = active_bursts_[cursor];
    const std::size_t extra = additional_issued[burst.burst_id];
    if (burst.beats_issued + extra < burst.beats_total) {
      const std::uint64_t beat_address =
          burst.address + static_cast<std::uint64_t>(burst.beats_issued + extra) *
                              config_.data_width_bytes;
      const std::uint64_t consumed =
          static_cast<std::uint64_t>(burst.beats_issued + extra) *
          config_.data_width_bytes;
      const auto beat_bytes = static_cast<std::uint32_t>(
          std::min<std::uint64_t>(config_.data_width_bytes, burst.bytes - consumed));
      BackendRequest request{
          .initiator_id = config_.initiator_id,
          .request_id = next_backend_id_ + staged_beats_.size(),
          .channel = channel_for(beat_address),
          .operation = burst.operation,
          .address = beat_address,
          .bytes = beat_bytes,
      };
      if (backend_.try_submit(request)) {
        staged_beats_.push_back(StagedBeat{
            .burst_id = burst.burst_id,
            .request = request,
        });
        ++additional_issued[burst.burst_id];
        inspected_without_issue = 0;
      } else {
        ++stats_.backend_submit_stalls;
        ++inspected_without_issue;
      }
    } else {
      ++inspected_without_issue;
    }
    cursor = (cursor + 1) % active_bursts_.size();
  }
}

void AxiMaster::evaluate(const CycleContext&) {
  reset_staging();
  evaluate_output();
  evaluate_backend_responses();
  evaluate_request_input();
  evaluate_address_channel();
  evaluate_data_channel();
}

void AxiMaster::commit_backend_responses() {
  for (const BackendResponse& response : staged_backend_responses_) {
    if (response.initiator_id != config_.initiator_id) {
      throw std::logic_error("AXI received a response for another initiator");
    }
    const auto mapping = backend_to_burst_.find(response.request_id);
    if (mapping == backend_to_burst_.end()) {
      throw std::logic_error("AXI received a response for an unknown backend request");
    }
    Burst* burst = find_active(mapping->second);
    if (burst == nullptr) {
      throw std::logic_error("AXI response references a non-active burst");
    }
    ++burst->beats_completed;
    ++stats_.beats_completed;
    Parent& parent = parents_.at(burst->parent_id);
    parent.success = parent.success && response.success;
    backend_to_burst_.erase(mapping);
  }

  for (auto iterator = active_bursts_.begin(); iterator != active_bursts_.end();) {
    if (iterator->beats_completed != iterator->beats_total) {
      ++iterator;
      continue;
    }
    Parent& parent = parents_.at(iterator->parent_id);
    ++parent.completed_bursts;
    if (parent.completed_bursts == parent.total_bursts) {
      ready_responses_.push_back(ReadyResponse{
          .parent_id = iterator->parent_id,
          .response = AxiResponse{
              .transaction_id = parent.request.transaction_id,
              .operation = parent.request.operation,
              .success = parent.success,
          },
      });
    }
    iterator = active_bursts_.erase(iterator);
  }
}

void AxiMaster::commit_request_input() {
  if (!staged_input_.has_value()) {
    return;
  }
  parents_.emplace(
      staged_parent_id_,
      Parent{
          .request = *staged_input_,
          .total_bursts = staged_new_bursts_.size(),
          .completed_bursts = 0,
          .success = true,
      });
  for (const Burst& burst : staged_new_bursts_) {
    pending_address_.push_back(burst);
  }
  next_burst_id_ += staged_new_bursts_.size();
  ++next_parent_id_;
  ++stats_.requests_accepted;
}

void AxiMaster::commit_address_channel() {
  for (std::uint64_t burst_id : staged_address_bursts_) {
    if (pending_address_.empty() || pending_address_.front().burst_id != burst_id) {
      throw std::logic_error("AXI pending address queue changed before commit");
    }
    active_bursts_.push_back(pending_address_.front());
    pending_address_.pop_front();
    ++stats_.bursts_accepted;
  }
  stats_.max_outstanding_bursts =
      std::max(stats_.max_outstanding_bursts, active_bursts_.size());
}

void AxiMaster::commit_data_channel() {
  for (const StagedBeat& staged : staged_beats_) {
    Burst* burst = find_active(staged.burst_id);
    if (burst == nullptr) {
      throw std::logic_error("AXI staged beat references a non-active burst");
    }
    ++burst->beats_issued;
    backend_to_burst_.emplace(staged.request.request_id, staged.burst_id);
    ++stats_.beats_issued;
    if (staged.request.operation == MemoryOperation::kRead) {
      stats_.read_bytes += staged.request.bytes;
    } else {
      stats_.write_bytes += staged.request.bytes;
    }
  }
  next_backend_id_ += staged_beats_.size();
  if (!active_bursts_.empty()) {
    issue_round_robin_ = (issue_round_robin_ + 1) % active_bursts_.size();
  } else {
    issue_round_robin_ = 0;
  }
}

void AxiMaster::commit_output() {
  if (!staged_output_) {
    return;
  }
  const ReadyResponse response = ready_responses_.front();
  ready_responses_.pop_front();
  const auto parent = parents_.find(response.parent_id);
  if (parent == parents_.end()) {
    throw std::logic_error("AXI completed response has no parent request");
  }
  parents_.erase(parent);
  ++stats_.requests_completed;
}

void AxiMaster::commit(const CycleContext&) {
  commit_output();
  commit_backend_responses();
  commit_request_input();
  commit_address_channel();
  commit_data_channel();
}

}  // namespace spine::sim
