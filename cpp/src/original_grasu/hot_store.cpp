#include "spine_sim/original_grasu/hot_store.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_grasu {

HotStore::HotStore(std::string name, ClockId clock, StreamPort memory)
    : Component(std::move(name), clock), memory_(memory), data_(kHotSegments) {}

void HotStore::connect(std::array<CachePe*, 16> lanes) {
  if (std::any_of(lanes.begin(), lanes.end(), [](auto* lane) { return !lane; }))
    throw std::invalid_argument("G hot store requires sixteen PE owners");
  lanes_ = lanes;
}

void HotStore::begin(std::uint64_t address) {
  if (phase_ != Phase::kIdle && !finished()) throw std::logic_error("G hot store restart before drain");
  if (address % 64 || !lanes_[0]) throw std::invalid_argument("G hot store alignment/owners");
  address_ = address; received_ = 0; transaction_ = next_transaction_++;
  issued_ = acknowledged_ = false; phase_ = Phase::kLoad;
}

void HotStore::evaluate(const CycleContext&) {
  stage_issue_ = stage_ack_ = stage_beat_ = stage_store_ = false;
  if (phase_ == Phase::kIdle || finished()) return;
  if (phase_ == Phase::kProcess) {
    stage_store_ = std::all_of(lanes_.begin(), lanes_.end(), [](auto* lane) { return lane->finished(); });
    return;
  }
  const auto operation = phase_ == Phase::kLoad ? MemoryOperation::kRead : MemoryOperation::kWrite;
  if (!issued_) stage_issue_ = memory_.parent.requests.try_push(AxiRequest{
      .transaction_id = transaction_, .operation = operation, .address = address_,
      .bytes = kHotSegments * 64ull, .stream_read_beats = operation == MemoryOperation::kRead,
      .target_channel = std::nullopt, .write_data = write_data_});
  if (!acknowledged_ && !memory_.parent.responses.empty()) {
    AxiResponse response; memory_.parent.responses.try_pop(response);
    require_ack(response, transaction_, operation, kHotSegments * 64ull); stage_ack_ = true;
  }
  if (phase_ == Phase::kLoad && !memory_.beats.empty()) {
    AxiReadBeatResponse beat; memory_.beats.try_pop(beat);
    if (!beat.success || beat.transaction_id != transaction_ || received_ >= kHotSegments ||
        beat.parent_offset != received_ * 64ull || beat.address != address_ + received_ * 64ull ||
        beat.last != (received_ + 1 == kHotSegments)) throw std::logic_error("G hot load beat identity/order");
    incoming_ = decode_segment(beat.read_data); stage_beat_ = true;
  }
}

void HotStore::commit(const CycleContext&) {
  if (stage_issue_) { issued_ = true; if (phase_ == Phase::kStore) counters_.writes += kHotSegments; }
  if (stage_ack_) { acknowledged_ = true; ++counters_.acknowledgements; }
  if (stage_beat_) { data_[received_++] = incoming_; ++counters_.reads; }
  if (phase_ == Phase::kLoad && acknowledged_ && received_ == kHotSegments) phase_ = Phase::kProcess;
  if (phase_ == Phase::kProcess && stage_store_) {
    write_data_ = encode_segments(data_); issued_ = acknowledged_ = false;
    transaction_ = next_transaction_++; phase_ = Phase::kStore;
  }
  if (phase_ == Phase::kStore && acknowledged_) { phase_ = Phase::kDone; write_data_.clear(); }
}

CachePe::CachePe(std::string name, ClockId clock, unsigned bank, HotStore& store,
                 Fifo<Update>& input, Timing timing)
    : Component(std::move(name), clock), bank_(bank), store_(store), input_(input), timing_(timing) {
  if (bank >= 16 || !timing.cache_interval || !timing.cache_latency)
    throw std::invalid_argument("G cache PE geometry/timing");
}

void CachePe::begin() {
  if (started_ && !finished()) throw std::logic_error("G cache PE restart before drain");
  started_ = true; ended_ = false; next_accept_ = 0;
}

void CachePe::evaluate(const CycleContext& context) {
  staged_.reset(); stage_end_ = stage_retire_ = false;
  if (!started_ || !store_.loaded()) return;
  stage_retire_ = !pending_.empty() && pending_.front().ready <= context.domain_cycle;
  if (ended_ || input_.empty() || context.domain_cycle < next_accept_) return;
  const auto item = *input_.front();
  if (item.end) stage_end_ = true;
  else {
    const auto index = item.slot >> 5;
    if (index >= kHotSegments || index % 16 != bank_) throw std::logic_error("G cache bank/address route");
    if (pending_.size() >= (timing_.cache_latency + timing_.cache_interval - 1) / timing_.cache_interval ||
        std::any_of(pending_.begin(), pending_.end(), [index](const auto& pending) { return pending.index == index; })) {
      ++counters_.dependency_stalls; return;
    }
    staged_ = Pending{context.domain_cycle + timing_.cache_latency, index, apply_update(store_.segment(index), item)};
  }
  Update consumed; input_.try_pop(consumed);
}

void CachePe::commit(const CycleContext& context) {
  if (stage_retire_) {
    store_.segment(pending_.front().index) = pending_.front().value;
    pending_.pop_front(); ++counters_.writes;
  }
  if (staged_) {
    pending_.push_back(*staged_); next_accept_ = context.domain_cycle + timing_.cache_interval;
    ++counters_.updates; ++counters_.reads;
  }
  if (stage_end_) { ended_ = true; ++counters_.ends; }
}

}  // namespace spine::sim::original_grasu
