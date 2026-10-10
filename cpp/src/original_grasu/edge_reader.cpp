#include "spine_sim/original_grasu/search.hpp"

#include <stdexcept>

namespace spine::sim::original_grasu {

EdgeReader::EdgeReader(std::string name, ClockId clock, StreamPort memory, SearchQueues output)
    : Component(std::move(name), clock), memory_(memory), output_(output) {}

bool EdgeReader::finished() const noexcept {
  return started_ && issued_ && acknowledged_ && received_ == count_ && ends_ == 64;
}

void EdgeReader::begin(std::uint64_t address, std::uint32_t updates) {
  if (started_ && !finished()) throw std::logic_error("G edge reader restart before drain");
  if (address % 8) throw std::invalid_argument("G input edges require 64-bit alignment");
  address_ = address; count_ = updates; received_ = ends_ = 0;
  started_ = true; issued_ = acknowledged_ = updates == 0;
  transaction_ = next_transaction_++;
}

void EdgeReader::evaluate(const CycleContext&) {
  stage_issue_ = stage_ack_ = stage_beat_ = stage_end_ = false;
  if (!started_ || finished()) return;
  if (!issued_) stage_issue_ = memory_.parent.requests.try_push(AxiRequest{
      .transaction_id = transaction_, .operation = MemoryOperation::kRead,
      .address = address_, .bytes = std::uint64_t{count_} * 8, .stream_read_beats = true,
      .target_channel = std::nullopt, .write_data = {}});
  if (!acknowledged_ && !memory_.parent.responses.empty()) {
    AxiResponse response;
    if (!memory_.parent.responses.try_pop(response)) throw std::logic_error("G edge parent ownership");
    require_ack(response, transaction_, MemoryOperation::kRead, std::uint64_t{count_} * 8);
    stage_ack_ = true;
  }
  if (received_ < count_ && !memory_.beats.empty()) {
    const auto& beat = *memory_.beats.front();
    if (!beat.success || beat.transaction_id != transaction_ || beat.address != address_ + received_ * 8ull ||
        beat.parent_offset != received_ * 8ull || beat.last != (received_ + 1 == count_) || beat.read_data.size() != 8)
      throw std::logic_error("G edge beat identity/order/extent");
    if (output_[received_ % 64]->try_push(Update{.edge = little_word(beat.read_data)})) {
      AxiReadBeatResponse consumed; memory_.beats.try_pop(consumed); stage_beat_ = true;
    } else ++counters_.output_stalls;
  } else if (received_ == count_ && ends_ < 64)
    stage_end_ = output_[(received_ + ends_) % 64]->try_push(Update{.end = true});
}

void EdgeReader::commit(const CycleContext&) {
  if (stage_issue_) issued_ = true;
  if (stage_ack_) { acknowledged_ = true; ++counters_.acknowledgements; }
  if (stage_beat_) { ++received_; ++counters_.reads; ++counters_.updates; }
  if (stage_end_) { ++ends_; ++counters_.ends; }
}

}  // namespace spine::sim::original_grasu
