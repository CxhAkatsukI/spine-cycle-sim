#include "spine_sim/axi.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace spine::sim {

namespace {
constexpr std::uint64_t kAxiBoundaryBytes = 4096;
}

void accumulate_axi_stats(AxiStats &total, const AxiStats &sample) noexcept {
  total.requests_accepted += sample.requests_accepted;
  total.requests_completed += sample.requests_completed;
  total.request_queue_stalls += sample.request_queue_stalls;
  total.response_queue_stalls += sample.response_queue_stalls;
  total.read_beat_queue_stalls += sample.read_beat_queue_stalls;
  total.read_reorder_stalls += sample.read_reorder_stalls;
  total.read_data_pipeline_stalls += sample.read_data_pipeline_stalls;
  total.read_beats_streamed += sample.read_beats_streamed;
  total.bursts_accepted += sample.bursts_accepted;
  total.beats_issued += sample.beats_issued;
  total.beats_completed += sample.beats_completed;
  total.backend_submit_stalls += sample.backend_submit_stalls;
  total.address_pipeline_stalls += sample.address_pipeline_stalls;
  total.write_burst_serialization_stalls +=
      sample.write_burst_serialization_stalls;
  total.read_address_channel_stalls += sample.read_address_channel_stalls;
  total.write_address_channel_stalls += sample.write_address_channel_stalls;
  total.write_data_channel_stalls += sample.write_data_channel_stalls;
  total.read_response_channel_stalls += sample.read_response_channel_stalls;
  total.write_response_channel_stalls += sample.write_response_channel_stalls;
  total.four_kib_splits += sample.four_kib_splits;
  total.read_bytes += sample.read_bytes;
  total.write_bytes += sample.write_bytes;
  total.zero_filled_write_bytes += sample.zero_filled_write_bytes;
  total.max_outstanding_bursts =
      std::max(total.max_outstanding_bursts,
               sample.max_outstanding_bursts);
  total.burst_trace_dropped += sample.burst_trace_dropped;
  total.beat_trace_dropped += sample.beat_trace_dropped;
}

