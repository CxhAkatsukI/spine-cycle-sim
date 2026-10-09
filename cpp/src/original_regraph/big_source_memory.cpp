#include "spine_sim/original_regraph/big_source_memory.hpp"

#include <algorithm>
#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"

namespace spine::sim::original_regraph {

BigSourceMemory::BigSourceMemory(std::string name, ClockId clock, ReadPort memory,
    Fifo<CachelineRequest>& input, Fifo<CachelineResponse>& output,
    std::uint64_t address, std::uint64_t bytes, std::size_t capacity)
    : Component(std::move(name), clock), memory_(memory), input_(input), output_(output),
      address_(address), bytes_(bytes), capacity_(capacity) {
  detail::validate_port(memory_, clock);
  if (input.clock_id() != clock || output.clock_id() != clock || !capacity || address % 64 || !bytes || bytes % 64 ||
      bytes > std::numeric_limits<std::uint64_t>::max() - address) {
    throw std::invalid_argument("invalid Big source ports/allocation/capacity");
  }
}
bool BigSourceMemory::finished() const noexcept {
  return completed_ends_ == partitions_ && entries_.empty() && reads_.empty();
}
void BigSourceMemory::begin_partitions(unsigned count) {
  if (!finished() || !input_.empty() || !output_.empty() || !memory_.requests.empty() ||
      !memory_.responses.empty() || !memory_.beats.empty()) throw std::logic_error("Big source restart requires drain");
  if (!count || count > 255) throw std::invalid_argument("original Big wrapper partition count is an uchar");
  partitions_ = count; accepted_ends_ = completed_ends_ = 0; cache_.reset();
}
void BigSourceMemory::evaluate(const CycleContext&) {
  accepted_.reset(); acknowledged_.reset(); stage_output_ = false;
  if (!memory_.beats.empty()) throw std::logic_error("Big single-line source uses parent responses, not a second beat stream");
  if (!memory_.responses.empty()) {
    const auto& response = *memory_.responses.front();
    if (!reads_.contains(response.transaction_id)) throw std::logic_error("unknown or duplicate Big source acknowledgement");
    detail::require_read_ack(response, response.transaction_id, 64);
    AxiResponse consumed;
    if (!memory_.responses.try_pop(consumed)) throw std::logic_error("Big source acknowledgement ownership");
    acknowledged_ = std::move(consumed);
  }
  if (!entries_.empty()) {
    const auto& entry = entries_.front();
    if (entry.request.end || entry.read->ready) {
      if (output_.full()) { ++counters_.output_stalls; }
      else {
        CachelineResponse value{};
        value.line = entry.request.line; value.lane = entry.request.lane; value.end = entry.request.end;
        if (!value.end) value.data = entry.read->data;
        if (!output_.try_push(value)) throw std::logic_error("Big source response ownership");
        stage_output_ = true;
      }
    }
  }
  if (accepted_ends_ == partitions_ || input_.empty()) return;
  if (entries_.size() == capacity_) { ++counters_.capacity_stalls; return; }
  const auto request = *input_.front();
  if (request.lane >= 8 || (!request.end && (request.line >= (1u << 26) || request.line >= bytes_ / 64))) {
    throw std::invalid_argument("Big source request lane/line outside allocation");
  }
  std::shared_ptr<Read> read;
  if (!request.end) {
    if (cache_ && cache_->line == request.line) read = cache_;
    else {
      if (memory_.requests.full()) return;
      read = std::make_shared<Read>(Read{next_transaction_, request.line, {}, false});
      if (!memory_.requests.try_push(AxiRequest{.transaction_id=next_transaction_, .operation=MemoryOperation::kRead,
          .address=address_ + request.line * 64ull, .bytes=64, .stream_read_beats=false,
          .target_channel=std::nullopt, .write_data={}})) throw std::logic_error("Big source read ownership");
    }
  }
  CachelineRequest consumed;
  if (!input_.try_pop(consumed)) throw std::logic_error("Big source request ownership");
  accepted_ = Entry{consumed, read};
}
void BigSourceMemory::commit(const CycleContext&) {
  if (acknowledged_) {
    auto read = reads_.at(acknowledged_->transaction_id);
    read->data = detail::property_line(acknowledged_->read_data);
    read->ready = true;
    reads_.erase(read->transaction);
    ++counters_.acknowledgements;
  }
  if (stage_output_) {
    if (entries_.front().request.end) { ++completed_ends_; ++counters_.partition_ends; }
    else ++counters_.responses;
    entries_.pop_front();
  }
  if (accepted_) {
    if (accepted_->request.end) { ++accepted_ends_; cache_.reset(); }
    else {
      ++counters_.requests;
      if (accepted_->read == cache_) ++counters_.cache_hits;
      else {
        reads_.emplace(accepted_->read->transaction, accepted_->read);
        ++next_transaction_; ++counters_.reads; counters_.read_bytes += 64;
      }
      cache_ = accepted_->read;
    }
    entries_.push_back(std::move(*accepted_));
    counters_.max_live = std::max(counters_.max_live, entries_.size());
  }
}

}  // namespace spine::sim::original_regraph
