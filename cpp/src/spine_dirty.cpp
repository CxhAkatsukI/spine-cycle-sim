#include "spine_sim/spine_dirty.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kPersistentWordBytes = 16;
constexpr std::uint64_t kResultBytes = 96 * 4;
constexpr std::uint64_t kAckMode = 3;
constexpr std::size_t kResultInputEdges = 0;
constexpr std::size_t kResultOverflow = 1;
constexpr std::size_t kResultPath = 8;
constexpr std::size_t kResultLayoutVersion = 75;
constexpr std::size_t kResultMetadataVersion = 76;
constexpr std::size_t kResultDirtyMode = 80;
constexpr std::size_t kResultDirtyStatus = 81;
constexpr std::size_t kResultDirtyCount = 82;
constexpr std::size_t kResultDirtyGeneration = 83;
constexpr std::size_t kResultDirtyHashSumLow = 84;
constexpr std::size_t kResultDirtyHashXorLow = 86;
constexpr std::size_t kResultDirtyAux = 95;
constexpr std::uint32_t kResultPathOverflow = 5;
constexpr std::uint32_t kResultLayoutVersionValue = 3;
constexpr std::uint32_t kResultMetadataVersionValue = 2;

std::vector<std::uint8_t> encode_u64(std::uint64_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] = static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

std::vector<std::uint8_t>
encode_u64_words(const std::vector<std::uint64_t> &values) {
  std::vector<std::uint8_t> data(values.size() * sizeof(std::uint64_t));
  for (std::size_t index = 0; index < values.size(); ++index) {
    const auto word = encode_u64(values[index]);
    std::copy(word.begin(), word.end(),
              data.begin() + static_cast<std::ptrdiff_t>(index * word.size()));
  }
  return data;
}

std::vector<std::uint8_t>
encode_u32_words(const std::vector<std::uint32_t> &values) {
  std::vector<std::uint8_t> data(values.size() * sizeof(std::uint32_t));
  for (std::size_t index = 0; index < values.size(); ++index) {
    for (std::size_t byte = 0; byte < sizeof(std::uint32_t); ++byte) {
      data[index * sizeof(std::uint32_t) + byte] =
          static_cast<std::uint8_t>((values[index] >> (byte * 8)) & 0xffU);
    }
  }
  return data;
}

std::uint32_t decode_u32(const std::vector<std::uint8_t> &data,
                         std::size_t offset) {
  if (offset + sizeof(std::uint32_t) > data.size()) {
    throw std::invalid_argument("dirty ACK uint32 payload is truncated");
  }
  return static_cast<std::uint32_t>(data[offset]) |
         (static_cast<std::uint32_t>(data[offset + 1]) << 8) |
         (static_cast<std::uint32_t>(data[offset + 2]) << 16) |
         (static_cast<std::uint32_t>(data[offset + 3]) << 24);
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &data) {
  if (data.size() != sizeof(std::uint64_t)) {
    throw std::invalid_argument("dirty ACK uint64 payload has the wrong size");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    value |= static_cast<std::uint64_t>(data[byte]) << (byte * 8);
  }
  return value;
}

std::uint32_t next_generation(std::uint32_t generation) {
  const std::uint32_t next = generation + 1;
  return next == 0 ? 1 : next;
}

} // namespace

SpineDirtyAck::SpineDirtyAck(std::string name, ClockId clock_id,
                             SpineL0Config config, SpineDirtyAckPorts ports)
    : Component(std::move(name), clock_id), config_(std::move(config)),
      ports_(ports) {
  if (ports_.task_scratch == nullptr || ports_.metadata == nullptr ||
      ports_.result == nullptr) {
    throw std::invalid_argument("invalid Spine dirty ACK ports");
  }
  (void)spine_metadata_layout(config_);
}

