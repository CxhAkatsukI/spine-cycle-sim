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
  total.write_child_beats_accepted += sample.write_child_beats_accepted;
  total.write_child_data_stalls += sample.write_child_data_stalls;
  total.write_store_to_bridge_beats += sample.write_store_to_bridge_beats;
  total.write_bridge_to_throttle_beats +=
      sample.write_bridge_to_throttle_beats;
  total.write_throttle_data_stalls += sample.write_throttle_data_stalls;
  total.four_kib_splits += sample.four_kib_splits;
  total.read_bytes += sample.read_bytes;
  total.write_bytes += sample.write_bytes;
  total.zero_filled_write_bytes += sample.zero_filled_write_bytes;
  total.max_outstanding_bursts =
      std::max(total.max_outstanding_bursts,
               sample.max_outstanding_bursts);
  total.max_write_store_occupancy =
      std::max(total.max_write_store_occupancy,
               sample.max_write_store_occupancy);
  total.max_write_throttle_occupancy =
      std::max(total.max_write_throttle_occupancy,
               sample.max_write_throttle_occupancy);
  total.burst_trace_dropped += sample.burst_trace_dropped;
  total.beat_trace_dropped += sample.beat_trace_dropped;
  total.write_ingress_trace_dropped += sample.write_ingress_trace_dropped;
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
      !config_.write_response_stall.valid() ||
      (config_.write_ingress_fifo_depth != 0 &&
       config_.write_throttle_fifo_depth == 0) ||
      (config_.write_ingress_fifo_depth == 0 &&
       (config_.write_throttle_fifo_depth != 0 ||
        config_.write_ingress_pipeline_cycles != 0 ||
        config_.write_address_after_full_burst_cycles != 0))) {
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
  requests_.bind_nonempty_notifier(this, &AxiMaster::notify_request_nonempty);
  refresh_pending_work();
}

AxiMaster::~AxiMaster() { requests_.unbind_nonempty_notifier(this); }

void AxiMaster::notify_request_nonempty(void* owner) noexcept {
  AxiMaster *master = static_cast<AxiMaster*>(owner);
  master->scheduler_ready_ = true;
  master->set_latched_evaluate_ready(true);
}

std::size_t AxiMaster::pending_requests() const noexcept {
  return parents_.size() + (staged_input_.has_value() ? 1 : 0);
}

