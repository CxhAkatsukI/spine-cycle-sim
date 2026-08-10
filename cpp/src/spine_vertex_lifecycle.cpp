#include "spine_sim/spine_vertex_lifecycle.hpp"

#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kBitmapWordBytes = sizeof(std::uint64_t);
constexpr std::uint64_t kVerticesPerWord = 64;

}  // namespace

SpineVertexLifecycle::SpineVertexLifecycle(
    std::string name, ClockId clock_id, SpineVertexLifecycleConfig config,
    FixedAxiPort &bitmap_port)
    : Component(std::move(name), clock_id), config_(config),
      bitmap_port_(bitmap_port),
      validity_words_((config.max_vertices + kVerticesPerWord - 1) /
                          kVerticesPerWord,
                      0) {
  if (config_.max_vertices == 0 ||
      config_.max_vertices >
          static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max()) +
              1ULL ||
      config_.initial_valid_vertices > config_.max_vertices) {
    throw std::invalid_argument("invalid Spine vertex lifecycle geometry");
  }
  for (std::size_t vertex = 0; vertex < config_.initial_valid_vertices;
       ++vertex) {
    validity_words_[vertex / kVerticesPerWord] |=
        std::uint64_t{1} << (vertex % kVerticesPerWord);
  }
  std::vector<std::uint8_t> payload;
  payload.reserve(validity_words_.size() * kBitmapWordBytes);
  for (const std::uint64_t word : validity_words_) {
    const std::vector<std::uint8_t> encoded = encode_word(word);
    payload.insert(payload.end(), encoded.begin(), encoded.end());
  }
  bitmap_port_.initialize_payload(config_.bitmap_base, payload);
}

std::uint64_t SpineVertexLifecycle::word_index(
    std::uint32_t vertex) const noexcept {
  return vertex / kVerticesPerWord;
}

std::uint64_t SpineVertexLifecycle::word_address(
    std::uint32_t vertex) const noexcept {
  return config_.bitmap_base + word_index(vertex) * kBitmapWordBytes;
}

std::vector<std::uint8_t> SpineVertexLifecycle::encode_word(
    std::uint64_t word) const {
  std::vector<std::uint8_t> payload(kBitmapWordBytes, 0);
  for (std::size_t byte = 0; byte < payload.size(); ++byte) {
    payload[byte] = static_cast<std::uint8_t>((word >> (byte * 8)) & 0xffU);
  }
  return payload;
}

std::uint64_t SpineVertexLifecycle::decode_word(
    const std::vector<std::uint8_t> &payload) const {
  if (payload.size() != kBitmapWordBytes) {
    throw std::logic_error("vertex validity read returned a malformed word");
  }
  std::uint64_t word = 0;
  for (std::size_t byte = 0; byte < payload.size(); ++byte) {
    word |= static_cast<std::uint64_t>(payload[byte]) << (byte * 8);
  }
  return word;
}

bool SpineVertexLifecycle::valid(std::uint32_t vertex) const {
  if (vertex >= config_.max_vertices) {
    throw std::out_of_range("vertex validity query exceeds fixed capacity");
  }
  return (validity_words_[word_index(vertex)] &
          (std::uint64_t{1} << (vertex % kVerticesPerWord))) != 0;
}

bool SpineVertexLifecycle::busy() const noexcept {
  return phase_ != Phase::kIdle || operation_.has_value();
}

bool SpineVertexLifecycle::begin_operation(std::uint32_t vertex,
                                           bool requested_valid) {
  if (vertex >= config_.max_vertices) {
    throw std::out_of_range("vertex lifecycle operation exceeds fixed capacity");
  }
  if (failed_) {
    throw std::logic_error("failed vertex lifecycle cannot accept operations");
  }
  if (busy()) {
    ++counters_.busy_stalls;
    return false;
  }
  operation_ = Operation{
      .vertex = vertex,
      .requested_valid = requested_valid,
      .start_cycle = 0,
  };
  last_result_.reset();
  phase_ = Phase::kIssueRead;
  ++counters_.accepted_operations;
  return true;
}

bool SpineVertexLifecycle::try_activate(std::uint32_t vertex) {
  ++counters_.activation_attempts;
  return begin_operation(vertex, true);
}

bool SpineVertexLifecycle::try_deactivate(
    std::uint32_t vertex, bool incident_edges_retired_or_masked) {
  ++counters_.deactivation_attempts;
  if (!incident_edges_retired_or_masked) {
    ++counters_.unsafe_deactivation_rejections;
    return false;
  }
  return begin_operation(vertex, false);
}

