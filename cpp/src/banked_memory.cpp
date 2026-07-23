#include "spine_sim/banked_memory.hpp"

#include <algorithm>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace spine::sim {

BankedMemory::BankedMemory(std::string name, ClockId clock_id,
                           BankedMemoryConfig config)
    : Component(std::move(name), clock_id),
      config_(config),
      round_robin_start_(config.banks, 0) {
  if (config_.banks == 0 || config_.capacity_words == 0) {
    throw std::invalid_argument("banked memory requires banks and capacity");
  }
  if (config_.read_ports_per_bank == 0 || config_.write_ports_per_bank == 0) {
    throw std::invalid_argument("banked memory requires read and write ports");
  }
  if (config_.latency_cycles == 0 || config_.max_outstanding_per_port == 0) {
    throw std::invalid_argument("latency and max outstanding must be positive");
  }
}

std::size_t BankedMemory::attach_port(Fifo<OnChipRequest>& requests,
                                      Fifo<OnChipResponse>& responses) {
  if (requests.clock_id() != clock_id() || responses.clock_id() != clock_id()) {
    throw std::invalid_argument("banked memory ports must share its clock");
  }
  ports_.push_back(Port{.requests = &requests, .responses = &responses});
  completions_.emplace_back();
  return ports_.size() - 1;
}

void BankedMemory::validate_address(std::uint64_t word_address) const {
  if (word_address >= config_.capacity_words) {
    throw std::out_of_range("banked memory word address exceeds capacity");
  }
}

std::size_t BankedMemory::bank_for(std::uint64_t word_address) const {
  return static_cast<std::size_t>(word_address % config_.banks);
}

void BankedMemory::initialize_word(std::uint64_t word_address,
                                   std::uint64_t value) {
  validate_address(word_address);
  if (value == 0) {
    words_.erase(word_address);
  } else {
    words_[word_address] = value;
  }
}

std::uint64_t BankedMemory::inspect_word(std::uint64_t word_address) const {
  validate_address(word_address);
  const auto found = words_.find(word_address);
  return found == words_.end() ? 0 : found->second;
}

std::size_t BankedMemory::outstanding() const noexcept {
  std::size_t total = 0;
  for (const auto& queue : completions_) {
    total += queue.size();
  }
  return total;
}

bool BankedMemory::has_pending_write(std::uint64_t word_address) const {
  for (const auto& queue : completions_) {
    for (const auto& completion : queue) {
      if (!completion.write_applied &&
          completion.response.operation == OnChipOperation::kWrite &&
          completion.word_address == word_address) {
        return true;
      }
    }
  }
  return false;
}

std::uint64_t BankedMemory::visible_word(std::uint64_t word_address) const {
  if (config_.raw_policy == ReadAfterWritePolicy::kBypassLatest) {
    const Completion* latest = nullptr;
    for (const auto& queue : completions_) {
      for (const auto& completion : queue) {
        if (!completion.write_applied &&
            completion.response.operation == OnChipOperation::kWrite &&
            completion.word_address == word_address &&
            (latest == nullptr || completion.due_cycle >= latest->due_cycle)) {
          latest = &completion;
        }
      }
    }
    if (latest != nullptr) {
      return latest->write_data;
    }
  }
  const auto found = words_.find(word_address);
  return found == words_.end() ? 0 : found->second;
}

void BankedMemory::retire_completions(const CycleContext& context) {
  for (std::size_t port = 0; port < ports_.size(); ++port) {
    auto& queue = completions_[port];
    if (queue.empty() || queue.front().due_cycle > context.domain_cycle) {
      continue;
    }
    Completion& completion = queue.front();
    if (completion.response.operation == OnChipOperation::kWrite &&
        !completion.write_applied) {
      initialize_word(completion.word_address, completion.write_data);
      completion.write_applied = true;
    }
    if (ports_[port].responses->try_push(completion.response)) {
      queue.pop_front();
    } else {
      ++stats_.response_backpressure_stalls;
    }
  }
}

void BankedMemory::grant(const Candidate& candidate,
                         const CycleContext& context) {
  OnChipRequest popped;
  if (!ports_[candidate.port].requests->try_pop(popped)) {
    throw std::logic_error("banked memory candidate disappeared before commit");
  }
  OnChipResponse response{
      .transaction_id = popped.transaction_id,
      .operation = popped.operation,
      .read_data = 0,
  };
  if (popped.operation == OnChipOperation::kRead) {
    response.read_data = visible_word(popped.word_address);
    ++stats_.accepted_reads;
  } else {
    ++stats_.accepted_writes;
  }
  completions_[candidate.port].push_back(Completion{
      .due_cycle = context.domain_cycle + config_.latency_cycles,
      .response = response,
      .word_address = popped.word_address,
      .write_data = popped.write_data,
      .write_applied = false,
  });
}

void BankedMemory::accept_requests(const CycleContext& context) {
  if (ports_.empty()) {
    return;
  }
  std::vector<Candidate> candidates;
  std::unordered_set<std::uint64_t> same_edge_writes;
  for (std::size_t port = 0; port < ports_.size(); ++port) {
    const OnChipRequest* request = ports_[port].requests->front();
    if (request == nullptr) {
      continue;
    }
    validate_address(request->word_address);
    if (completions_[port].size() >= config_.max_outstanding_per_port) {
      ++stats_.outstanding_limit_stalls;
      continue;
    }
    if (request->operation == OnChipOperation::kWrite) {
      same_edge_writes.insert(request->word_address);
    }
    candidates.push_back(Candidate{
        .port = port,
        .bank = bank_for(request->word_address),
        .request = *request,
        .raw_blocked = false,
    });
  }

  for (auto& candidate : candidates) {
    if (candidate.request.operation != OnChipOperation::kRead) {
      continue;
    }
    const bool same_edge_hazard = same_edge_writes.contains(
        candidate.request.word_address);
    const bool pending_hazard = has_pending_write(candidate.request.word_address);
    candidate.raw_blocked = same_edge_hazard ||
        (config_.raw_policy == ReadAfterWritePolicy::kStall && pending_hazard);
    if (candidate.raw_blocked) {
      ++stats_.raw_hazard_stalls;
    }
  }

  for (std::size_t bank = 0; bank < config_.banks; ++bank) {
    std::size_t reads = 0;
    std::size_t writes = 0;
    std::size_t last_granted = round_robin_start_[bank];
    bool granted_any = false;
    for (std::size_t offset = 0; offset < ports_.size(); ++offset) {
      const std::size_t port = (round_robin_start_[bank] + offset) % ports_.size();
      const auto found = std::find_if(
          candidates.begin(), candidates.end(), [bank, port](const Candidate& candidate) {
            return candidate.bank == bank && candidate.port == port;
          });
      if (found == candidates.end() || found->raw_blocked) {
        continue;
      }
      if (found->request.operation == OnChipOperation::kRead) {
        if (reads >= config_.read_ports_per_bank) {
          ++stats_.read_bank_conflict_stalls;
          continue;
        }
        ++reads;
      } else {
        if (writes >= config_.write_ports_per_bank) {
          ++stats_.write_bank_conflict_stalls;
          continue;
        }
        ++writes;
      }
      grant(*found, context);
      last_granted = port;
      granted_any = true;
    }
    if (granted_any) {
      round_robin_start_[bank] = (last_granted + 1) % ports_.size();
    }
  }
  stats_.max_outstanding = std::max(stats_.max_outstanding, outstanding());
}

void BankedMemory::evaluate(const CycleContext& context) {
  retire_completions(context);
  accept_requests(context);
}

}  // namespace spine::sim