bool AxiMaster::idle() const noexcept {
  return parents_.empty() && pending_address_.empty() && active_bursts_.empty() &&
      ready_responses_.empty() && pending_write_input_.empty() &&
      write_store_fifo_.empty() && !write_bridge_.has_value() &&
      write_throttle_fifo_.empty() &&
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
        request.operation == MemoryOperation::kRead
            ? accepted_cycle + config_.read_address_pipeline_cycles
            : (write_ingress_enabled()
                   ? std::numeric_limits<std::uint64_t>::max() - 1
                   : accepted_cycle +
                         (config_.write_buffer_pipeline_cycles == 0
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
  staged_new_write_beats_.clear();
  staged_child_write_beat_.reset();
  staged_store_to_bridge_.reset();
  staged_bridge_to_throttle_.reset();
  staged_address_bursts_.clear();
  staged_beats_.clear();
  staged_backend_response_count_ = 0;
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
    ++staged_backend_response_count_;
  }
  if (staged_backend_response_count_ == 0) {
    return;
  }
  if (!backend_.stage_pop_responses(config_.initiator_id,
                                    staged_backend_response_count_)) {
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
  if (write_ingress_enabled() &&
      request.operation == MemoryOperation::kWrite) {
    if (context.domain_cycle >
        std::numeric_limits<std::uint64_t>::max() -
            config_.write_ingress_pipeline_cycles) {
      throw std::overflow_error("AXI write ingress cycle overflow");
    }
    const std::uint64_t ready_cycle =
        context.domain_cycle + config_.write_ingress_pipeline_cycles;
    for (const Burst &burst : staged_new_bursts_) {
      for (std::size_t beat = 0; beat < burst.beats_total; ++beat) {
        staged_new_write_beats_.push_back(WriteIngressBeat{
            .burst_id = burst.burst_id,
            .last = beat + 1 == burst.beats_total,
            .store_ready_cycle = ready_cycle,
        });
      }
    }
  }
}

void AxiMaster::evaluate_write_ingress(const CycleContext &context) {
  if (!write_ingress_enabled()) {
    return;
  }

  if (!pending_write_input_.empty()) {
    if (write_store_fifo_.size() < config_.write_ingress_fifo_depth) {
      staged_child_write_beat_ = pending_write_input_.front();
    } else {
      ++stats_.write_child_data_stalls;
    }
  } else if (!staged_new_write_beats_.empty()) {
    if (write_store_fifo_.size() < config_.write_ingress_fifo_depth) {
      staged_child_write_beat_ = staged_new_write_beats_.front();
    } else {
      ++stats_.write_child_data_stalls;
    }
  }

  const bool bridge_can_advance =
      write_bridge_.has_value() &&
      write_throttle_fifo_.size() < config_.write_throttle_fifo_depth;
  if (bridge_can_advance) {
    staged_bridge_to_throttle_ = *write_bridge_;
  }
  if (!write_store_fifo_.empty() &&
      context.domain_cycle >= write_store_fifo_.front().store_ready_cycle &&
      (!write_bridge_.has_value() || bridge_can_advance)) {
    staged_store_to_bridge_ = write_store_fifo_.front();
  }
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
      if (active_write_data_bursts_ != 0 || serialized_write_staged) {
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
  if (active_issueable_bursts_ == 0) {
    return;
  }
  staged_additional_issued_.assign(active_bursts_.size(), 0);
  std::size_t staged_fully_issued = 0;
  std::size_t inspected_without_issue = 0;
  const bool ordered_stream = active_stream_bursts_ != 0;
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
        const std::size_t extra = staged_additional_issued_[index];
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
    const std::size_t extra = staged_additional_issued_[cursor];
    if (burst.beats_issued + extra < burst.beats_total) {
      if (burst.operation == MemoryOperation::kWrite &&
          write_ingress_enabled() &&
          (write_throttle_fifo_.empty() ||
           write_throttle_fifo_.front().burst_id != burst.burst_id)) {
        ++stats_.write_throttle_data_stalls;
        ++inspected_without_issue;
        cursor = (cursor + 1) % active_bursts_.size();
        continue;
      }
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
      const BackendRequestHeader header{
          .initiator_id = config_.initiator_id,
          .request_id = next_backend_id_ + staged_beats_.size(),
          .channel = channel_for(beat_address),
          .operation = burst.operation,
          .address = beat_address,
          .bytes = beat_bytes,
      };
      const Parent& parent = parents_.at(burst.parent_id);
      const std::uint64_t parent_offset =
          burst.parent_offset +
          static_cast<std::uint64_t>(burst.beats_issued + extra) *
              config_.data_width_bytes;
      if (backend_.try_reserve(header)) {
        BackendRequest request{
            .initiator_id = header.initiator_id,
            .request_id = header.request_id,
            .channel = header.channel,
            .operation = header.operation,
            .address = header.address,
            .bytes = header.bytes,
            .write_data = {},
        };
        if (burst.operation == MemoryOperation::kWrite) {
          if (parent.request.write_data.empty()) {
            request.write_data.assign(beat_bytes, 0);
          } else {
            const auto begin = parent.request.write_data.begin() +
                               static_cast<std::ptrdiff_t>(parent_offset);
            request.write_data.assign(begin, begin + beat_bytes);
          }
        }
        backend_.submit_reserved(std::move(request));
        staged_beats_.push_back(StagedBeat{
            .burst_id = burst.burst_id,
            .parent_offset = parent_offset,
            .issue_cycle = context.domain_cycle,
            .request = header,
        });
        ++staged_additional_issued_[cursor];
        staged_fully_issued +=
            burst.beats_issued + staged_additional_issued_[cursor] ==
                    burst.beats_total
                ? 1
                : 0;
        inspected_without_issue = 0;
      } else {
        ++stats_.backend_submit_stalls;
        if (ordered_stream) {
          break;
        }
        ++inspected_without_issue;
        if (config_.fixed_channel.has_value() &&
            backend_.reservation_intent_pending(config_.initiator_id,
                                                header.channel)) {
          if (active_write_data_bursts_ == 0) {
            if (active_issueable_bursts_ <= staged_fully_issued) {
              throw std::logic_error(
                  "AXI issueable read burst count underflow");
            }
            const std::uint64_t coalesced_stalls =
                active_issueable_bursts_ - staged_fully_issued - 1;
            stats_.backend_submit_stalls += coalesced_stalls;
            backend_.account_same_cycle_reservation_stalls(
                config_.initiator_id, header.channel, coalesced_stalls);
            break;
          }
          std::uint64_t coalesced_stalls = 0;
          cursor = (cursor + 1) % active_bursts_.size();
          while (inspected_without_issue < active_bursts_.size()) {
            const Burst &retry = active_bursts_[cursor];
            const std::size_t retry_extra = staged_additional_issued_[cursor];
            if (retry.beats_issued + retry_extra < retry.beats_total) {
              if (retry.operation == MemoryOperation::kWrite &&
                  write_ingress_enabled() &&
                  (write_throttle_fifo_.empty() ||
                   write_throttle_fifo_.front().burst_id != retry.burst_id)) {
                ++stats_.write_throttle_data_stalls;
              } else if (retry.operation == MemoryOperation::kWrite &&
                         config_.write_data_stall.stalled(
                             context.domain_cycle)) {
                ++stats_.write_data_channel_stalls;
                break;
              } else {
                ++stats_.backend_submit_stalls;
                ++coalesced_stalls;
              }
            }
            ++inspected_without_issue;
            cursor = (cursor + 1) % active_bursts_.size();
          }
          backend_.account_same_cycle_reservation_stalls(
              config_.initiator_id, header.channel, coalesced_stalls);
          break;
        }
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
  evaluate_write_ingress(context);
  evaluate_address_channel(context);
  evaluate_data_channel(context);
  set_latched_commit_ready(true);
}

void AxiMaster::commit_backend_responses(const CycleContext &context) {
  for (std::size_t index = 0; index < staged_backend_response_count_; ++index) {
    const BackendResponse& response =
        backend_.staged_response_at(config_.initiator_id, index);
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
    if (parent.request.stream_read_beats) {
      if (active_stream_bursts_ == 0) {
        throw std::logic_error("AXI active stream burst count underflow");
      }
      --active_stream_bursts_;
    }
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

void AxiMaster::record_write_ingress(AxiWriteIngressStage stage,
                                     const WriteIngressBeat &beat,
                                     std::uint64_t cycle) {
  if (config_.beat_trace_limit == 0) {
    return;
  }
  if (write_ingress_trace_.size() >= config_.beat_trace_limit * 3) {
    ++stats_.write_ingress_trace_dropped;
    return;
  }
  write_ingress_trace_.push_back(AxiWriteIngressTrace{
      .stage = stage,
      .burst_id = beat.burst_id,
      .last = beat.last,
      .cycle = cycle,
  });
}

void AxiMaster::commit_write_ingress(const CycleContext &context) {
  if (!write_ingress_enabled()) {
    return;
  }
  for (const WriteIngressBeat &beat : staged_new_write_beats_) {
    pending_write_input_.push_back(beat);
  }
  if (staged_child_write_beat_.has_value()) {
    if (pending_write_input_.empty() ||
        pending_write_input_.front().burst_id !=
            staged_child_write_beat_->burst_id ||
        pending_write_input_.front().last != staged_child_write_beat_->last) {
      throw std::logic_error("AXI child write stream changed before commit");
    }
    const WriteIngressBeat beat = pending_write_input_.front();
    pending_write_input_.pop_front();
    write_store_fifo_.push_back(beat);
    ++stats_.write_child_beats_accepted;
    record_write_ingress(AxiWriteIngressStage::kChildAccept, beat,
                         context.domain_cycle);
  }

  if (staged_bridge_to_throttle_.has_value()) {
    if (!write_bridge_.has_value() ||
        write_bridge_->burst_id != staged_bridge_to_throttle_->burst_id ||
        write_bridge_->last != staged_bridge_to_throttle_->last) {
      throw std::logic_error("AXI write bridge changed before commit");
    }
    const WriteIngressBeat beat = *write_bridge_;
    write_bridge_.reset();
    write_throttle_fifo_.push_back(beat);
    ++stats_.write_bridge_to_throttle_beats;
    record_write_ingress(AxiWriteIngressStage::kBridgeToThrottle, beat,
                         context.domain_cycle);
    if (beat.last) {
      const auto pending = std::find_if(
          pending_address_.begin(), pending_address_.end(),
          [&beat](const Burst &burst) { return burst.burst_id == beat.burst_id; });
      if (pending == pending_address_.end()) {
        throw std::logic_error(
            "AXI completed write burst has no pending address");
      }
      if (context.domain_cycle >
          std::numeric_limits<std::uint64_t>::max() -
              config_.write_address_after_full_burst_cycles) {
        throw std::overflow_error("AXI write address cycle overflow");
      }
      pending->address_ready_cycle =
          context.domain_cycle +
          config_.write_address_after_full_burst_cycles;
    }
  }
  if (staged_store_to_bridge_.has_value()) {
    if (write_store_fifo_.empty() ||
        write_store_fifo_.front().burst_id !=
            staged_store_to_bridge_->burst_id ||
        write_store_fifo_.front().last != staged_store_to_bridge_->last) {
      throw std::logic_error("AXI write store changed before commit");
    }
    const WriteIngressBeat beat = write_store_fifo_.front();
    write_store_fifo_.pop_front();
    if (write_bridge_.has_value()) {
      throw std::logic_error("AXI write bridge was not released before refill");
    }
    write_bridge_ = beat;
    ++stats_.write_store_to_bridge_beats;
    record_write_ingress(AxiWriteIngressStage::kStoreToBridge, beat,
                         context.domain_cycle);
  }
  stats_.max_write_store_occupancy =
      std::max(stats_.max_write_store_occupancy, write_store_fifo_.size());
  stats_.max_write_throttle_occupancy =
      std::max(stats_.max_write_throttle_occupancy,
               write_throttle_fifo_.size());
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
    ++active_issueable_bursts_;
    if (parents_.at(burst.parent_id).request.stream_read_beats) {
      ++active_stream_bursts_;
    }
    if (burst.operation == MemoryOperation::kWrite) {
      ++active_write_data_bursts_;
    }
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
    if (staged.request.operation == MemoryOperation::kWrite &&
        write_ingress_enabled()) {
      if (write_throttle_fifo_.empty() ||
          write_throttle_fifo_.front().burst_id != staged.burst_id) {
        throw std::logic_error(
            "AXI external write beat diverged from throttle FIFO");
      }
      write_throttle_fifo_.pop_front();
    }
    ++burst->beats_issued;
    if (burst->beats_issued == burst->beats_total) {
      if (active_issueable_bursts_ == 0) {
        throw std::logic_error("AXI issueable burst count underflow");
      }
      --active_issueable_bursts_;
      if (burst->operation == MemoryOperation::kWrite) {
        if (active_write_data_bursts_ == 0) {
          throw std::logic_error("AXI write-data burst count underflow");
        }
        --active_write_data_bursts_;
      }
    }
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

void AxiMaster::refresh_pending_work() noexcept {
  internal_pending_work_ =
      !parents_.empty() || !pending_address_.empty() ||
      !active_bursts_.empty() || !backend_mappings_.empty() ||
      !ready_responses_.empty() || !pending_write_input_.empty() ||
      !write_store_fifo_.empty() || write_bridge_.has_value() ||
      !write_throttle_fifo_.empty();
  scheduler_ready_ = !requests_.empty() || internal_pending_work_;
  set_latched_evaluate_ready(scheduler_ready_);
}

void AxiMaster::commit(const CycleContext &context) {
  const bool staged_state_change =
      staged_output_ || staged_backend_response_count_ != 0 ||
      staged_input_.has_value() || !staged_address_bursts_.empty() ||
      !staged_beats_.empty() || !staged_new_write_beats_.empty() ||
      staged_child_write_beat_.has_value() ||
      staged_store_to_bridge_.has_value() ||
      staged_bridge_to_throttle_.has_value() ||
      staged_read_beat_output_.has_value();
  if (!staged_state_change) {
    if (!active_bursts_.empty()) {
      issue_round_robin_ =
          (issue_round_robin_ + 1) % active_bursts_.size();
    } else {
      issue_round_robin_ = 0;
    }
    set_latched_commit_ready(false);
    return;
  }
  commit_output();
  commit_backend_responses(context);
  commit_request_input();
  commit_address_channel(context);
  commit_data_channel();
  commit_write_ingress(context);
  commit_read_beat_output();
  refresh_pending_work();
  set_latched_commit_ready(false);
}

}  // namespace spine::sim
