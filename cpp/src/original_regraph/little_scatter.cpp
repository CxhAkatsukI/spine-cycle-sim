#include "spine_sim/original_regraph/little_scatter.hpp"

namespace spine::sim::original_regraph {

LittleScatter::LittleScatter(std::string name, ClockId clock, Fifo<EdgeBurst>& edges,
                             Fifo<SourceRequest>& requests, Fifo<SourceResponse>& responses,
                             Fifo<UpdateBurst>& updates, PipelineTiming timing,
                             std::size_t trace_limit)
    : Component(std::move(name), clock), edges_(edges), requests_(requests),
      responses_(responses), updates_(updates), pipeline_(timing), trace_limit_(trace_limit) {
  if (edges.clock_id() != clock || requests.clock_id() != clock ||
      responses.clock_id() != clock || updates.clock_id() != clock) {
    throw std::invalid_argument("Little Scatter port clock mismatch");
  }
}

void LittleScatter::begin_partition(std::uint32_t edges) {
  if (!finished() || !edges_.empty() || !requests_.empty() ||
      !responses_.empty() || !updates_.empty()) {
    throw std::logic_error("Little Scatter restart requires drained queues");
  }
  if (!edges || edges % 8) throw std::invalid_argument("Scatter requires nonempty padded bursts");
  control_ = {};
  control_.expected_bursts = edges / 8;
  control_.phase = Phase::kRequest;
  valid_ = {};
  request_trace_.clear();
}

bool LittleScatter::finished() const noexcept {
  return control_.phase == Phase::kFinished && pipeline_.drained();
}

void LittleScatter::record_request(SourceRequest request) {
  if (!trace_limit_) return;
  if (request_trace_.size() == trace_limit_) ++counters_.trace_dropped;
  else request_trace_.push_back(request);
}

UpdateBurst LittleScatter::map_edge(const Control& control) const {
  UpdateBurst updates;
  for (std::size_t lane = 0; lane < updates.size(); ++lane) {
    const auto source = control.edge[lane].source & 0x7fffffffu;
    const auto round = source / kSourceWindowVertices;
    const auto line = (source % kSourceWindowVertices) / 16;
    const auto bank = round & 1u;
    if (round != control.read_round || valid_[bank][line] != round) {
      throw std::logic_error("Little source cache read is uninitialized or spans source windows");
    }
    updates[lane] = {control.edge[lane].destination, buffers_[lane][bank][line][source % 16]};
  }
  return updates;
}

void LittleScatter::evaluate(const CycleContext& context) {
  next_ = control_;
  loaded_.reset();
  if (const auto* update = pipeline_.ready(context.domain_cycle)) {
    if (updates_.try_push(*update)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (next_.phase == Phase::kRequest) {
    // ap_uint<32> subtraction promotes to signed 33 bits, unlike uint32_t.
    // The negative difference is essential to jump over empty source windows.
    if (static_cast<std::int64_t>(next_.request_round) - next_.read_round <= 1) {
      if (next_.request_round < next_.read_round) next_.request_round = next_.read_round;
      SourceRequest request{next_.request_round, false};
      if (!requests_.try_push(request)) { ++counters_.request_stalls; return; }
      next_.last_request_round = next_.request_round++;
      ++counters_.source_round_requests;
      record_request(request);
    }
    next_.phase = Phase::kResponse;
  }
  if (next_.phase == Phase::kResponse) {
    SourceResponse response;
    if (responses_.try_pop(response)) {
      if (response.end) throw std::logic_error("unexpected early source terminator");
      loaded_ = response;
      next_.write_round = response.line / kSourceWindowLines;
    }
    next_.phase = Phase::kEdge;
  }
  if (next_.phase == Phase::kEdge) {
    if (!next_.waiting) {
      if (!edges_.try_pop(next_.edge)) { ++counters_.edge_wait_cycles; return; }
    }
    next_.read_round = (next_.edge[0].source & 0x7fffffffu) / kSourceWindowVertices;
    next_.waiting = next_.read_round >= next_.write_round;
    if (next_.waiting) {
      ++counters_.source_wait_cycles;
      next_.phase = Phase::kRequest;
      return;
    }
    next_.phase = Phase::kEmit;
  }
  if (next_.phase == Phase::kEmit && pipeline_.can_accept(context.domain_cycle)) {
    pipeline_.stage_accept(map_edge(next_), context.domain_cycle);
    ++counters_.bursts;
    counters_.source_lookups += 8;
    next_.phase = ++next_.emitted_bursts == next_.expected_bursts
                      ? Phase::kEndRequest : Phase::kRequest;
    return;
  }
  if (next_.phase == Phase::kEndRequest) {
    SourceRequest end{next_.last_request_round, true};
    if (requests_.try_push(end)) {
      ++counters_.end_requests;
      record_request(end);
      next_.phase = Phase::kDrain;
    } else ++counters_.request_stalls;
    return;
  }
  if (next_.phase == Phase::kDrain) {
    SourceResponse response;
    if (responses_.try_pop(response)) {
      if (response.end) { next_.phase = Phase::kFinished; ++counters_.end_responses; }
      else ++counters_.source_lines_discarded;
    }
  }
}

void LittleScatter::commit(const CycleContext& context) {
  if (loaded_) {
    const auto round = loaded_->line / kSourceWindowLines;
    const auto line = loaded_->line % kSourceWindowLines;
    for (auto& lane : buffers_) lane[round & 1u][line] = loaded_->data;
    valid_[round & 1u][line] = round;
    ++counters_.source_lines_loaded;
    counters_.buffer_write_bytes += 64 * 8;
  }
  control_ = next_;
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