void SpineDirtyAck::start(std::uint32_t expected_generation,
                          SpineDirtyIdentity candidate) {
  if (started_ || done_ || waiting_memory_ || !memory_tasks_.empty()) {
    throw std::logic_error("Spine dirty ACK can only be started once");
  }
  started_ = true;
  counters_.expected_generation = expected_generation;
  counters_.candidate = candidate;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  enqueue(*ports_.metadata, MemoryOperation::kWrite,
          config_.metadata_base + metadata.dirty_candidate_generation_word *
                                      kSpineMetadataWordBytes,
          4 * kSpineMetadataWordBytes, PayloadKind::kNone,
          encode_u64_words({candidate.generation, candidate.count,
                            candidate.hash_sum, candidate.hash_xor}));
  enqueue(*ports_.metadata, MemoryOperation::kWrite,
          config_.metadata_base +
              metadata.dirty_candidate_valid_word * kSpineMetadataWordBytes,
          kSpineMetadataWordBytes, PayloadKind::kNone, encode_u64(1));
  counters_.candidate_write_bytes = 5 * kSpineMetadataWordBytes;

  const auto enqueue_header = [&](std::uint64_t word, PayloadKind kind) {
    enqueue(*ports_.metadata, MemoryOperation::kRead,
            config_.metadata_base + word * kSpineMetadataWordBytes,
            kSpineMetadataWordBytes, kind);
    counters_.metadata_read_bytes += kSpineMetadataWordBytes;
  };
  enqueue_header(metadata.dirty_count_word, PayloadKind::kCount);
  enqueue_header(metadata.dirty_generation_word, PayloadKind::kGeneration);
  enqueue_header(metadata.dirty_hash_sum_word, PayloadKind::kHashSum);
  enqueue_header(metadata.dirty_hash_xor_word, PayloadKind::kHashXor);
  enqueue_header(metadata.dirty_candidate_generation_word,
                 PayloadKind::kCandidateGeneration);
  enqueue_header(metadata.dirty_candidate_count_word,
                 PayloadKind::kCandidateCount);
  enqueue_header(metadata.dirty_candidate_hash_sum_word,
                 PayloadKind::kCandidateHashSum);
  enqueue_header(metadata.dirty_candidate_hash_xor_word,
                 PayloadKind::kCandidateHashXor);
  enqueue_header(metadata.dirty_candidate_valid_word,
                 PayloadKind::kCandidateValid);
  phase_ = Phase::kHeaderResolve;
}

void SpineDirtyAck::enqueue(FixedAxiPort &port, MemoryOperation operation,
                            std::uint64_t address, std::uint64_t bytes,
                            PayloadKind payload_kind,
                            std::vector<std::uint8_t> write_data) {
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .write_data = std::move(write_data),
      .payload_kind = payload_kind,
  });
}

void SpineDirtyAck::enqueue_metadata_write(std::uint64_t word,
                                           std::uint64_t value) {
  enqueue(*ports_.metadata, MemoryOperation::kWrite,
          config_.metadata_base + word * kSpineMetadataWordBytes,
          kSpineMetadataWordBytes, PayloadKind::kNone, encode_u64(value));
  counters_.metadata_write_bytes += kSpineMetadataWordBytes;
}

void SpineDirtyAck::consume_response(const MemoryTask &task,
                                     const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("dirty ACK write response carried a payload");
    }
    if (task.payload_kind == PayloadKind::kBitmapClear) {
      ++counters_.cleared_sources;
      ++source_index_;
      phase_ = Phase::kClearList;
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("dirty ACK read response payload size mismatch");
  }
  switch (task.payload_kind) {
  case PayloadKind::kNone:
    return;
  case PayloadKind::kCount:
    counters_.captured.count = decode_u64(response.read_data);
    return;
  case PayloadKind::kGeneration:
    counters_.captured.generation =
        static_cast<std::uint32_t>(decode_u64(response.read_data));
    return;
  case PayloadKind::kHashSum:
    counters_.captured.hash_sum = decode_u64(response.read_data);
    return;
  case PayloadKind::kHashXor:
    counters_.captured.hash_xor = decode_u64(response.read_data);
    return;
  case PayloadKind::kCandidateGeneration:
    counters_.candidate.generation =
        static_cast<std::uint32_t>(decode_u64(response.read_data));
    return;
  case PayloadKind::kCandidateCount:
    counters_.candidate.count = decode_u64(response.read_data);
    return;
  case PayloadKind::kCandidateHashSum:
    counters_.candidate.hash_sum = decode_u64(response.read_data);
    return;
  case PayloadKind::kCandidateHashXor:
    counters_.candidate.hash_xor = decode_u64(response.read_data);
    return;
  case PayloadKind::kCandidateValid:
    candidate_valid_ = decode_u64(response.read_data) != 0;
    return;
  case PayloadKind::kList:
    current_source_ = decode_u32(response.read_data,
                                 (source_index_ & 3U) * sizeof(std::uint32_t));
    return;
  case PayloadKind::kBitmapValidate: {
    const std::size_t byte = (current_source_ & 127U) >> 3;
    const std::uint8_t bit =
        static_cast<std::uint8_t>(1U << (current_source_ & 7U));
    if (current_source_ >= config_.max_vertices ||
        byte >= response.read_data.size() ||
        (response.read_data[byte] & bit) == 0) {
      counters_.status =
          static_cast<std::uint32_t>(SpineDirtyStatus::kMalformedAck);
    } else {
      checked_hash_sum_ += spine_dirty_hash_sum_term(current_source_);
      checked_hash_xor_ ^= spine_dirty_hash_xor_term(current_source_);
      ++counters_.validated_sources;
    }
    ++source_index_;
    phase_ = Phase::kValidateList;
    return;
  }
  case PayloadKind::kBitmapClear: {
    bitmap_payload_ = response.read_data;
    const std::size_t byte = (current_source_ & 127U) >> 3;
    bitmap_payload_.at(byte) &=
        static_cast<std::uint8_t>(~(1U << (current_source_ & 7U)));
    return;
  }
  }
}

