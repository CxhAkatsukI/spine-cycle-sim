#include "spine_sim/original_regraph/source_memory.hpp"

#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"

namespace spine::sim::original_regraph {

LittleSourceMemory::LittleSourceMemory(std::string name, ClockId clock, ReadPort memory,
                                     Fifo<SourceRequest>& input, Fifo<SourceResponse>& output,
                                     std::uint64_t address, std::uint64_t bytes)
    : Component(std::move(name), clock), memory_(memory), input_(input), output_(output),
      property_address_(address), property_bytes_(bytes) {
  detail::validate_port(memory, clock);
  if (input.clock_id() != clock || output.clock_id() != clock || address % 64 ||
      !bytes || bytes % 64 || bytes > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("invalid source-memory extent or clock");
  }
}

void LittleSourceMemory::begin_partitions(unsigned count, std::optional<std::uint64_t> address) {
  if (!finished() || !input_.empty() || !output_.empty() ||
      !memory_.requests.empty() || !memory_.responses.empty() || !memory_.beats.empty()) {
    throw std::logic_error("source-memory restart requires drained queues");
  }
  if (!count || count > 255) throw std::invalid_argument("original wrapper has an 8-bit partition count");
  if (address) {
    if (*address % 64 || property_bytes_ > std::numeric_limits<std::uint64_t>::max() - *address) {
      throw std::invalid_argument("invalid relocated source-property allocation");
    }
    property_address_ = *address;
  }
  partitions_ = count;
  completed_ = 0;
  phase_ = Phase::kIdle;
}

void LittleSourceMemory::evaluate(const CycleContext&) {
  accepted_.reset();
  stage_issue_ = stage_ack_ = stage_beat_ = stage_end_ = false;
  if (phase_ == Phase::kIdle && !input_.empty()) {
    SourceRequest request;
    if (input_.try_pop(request)) {
      if (!request.end && (static_cast<std::uint64_t>(request.round) + 1) *
          kSourceWindowVertices * 4 > property_bytes_) {
        throw std::out_of_range("original Little lookahead exceeds allocated source properties");
      }
      accepted_ = request;
    }
  }
  if (phase_ == Phase::kRequest) {
    stage_issue_ = memory_.requests.try_push(AxiRequest{
        .transaction_id = transaction_, .operation = MemoryOperation::kRead,
        .address = property_address_ + static_cast<std::uint64_t>(round_) * kSourceWindowVertices * 4,
        .bytes = kSourceWindowVertices * 4, .stream_read_beats = true,
        .target_channel = std::nullopt, .write_data = {}});
  }
  if (phase_ == Phase::kStream) {
    if (!acknowledged_ && !memory_.responses.empty()) {
      AxiResponse response;
      if (memory_.responses.try_pop(response)) {
        detail::require_read_ack(response, transaction_, kSourceWindowVertices * 4);
        stage_ack_ = true;
      }
    }
    if (!memory_.beats.empty()) {
      if (output_.full()) {
        ++counters_.response_stalls;
      } else {
        AxiReadBeatResponse beat;
        if (!memory_.beats.try_pop(beat)) throw std::logic_error("source beat ownership mismatch");
        const auto line = static_cast<std::uint64_t>(round_) * kSourceWindowLines + returned_;
        if (!beat.success || beat.transaction_id != transaction_ || returned_ >= kSourceWindowLines ||
            beat.address != property_address_ + line * 64 || beat.parent_offset != returned_ * 64 ||
            beat.last != (returned_ + 1 == kSourceWindowLines)) {
          throw std::logic_error("source beat address/order/extent mismatch");
        }
        if (!output_.try_push({detail::property_line(beat.read_data), static_cast<std::uint32_t>(line), false})) {
          throw std::logic_error("source response ownership mismatch");
        }
        stage_beat_ = true;
      }
    }
  }
  if (phase_ == Phase::kEnd) stage_end_ = output_.try_push({{}, 0, true});
}

void LittleSourceMemory::commit(const CycleContext&) {
  if (accepted_) {
    if (accepted_->end) phase_ = Phase::kEnd;
    else {
      round_ = accepted_->round;
      returned_ = 0;
      acknowledged_ = false;
      transaction_ = next_transaction_++;
      phase_ = Phase::kRequest;
    }
  }
  if (stage_issue_) { phase_ = Phase::kStream; ++counters_.rounds; }
  if (stage_ack_) { acknowledged_ = true; ++counters_.acknowledgements; }
  if (stage_beat_) {
    ++returned_;
    ++counters_.response_lines;
    counters_.read_bytes += 64;
  }
  if (phase_ == Phase::kStream && acknowledged_ && returned_ == kSourceWindowLines) {
    phase_ = Phase::kIdle;
  }
  if (stage_end_) {
    ++completed_;
    ++counters_.partition_terminators;
    phase_ = completed_ == partitions_ ? Phase::kFinished : Phase::kIdle;
  }
}

}  // namespace spine::sim::original_regraph
