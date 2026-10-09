#include "spine_sim/original_regraph/property_writer.hpp"

#include <algorithm>
#include <bit>
#include <limits>

namespace spine::sim::original_regraph {
namespace {
std::vector<std::uint8_t> encode(const PropertyLine& data) {
  std::vector<std::uint8_t> result;
  result.reserve(64);
  for (const auto value : data) {
    for (unsigned byte = 0; byte < 4; ++byte) result.push_back((value >> (byte * 8)) & 255u);
  }
  return result;
}
}  // namespace

PropertyBroadcastWriter::PropertyBroadcastWriter(std::string name, ClockId clock,
    Fifo<PropertyWrite>& input, std::vector<WriteTarget> targets, std::size_t line_credits)
    : Component(std::move(name), clock), input_(input), targets_(std::move(targets)),
      line_credits_(line_credits) {
  if (input.clock_id() != clock || targets_.empty() || targets_.size() > 14 || !line_credits) {
    throw std::invalid_argument("invalid original property-writer topology or credits");
  }
  for (const auto& target : targets_) {
    if (target.port.requests.clock_id() != clock || target.port.responses.clock_id() != clock ||
        target.address % 64 || !target.bytes || target.bytes % 64 ||
        target.bytes > std::numeric_limits<std::uint64_t>::max() - target.address) {
      throw std::invalid_argument("invalid original property-writer port or allocation");
    }
  }
  all_targets_ = (1u << targets_.size()) - 1;
}

void PropertyBroadcastWriter::begin(std::uint32_t lines, std::optional<std::uint64_t> address) {
  if (active_ || !pending_.empty() || !input_.empty() ||
      std::any_of(targets_.begin(), targets_.end(), [](const auto& target) {
        return !target.port.requests.empty() || !target.port.responses.empty();
      })) {
    throw std::logic_error("property writer restart requires drained queues");
  }
  if (address) {
    for (const auto& target : targets_) {
      if (*address % 64 || target.bytes > std::numeric_limits<std::uint64_t>::max() - *address) {
        throw std::invalid_argument("invalid relocated property-write allocation");
      }
    }
    for (auto& target : targets_) target.address = *address;
  }
  expected_ = lines;
  accepted_ = 0;
  input_ended_ = false;
  active_ = true;
}

void PropertyBroadcastWriter::evaluate(const CycleContext&) {
  staged_input_.reset();
  staged_issue_.reset();
  staged_acks_.clear();
  stage_end_ = false;
  if (!active_) return;
  for (std::size_t index = 0; index < targets_.size(); ++index) {
    auto& port = targets_[index].port;
    if (port.responses.empty()) continue;
    AxiResponse response;
    if (!port.responses.try_pop(response)) throw std::logic_error("property acknowledgement ownership");
    const auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& entry) {
      return entry.transaction == response.transaction_id;
    });
    const auto bit = 1u << index;
    if (!response.success || response.operation != MemoryOperation::kWrite || !response.read_data.empty() ||
        found == pending_.end() || !(found->issued & bit) || found->acknowledged & bit) {
      throw std::logic_error("unexpected property-write acknowledgement");
    }
    staged_acks_.emplace_back(response.transaction_id, bit);
  }
  const auto next = std::find_if(pending_.begin(), pending_.end(), [&](const auto& entry) {
    return entry.issued != all_targets_;
  });
  if (next != pending_.end()) {
    std::uint32_t issued = 0;
    for (std::size_t index = 0; index < targets_.size(); ++index) {
      const auto bit = 1u << index;
      if (next->issued & bit) continue;
      auto& target = targets_[index];
      if (target.port.requests.try_push(AxiRequest{
          .transaction_id = next->transaction, .operation = MemoryOperation::kWrite,
          .address = target.address + static_cast<std::uint64_t>(next->packet.index) * 64,
          .bytes = 64, .stream_read_beats = false, .target_channel = std::nullopt,
          .write_data = next->payload})) issued |= bit;
      else ++counters_.request_stalls;
    }
    staged_issue_ = {next->transaction, issued};
  }
  if (!input_ended_ && !input_.empty()) {
    const auto packet = *input_.front();
    if (packet.end) {
      if (accepted_ != expected_) throw std::logic_error("property stream terminated before expected extent");
      PropertyWrite consumed;
      if (!input_.try_pop(consumed)) throw std::logic_error("property input ownership");
      stage_end_ = true;
    } else {
      if (accepted_ == expected_) throw std::logic_error("excess property data after expected extent");
      for (const auto& target : targets_) {
        if (static_cast<std::uint64_t>(packet.index) >= target.bytes / 64) {
          throw std::out_of_range("property-write index exceeds allocation");
        }
      }
      if (pending_.size() == line_credits_) ++counters_.credit_stalls;
      else {
        PropertyWrite consumed;
        if (!input_.try_pop(consumed)) throw std::logic_error("property input ownership");
        staged_input_ = packet;
      }
    }
  }
}

void PropertyBroadcastWriter::commit(const CycleContext&) {
  for (const auto& [transaction, bit] : staged_acks_) {
    auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& entry) {
      return entry.transaction == transaction;
    });
    if (found == pending_.end()) throw std::logic_error("property acknowledgement lost metadata");
    found->acknowledged |= bit;
    ++counters_.acknowledgements;
  }
  if (staged_issue_) {
    auto found = std::find_if(pending_.begin(), pending_.end(), [&](const auto& entry) {
      return entry.transaction == staged_issue_->first;
    });
    if (found == pending_.end()) throw std::logic_error("property issue lost metadata");
    found->issued |= staged_issue_->second;
    counters_.write_requests += std::popcount(staged_issue_->second);
    counters_.write_bytes += std::popcount(staged_issue_->second) * 64;
  }
  while (!pending_.empty() && pending_.front().acknowledged == all_targets_) pending_.pop_front();
  if (staged_input_) {
    pending_.push_back({next_transaction_++, *staged_input_, encode(staged_input_->data), 0, 0});
    ++accepted_;
    ++counters_.lines;
  }
  if (stage_end_) { input_ended_ = true; ++counters_.input_terminators; }
  if (input_ended_ && pending_.empty()) active_ = false;
  counters_.max_live_lines = std::max(counters_.max_live_lines, pending_.size());
}

}  // namespace spine::sim::original_regraph