AxiMaster::AxiMaster(std::string name, ClockId clock_id, AxiConfig config,
                     Fifo<AxiRequest> &requests, Fifo<AxiResponse> &responses,
                     MemoryBackend &backend,
                     Fifo<AxiReadBeatResponse> *read_beats)
    : Component(std::move(name), clock_id), config_(config),
      requests_(requests), responses_(responses), backend_(backend),
      read_beats_(read_beats) {
  if (config_.data_width_bytes == 0 || config_.max_burst_beats == 0 ||
      config_.channels == 0 || config_.channel_interleave_bytes == 0 ||
      config_.max_pending_requests == 0 ||
      config_.max_outstanding_bursts == 0 ||
      config_.address_accepts_per_cycle == 0 ||
      config_.beat_issues_per_cycle == 0 ||
      config_.response_beats_per_cycle == 0 ||
      config_.read_reorder_capacity == 0 ||
      !config_.read_address_stall.valid() ||
      !config_.write_address_stall.valid() ||
      !config_.write_data_stall.valid() ||
      !config_.read_response_stall.valid() ||
      !config_.write_response_stall.valid()) {
    throw std::invalid_argument("AXI configuration values must be positive");
  }
  if (config_.fixed_channel.has_value() &&
      *config_.fixed_channel >= config_.channels) {
    throw std::invalid_argument("AXI fixed channel is outside memory geometry");
  }
  if (requests_.clock_id() != clock_id || responses_.clock_id() != clock_id ||
      backend_.clock_id() != clock_id ||
      (read_beats_ != nullptr && read_beats_->clock_id() != clock_id)) {
    throw std::invalid_argument(
        "AXI master, links, and backend must share a clock");
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
    std::uint64_t parent_id, const AxiRequest &request,
    std::uint64_t accepted_cycle) {
  if (request.bytes == 0) {
    throw std::invalid_argument("AXI request byte count must be positive");
  }
  std::vector<Burst> bursts;
  std::uint64_t address = request.address;
  std::uint64_t remaining = request.bytes;
  std::uint64_t parent_offset = 0;
  const std::uint64_t max_burst_bytes =
      static_cast<std::uint64_t>(config_.data_width_bytes) * config_.max_burst_beats;
  while (remaining != 0) {
    const std::uint64_t boundary_remaining =
        kAxiBoundaryBytes - (address % kAxiBoundaryBytes);
    const std::uint64_t bytes = std::min({remaining, max_burst_bytes,
                                          boundary_remaining});
    const std::size_t beats = static_cast<std::size_t>(
        (bytes + config_.data_width_bytes - 1) / config_.data_width_bytes);
    const std::uint64_t cumulative_beats =
        (parent_offset + bytes + config_.data_width_bytes - 1) /
        config_.data_width_bytes;
    const std::uint64_t address_ready_cycle =
        accepted_cycle +
        (request.operation == MemoryOperation::kRead
             ? config_.read_address_pipeline_cycles
             : (config_.write_buffer_pipeline_cycles == 0
                    ? 0
                    : config_.write_buffer_pipeline_cycles +
                          cumulative_beats));
    bursts.push_back(Burst{
        .burst_id = next_burst_id_ + bursts.size(),
        .parent_id = parent_id,
        .operation = request.operation,
        .address = address,
        .bytes = bytes,
        .parent_offset = parent_offset,
        .beats_total = beats,
        .beats_issued = 0,
        .beats_completed = 0,
        .parent_accept_cycle = accepted_cycle,
        .address_ready_cycle = address_ready_cycle,
    });
    if (bytes == boundary_remaining && remaining > bytes) {
      ++stats_.four_kib_splits;
    }
    address += bytes;
    parent_offset += bytes;
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
  staged_read_beat_output_.reset();
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

std::size_t AxiMaster::read_reorder_occupancy() const noexcept {
  std::size_t occupancy = 0;
  for (const auto &[parent_id, parent] : parents_) {
    (void)parent_id;
    occupancy += parent.ready_stream_beats.size();
  }
  return occupancy;
}

void AxiMaster::evaluate_read_beat_output(const CycleContext &context) {
  if (read_beats_ == nullptr) {
    return;
  }
  std::uint64_t selected_parent = std::numeric_limits<std::uint64_t>::max();
  const TimedReadBeat *selected = nullptr;
  for (const auto &[parent_id, parent] : parents_) {
    if (!parent.request.stream_read_beats || parent_id >= selected_parent) {
      continue;
    }
    const auto found =
        parent.ready_stream_beats.find(parent.next_stream_offset);
    if (found != parent.ready_stream_beats.end()) {
      selected_parent = parent_id;
      selected = &found->second;
    }
  }
  if (selected == nullptr) {
    return;
  }
  if (context.domain_cycle < selected->ready_cycle) {
    ++stats_.read_data_pipeline_stalls;
    return;
  }
  if (!read_beats_->try_push(selected->response)) {
    ++stats_.read_beat_queue_stalls;
    return;
  }
  staged_read_beat_output_ =
      std::pair(selected_parent, selected->response.parent_offset);
}

void AxiMaster::evaluate_backend_responses(const CycleContext &context) {
  const std::size_t available =
      std::min(config_.response_beats_per_cycle,
               backend_.response_count(config_.initiator_id));
  if (available == 0) {
    return;
  }
  staged_backend_responses_.reserve(available);
  std::size_t staged_stream_beats = 0;
  for (std::size_t index = 0; index < available; ++index) {
    const BackendResponse &response =
        backend_.response_at(config_.initiator_id, index);
    const auto mapping = backend_mappings_.find(response.request_id);
    if (mapping == backend_mappings_.end()) {
      throw std::logic_error(
          "AXI backend response has no request mapping during evaluate");
    }
    Burst *burst = find_active(mapping->second.burst_id);
    if (burst == nullptr) {
      throw std::logic_error(
          "AXI backend response references no active burst during evaluate");
    }
    const AxiPeriodicStall &response_stall =
        burst->operation == MemoryOperation::kRead
            ? config_.read_response_stall
            : config_.write_response_stall;
    if (response_stall.stalled(context.domain_cycle)) {
      if (burst->operation == MemoryOperation::kRead) {
        ++stats_.read_response_channel_stalls;
      } else {
        ++stats_.write_response_channel_stalls;
      }
      break;
    }
    const Parent &parent = parents_.at(burst->parent_id);
    if (burst->operation == MemoryOperation::kRead &&
        parent.request.stream_read_beats) {
      if (read_beats_ == nullptr) {
        throw std::logic_error(
            "AXI request enabled beat streaming without a beat output");
      }
      if (read_reorder_occupancy() + staged_stream_beats >=
          config_.read_reorder_capacity) {
        ++stats_.read_reorder_stalls;
        break;
      }
      ++staged_stream_beats;
    }
    staged_backend_responses_.push_back(response);
  }
  if (staged_backend_responses_.empty()) {
    return;
  }
  if (!backend_.stage_pop_responses(config_.initiator_id,
                                    staged_backend_responses_.size())) {
    throw std::logic_error("memory backend rejected a valid response pop");
  }
}

void AxiMaster::evaluate_request_input(const CycleContext &context) {
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
  staged_new_bursts_ =
      split_request(staged_parent_id_, request, context.domain_cycle);
}

void AxiMaster::evaluate_address_channel(const CycleContext &context) {
  const std::size_t free_slots = config_.max_outstanding_bursts > active_bursts_.size()
      ? config_.max_outstanding_bursts - active_bursts_.size()
      : 0;
  const std::size_t candidate_count = std::min(
      {config_.address_accepts_per_cycle, free_slots, pending_address_.size()});
  bool serialized_write_staged = false;
  for (std::size_t index = 0; index < candidate_count; ++index) {
    const Burst &candidate = pending_address_[index];
    if (context.domain_cycle < candidate.address_ready_cycle) {
      ++stats_.address_pipeline_stalls;
      break;
    }
    if (config_.serialize_write_bursts &&
        candidate.operation == MemoryOperation::kWrite) {
      const bool write_data_active = std::any_of(
          active_bursts_.begin(), active_bursts_.end(),
          [](const Burst &burst) {
            return burst.operation == MemoryOperation::kWrite &&
                   burst.beats_issued < burst.beats_total;
          });
      if (write_data_active || serialized_write_staged) {
        ++stats_.write_burst_serialization_stalls;
        break;
      }
    }
    const AxiPeriodicStall &address_stall =
        candidate.operation == MemoryOperation::kRead
            ? config_.read_address_stall
            : config_.write_address_stall;
    if (address_stall.stalled(context.domain_cycle)) {
      if (candidate.operation == MemoryOperation::kRead) {
        ++stats_.read_address_channel_stalls;
      } else {
        ++stats_.write_address_channel_stalls;
      }
      break;
    }
    staged_address_bursts_.push_back(pending_address_[index].burst_id);
    serialized_write_staged =
        serialized_write_staged ||
        (config_.serialize_write_bursts &&
         candidate.operation == MemoryOperation::kWrite);
  }
}

void AxiMaster::evaluate_data_channel(const CycleContext &context) {
  if (active_bursts_.empty()) {
    return;
  }
  std::unordered_map<std::uint64_t, std::size_t> additional_issued;
  std::size_t inspected_without_issue = 0;
  const bool ordered_stream = std::any_of(
      active_bursts_.begin(), active_bursts_.end(), [this](const Burst &burst) {
        return parents_.at(burst.parent_id).request.stream_read_beats;
      });
  std::size_t cursor = issue_round_robin_ % active_bursts_.size();
  while (staged_beats_.size() < config_.beat_issues_per_cycle &&
         inspected_without_issue < active_bursts_.size()) {
    if (ordered_stream) {
      std::size_t selected = active_bursts_.size();
      std::pair<std::uint64_t, std::uint64_t> selected_key{
          std::numeric_limits<std::uint64_t>::max(),
          std::numeric_limits<std::uint64_t>::max()};
      for (std::size_t index = 0; index < active_bursts_.size(); ++index) {
        const Burst &candidate = active_bursts_[index];
        const Parent &candidate_parent = parents_.at(candidate.parent_id);
        const std::size_t extra = additional_issued[candidate.burst_id];
        if (!candidate_parent.request.stream_read_beats ||
            candidate.beats_issued + extra >= candidate.beats_total) {
          continue;
        }
        const auto key = std::pair(
            candidate.parent_id,
            candidate.parent_offset +
                static_cast<std::uint64_t>(candidate.beats_issued + extra) *
                    config_.data_width_bytes);
        if (key < selected_key) {
          selected = index;
          selected_key = key;
        }
      }
      if (selected == active_bursts_.size()) {
        break;
      }
      cursor = selected;
    }
    const Burst &burst = active_bursts_[cursor];
    const std::size_t extra = additional_issued[burst.burst_id];
    if (burst.beats_issued + extra < burst.beats_total) {
      if (burst.operation == MemoryOperation::kWrite &&
          config_.write_data_stall.stalled(context.domain_cycle)) {
        ++stats_.write_data_channel_stalls;
        break;
      }
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
          .write_data = {},
      };
      const Parent& parent = parents_.at(burst.parent_id);
      const std::uint64_t parent_offset =
          burst.parent_offset +
          static_cast<std::uint64_t>(burst.beats_issued + extra) *
              config_.data_width_bytes;
      if (burst.operation == MemoryOperation::kWrite) {
        if (parent.request.write_data.empty()) {
          request.write_data.assign(beat_bytes, 0);
        } else {
          const auto begin = parent.request.write_data.begin() +
                             static_cast<std::ptrdiff_t>(parent_offset);
          request.write_data.assign(begin, begin + beat_bytes);
        }
      }
      if (backend_.try_submit(request)) {
        staged_beats_.push_back(StagedBeat{
            .burst_id = burst.burst_id,
            .parent_offset = parent_offset,
            .issue_cycle = context.domain_cycle,
            .request = request,
        });
        ++additional_issued[burst.burst_id];
        inspected_without_issue = 0;
      } else {
        ++stats_.backend_submit_stalls;
        if (ordered_stream) {
          break;
        }
        ++inspected_without_issue;
      }
    } else {
      ++inspected_without_issue;
    }
    if (!ordered_stream) {
      cursor = (cursor + 1) % active_bursts_.size();
    }
  }
}

void AxiMaster::evaluate(const CycleContext &context) {
  reset_staging();
  evaluate_output();
  evaluate_read_beat_output(context);
  evaluate_backend_responses(context);
  evaluate_request_input(context);
  evaluate_address_channel(context);
  evaluate_data_channel(context);
}

void AxiMaster::commit_backend_responses(const CycleContext &context) {
  for (const BackendResponse& response : staged_backend_responses_) {
    if (response.initiator_id != config_.initiator_id) {
      throw std::logic_error("AXI received a response for another initiator");
    }
    const auto mapping = backend_mappings_.find(response.request_id);
    if (mapping == backend_mappings_.end()) {
      throw std::logic_error("AXI received a response for an unknown backend request");
    }
    Burst* burst = find_active(mapping->second.burst_id);
    if (burst == nullptr) {
      throw std::logic_error("AXI response references a non-active burst");
    }
    ++burst->beats_completed;
    ++stats_.beats_completed;
    Parent& parent = parents_.at(burst->parent_id);
    parent.success = parent.success && response.success;
    if (burst->operation == MemoryOperation::kRead) {
      if (response.read_data.size() != mapping->second.bytes ||
          mapping->second.parent_offset + response.read_data.size() >
              parent.read_data.size()) {
        throw std::logic_error("AXI read response payload shape mismatch");
      }
      std::copy(response.read_data.begin(), response.read_data.end(),
                parent.read_data.begin() +
                    static_cast<std::ptrdiff_t>(mapping->second.parent_offset));
      if (parent.request.stream_read_beats) {
        AxiReadBeatResponse beat{
            .transaction_id = parent.request.transaction_id,
            .address = parent.request.address + mapping->second.parent_offset,
            .parent_offset = mapping->second.parent_offset,
            .success = response.success,
            .last = mapping->second.parent_offset + mapping->second.bytes ==
                    parent.request.bytes,
            .read_data = response.read_data,
        };
        if (!parent.ready_stream_beats
                 .emplace(mapping->second.parent_offset,
                          TimedReadBeat{
                              .response = std::move(beat),
                              .ready_cycle = context.domain_cycle + 1 +
                                  config_.read_data_pipeline_cycles,
                          })
                 .second) {
          throw std::logic_error("AXI received a duplicate streamed read beat");
        }
      }
    } else if (!response.read_data.empty()) {
      throw std::logic_error("AXI write response unexpectedly carried data");
    }
    if (mapping->second.trace_index.has_value()) {
      AxiBeatTrace &trace = beat_trace_.at(*mapping->second.trace_index);
      if (trace.completion_cycle != 0) {
        throw std::logic_error("AXI beat trace completed more than once");
      }
      trace.completion_cycle = context.domain_cycle;
    }
    backend_mappings_.erase(mapping);
  }
  for (auto iterator = active_bursts_.begin();
       iterator != active_bursts_.end();) {
    if (iterator->beats_completed != iterator->beats_total) {
      ++iterator;
      continue;
    }
    Parent& parent = parents_.at(iterator->parent_id);
    ++parent.completed_bursts;
    if (parent.completed_bursts == parent.total_bursts) {
      parent.memory_complete = true;
      queue_parent_response_if_ready(iterator->parent_id);
    }
    iterator = active_bursts_.erase(iterator);
  }
}

void AxiMaster::commit_request_input() {
  if (!staged_input_.has_value()) {
    return;
  }
  if (staged_input_->operation == MemoryOperation::kRead &&
      !staged_input_->write_data.empty()) {
    throw std::invalid_argument("AXI read request cannot carry write data");
  }
  if (staged_input_->stream_read_beats &&
      (staged_input_->operation != MemoryOperation::kRead ||
       read_beats_ == nullptr)) {
    throw std::invalid_argument(
        "AXI beat streaming requires a read request and beat output");
  }
  if (staged_input_->operation == MemoryOperation::kWrite &&
      !staged_input_->write_data.empty() &&
      staged_input_->write_data.size() != staged_input_->bytes) {
    throw std::invalid_argument("AXI write payload size must match byte count");
  }
  std::size_t stream_beats_expected = 0;
  if (staged_input_->stream_read_beats) {
    for (const Burst &burst : staged_new_bursts_) {
      stream_beats_expected += burst.beats_total;
    }
  }
  parents_.emplace(
      staged_parent_id_,
      Parent{
          .request = *staged_input_,
          .total_bursts = staged_new_bursts_.size(),
          .completed_bursts = 0,
          .success = true,
          .read_data = staged_input_->operation == MemoryOperation::kRead
                           ? std::vector<std::uint8_t>(staged_input_->bytes, 0)
                           : std::vector<std::uint8_t>{},
          .stream_beats_expected = stream_beats_expected,
          .stream_beats_published = 0,
          .next_stream_offset = 0,
          .ready_stream_beats = {},
          .memory_complete = false,
          .response_queued = false,
      });
  for (const Burst& burst : staged_new_bursts_) {
    pending_address_.push_back(burst);
  }
  next_burst_id_ += staged_new_bursts_.size();
  ++next_parent_id_;
  ++stats_.requests_accepted;
}

void AxiMaster::commit_address_channel(const CycleContext &context) {
  for (std::uint64_t burst_id : staged_address_bursts_) {
    if (pending_address_.empty() || pending_address_.front().burst_id != burst_id) {
      throw std::logic_error("AXI pending address queue changed before commit");
    }
    const Burst &burst = pending_address_.front();
    if (config_.burst_trace_limit != 0) {
      if (burst_trace_.size() < config_.burst_trace_limit) {
        burst_trace_.push_back(AxiBurstTrace{
            .transaction_id = parents_.at(burst.parent_id)
                                  .request.transaction_id,
            .operation = burst.operation,
            .address = burst.address,
            .bytes = burst.bytes,
            .beats = burst.beats_total,
            .parent_accept_cycle = burst.parent_accept_cycle,
            .address_issue_cycle = context.domain_cycle,
        });
      } else {
        ++stats_.burst_trace_dropped;
      }
    }
    active_bursts_.push_back(burst);
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
    std::optional<std::size_t> trace_index;
    if (config_.beat_trace_limit != 0) {
      if (beat_trace_.size() < config_.beat_trace_limit) {
        trace_index = beat_trace_.size();
        const Burst &accepted_burst = *burst;
        beat_trace_.push_back(AxiBeatTrace{
            .backend_request_id = staged.request.request_id,
            .transaction_id =
                parents_.at(accepted_burst.parent_id).request.transaction_id,
            .operation = staged.request.operation,
            .address = staged.request.address,
            .bytes = staged.request.bytes,
            .issue_cycle = staged.issue_cycle,
            .completion_cycle = 0,
        });
      } else {
        ++stats_.beat_trace_dropped;
      }
    }
    backend_mappings_.emplace(
        staged.request.request_id,
        BackendMapping{
            .burst_id = staged.burst_id,
            .parent_offset = staged.parent_offset,
            .bytes = staged.request.bytes,
            .trace_index = trace_index,
        });
    ++stats_.beats_issued;
    if (staged.request.operation == MemoryOperation::kRead) {
      stats_.read_bytes += staged.request.bytes;
    } else {
      stats_.write_bytes += staged.request.bytes;
      if (parents_.at(burst->parent_id).request.write_data.empty()) {
        stats_.zero_filled_write_bytes += staged.request.bytes;
      }
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

void AxiMaster::queue_parent_response_if_ready(std::uint64_t parent_id) {
  Parent &parent = parents_.at(parent_id);
  if (parent.response_queued || !parent.memory_complete ||
      (parent.request.stream_read_beats &&
       parent.stream_beats_published != parent.stream_beats_expected)) {
    return;
  }
  parent.response_queued = true;
  ready_responses_.push_back(ReadyResponse{
      .parent_id = parent_id,
      .response =
          AxiResponse{
              .transaction_id = parent.request.transaction_id,
              .operation = parent.request.operation,
              .success = parent.success,
              .read_data = std::move(parent.read_data),
          },
  });
}

void AxiMaster::commit_read_beat_output() {
  if (!staged_read_beat_output_.has_value()) {
    return;
  }
  const auto [parent_id, offset] = *staged_read_beat_output_;
  Parent &parent = parents_.at(parent_id);
  const auto beat = parent.ready_stream_beats.find(offset);
  if (beat == parent.ready_stream_beats.end() ||
      offset != parent.next_stream_offset) {
    throw std::logic_error("AXI streamed read beat changed before commit");
  }
  parent.next_stream_offset += beat->second.response.read_data.size();
  parent.ready_stream_beats.erase(beat);
  ++parent.stream_beats_published;
  ++stats_.read_beats_streamed;
  queue_parent_response_if_ready(parent_id);
}

void AxiMaster::commit(const CycleContext &context) {
  commit_output();
  commit_backend_responses(context);
  commit_request_input();
  commit_address_channel(context);
  commit_data_channel();
  commit_read_beat_output();
}

}  // namespace spine::sim
