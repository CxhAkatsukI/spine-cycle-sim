#include "network.hpp"

#include <stdexcept>

namespace spine::sim::grasu_update_detail::finite {
namespace {
template <typename T, std::size_t N>
void arbitrate(Channels<T, N>& input, std::size_t offset, Fifo<Request>& output,
               const Arbiter& state, Arbiter& next) {
  if (state.ended) return;
  if (state.finished == 255) {
    if (output.try_push(Request{0, 0, false, true})) next.ended = true;
    return;
  }
  for (std::size_t step = 0; step < kWidth; ++step) {
    const auto index = (state.cursor + step) % kWidth;
    auto& queue = *input[offset + index];
    const auto* request = queue.front();
    if (request == nullptr) continue;
    if (!request->end && !output.try_push(*request)) return;
    Request consumed; queue.try_pop(consumed);
    if (consumed.end) next.finished |= 1U << index;
    next.cursor = (index + 1) % kWidth;
    return;
  }
}
}  // namespace

void FiniteSearch::gather_groups() {
  for (std::size_t group = 0; group < kGroups; ++group)
    arbitrate(requests_, group * kWidth, *group_requests_[group],
              state_.groups[group], next_.groups[group]);
}

void FiniteSearch::gather() {
  arbitrate(group_requests_, 0, *memory_requests_, state_.central, next_.central);
}

void FiniteSearch::memory() {
  const auto outstanding = state_.metadata_issued - state_.metadata_received;
  const auto* request = memory_requests_->front();
  if (request != nullptr && !state_.memory_done) {
    if (request->end) {
      if (outstanding == 0 && memory_responses_->try_push(Response{0, 0, true})) {
        Request consumed; memory_requests_->try_pop(consumed); next_.memory_done = true;
      }
    } else if (outstanding < kMetadataCredits) {
      const auto address = (request->binary ? binary_base_ : row_base_) +
                           std::uint64_t(request->address) * 8;
      if (metadata_.requests().try_push(AxiRequest{
          .transaction_id = state_.metadata_issued, .operation = MemoryOperation::kRead,
          .address = address, .bytes = 8, .stream_read_beats = false,
          .target_channel = request->binary ? metadata_channels_.binary : metadata_channels_.row,
          .write_data = {}})) {
        next_.pending_lanes[state_.metadata_issued % kMetadataCredits] = request->lane;
        ++next_.metadata_issued;
        (request->binary ? next_.probes : next_.rows)++;
        Request consumed; memory_requests_->try_pop(consumed);
      }
    }
  }
  AxiResponse response;
  if (metadata_.responses().try_pop(response))
    next_.metadata_replies.accept(response, state_.metadata_received, state_.metadata_issued);
  // A bounded response window emulates ordered HLS loop consumption. Arrival
  // becomes visible next edge; a blocked publication retains its issue credit.
  const auto slot = state_.metadata_received % kMetadataCredits;
  if (outstanding == 0 || memory_responses_->full() ||
      !state_.metadata_replies.ready[slot]) return;
  memory_responses_->try_push(Response{state_.metadata_replies.words[slot],
                                      state_.pending_lanes[slot], false});
  next_.metadata_replies.ready[slot] = false;
  ++next_.metadata_received;
}

void FiniteSearch::scatter() {
  if (state_.scatter_done) return;
  const auto* response = memory_responses_->front();
  if (response == nullptr) return;
  if (response->end) {
    for (const auto& group : group_responses_) if (group->full()) return;
    for (auto& group : group_responses_) group->try_push(*response);
    next_.scatter_done = true;
  } else if (!group_responses_[response->lane / kWidth]->try_push(*response)) return;
  Response consumed; memory_responses_->try_pop(consumed);
}

void FiniteSearch::scatter_groups() {
  for (std::size_t group = 0; group < kGroups; ++group) {
    if (state_.scatter_groups_done & (1U << group)) continue;
    const auto* response = group_responses_[group]->front();
    if (response == nullptr) continue;
    if (!response->end && !responses_[response->lane]->try_push(response->data)) continue;
    if (response->end) next_.scatter_groups_done |= 1U << group;
    Response consumed; group_responses_[group]->try_pop(consumed);
  }
}

}  // namespace spine::sim::grasu_update_detail::finite
