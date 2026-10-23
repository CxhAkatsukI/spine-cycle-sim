#include "spine_sim/axi.hpp"

#include <array>
#include <limits>

namespace spine::sim {
namespace {
std::size_t direction(MemoryOperation operation) {
  return operation == MemoryOperation::kWrite ? 1 : 0;
}
} // namespace

void AxiMaster::evaluate_independent_responses(const CycleContext &context) {
  // An absent direction cannot have a response; stop once neither can progress.
  if (active_direction_bursts_[0] + active_direction_bursts_[1] !=
      active_bursts_.size())
    throw std::logic_error("AXI active direction counts do not conserve");
  std::array<bool, 2> blocked{active_direction_bursts_[0] == 0,
                              active_direction_bursts_[1] == 0};
  std::size_t stream_beats = 0;
  std::vector<std::size_t> selected;
  for (std::size_t index = 0;
       index < backend_.response_count(config_.initiator_id) &&
       selected.size() < config_.response_beats_per_cycle &&
       (!blocked[0] || !blocked[1]);
       ++index) {
    const auto &response = backend_.response_at(config_.initiator_id, index);
    const auto op = direction(response.operation);
    if (blocked[op])
      continue;
    const auto mapping = backend_mappings_.find(response.request_id);
    if (mapping == backend_mappings_.end())
      throw std::logic_error("independent response has no mapping");
    auto *burst = find_active(mapping->second.burst_id);
    if (!burst || response.operation != burst->operation)
      throw std::logic_error("independent response operation or burst differs");
    auto &parent = parents_.at(burst->parent_id);
    const auto &stall =
        op ? config_.write_response_stall : config_.read_response_stall;
    if (stall.stalled(context.domain_cycle)) {
      if (op)
        ++stats_.write_response_channel_stalls;
      else
        ++stats_.read_response_channel_stalls;
      blocked[op] = true;
      continue;
    }
    if (!op && parent.request.stream_read_beats) {
      if (read_reorder_occupancy() + stream_beats >=
          config_.read_reorder_capacity) {
        ++stats_.read_reorder_stalls;
        blocked[0] = true;
        continue;
      }
      ++stream_beats;
    }
    selected.push_back(index);
    staged_backend_responses_.push_back(
        {response.request_id, mapping->second, burst, &parent});
  }
  if (!selected.empty() &&
      !backend_.stage_select_responses(config_.initiator_id, selected))
    throw std::logic_error("backend rejected independent response selection");
}

void AxiMaster::evaluate_independent_addresses(const CycleContext &context) {
  if (pending_address_.empty())
    return;
  auto active = active_direction_bursts_;
  std::array<bool, 2> blocked{};
  bool serialized_write = active_write_data_bursts_ != 0;
  for (const auto &burst : pending_address_) {
    if (staged_address_bursts_.size() == config_.address_accepts_per_cycle)
      break;
    const auto op = direction(burst.operation);
    if (blocked[op])
      continue;
    if (active[op] == config_.max_outstanding_bursts) {
      blocked[op] = true;
      continue;
    }
    if (context.domain_cycle < burst.address_ready_cycle) {
      ++stats_.address_pipeline_stalls;
      blocked[op] = true;
      continue;
    }
    if (op && config_.serialize_write_bursts && serialized_write) {
      ++stats_.write_burst_serialization_stalls;
      blocked[op] = true;
      continue;
    }
    const auto &stall =
        op ? config_.write_address_stall : config_.read_address_stall;
    if (stall.stalled(context.domain_cycle)) {
      if (op)
        ++stats_.write_address_channel_stalls;
      else
        ++stats_.read_address_channel_stalls;
      blocked[op] = true;
      continue;
    }
    staged_address_bursts_.push_back(burst.burst_id);
    ++active[op];
    if (op)
      serialized_write = true;
  }
}

std::size_t AxiMaster::independent_issue_index(
    const CycleContext &context, bool stream_credit_available) {
  std::array<std::size_t, 2> chosen{active_bursts_.size(),
                                    active_bursts_.size()};
  std::array<std::pair<std::uint64_t, std::uint64_t>, 2> keys;
  keys.fill({std::numeric_limits<std::uint64_t>::max(),
             std::numeric_limits<std::uint64_t>::max()});
  for (std::size_t index = 0; index < active_bursts_.size(); ++index) {
    const auto &burst = active_bursts_[index];
    const auto issued = burst.beats_issued + staged_additional_issued_[index];
    if (issued == burst.beats_total)
      continue;
    if (!stream_credit_available &&
        parents_.at(burst.parent_id).request.stream_read_beats) {
      ++stats_.read_issue_credit_stalls;
      continue;
    }
    const auto op = direction(burst.operation);
    const auto key =
        std::pair(burst.parent_id,
                  burst.parent_offset + issued * config_.data_width_bytes);
    if (key < keys[op]) {
      keys[op] = key;
      chosen[op] = index;
    }
  }
  if (chosen[1] != active_bursts_.size()) {
    const auto &write = active_bursts_[chosen[1]];
    if (config_.write_data_stall.stalled(context.domain_cycle)) {
      ++stats_.write_data_channel_stalls;
      chosen[1] = active_bursts_.size();
    } else if (write_ingress_enabled() &&
               (write_throttle_fifo_.empty() ||
                write_throttle_fifo_.front().burst_id != write.burst_id)) {
      ++stats_.write_throttle_data_stalls;
      chosen[1] = active_bursts_.size();
    }
  }
  const bool prefer_write =
      staged_beats_.empty()
          ? independent_prefer_write_
          : staged_beats_.back().request.operation == MemoryOperation::kRead;
  return chosen[prefer_write] != active_bursts_.size() ? chosen[prefer_write]
                                                       : chosen[!prefer_write];
}
} // namespace spine::sim
