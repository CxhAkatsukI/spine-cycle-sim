#include "spine_sim/original_grasu/search.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::original_grasu {

Search::Search(std::string name, ClockId clock, SearchQueues input, SearchQueues results,
               Fifo<Update>& output, std::array<Port, 8> memory, Timing timing)
    : Component(std::move(name), clock), input_(input), results_(results), output_(output),
      memory_(memory), timing_(timing) {
  if (!timing.search_control) throw std::invalid_argument("G search control delay must be positive");
}

void Search::begin(std::uint32_t updates, std::uint64_t binary, std::uint64_t rows,
                   std::uint32_t segments, std::uint32_t vertices) {
  if (started_ && !finished()) throw std::logic_error("G search restart before drain");
  if (binary % 8 || rows % 8 || !segments || !vertices) throw std::invalid_argument("G search table geometry");
  count_ = updates; merged_ = 0; binary_address_ = binary; row_address_ = rows;
  segments_ = segments; vertices_ = vertices; lanes_ = {}; cursors_ = {}; ended_ = {};
  started_ = true;
}

bool Search::finished() const noexcept {
  return started_ && merged_ == count_ &&
      std::all_of(lanes_.begin(), lanes_.end(), [](const auto& lane) { return lane.phase == Phase::kEnd; }) &&
      std::all_of(ended_.begin(), ended_.end(), [](auto mask) { return mask == 0xffff; }) &&
      std::all_of(pending_.begin(), pending_.end(), [](const auto& queue) { return queue.empty(); });
}

void Search::evaluate(const CycleContext& context) {
  issues_.clear(); responses_.clear(); retire_.clear(); stage_merge_ = false; next_lanes_ = lanes_;
  advance_.fill(true);
  if (!started_ || finished()) return;
  for (unsigned lane = 0; lane < 64; ++lane) {
    auto& next = next_lanes_[lane]; const auto& state = lanes_[lane];
    if (state.phase == Phase::kEdge && !input_[lane]->empty()) {
      Update item; input_[lane]->try_pop(item); next.edge = item.edge;
      next.phase = item.end ? Phase::kEnd : Phase::kRow;
      next.ready = context.domain_cycle + timing_.search_control;
    } else if (state.phase == Phase::kEmit) {
      if (results_[lane]->try_push(Update{.edge = state.edge, .slot = state.begin * 16})) next.phase = Phase::kEdge;
      else ++counters_.output_stalls;
    }
  }
  for (unsigned port = 0; port < 8; ++port) {
    if (!memory_[port].responses.empty()) {
      if (pending_[port].empty()) throw std::logic_error("G BIPA response without request");
      AxiResponse response; memory_[port].responses.try_pop(response);
      const auto found = std::find_if(pending_[port].begin(), pending_[port].end(), [&](const auto& item) {
        return item.transaction == response.transaction_id && !item.value.has_value();
      });
      if (found == pending_[port].end()) throw std::logic_error("G BIPA unknown or duplicate response");
      const auto request = *found;
      require_ack(response, request.transaction, MemoryOperation::kRead, 8);
      responses_.push_back({port, request, little_word(response.read_data)});
    }
    if (!pending_[port].empty() && pending_[port].front().value)
      retire_.push_back({port, pending_[port].front(), *pending_[port].front().value});
    const unsigned kind = port / 4, lane = (port % 4) * 16 + cursors_[port];
    const auto& state = lanes_[lane];
    if (state.phase != (kind ? Phase::kRow : Phase::kBinary) || state.ready > context.domain_cycle) continue;
    const auto address = kind ? static_cast<std::uint32_t>((state.edge & ~(1ull << 63)) >> 32) : state.middle;
    if (address >= (kind ? vertices_ : segments_)) throw std::logic_error("G search address outside admitted table");
    if (pending_[port].size() >= 16) { ++counters_.dependency_stalls; advance_[port] = false; continue; }
    const auto transaction = next_transaction_ + issues_.size();
    if (memory_[port].requests.try_push(AxiRequest{.transaction_id = transaction,
        .operation = MemoryOperation::kRead, .address = (kind ? row_address_ : binary_address_) + address * 8ull,
        .bytes = 8, .stream_read_beats = false, .target_channel = std::nullopt, .write_data = {}})) {
      issues_.push_back({port, {lane, address, transaction, std::nullopt}});
      next_lanes_[lane].phase = kind ? Phase::kRowWait : Phase::kBinaryWait;
    } else { ++counters_.output_stalls; advance_[port] = false; }
  }
  if (merged_ < count_ && !results_[merged_ % 64]->empty()) {
    if (output_.try_push(*results_[merged_ % 64]->front())) {
      Update consumed; results_[merged_ % 64]->try_pop(consumed); stage_merge_ = true;
    } else ++counters_.output_stalls;
  }
}

void Search::commit(const CycleContext& context) {
  if (!started_ || finished()) return;
  for (unsigned port = 0; port < 8; ++port) {
    const auto lane = (port % 4) * 16 + cursors_[port];
    if (lanes_[lane].phase == Phase::kEnd && !(ended_[port] & (1u << cursors_[port]))) {
      ended_[port] |= 1u << cursors_[port]; ++counters_.ends;
    }
    if (advance_[port]) cursors_[port] = (cursors_[port] + 1) % 16;
  }
  lanes_ = next_lanes_;
  for (const auto& [port, request] : issues_) { pending_[port].push_back(request); ++counters_.reads; }
  next_transaction_ += issues_.size();
  for (const auto& response : responses_) {
    auto& queue = pending_[response.port];
    const auto found = std::find_if(queue.begin(), queue.end(), [&](const auto& item) {
      return item.transaction == response.pending.transaction;
    });
    if (found == queue.end()) throw std::logic_error("G BIPA lost pending response");
    found->value = response.value; ++counters_.acknowledgements;
  }
  // The generic AXI fixture may complete parents out of order. Retire BIPA
  // requests in issue order, with the same bounded sixteen-request credit.
  for (const auto& response : retire_) {
    pending_[response.port].pop_front();
    auto& state = lanes_[response.pending.lane];
    if (response.port >= 4) {
      state.begin = static_cast<std::uint32_t>(response.value >> 32) >> 4;
      state.end = static_cast<std::uint32_t>(response.value) >> 4;
      if (state.begin >= state.end || state.end > segments_) throw std::logic_error("G source row bounds");
    } else if (response.value <= (state.edge & ~(1ull << 63))) state.begin = state.middle;
    else state.end = state.middle;
    state.middle = (state.begin + state.end) / 2;
    state.phase = state.begin == state.middle ? Phase::kEmit : Phase::kBinary;
    state.ready = context.domain_cycle + timing_.search_control;
    trace_.push_back({response.pending.lane, response.port >= 4 ? 0u : 1u, response.pending.address, response.value});
  }
  if (stage_merge_) { ++merged_; ++counters_.updates; }
}

}  // namespace spine::sim::original_grasu
