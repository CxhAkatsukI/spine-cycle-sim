#include "network.hpp"

#include <stdexcept>

namespace spine::sim::grasu_update_detail::finite {

void FiniteSearch::read_updates() {
  if (state_.update_issued < count_ &&
      state_.update_issued - state_.update_received < kUpdateCredits &&
      updates_.requests().try_push(AxiRequest{
          .transaction_id = state_.update_issued, .operation = MemoryOperation::kRead,
          .address = update_base_ + state_.update_issued * 8, .bytes = 8,
          .stream_read_beats = false, .write_data = {}})) ++next_.update_issued;
  AxiResponse response;
  if (updates_.responses().try_pop(response))
    next_.update_replies.accept(response, state_.update_received, state_.update_issued);
  const auto slot = state_.update_received % kUpdateCredits;
  if (input_->full() || !state_.update_replies.ready[slot]) return;
  const auto raw = state_.update_replies.words[slot];
  if (raw == ~std::uint64_t{0})
    throw std::runtime_error("finite search input collides with HLS end sentinel");
  input_->try_push(Input{raw, false});
  next_.update_replies.ready[slot] = false;
  ++next_.update_received;
}

void FiniteSearch::distribute() {
  if (state_.distributed == count_) {
    if (state_.end_lane < kLanes &&
        edges_[state_.end_lane]->try_push(Input{0, true})) ++next_.end_lane;
    return;
  }
  const auto lane = state_.distributed % kLanes;
  if (input_->empty() || edges_[lane]->full() ||
      (state_.distributed >= kLanes && credits_[lane]->empty())) return;
  if (state_.distributed >= kLanes) {
    bool credit; credits_[lane]->try_pop(credit);
  }
  Input input; input_->try_pop(input); edges_[lane]->try_push(input);
  ++next_.distributed;
}

void FiniteSearch::advance(Worker& worker) {
  worker.mid = (worker.begin + worker.end) >> 1;
  worker.phase = worker.begin == worker.mid ? Phase::kEmit : Phase::kBinary;
}

LocatedUpdate FiniteSearch::located(const Worker& worker) const {
  const auto encoded = static_cast<std::uint32_t>(worker.raw);
  return {.global_index = cu_ + worker.index * 4,
      .source = static_cast<std::uint32_t>((worker.raw >> 32) & 0x7fffffffULL),
      .partition = 0, .segment_head_slot = worker.begin << 4,
      .destination = decode_grasu_pma_destination(encoded),
      .weight = decode_grasu_pma_weight(encoded),
      .delete_op = static_cast<bool>(worker.raw >> 63),
      .last_binary_head = worker.last_head};
}

void FiniteSearch::workers() {
  for (std::size_t lane = 0; lane < kLanes; ++lane) {
    const auto& old = state_.workers[lane];
    auto& next = next_.workers[lane];
    switch (old.phase) {
    case Phase::kIdle: {
      Input input;
      if (edges_[lane]->try_pop(input)) {
        next.raw = input.raw; next.last_head = 0;
        next.phase = input.end ? Phase::kEnd : Phase::kRow;
      }
      break;
    }
    case Phase::kRow:
    case Phase::kBinary: {
      const bool binary = old.phase == Phase::kBinary;
      const auto address = binary ? old.mid :
          static_cast<std::uint32_t>((old.raw >> 32) & 0x7fffffffULL);
      if (requests_[lane]->try_push(Request{address, lane, binary, false}))
        next.phase = binary ? Phase::kWaitBinary : Phase::kWaitRow;
      break;
    }
    case Phase::kWaitRow:
    case Phase::kWaitBinary: {
      std::uint64_t word;
      if (!responses_[lane]->try_pop(word)) break;
      if (old.phase == Phase::kWaitRow) {
        next.begin = static_cast<std::uint32_t>(word >> 32) >> 4;
        next.end = static_cast<std::uint32_t>(word) >> 4;
        if (next.begin >= next.end)
          throw std::runtime_error("finite search source has no reserved segment");
      } else {
        next.last_head = word;
        if (word <= (old.raw & ~(std::uint64_t{1} << 63))) next.begin = old.mid;
        else next.end = old.mid;
      }
      advance(next);
      break;
    }
    case Phase::kEmit:
      if (results_[lane]->try_push(located(old))) {
        next.index += kLanes; next.phase = Phase::kIdle;
      }
      break;
    case Phase::kEnd:
      if (requests_[lane]->try_push(Request{0, lane, false, true})) next.phase = Phase::kDone;
      break;
    case Phase::kDone: break;
    }
  }
}

void FiniteSearch::merge() {
  if (state_.published == count_) return;
  const auto lane = state_.published % kLanes;
  const auto* result = results_[lane]->front();
  const bool credit = state_.published + kLanes < count_;
  if (result == nullptr || (credit && credits_[lane]->full())) return;
  if (result->global_index != cu_ + state_.published * 4)
    throw std::runtime_error("finite search ordered result ownership mismatch");
  if (!output_.try_push(*result)) return;
  LocatedUpdate consumed; results_[lane]->try_pop(consumed);
  if (credit) credits_[lane]->try_push(true);
  ++next_.published;
}

}  // namespace spine::sim::grasu_update_detail::finite