void SpineVertexLifecycle::evaluate(const CycleContext &) {
  staged_issue_ = false;
  staged_response_.reset();
  if (failed_ || phase_ == Phase::kIdle) {
    return;
  }
  if (const AxiResponse *response = bitmap_port_.responses().front();
      response != nullptr) {
    AxiResponse popped;
    if (bitmap_port_.responses().try_pop(popped)) {
      staged_response_ = std::move(popped);
    }
    return;
  }
  if (phase_ != Phase::kIssueRead && phase_ != Phase::kIssueWrite) {
    return;
  }
  if (!operation_.has_value()) {
    throw std::logic_error("vertex lifecycle phase has no operation");
  }
  const bool write = phase_ == Phase::kIssueWrite;
  const AxiRequest request{
      .transaction_id = next_transaction_,
      .operation = write ? MemoryOperation::kWrite : MemoryOperation::kRead,
      .address = word_address(operation_->vertex),
      .bytes = static_cast<std::uint32_t>(kBitmapWordBytes),
      .write_data = write ? encode_word(operation_->updated_word)
                          : std::vector<std::uint8_t>{},
  };
  if (bitmap_port_.requests().try_push(request)) {
    staged_issue_ = true;
  } else {
    ++counters_.memory_request_fifo_stall_cycles;
  }
}

void SpineVertexLifecycle::complete_operation(bool changed,
                                              std::uint64_t end_cycle) {
  if (!operation_.has_value()) {
    throw std::logic_error("vertex lifecycle completion has no operation");
  }
  const Operation operation = *operation_;
  if (changed) {
    const std::uint64_t mask =
        std::uint64_t{1} << (operation.vertex % kVerticesPerWord);
    if (operation.requested_valid) {
      validity_words_[word_index(operation.vertex)] |= mask;
    } else {
      validity_words_[word_index(operation.vertex)] &= ~mask;
    }
    ++counters_.changed_operations;
  } else {
    ++counters_.no_op_operations;
  }
  counters_.last_end_cycle = end_cycle;
  last_result_ = SpineVertexLifecycleResult{
      .vertex = operation.vertex,
      .requested_valid = operation.requested_valid,
      .changed = changed,
      .final_valid = operation.requested_valid,
      .start_cycle = operation.start_cycle,
      .end_cycle = end_cycle,
  };
  operation_.reset();
  phase_ = Phase::kIdle;
}

void SpineVertexLifecycle::fail(std::string message) {
  failed_ = true;
  failure_ = std::move(message);
}

void SpineVertexLifecycle::commit(const CycleContext &context) {
  if (failed_ || phase_ == Phase::kIdle) {
    return;
  }
  if (operation_.has_value() && !operation_->started) {
    operation_->start_cycle = context.domain_cycle;
    operation_->started = true;
    counters_.last_start_cycle = context.domain_cycle;
  }
  if (staged_response_.has_value()) {
    const AxiResponse response = std::move(*staged_response_);
    if (response.transaction_id != inflight_transaction_ ||
        !response.success) {
      fail("vertex lifecycle received an invalid AXI response");
      return;
    }
    ++counters_.memory_requests_completed;
    if (phase_ == Phase::kWaitRead) {
      if (response.operation != MemoryOperation::kRead ||
          !operation_.has_value()) {
        fail("vertex lifecycle received an unexpected read response");
        return;
      }
      std::uint64_t word = 0;
      try {
        word = decode_word(response.read_data);
      } catch (const std::logic_error &) {
        fail("vertex lifecycle received a malformed bitmap response");
        return;
      }
      const std::uint64_t index = word_index(operation_->vertex);
      if (word != validity_words_[index]) {
        fail("vertex lifecycle HBM bitmap diverged from committed state");
        return;
      }
      operation_->bitmap_word = word;
      const std::uint64_t mask =
          std::uint64_t{1} << (operation_->vertex % kVerticesPerWord);
      const bool current_valid = (word & mask) != 0;
      if (current_valid == operation_->requested_valid) {
        complete_operation(false, context.domain_cycle);
        return;
      }
      operation_->updated_word = operation_->requested_valid ? word | mask
                                                             : word & ~mask;
      phase_ = Phase::kIssueWrite;
    } else if (phase_ == Phase::kWaitWrite) {
      if (response.operation != MemoryOperation::kWrite ||
          !response.read_data.empty()) {
        fail("vertex lifecycle received an unexpected write response");
        return;
      }
      complete_operation(true, context.domain_cycle);
    } else {
      fail("vertex lifecycle response arrived outside a wait phase");
    }
  }
  if (failed_ || !staged_issue_) {
    return;
  }
  inflight_transaction_ = next_transaction_++;
  ++counters_.memory_requests_issued;
  if (phase_ == Phase::kIssueRead) {
    ++counters_.bitmap_reads;
    counters_.read_bytes += kBitmapWordBytes;
    phase_ = Phase::kWaitRead;
  } else if (phase_ == Phase::kIssueWrite) {
    ++counters_.bitmap_writes;
    counters_.write_bytes += kBitmapWordBytes;
    phase_ = Phase::kWaitWrite;
  } else {
    fail("vertex lifecycle issued outside an AXI issue phase");
  }
}

}  // namespace spine::sim