void SpineDirtyAck::begin_finalize(std::uint32_t status) {
  counters_.status = status;
  enqueue_final_writes();
  phase_ = Phase::kDrain;
}

void SpineDirtyAck::enqueue_final_writes() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  counters_.result = counters_.captured;
  if (counters_.status == static_cast<std::uint32_t>(SpineDirtyStatus::kOk)) {
    counters_.result = SpineDirtyIdentity{
        .generation = next_generation(counters_.captured.generation),
    };
    enqueue_metadata_write(metadata.dirty_count_word, 0);
    enqueue_metadata_write(metadata.dirty_generation_word,
                           counters_.result.generation);
    enqueue_metadata_write(metadata.dirty_hash_sum_word, 0);
    enqueue_metadata_write(metadata.dirty_hash_xor_word, 0);
    enqueue_metadata_write(metadata.dirty_candidate_valid_word, 0);
    enqueue_metadata_write(metadata.dirty_host_valid_word, 0);
    counters_.generation_advances = 1;
  }
  enqueue_metadata_write(metadata.dirty_last_mode_word, kAckMode);
  enqueue_metadata_write(metadata.dirty_last_status_word, counters_.status);
  std::vector<std::uint32_t> result_words(kResultBytes / sizeof(std::uint32_t),
                                          0);
  result_words[kResultInputEdges] = counters_.expected_generation;
  const bool success =
      counters_.status == static_cast<std::uint32_t>(SpineDirtyStatus::kOk);
  result_words[kResultOverflow] = success ? 0U : 1U;
  result_words[kResultPath] = success ? 0U : kResultPathOverflow;
  result_words[kResultLayoutVersion] = kResultLayoutVersionValue;
  result_words[kResultMetadataVersion] = kResultMetadataVersionValue;
  result_words[kResultDirtyMode] = kAckMode;
  result_words[kResultDirtyStatus] = counters_.status;
  result_words[kResultDirtyCount] =
      static_cast<std::uint32_t>(counters_.result.count);
  result_words[kResultDirtyGeneration] = counters_.result.generation;
  result_words[kResultDirtyHashSumLow] =
      static_cast<std::uint32_t>(counters_.result.hash_sum);
  result_words[kResultDirtyHashSumLow + 1] =
      static_cast<std::uint32_t>(counters_.result.hash_sum >> 32);
  result_words[kResultDirtyHashXorLow] =
      static_cast<std::uint32_t>(counters_.result.hash_xor);
  result_words[kResultDirtyHashXorLow + 1] =
      static_cast<std::uint32_t>(counters_.result.hash_xor >> 32);
  result_words[kResultDirtyAux] = candidate_valid_ ? 1U : 0U;
  enqueue(*ports_.result, MemoryOperation::kWrite, config_.result_base,
          kResultBytes, PayloadKind::kNone, encode_u32_words(result_words));
  counters_.result_write_bytes += kResultBytes;
}

