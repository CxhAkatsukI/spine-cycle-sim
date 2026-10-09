#include "spine_sim/pma_adapter/reader.hpp"

#include <algorithm>
#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"

namespace spine::sim::pma_adapter {
namespace rg = original_regraph;

Reader::Reader(std::string name, ClockId clock, rg::ReadPort memory,
               Fifo<rg::EdgeBurst>& output, Timing timing)
    : Component(std::move(name), clock), memory_(memory), output_(output), timing_(timing) {
  rg::detail::validate_port(memory, clock);
  if (output.clock_id() != clock || !timing.minimum_read_cycles ||
      !timing.segment_issue_interval || !timing.row_decode_cycles ||
      !timing.source_restart_cycles || !timing.output_latency || !timing.segment_capacity) {
    throw std::invalid_argument("PMA adapter clock/timing/capacity mismatch");
  }
}

void Reader::begin_partition(Partition partition) {
  if (!finished() || !output_.empty()) throw std::logic_error("PMA adapter restart before drain");
  constexpr auto maximum = std::numeric_limits<std::uint64_t>::max();
  const auto row_bytes = (std::uint64_t{partition.vertices} * 8 + 63) / 64 * 64;
  const auto pma_bytes = (std::uint64_t{partition.slots} * 4 + 127) / 128 * 64;
  if (!partition.vertices || partition.vertices >= 0x80000000u || !partition.slots ||
      partition.slots % 16 || !partition.destination_vertices || partition.destination_vertices > 65536 ||
      std::uint64_t{partition.destination_offset} + partition.destination_vertices > 0x80000000ull ||
      partition.row_address % 64 || partition.row_address > maximum - row_bytes ||
      std::any_of(partition.pma_addresses.begin(), partition.pma_addresses.end(), [=](auto address) {
        return address % 64 || address > maximum - pma_bytes;
      })) throw std::invalid_argument("PMA adapter partition geometry/extent");
  partition_ = partition;
  phase_ = Phase::kTotal;
  row_.reset(); segments_.clear();
  source_ = total_slots_ = previous_end_ = begin_ = end_ = next_segment_ = end_segment_ = emitted_ = 0;
  ready_cycle_ = next_issue_cycle_ = 0;
  staged_request_.reset(); staged_response_.reset(); staged_output_ = staged_row_ = false;
  ++counters_.tasks;
}

bool Reader::finished() const noexcept {
  return (phase_ == Phase::kIdle || phase_ == Phase::kDone) && !row_ && segments_.empty() &&
      memory_.requests.empty() && memory_.responses.empty() && memory_.beats.empty();
}

Reader::Pending Reader::row_request(std::uint64_t cycle) const {
  const auto source = phase_ == Phase::kTotal ? partition_.vertices - 1 : source_;
  return {.transaction = next_transaction_,
          .address = partition_.row_address + (std::uint64_t{source} * 8 / 64) * 64,
          .issue_cycle = cycle, .ready_cycle = cycle + timing_.minimum_read_cycles, .data = std::nullopt};
}

Reader::Pending Reader::segment_request(std::uint64_t cycle) const {
  const auto route = (next_segment_ & 1u) * 2 + (next_segment_ / 2 >= partition_.cache_segments);
  return {.transaction = next_transaction_,
          .address = partition_.pma_addresses[route] + std::uint64_t{next_segment_ / 2} * 64,
          .issue_cycle = cycle, .ready_cycle = cycle + timing_.minimum_read_cycles,
          .segment = next_segment_, .route = route, .data = std::nullopt};
}

rg::EdgeBurst Reader::edges(const Pending& segment) const {
  rg::EdgeBurst output;
  for (unsigned lane = 0; lane < output.size(); ++lane) {
    const auto slot = segment.segment * 16 + segment.half * 8 + lane;
    const auto word = (*segment.data)[segment.half * 8 + lane], destination = word & 0x7ffffu;
    const bool dummy = (word >> 31) || slot < begin_ || slot >= end_ ||
        slot >= total_slots_ || destination >= partition_.destination_vertices;
    // The adapter's global destination is localized at the original R input
    // boundary, exactly as LittleEdgeReader does for compact edges.
    output[lane] = {source_ | (dummy ? 0x80000000u : 0),
                    destination | (dummy ? rg::kDummyDestination : 0)};
  }
  return output;
}

void Reader::evaluate(const CycleContext& context) {
  staged_request_.reset(); staged_response_.reset(); staged_output_ = staged_row_ = false;
  if (phase_ == Phase::kIdle || phase_ == Phase::kDone) return;
  if (!memory_.responses.empty()) {
    AxiResponse response;
    if (!memory_.responses.try_pop(response)) throw std::logic_error("PMA adapter response ownership");
    staged_response_ = std::move(response);
  }
  if (row_ && row_->data && context.domain_cycle >= row_->ready_cycle) staged_row_ = true;
  if (!segments_.empty() && segments_.front().data && context.domain_cycle >= segments_.front().ready_cycle) {
    staged_output_ = output_.try_push(edges(segments_.front()));
    if (!staged_output_) ++counters_.output_stalls;
  }
  std::optional<Pending> request;
  if ((phase_ == Phase::kTotal || phase_ == Phase::kRow) && !row_ && context.domain_cycle >= ready_cycle_) {
    request = row_request(context.domain_cycle);
  } else if (phase_ == Phase::kSegments && next_segment_ < end_segment_ && context.domain_cycle >= ready_cycle_) {
    if (segments_.size() == timing_.segment_capacity) ++counters_.capacity_stalls;
    else if (context.domain_cycle < next_issue_cycle_) ++counters_.interval_stalls;
    else request = segment_request(context.domain_cycle);
  }
  if (request) {
    if (memory_.requests.try_push(AxiRequest{
        .transaction_id = request->transaction, .operation = MemoryOperation::kRead,
        .address = request->address, .bytes = 64, .stream_read_beats = false,
        .target_channel = std::nullopt, .write_data = {}})) staged_request_ = request;
    else ++counters_.request_stalls;
  }
}

void Reader::accept_response(const AxiResponse& response, std::uint64_t cycle) {
  rg::detail::require_read_ack(response, response.transaction_id, 64);
  Pending* pending = nullptr;
  if (row_ && row_->transaction == response.transaction_id) pending = &*row_;
  else {
    const auto found = std::find_if(segments_.begin(), segments_.end(), [&](const auto& segment) {
      return segment.transaction == response.transaction_id;
    });
    if (found != segments_.end()) pending = &*found;
  }
  if (!pending || pending->data) throw std::logic_error("PMA adapter unknown/duplicate response");
  pending->data = rg::detail::property_line(response.read_data);
  pending->ready_cycle = std::max(pending->ready_cycle, cycle + timing_.output_latency);
  ++counters_.acknowledgements;
}

void Reader::accept_row(std::uint64_t cycle) {
  const auto source = phase_ == Phase::kTotal ? partition_.vertices - 1 : source_;
  const auto lane = (source % 8) * 2;
  const auto end = std::min((*row_->data)[lane], partition_.slots);
  const auto begin = (*row_->data)[lane + 1];
  row_.reset();
  if (phase_ == Phase::kTotal) {
    total_slots_ = end;
    if (!total_slots_ || total_slots_ % 16) throw std::logic_error("PMA adapter invalid total slots");
    phase_ = Phase::kRow;
  } else {
    if (begin != previous_end_ || begin > end || begin % 16 || end % 16 || end > total_slots_) {
      throw std::logic_error("PMA adapter noncontiguous/aligned source row");
    }
    begin_ = begin; end_ = end; previous_end_ = end;
    next_segment_ = begin / 16; end_segment_ = end / 16;
    if (begin == end) advance_source(cycle);
    else phase_ = Phase::kSegments;
  }
  ready_cycle_ = std::max(ready_cycle_, cycle + timing_.row_decode_cycles);
}

void Reader::advance_source(std::uint64_t cycle) {
  ++source_;
  if (source_ == partition_.vertices) {
    if (previous_end_ != total_slots_ || emitted_ != total_slots_) {
      throw std::logic_error("PMA adapter incomplete source traversal");
    }
    phase_ = Phase::kDone;
  } else phase_ = Phase::kRow;
  ready_cycle_ = cycle + timing_.source_restart_cycles;
}

void Reader::commit(const CycleContext& context) {
  if (staged_response_) accept_response(*staged_response_, context.domain_cycle);
  if (staged_row_) accept_row(context.domain_cycle);
  if (staged_output_) {
    for (const auto& edge : edges(segments_.front())) {
      ++counters_.physical_edges;
      if (edge.destination & rg::kDummyDestination) ++counters_.dummy_edges;
      else ++counters_.valid_edges;
    }
    emitted_ += 8;
    if (emitted_ >= total_slots_) ++counters_.final_bursts;
    if (++segments_.front().half == 2) segments_.pop_front();
  }
  if (staged_request_) {
    ++next_transaction_; ++counters_.parent_requests; counters_.read_bytes += 64;
    if (phase_ == Phase::kTotal || phase_ == Phase::kRow) {
      row_ = *staged_request_; ++counters_.row_word_reads; counters_.row_bus_bytes += 64;
    } else {
      segments_.push_back(*staged_request_); ++next_segment_;
      ++counters_.segment_reads[staged_request_->route]; counters_.pma_bus_bytes += 64;
      next_issue_cycle_ = context.domain_cycle + timing_.segment_issue_interval;
      counters_.max_segments = std::max(counters_.max_segments, segments_.size());
    }
  }
  if (phase_ == Phase::kSegments && next_segment_ == end_segment_ && segments_.empty()) advance_source(context.domain_cycle);
}

}  // namespace spine::sim::pma_adapter
