#include "../detail/routed_regraph_source.hpp"

#include <limits>

namespace spine::sim::detail {

RoutedSourceService::RoutedSourceService(std::string name, ClockId clock,
    std::vector<RoutedSourceWorker> workers, AxiEndpoint memory,
    std::size_t parent_capacity)
    : Component(std::move(name), clock), workers_(workers), memory_(memory),
      parent_capacity_(parent_capacity) {
  if (!parent_capacity || !memory.read_beats() || workers.empty() || workers.size() > 2)
    throw std::invalid_argument("source service requires bounded streamed AXI");
  if (memory.requests().clock_id() != clock || memory.responses().clock_id() != clock ||
      memory.read_beats()->clock_id() != clock)
    throw std::invalid_argument("source service AXI clock mismatch");
  for (const auto &worker : workers)
    if (!worker.requests || !worker.responses || worker.requests->clock_id() != clock ||
        worker.responses->clock_id() != clock)
      throw std::invalid_argument("source service worker wiring is invalid");
  if (workers.size() == 2 &&
      (workers[0].requests == workers[1].requests || workers[0].responses == workers[1].responses))
    throw std::invalid_argument("source service workers must have distinct queues");
}

void RoutedSourceService::start_round(std::vector<RoutedSourceRegion> regions,
                                     std::vector<std::size_t> invocations) {
  if (regions.size() != workers_.size() || invocations.size() != workers_.size() ||
      (workers_.size() == 1 && invocations[0] > 255))
    throw std::invalid_argument("source service invocation shape or dedicated 8-bit count is invalid");
  if ((started_ && !done()) || !memory_.requests().empty() || !memory_.responses().empty() ||
      !memory_.read_beats()->empty() || std::any_of(workers_.begin(), workers_.end(),
          [](const auto &worker) { return !worker.responses->empty(); }))
    throw std::logic_error("source service restart requires drained previous round");
  for (const auto &region : regions)
    if (region.base % 64 || region.allocated_vertices >
        (std::numeric_limits<std::uint64_t>::max() - region.base) / 4)
      throw std::invalid_argument("source service allocation is unaligned or overflows");
  regions_ = regions;
  expected_ = invocations;
  completed_.assign(workers_.size(), 0);
  prefer_second_ = false;
  started_ = true;
}

bool RoutedSourceService::done() const noexcept {
  return started_ && completed_ == expected_ && !block_ && pending_.empty();
}

void RoutedSourceService::select_request() {
  std::array<bool, 2> ready{};
  for (std::size_t worker = 0; worker < workers_.size(); ++worker) {
    if (completed_[worker] == expected_[worker] && !workers_[worker].requests->empty())
      throw std::logic_error("source service received more invocations than declared");
    ready[worker] = completed_[worker] < expected_[worker] && !workers_[worker].requests->empty();
  }
  if (!ready[0] && !ready[1]) return;
  const std::size_t worker = ready[1] && (!ready[0] || prefer_second_) ? 1 : 0;
  ReGraphSourceCacheRequest request;
  if (!workers_[worker].requests->try_pop(request))
    throw std::logic_error("source service request disappeared");
  Block block{.worker = worker, .round = request.source_round, .end = request.end};
  if (!request.end) {
    const auto &region = regions_[worker];
    // The HLS address calculation is 32-bit; never wrap or invent zero padding.
    if (request.source_round > std::numeric_limits<std::uint32_t>::max() / kRoutedSourceVertices ||
        region.allocated_vertices < kRoutedSourceVertices ||
        request.source_round > (region.allocated_vertices - kRoutedSourceVertices) / kRoutedSourceVertices)
      throw std::out_of_range("source block exceeds the declared HLS allocation");
    block.address = region.base + request.source_round * kRoutedSourceBytes;
  }
  selected_ = block;
}

void RoutedSourceService::issue_block() {
  if (pending_.size() == parent_capacity_) { ++counters_.issue_stalls; return; }
  issued_ = memory_.requests().try_push(AxiRequest{
      .transaction_id = next_id_, .address = block_->address, .bytes = kRoutedSourceBytes,
      .stream_read_beats = true, .target_channel = regions_[block_->worker].channel,
      .write_data = {}});
  if (!issued_) ++counters_.issue_stalls;
}

void RoutedSourceService::forward_line() {
  const auto *beat = memory_.read_beats()->front();
  if (!beat) return;
  const auto &block = *block_;
  if (!beat->success || beat->transaction_id != block.id ||
      beat->parent_offset != block.line * 64 || beat->address != block.address + block.line * 64 ||
      beat->read_data.size() != 64 || beat->last != (block.line + 1 == kRoutedSourceLines))
    throw std::logic_error("source service read beat has invalid ID, bounds, order or payload");
  ReGraphSourceCacheResponse result{.source_round = block.round, .line = block.line, .vertices = 16};
  for (std::size_t word = 0; word < 16; ++word) result.words[word] = decode_u32(beat->read_data, word * 4);
  if (!workers_[block.worker].responses->try_push(result)) { ++counters_.output_stalls; return; }
  AxiReadBeatResponse consumed;
  if (!memory_.read_beats()->try_pop(consumed)) throw std::logic_error("source beat disappeared");
  forwarded_ = true;
}

void RoutedSourceService::evaluate(const CycleContext &) {
  selected_.reset();
  response_.reset();
  issued_ = forwarded_ = false;
  if (!started_) return;
  AxiResponse response;
  if (memory_.responses().try_pop(response)) {
    const auto found = pending_.find(response.transaction_id);
    if (found == pending_.end() || found->second.response || !response.success ||
        response.operation != MemoryOperation::kRead || response.read_data.size() != kRoutedSourceBytes)
      throw std::logic_error("source service received an invalid parent completion");
    response_ = std::move(response);
  }
  if (!block_) { select_request(); return; }
  if (block_->end) {
    forwarded_ = workers_[block_->worker].responses->try_push(ReGraphSourceCacheResponse{.end = true});
    if (!forwarded_) ++counters_.output_stalls;
  } else if (!block_->issued) issue_block();
  else forward_line();
}

void RoutedSourceService::commit(const CycleContext &) {
  if (response_) {
    pending_.at(response_->transaction_id).response = true;
    ++counters_.memory_completions;
  }
  if (selected_) { block_ = selected_; prefer_second_ = block_->worker == 0; }
  if (issued_) {
    block_->id = next_id_++;
    block_->issued = true;
    pending_.emplace(block_->id, Parent{.address = block_->address});
    ++counters_.blocks[block_->worker];
    ++counters_.memory_parents;
    counters_.max_pending = std::max(counters_.max_pending, pending_.size());
  }
  if (forwarded_) {
    if (block_->end) {
      ++completed_[block_->worker];
      ++counters_.terminators[block_->worker];
      block_.reset();
    } else {
      ++counters_.lines[block_->worker];
      if (++block_->line == kRoutedSourceLines) {
        pending_.at(block_->id).data = true;
        block_.reset();
      }
    }
  }
  std::erase_if(pending_, [](const auto &entry) { return entry.second.data && entry.second.response; });
}

} // namespace spine::sim::detail
