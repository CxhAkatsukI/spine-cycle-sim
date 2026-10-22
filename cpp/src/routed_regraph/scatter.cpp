#include "../detail/routed_regraph_scatter.hpp"

namespace spine::sim::detail {

RoutedScatter::RoutedScatter(std::string name, ClockId clock, GraphAlgorithmPolicy policy,
    ReGraphPmaFormat format, Fifo<ReGraphPmaPacket> &edges, RoutedSourceWorker source,
    Fifo<PmaEdgeBatch> &output, RoutedScatterTiming timing, RoutedSourceLoading loading)
    : Component(std::move(name), clock), policy_(std::move(policy)), format_(format),
      edges_(edges), source_(source), output_(output), timing_(timing), loading_(loading) {
  if (!timing.latency || !timing.initiation_interval || !timing.capacity)
    throw std::invalid_argument("routed Scatter requires a finite positive pipeline");
  if (loading != RoutedSourceLoading::kEdgeCoupled &&
      loading != RoutedSourceLoading::kIndependentExperimental)
    throw std::invalid_argument("unsupported routed source-cache loading schedule");
  if (!source.requests || !source.responses || source.requests->clock_id() != clock ||
      source.responses->clock_id() != clock || edges.clock_id() != clock || output.clock_id() != clock)
    throw std::invalid_argument("routed Scatter queue wiring is invalid");
}

void RoutedScatter::start_partition(RoutedScatterPartition partition) {
  if ((control_.phase != Phase::kIdle && !finished()) || !source_.requests->empty() ||
      !source_.responses->empty() || !output_.empty())
    throw std::logic_error("routed Scatter restart requires drained prior invocation");
  if (!partition.physical_slots || partition.physical_slots % 8 ||
      !partition.destination_vertices || partition.destination_vertices > 65536 ||
      partition.destination_base > 0x7fffffffU - partition.destination_vertices)
    throw std::invalid_argument("routed Scatter requires nonempty padded input and a local destination partition");
  // Adapter invocations may run ahead, so their raw input FIFO need not be empty.
  partition_ = partition;
  control_ = {};
  control_.phase = Phase::kRequest;
  stream_done_ = false;
  valid_ = {};
  next_issue_ = 0;
}

bool RoutedScatter::finished() const noexcept {
  return control_.phase == Phase::kFinished && pipeline_.empty();
}

PmaEdgeBatch RoutedScatter::map_sources() const {
  PmaEdgeBatch result{.per_lane_source = true, .lanes = 8};
  for (std::size_t lane = 0; lane < 8; ++lane) {
    const auto source = next_.edge.sources[lane] & 0x7fffffffU;
    const auto round = source / kRoutedSourceVertices;
    const auto line = (source % kRoutedSourceVertices) / 16;
    if (round != next_.read_round || valid_[round & 1][line] != round)
      throw std::logic_error("routed Scatter source cache is uninitialized or packet crosses source windows");
    const auto encoded = cache_[round & 1][line][source % 16];
    const auto kind = policy_.config().kind;
    if (kind == GraphAlgorithmKind::kFullPageRank || kind == GraphAlgorithmKind::kResidualPageRank) {
      // The routed PR host/apply path provides already degree-scaled FP32 words.
      result.source_payloads[lane] = encoded;
      result.source_actives[lane] = GraphAlgorithmPolicy::word_to_float(encoded) != 0.0F;
    } else {
      result.source_payloads[lane] = decode_policy_value(policy_, encoded);
      result.source_actives[lane] = (encoded & kReGraphActive) != 0;
    }
    const auto destination = next_.edge.destinations[lane];
    result.valid[lane] = (destination & 0x80000000U) == 0;
    if ((next_.edge.sources[lane] >> 31) != (destination >> 31))
      throw std::logic_error("routed adapter source/destination dummy flags disagree");
    if (format_ == ReGraphPmaFormat::kDestination) {
      const auto global = destination & 0x7fffffffU;
      if (result.valid[lane] && (global < partition_.destination_base ||
          global - partition_.destination_base >= partition_.destination_vertices))
        throw std::out_of_range("routed global destination is outside its shard");
      result.destinations[lane] = global - partition_.destination_base;
      result.weights[lane] = 1;
    } else {
      result.destinations[lane] = destination & 0x7ffffU;
      result.weights[lane] = (destination >> 19) & 0xfffU;
      if (result.valid[lane] && result.destinations[lane] >= partition_.destination_vertices)
        throw std::out_of_range("routed local destination is outside its shard");
    }
  }
  return result;
}

void RoutedScatter::load_source_line() {
  ReGraphSourceCacheResponse response;
  if (!source_.responses->try_pop(response)) return;
  if (response.end || response.line >= kRoutedSourceLines || response.vertices != 16)
    throw std::logic_error("routed Scatter received an early end or invalid source line");
  loaded_ = response;
  next_.write_round = response.source_round;
}

void RoutedScatter::evaluate(const CycleContext &context) {
  next_ = control_;
  loaded_.reset(); accepted_.reset(); retired_ = false;
  if (!pipeline_.empty() && pipeline_.front().ready <= context.domain_cycle) {
    retired_ = output_.try_push(pipeline_.front().batch);
    if (!retired_) ++counters_.output_stalls;
    else ++next_.emitted;
  }
  // At most one returned line/cycle, even when the edge path is stalled.
  // Requests still look ahead by one window; alternating banks prevent an
  // in-use window from being overwritten. Cache writes commit at the edge.
  if (loading_ == RoutedSourceLoading::kIndependentExperimental &&
      (next_.phase == Phase::kRequest || next_.phase == Phase::kResponse ||
       next_.phase == Phase::kEdge || next_.phase == Phase::kEmit))
    load_source_line();
  if (next_.phase == Phase::kRequest) {
    // HLS ap_uint subtraction here is signed 33-bit, allowing skipped windows.
    if (static_cast<std::int64_t>(next_.request_round) - static_cast<std::int64_t>(next_.read_round) <= 1) {
      next_.request_round = std::max(next_.request_round, next_.read_round);
      if (!source_.requests->try_push({next_.request_round, false})) { ++counters_.request_stalls; return; }
      next_.last_request = next_.request_round++;
      ++counters_.source_requests;
    }
    next_.phase = Phase::kResponse;
  }
  if (next_.phase == Phase::kResponse) {
    if (loading_ == RoutedSourceLoading::kEdgeCoupled) load_source_line();
    next_.phase = Phase::kEdge;
  }
  if (next_.phase == Phase::kEdge) {
    if (!next_.waiting && !edges_.try_pop(next_.edge)) { ++counters_.edge_waits; return; }
    next_.read_round = (next_.edge.sources[0] & 0x7fffffffU) / kRoutedSourceVertices;
    next_.waiting = next_.read_round >= next_.write_round;
    if (next_.waiting) { ++counters_.source_waits; next_.phase = Phase::kRequest; return; }
    next_.phase = Phase::kEmit;
  }
  if (next_.phase == Phase::kEmit) {
    if (pipeline_.size() == timing_.capacity || context.domain_cycle < next_issue_) {
      ++counters_.pipeline_stalls; return;
    }
    const auto at_bound = next_.accepted + 1 == partition_.physical_slots / 8;
    if ((!partition_.terminal_framed && next_.edge.last != at_bound) ||
        (partition_.terminal_framed && (next_.accepted >= partition_.physical_slots / 8 ||
                                      (at_bound && !next_.edge.last))))
      throw std::logic_error("routed adapter TLAST disagrees with declared packet count");
    accepted_ = Entry{context.domain_cycle + timing_.latency, map_sources()};
    ++next_.accepted;
    next_.terminal_accepted = next_.edge.last;
    next_.phase = next_.edge.last ? Phase::kEndRequest : Phase::kRequest;
    return;
  }
  if (next_.phase == Phase::kEndRequest) {
    if (source_.requests->try_push({next_.last_request, true})) {
      ++counters_.end_requests; next_.phase = Phase::kDrain;
    } else ++counters_.request_stalls;
    return;
  }
  if (next_.phase == Phase::kDrain) {
    ReGraphSourceCacheResponse response;
    if (source_.responses->try_pop(response)) {
      if (response.end) { ++counters_.end_responses; next_.phase = Phase::kFinished; }
      else ++counters_.discarded_lines;
    }
  }
}

void RoutedScatter::commit(const CycleContext &context) {
  if (loaded_) {
    cache_[loaded_->source_round & 1][loaded_->line] = loaded_->words;
    valid_[loaded_->source_round & 1][loaded_->line] = loaded_->source_round;
    ++counters_.source_lines;
    counters_.buffer_write_bytes += 64 * 8;
  }
  if (retired_) { pipeline_.pop_front(); ++counters_.emitted; }
  if (accepted_) {
    pipeline_.push_back(std::move(*accepted_));
    ++counters_.packets;
    counters_.max_inflight = std::max(counters_.max_inflight, pipeline_.size());
    next_issue_ = context.domain_cycle + timing_.initiation_interval;
  }
  control_ = next_;
  if (!stream_done_ && control_.terminal_accepted && control_.emitted == control_.accepted) {
    stream_done_ = true;
    notify_done();
  }
}

} // namespace spine::sim::detail