void SpineDirtyAck::advance(const CycleContext &context) {
  switch (phase_) {
  case Phase::kDormant:
    return;
  case Phase::kHeaderResolve:
    if (counters_.captured.count > config_.max_vertices) {
      begin_finalize(
          static_cast<std::uint32_t>(SpineDirtyStatus::kInvalidState));
    } else if (!candidate_valid_ ||
               counters_.expected_generation != counters_.captured.generation ||
               counters_.candidate.generation !=
                   counters_.captured.generation) {
      begin_finalize(static_cast<std::uint32_t>(SpineDirtyStatus::kStaleAck));
    } else if (counters_.candidate.count != counters_.captured.count ||
               counters_.candidate.hash_sum != counters_.captured.hash_sum ||
               counters_.candidate.hash_xor != counters_.captured.hash_xor) {
      begin_finalize(
          static_cast<std::uint32_t>(SpineDirtyStatus::kMalformedAck));
    } else {
      source_index_ = 0;
      checked_hash_sum_ = 0;
      checked_hash_xor_ = 0;
      phase_ = Phase::kValidateList;
    }
    return;
  case Phase::kValidateList:
    if (counters_.status != static_cast<std::uint32_t>(SpineDirtyStatus::kOk)) {
      begin_finalize(counters_.status);
      return;
    }
    if (source_index_ == counters_.captured.count) {
      if (checked_hash_sum_ != counters_.captured.hash_sum ||
          checked_hash_xor_ != counters_.captured.hash_xor) {
        begin_finalize(
            static_cast<std::uint32_t>(SpineDirtyStatus::kMalformedAck));
      } else {
        source_index_ = 0;
        phase_ = Phase::kClearList;
      }
      return;
    }
    enqueue(*ports_.task_scratch, MemoryOperation::kRead,
            config_.persistent_dirty_list_base +
                (source_index_ >> 2) * kPersistentWordBytes,
            kPersistentWordBytes, PayloadKind::kList);
    counters_.list_read_bytes += kPersistentWordBytes;
    phase_ = Phase::kValidateBitmap;
    return;
  case Phase::kValidateBitmap:
    if (current_source_ >= config_.max_vertices) {
      counters_.status =
          static_cast<std::uint32_t>(SpineDirtyStatus::kMalformedAck);
      ++source_index_;
      phase_ = Phase::kValidateList;
      return;
    }
    enqueue(*ports_.task_scratch, MemoryOperation::kRead,
            config_.persistent_dirty_bitmap_base +
                (current_source_ >> 7) * kPersistentWordBytes,
            kPersistentWordBytes, PayloadKind::kBitmapValidate);
    counters_.bitmap_read_bytes += kPersistentWordBytes;
    return;
  case Phase::kClearList:
    if (source_index_ == counters_.captured.count) {
      begin_finalize(static_cast<std::uint32_t>(SpineDirtyStatus::kOk));
      return;
    }
    enqueue(*ports_.task_scratch, MemoryOperation::kRead,
            config_.persistent_dirty_list_base +
                (source_index_ >> 2) * kPersistentWordBytes,
            kPersistentWordBytes, PayloadKind::kList);
    counters_.list_read_bytes += kPersistentWordBytes;
    phase_ = Phase::kClearBitmapRead;
    return;
  case Phase::kClearBitmapRead:
    enqueue(*ports_.task_scratch, MemoryOperation::kRead,
            config_.persistent_dirty_bitmap_base +
                (current_source_ >> 7) * kPersistentWordBytes,
            kPersistentWordBytes, PayloadKind::kBitmapClear);
    counters_.bitmap_read_bytes += kPersistentWordBytes;
    phase_ = Phase::kClearBitmapWrite;
    return;
  case Phase::kClearBitmapWrite:
    enqueue(*ports_.task_scratch, MemoryOperation::kWrite,
            config_.persistent_dirty_bitmap_base +
                (current_source_ >> 7) * kPersistentWordBytes,
            kPersistentWordBytes, PayloadKind::kBitmapClear, bitmap_payload_);
    counters_.bitmap_write_bytes += kPersistentWordBytes;
    return;
  case Phase::kDrain:
    counters_.end_cycle = context.domain_cycle;
    done_ = true;
    failed_ =
        counters_.status != static_cast<std::uint32_t>(SpineDirtyStatus::kOk);
    return;
  }
}

void SpineDirtyAck::evaluate(const CycleContext &context) {
  staged_action_ = Action::kNone;
  if (!started_ || done_) {
    return;
  }
  if (!start_cycle_recorded_) {
    counters_.start_cycle = context.domain_cycle;
    start_cycle_recorded_ = true;
  }
  if (waiting_memory_) {
    if (memory_tasks_.empty()) {
      throw std::logic_error("dirty ACK memory wait has no task");
    }
    if (memory_tasks_.front().port->responses().try_pop(staged_response_)) {
      staged_action_ = Action::kComplete;
    }
    return;
  }
  if (!memory_tasks_.empty()) {
    const MemoryTask &task = memory_tasks_.front();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = task.operation,
            .address = task.address,
            .bytes = task.bytes,
            .write_data = task.write_data,
        })) {
      staged_action_ = Action::kIssue;
    }
    return;
  }
  staged_action_ = Action::kAdvance;
}

void SpineDirtyAck::commit(const CycleContext &context) {
  switch (staged_action_) {
  case Action::kNone:
    return;
  case Action::kIssue:
    expected_transaction_id_ = next_transaction_id_++;
    waiting_memory_ = true;
    return;
  case Action::kComplete:
    if (!staged_response_.success ||
        staged_response_.transaction_id != expected_transaction_id_) {
      counters_.end_cycle = context.domain_cycle;
      failed_ = true;
      done_ = true;
      return;
    }
    consume_response(memory_tasks_.front(), staged_response_);
    waiting_memory_ = false;
    memory_tasks_.pop_front();
    return;
  case Action::kAdvance:
    advance(context);
    return;
  }
}

} // namespace spine::sim
