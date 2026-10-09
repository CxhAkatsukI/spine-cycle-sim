#include "spine_sim/original_regraph/edge_reader.hpp"

#include <limits>

#include "spine_sim/original_regraph/detail/wire.hpp"

namespace spine::sim::original_regraph {

LittleEdgeReader::LittleEdgeReader(std::string name, ClockId clock, ReadPort memory,
                                   Fifo<EdgeBurst>& output, PipelineTiming timing)
    : Component(std::move(name), clock), memory_(memory), output_(output), pipeline_(timing) {
  detail::validate_port(memory, clock);
  if (output.clock_id() != clock) throw std::invalid_argument("edge output clock mismatch");
}

void LittleEdgeReader::begin_partition(std::uint64_t address, std::uint64_t edges,
                                      std::uint32_t destination_offset) {
  if (!finished() || !output_.empty() || !memory_.requests.empty() ||
      !memory_.responses.empty() || !memory_.beats.empty()) {
    throw std::logic_error("edge reader restart requires drained queues");
  }
  if (!edges || edges > std::numeric_limits<std::uint32_t>::max() || edges % 8 || address % 64 ||
      edges > (std::numeric_limits<std::uint64_t>::max() - address) / 8) {
    throw std::invalid_argument("edge partition requires aligned nonempty padded bursts");
  }
  started_ = true;
  issued_ = acknowledged_ = false;
  address_ = address;
  bursts_ = edges / 8;
  received_ = 0;
  destination_offset_ = destination_offset;
  transaction_ = next_transaction_++;
}

bool LittleEdgeReader::finished() const noexcept {
  return !started_ || (issued_ && acknowledged_ && received_ == bursts_ && pipeline_.drained());
}

void LittleEdgeReader::evaluate(const CycleContext& context) {
  stage_issue_ = stage_ack_ = stage_beat_ = false;
  if (!started_) return;
  if (const auto* edge = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*edge)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (!issued_) {
    stage_issue_ = memory_.requests.try_push(AxiRequest{
        .transaction_id = transaction_, .operation = MemoryOperation::kRead,
        .address = address_, .bytes = bursts_ * 64, .stream_read_beats = true,
        .target_channel = std::nullopt, .write_data = {}});
  }
  if (!acknowledged_ && !memory_.responses.empty()) {
    AxiResponse response;
    if (memory_.responses.try_pop(response)) {
      detail::require_read_ack(response, transaction_, bursts_ * 64);
      stage_ack_ = true;
    }
  }
  if (!memory_.beats.empty() && pipeline_.can_accept(context.domain_cycle)) {
    AxiReadBeatResponse beat;
    if (!memory_.beats.try_pop(beat)) throw std::logic_error("edge beat ownership mismatch");
    if (!beat.success || beat.transaction_id != transaction_ || received_ >= bursts_ ||
        beat.address != address_ + received_ * 64 || beat.parent_offset != received_ * 64 ||
        beat.last != (received_ + 1 == bursts_)) {
      throw std::logic_error("edge beat address/order/extent mismatch");
    }
    EdgeBurst edges;
    for (std::size_t lane = 0; lane < edges.size(); ++lane) {
      const auto global = detail::word(beat.read_data, lane * 2 + 1);
      const auto local = ((global & 0x7fffffffu) - destination_offset_) & 0x7ffffu;
      edges[lane] = {detail::word(beat.read_data, lane * 2),
                    local | ((global >> 31) ? kDummyDestination : 0)};
    }
    pipeline_.stage_accept(edges, context.domain_cycle);
    stage_beat_ = true;
  }
}

void LittleEdgeReader::commit(const CycleContext& context) {
  if (stage_issue_) { issued_ = true; ++counters_.parent_requests; }
  if (stage_ack_) { acknowledged_ = true; ++counters_.acknowledgements; }
  if (stage_beat_) {
    ++received_;
    counters_.physical_edges += 8;
    counters_.read_bytes += 64;
  }
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
