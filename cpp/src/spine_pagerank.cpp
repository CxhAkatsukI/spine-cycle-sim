#include "spine_sim/spine_pagerank.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kWordBytes = sizeof(std::uint32_t);

std::vector<std::uint8_t> encode_u32(std::uint32_t value) {
  return {
      static_cast<std::uint8_t>(value & 0xffU),
      static_cast<std::uint8_t>((value >> 8) & 0xffU),
      static_cast<std::uint8_t>((value >> 16) & 0xffU),
      static_cast<std::uint8_t>((value >> 24) & 0xffU),
  };
}

std::uint32_t decode_u32(const std::vector<std::uint8_t> &data) {
  if (data.size() != kWordBytes) {
    throw std::invalid_argument("PageRank state word has the wrong size");
  }
  return static_cast<std::uint32_t>(data[0]) |
         (static_cast<std::uint32_t>(data[1]) << 8) |
         (static_cast<std::uint32_t>(data[2]) << 16) |
         (static_cast<std::uint32_t>(data[3]) << 24);
}

std::vector<std::uint8_t> encode_words(
    const std::vector<std::uint32_t> &words) {
  std::vector<std::uint8_t> payload;
  payload.reserve(words.size() * kWordBytes);
  for (const std::uint32_t word : words) {
    const std::vector<std::uint8_t> encoded = encode_u32(word);
    payload.insert(payload.end(), encoded.begin(), encoded.end());
  }
  return payload;
}

}  // namespace

SpineSplitPageRankCompute::SpineSplitPageRankCompute(
    std::string name, ClockId clock_id, GraphAlgorithmPolicy policy,
    std::vector<std::uint32_t> out_degrees, FixedAxiPort &vertex_state,
    FixedAxiPort *active_out, Fifo<PartConvWord> &edge_in,
    Fifo<SourceValueWord> &value_out,
    AlgorithmPipelineConfig pipeline_config,
    std::size_t memory_request_window, std::size_t tile_vertices,
    std::optional<AlgorithmInitialState> initial_state)
    : Component(std::move(name), clock_id),
      policy_(std::move(policy)),
      vertices_(policy_.config().vertices),
      tile_vertices_(tile_vertices),
      vertex_state_(vertex_state),
      active_out_(active_out),
      edge_in_(edge_in),
      value_out_(value_out),
      state_layout_(policy_.state_layout()),
      primary_read_base_(state_layout_.primary_read.base),
      primary_write_base_(state_layout_.primary_write.base),
      memory_request_window_(memory_request_window),
      source_requests_("pagerank-source-requests", clock_id, 16),
      source_responses_("pagerank-source-responses", clock_id, 16),
      edge_requests_("pagerank-edge-requests", clock_id, 16),
      edge_responses_("pagerank-edge-responses", clock_id, 16),
      reduce_requests_("pagerank-reduce-requests", clock_id, 32),
      reduce_responses_("pagerank-reduce-responses", clock_id, 32),
      apply_requests_("pagerank-apply-requests", clock_id, 32),
      apply_responses_("pagerank-apply-responses", clock_id, 32),
      pipeline_(
          "pagerank-algorithm-pipeline", clock_id, policy_, pipeline_config,
          AlgorithmPipelinePorts{
              .source_requests = &source_requests_,
              .source_responses = &source_responses_,
              .edge_requests = &edge_requests_,
              .edge_responses = &edge_responses_,
              .reduce_requests = &reduce_requests_,
              .reduce_responses = &reduce_responses_,
              .apply_requests = &apply_requests_,
              .apply_responses = &apply_responses_,
          }),
      rank_words_(vertices_),
      residual_words_(vertices_),
      tile_applied_((vertices_ + tile_vertices_ - 1) / tile_vertices_, false),
      dangling_mass_word_(GraphAlgorithmPolicy::float_to_word(0.0F)),
      dangling_share_word_(GraphAlgorithmPolicy::float_to_word(0.0F)) {
  const bool uses_degree = state_layout_.degree.has_value();
  if ((policy_.config().kind != GraphAlgorithmKind::kFullPageRank &&
       policy_.config().kind != GraphAlgorithmKind::kResidualPageRank &&
       policy_.config().kind != GraphAlgorithmKind::kConnectedComponents) ||
      vertices_ == 0 ||
      (uses_degree ? out_degrees.size() != vertices_
                   : !out_degrees.empty()) ||
      tile_vertices_ == 0 || memory_request_window_ == 0 ||
      edge_in_.clock_id() != clock_id || value_out_.clock_id() != clock_id ||
      vertex_state_.master().clock_id() != clock_id ||
      (active_out_ != nullptr &&
       active_out_->master().clock_id() != clock_id)) {
    throw std::invalid_argument("invalid Spine PageRank compute configuration");
  }
  initialize_state_payload(out_degrees, initial_state);
}

void SpineSplitPageRankCompute::register_components(Scheduler &scheduler) {
  if (registered_) {
    throw std::logic_error("Spine PageRank compute already registered");
  }
  registered_ = true;
  scheduler.add_component(*this);
  scheduler.add_component(source_requests_);
  scheduler.add_component(source_responses_);
  scheduler.add_component(edge_requests_);
  scheduler.add_component(edge_responses_);
  scheduler.add_component(reduce_requests_);
  scheduler.add_component(reduce_responses_);
  scheduler.add_component(apply_requests_);
  scheduler.add_component(apply_responses_);
  scheduler.add_component(pipeline_);
}

void SpineSplitPageRankCompute::configure_initial_start_gate(
    const bool *start_ready) {
  if (registered_ || start_ready == nullptr) {
    throw std::invalid_argument(
        "PageRank initial start gate must be configured before registration");
  }
  initial_start_gate_ = start_ready;
}

float SpineSplitPageRankCompute::dangling_mass() const noexcept {
  return GraphAlgorithmPolicy::word_to_float(dangling_mass_word_);
}

float SpineSplitPageRankCompute::dangling_share() const noexcept {
  return GraphAlgorithmPolicy::word_to_float(dangling_share_word_);
}

void SpineSplitPageRankCompute::reset_iteration() {
  if (!done_ || failed_ || !memory_drained() ||
      !algorithm_queues_drained() || !edge_reductions_.empty() ||
      !apply_transactions_.empty() || !pending_destinations_.empty() ||
      !ready_apply_.empty()) {
    throw std::logic_error("PageRank iteration reset requires a clean drain");
  }
  if (state_layout_.primary_ping_pong) {
    std::swap(primary_read_base_, primary_write_base_);
  }
  pipeline_.reset_counters();
  source_requests_.reset_stats();
  source_responses_.reset_stats();
  edge_requests_.reset_stats();
  edge_responses_.reset_stats();
  reduce_requests_.reset_stats();
  reduce_responses_.reset_stats();
  apply_requests_.reset_stats();
  apply_responses_.reset_stats();
  counters_ = {};
  std::fill(tile_applied_.begin(), tile_applied_.end(), false);
  tile_accumulators_.clear();
  next_active_.clear();
  phase_ = Phase::kInput;
  staged_input_action_ = InputAction::kNone;
  staged_memory_response_.reset();
  staged_source_response_.reset();
  staged_reduce_response_.reset();
  staged_apply_response_.reset();
  staged_source_request_.reset();
  staged_reduce_request_.reset();
  staged_apply_request_.reset();
  staged_apply_read_vertex_.reset();
  staged_phase_transition_.reset();
  staged_memory_issue_ = false;
  staged_value_push_ = false;
  staged_apply_tile_complete_ = false;
  staged_done_ = false;
  pending_source_ = 0;
  pending_source_rank_.reset();
  pending_source_residual_.reset();
  pending_source_degree_.reset();
  pending_source_result_.reset();
  pending_dangling_transaction_.reset();
  dangling_mass_word_ = GraphAlgorithmPolicy::float_to_word(0.0F);
  dangling_share_word_ = GraphAlgorithmPolicy::float_to_word(0.0F);
  tile_base_ = 0;
  tile_size_ = 0;
  apply_reads_issued_ = 0;
  apply_reads_completed_ = 0;
  apply_operations_issued_ = 0;
  apply_operations_completed_ = 0;
  apply_writes_completed_ = 0;
  iteration_error_ = 0.0F;
  source_count_seen_ = false;
  source_generation_seen_ = false;
  source_ack_pending_ = false;
  tile_open_ = false;
  reader_done_seen_ = false;
  done_ = false;
}

void SpineSplitPageRankCompute::initialize_state_payload(
    const std::vector<std::uint32_t> &out_degrees,
    const std::optional<AlgorithmInitialState> &initial_state) {
  if (initial_state.has_value() &&
      (initial_state->primary.size() != vertices_ ||
       (state_layout_.auxiliary.has_value()
            ? initial_state->auxiliary.size() != vertices_
            : !initial_state->auxiliary.empty()) ||
       std::any_of(initial_state->active_vertices.begin(),
                   initial_state->active_vertices.end(),
                   [this](std::uint32_t vertex) {
                     return vertex >= vertices_;
                   }))) {
    throw std::invalid_argument("invalid Spine algorithm initial state");
  }
  for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
    const AlgorithmVertexState initial =
        initial_state.has_value()
            ? AlgorithmVertexState{
                  .primary = initial_state->primary[vertex],
                  .auxiliary = state_layout_.auxiliary.has_value()
                                   ? initial_state->auxiliary[vertex]
                                   : 0U,
              }
            : policy_.initial_state(static_cast<std::uint32_t>(vertex));
    rank_words_[vertex] = initial.primary;
    residual_words_[vertex] = initial.auxiliary;
  }
  vertex_state_.initialize_payload(primary_read_base_, encode_words(rank_words_));
  if (state_layout_.primary_ping_pong) {
    vertex_state_.fill_payload(primary_write_base_, vertices_ * kWordBytes, 0);
  }
  if (state_layout_.auxiliary.has_value()) {
    vertex_state_.initialize_payload(state_layout_.auxiliary->base,
                                     encode_words(residual_words_));
  }
  if (state_layout_.degree.has_value()) {
    vertex_state_.initialize_payload(state_layout_.degree->base,
                                     encode_words(out_degrees));
  }
}

void SpineSplitPageRankCompute::enqueue_read(std::uint64_t address,
                                              MemoryPayloadKind kind,
                                              std::uint32_t vertex) {
  memory_tasks_.push_back(MemoryTask{
      .port = &vertex_state_,
      .operation = MemoryOperation::kRead,
      .address = address,
      .bytes = kWordBytes,
      .write_data = {},
      .kind = kind,
      .vertex = vertex,
  });
  if (kind == MemoryPayloadKind::kSourceDegree) {
    counters_.degree_read_bytes += kWordBytes;
  } else if (kind == MemoryPayloadKind::kSourceAuxiliary ||
             kind == MemoryPayloadKind::kApplyAuxiliary) {
    counters_.auxiliary_read_bytes += kWordBytes;
  } else {
    counters_.primary_read_bytes += kWordBytes;
  }
}

void SpineSplitPageRankCompute::enqueue_write(std::uint64_t address,
                                               std::uint32_t value,
                                               MemoryPayloadKind kind,
                                               std::uint32_t vertex) {
  memory_tasks_.push_back(MemoryTask{
      .port = &vertex_state_,
      .operation = MemoryOperation::kWrite,
      .address = address,
      .bytes = kWordBytes,
      .write_data = encode_u32(value),
      .kind = kind,
      .vertex = vertex,
  });
  if (kind == MemoryPayloadKind::kSourceAuxiliaryWrite ||
      kind == MemoryPayloadKind::kApplyAuxiliaryWrite) {
    counters_.auxiliary_write_bytes += kWordBytes;
  } else if (kind == MemoryPayloadKind::kActiveOutputWrite) {
    counters_.active_out_write_bytes += 8;
  } else {
    counters_.primary_write_bytes += kWordBytes;
  }
}

void SpineSplitPageRankCompute::enqueue_active_output(
    std::size_t index, std::uint32_t vertex, std::uint32_t value) {
  if (active_out_ == nullptr) {
    return;
  }
  std::vector<std::uint8_t> payload(8, 0);
  const std::vector<std::uint8_t> encoded_value = encode_u32(value);
  const std::vector<std::uint8_t> encoded_vertex = encode_u32(vertex);
  std::copy(encoded_value.begin(), encoded_value.end(), payload.begin());
  std::copy(encoded_vertex.begin(), encoded_vertex.end(),
            payload.begin() + sizeof(std::uint32_t));
  memory_tasks_.push_back(MemoryTask{
      .port = active_out_,
      .operation = MemoryOperation::kWrite,
      .address = index * 8,
      .bytes = 8,
      .write_data = std::move(payload),
      .kind = MemoryPayloadKind::kActiveOutputWrite,
      .vertex = vertex,
  });
  counters_.active_out_write_bytes += 8;
}

bool SpineSplitPageRankCompute::memory_drained() const noexcept {
  return memory_tasks_.empty() && inflight_memory_.empty() &&
         !staged_memory_response_.has_value() && !staged_memory_issue_;
}

bool SpineSplitPageRankCompute::algorithm_queues_drained() const noexcept {
  return source_requests_.empty() && source_responses_.empty() &&
         edge_requests_.empty() && edge_responses_.empty() &&
         reduce_requests_.empty() && reduce_responses_.empty() &&
         apply_requests_.empty() && apply_responses_.empty() &&
         pipeline_.drained();
}

bool SpineSplitPageRankCompute::tile_apply_drained() const noexcept {
  return apply_reads_issued_ == tile_size_ &&
         apply_reads_completed_ == tile_size_ &&
         apply_operations_issued_ == tile_size_ &&
         apply_operations_completed_ == tile_size_ &&
         apply_writes_completed_ == tile_size_ && ready_apply_.empty() &&
         apply_transactions_.empty() && memory_drained() &&
         algorithm_queues_drained();
}

void SpineSplitPageRankCompute::set_protocol_status(
    SpineSourceProtocolStatus status) {
  if (counters_.source_protocol_status ==
      static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk)) {
    counters_.source_protocol_status = static_cast<std::uint32_t>(status);
  }
}

void SpineSplitPageRankCompute::begin_apply_tile(std::uint32_t tile_base,
                                                 bool empty_tile) {
  if (tile_base >= vertices_ || tile_base % tile_vertices_ != 0) {
    failed_ = true;
    return;
  }
  tile_base_ = tile_base;
  tile_size_ = std::min<std::size_t>(tile_vertices_, vertices_ - tile_base_);
  if (tile_accumulators_.size() != tile_size_) {
    tile_accumulators_.assign(tile_size_, policy_.reduction_identity_word());
  }
  tile_applied_.at(tile_base_ / tile_vertices_) = true;
  apply_reads_issued_ = 0;
  apply_reads_completed_ = 0;
  apply_operations_issued_ = 0;
  apply_operations_completed_ = 0;
  apply_writes_completed_ = 0;
  if (empty_tile) {
    ++counters_.empty_tiles_applied;
  }
  phase_ = Phase::kApplyTile;
}

std::optional<std::uint32_t>
SpineSplitPageRankCompute::next_unapplied_tile() const {
  for (std::size_t tile = 0; tile < tile_applied_.size(); ++tile) {
    if (!tile_applied_[tile]) {
      const std::uint64_t base = tile * tile_vertices_;
      if (base > std::numeric_limits<std::uint32_t>::max()) {
        throw std::overflow_error("PageRank tile base exceeds stream field");
      }
      return static_cast<std::uint32_t>(base);
    }
  }
  return std::nullopt;
}

void SpineSplitPageRankCompute::advance_after_apply_tile() {
  tile_accumulators_.clear();
  if (!reader_done_seen_) {
    phase_ = Phase::kInput;
    return;
  }
  const std::optional<std::uint32_t> next = next_unapplied_tile();
  if (next.has_value()) {
    begin_apply_tile(*next, true);
  } else {
    phase_ = Phase::kFinish;
  }
}

void SpineSplitPageRankCompute::consume_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (!response.success || response.operation != task.operation) {
    failed_ = true;
    return;
  }
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty() ||
        (task.kind != MemoryPayloadKind::kSourcePrimaryWrite &&
         task.kind != MemoryPayloadKind::kSourceAuxiliaryWrite &&
         task.kind != MemoryPayloadKind::kApplyPrimaryWrite &&
         task.kind != MemoryPayloadKind::kApplyAuxiliaryWrite &&
         task.kind != MemoryPayloadKind::kActiveOutputWrite)) {
      failed_ = true;
      return;
    }
    if (task.kind == MemoryPayloadKind::kApplyPrimaryWrite ||
        task.kind == MemoryPayloadKind::kApplyAuxiliaryWrite) {
      ++apply_writes_completed_;
    }
    return;
  }
  const std::uint32_t value = decode_u32(response.read_data);
  switch (task.kind) {
    case MemoryPayloadKind::kSourcePrimary:
      pending_source_rank_ = value;
      return;
    case MemoryPayloadKind::kSourceAuxiliary:
      pending_source_residual_ = value;
      return;
    case MemoryPayloadKind::kSourceDegree:
      pending_source_degree_ = value;
      return;
    case MemoryPayloadKind::kApplyPrimary: {
      if (task.vertex < tile_base_ ||
          static_cast<std::size_t>(task.vertex - tile_base_) >=
              tile_accumulators_.size()) {
        failed_ = true;
        return;
      }
      const std::uint32_t reduced =
          tile_accumulators_[task.vertex - tile_base_];
      ready_apply_.push_back(ReadyApply{
          .vertex = task.vertex,
          .old_state = {.primary = value},
          .reduced = reduced,
      });
      ++apply_reads_completed_;
      return;
    }
    case MemoryPayloadKind::kApplyAuxiliary: {
      if (task.vertex < tile_base_ ||
          static_cast<std::size_t>(task.vertex - tile_base_) >=
              tile_accumulators_.size()) {
        failed_ = true;
        return;
      }
      const std::uint32_t reduced =
          tile_accumulators_[task.vertex - tile_base_];
      ready_apply_.push_back(ReadyApply{
          .vertex = task.vertex,
          .old_state = {
              .primary = rank_words_.at(task.vertex),
              .auxiliary = value,
          },
          .reduced = reduced,
      });
      ++apply_reads_completed_;
      return;
    }
    case MemoryPayloadKind::kSourcePrimaryWrite:
    case MemoryPayloadKind::kSourceAuxiliaryWrite:
    case MemoryPayloadKind::kApplyPrimaryWrite:
    case MemoryPayloadKind::kApplyAuxiliaryWrite:
    case MemoryPayloadKind::kActiveOutputWrite:
      failed_ = true;
      return;
  }
}

void SpineSplitPageRankCompute::evaluate(const CycleContext &) {
  staged_input_action_ = InputAction::kNone;
  staged_memory_response_.reset();
  staged_source_response_.reset();
  staged_reduce_response_.reset();
  staged_apply_response_.reset();
  staged_source_request_.reset();
  staged_reduce_request_.reset();
  staged_apply_request_.reset();
  staged_apply_read_vertex_.reset();
  staged_phase_transition_.reset();
  staged_memory_issue_ = false;
  staged_value_push_ = false;
  staged_apply_tile_complete_ = false;
  staged_done_ = false;
  if (done_ || failed_) {
    return;
  }
  if (initial_start_gate_ != nullptr && !*initial_start_gate_) {
    return;
  }

  const auto stage_memory_response = [this](FixedAxiPort &port) {
    const AxiResponse *memory_response = port.responses().front();
    if (memory_response == nullptr) {
      return false;
    }
    const std::uint64_t transaction_id = memory_response->transaction_id;
    const auto found = inflight_memory_.find(transaction_id);
    if (found == inflight_memory_.end()) {
      failed_ = true;
      return true;
    }
    AxiResponse staged;
    if (port.responses().try_pop(staged)) {
      staged_memory_response_ =
          std::make_pair(transaction_id, std::move(staged));
    }
    return true;
  };
  if (stage_memory_response(vertex_state_)) {
    if (failed_) {
      return;
    }
  } else if (active_out_ != nullptr &&
             stage_memory_response(*active_out_)) {
    if (failed_) {
      return;
    }
  }

  if (!memory_tasks_.empty()) {
    if (inflight_memory_.size() >= memory_request_window_) {
      ++counters_.memory_window_stall_cycles;
    } else {
      const MemoryTask &task = memory_tasks_.front();
      if (task.port == nullptr) {
        failed_ = true;
        return;
      }
      if (task.port->requests().try_push(AxiRequest{
              .transaction_id = next_memory_transaction_,
              .operation = task.operation,
              .address = task.address,
              .bytes = task.bytes,
              .write_data = task.write_data,
          })) {
        staged_memory_issue_ = true;
      } else {
        ++counters_.memory_request_fifo_stall_cycles;
      }
    }
  }

  if (phase_ == Phase::kSourceMapWait) {
    AlgorithmPipelineResponse response;
    if (source_responses_.try_pop(response)) {
      staged_source_response_ = response;
    }
  }
  if (phase_ == Phase::kDanglingReduceWait || phase_ == Phase::kInput) {
    AlgorithmPipelineResponse response;
    if (reduce_responses_.try_pop(response)) {
      staged_reduce_response_ = response;
    }
  }
  if (phase_ == Phase::kApplyTile) {
    AlgorithmPipelineResponse response;
    if (apply_responses_.try_pop(response)) {
      staged_apply_response_ = response;
    }
  }

  switch (phase_) {
    case Phase::kSourceMemory:
      if (pending_source_rank_.has_value() &&
          (!state_layout_.degree.has_value() ||
           pending_source_degree_.has_value()) &&
          (!state_layout_.auxiliary.has_value() ||
           pending_source_residual_.has_value())) {
        staged_phase_transition_ = Phase::kSourceMapPush;
      }
      return;
    case Phase::kSourceMapPush: {
      AlgorithmPipelineRequest request{};
      request.stage = AlgorithmPipelineStage::kSourceMap;
      request.transaction_id = next_algorithm_transaction_;
      request.state.primary = *pending_source_rank_;
      request.state.auxiliary = pending_source_residual_.value_or(0);
      request.out_degree = pending_source_degree_.value_or(0);
      if (source_requests_.try_push(request)) {
        staged_source_request_ = request;
      }
      return;
    }
    case Phase::kSourceMapWait:
      return;
    case Phase::kDanglingReducePush: {
      AlgorithmPipelineRequest request{};
      request.stage = AlgorithmPipelineStage::kReduce;
      request.transaction_id = next_algorithm_transaction_;
      request.current = dangling_mass_word_;
      request.candidate = pending_source_result_->dangling_payload;
      if (reduce_requests_.try_push(request)) {
        staged_reduce_request_ = request;
      }
      return;
    }
    case Phase::kDanglingReduceWait:
      return;
    case Phase::kSourceStateWriteWait:
      if (memory_drained()) {
        staged_phase_transition_ = Phase::kSourceReply;
      }
      return;
    case Phase::kSourceReply:
      staged_value_word_ = source_ack_pending_
                               ? SourceValueWord{
                                     .kind = SourceValueWord::Kind::kProtocolAck,
                                     .source = 0,
                                     .value = counters_.source_protocol_status,
                                 }
                               : SourceValueWord{
                                     .kind = SourceValueWord::Kind::kSourceValue,
                                     .source = pending_source_,
                                     .value = pending_source_result_->edge_payload,
                                 };
      staged_value_push_ = value_out_.try_push(staged_value_word_);
      return;
    case Phase::kApplyTile:
      if (apply_reads_issued_ < tile_size_ &&
          memory_tasks_.size() + inflight_memory_.size() <
              memory_request_window_) {
        staged_apply_read_vertex_ =
            tile_base_ + static_cast<std::uint32_t>(apply_reads_issued_);
      }
      if (!ready_apply_.empty()) {
        const ReadyApply &ready = ready_apply_.front();
        AlgorithmPipelineRequest request{};
        request.stage = AlgorithmPipelineStage::kApply;
        request.transaction_id = next_algorithm_transaction_;
        request.state = ready.old_state;
        request.reduced = ready.reduced;
        request.context.base = policy_.initial_base_word();
        request.context.dangling_share = dangling_share_word_;
        if (apply_requests_.try_push(request)) {
          staged_apply_request_ = request;
        }
      }
      if (tile_apply_drained()) {
        staged_apply_tile_complete_ = true;
      }
      return;
    case Phase::kFinish:
      if (memory_drained() && algorithm_queues_drained()) {
        staged_done_ = true;
      }
      return;
    case Phase::kInput:
      break;
  }

  const PartConvWord *word = edge_in_.front();
  if (word == nullptr) {
    return;
  }
  if (word->kind == PartConvWordKind::kEdge) {
    if (!tile_open_ || word->first < tile_base_ ||
        static_cast<std::size_t>(word->first - tile_base_) >= tile_size_) {
      failed_ = true;
      return;
    }
    if (pending_destinations_.contains(word->first)) {
      return;
    }
    const std::uint32_t current =
        tile_accumulators_.at(word->first - tile_base_);
    AlgorithmPipelineRequest request{};
    request.stage = AlgorithmPipelineStage::kReduce;
    request.transaction_id = next_algorithm_transaction_;
    request.current = current;
    request.candidate = word->second;
    if (!reduce_requests_.try_push(request)) {
      return;
    }
    PartConvWord staged;
    if (!edge_in_.try_pop(staged)) {
      throw std::logic_error("PageRank edge stream changed during evaluate");
    }
    staged_input_word_ = staged;
    staged_input_action_ = InputAction::kEdge;
    staged_reduce_request_ = request;
    return;
  }
  if (word->kind == PartConvWordKind::kTileEnd &&
      (!edge_reductions_.empty() || !pending_destinations_.empty() ||
       !reduce_requests_.empty() || !reduce_responses_.empty() ||
       !pipeline_.drained())) {
    return;
  }
  PartConvWord staged;
  if (!edge_in_.try_pop(staged)) {
    return;
  }
  staged_input_word_ = staged;
  switch (staged.kind) {
    case PartConvWordKind::kSourceRequest:
      staged_input_action_ = InputAction::kSourceRequest;
      break;
    case PartConvWordKind::kSourceCount:
      staged_input_action_ = InputAction::kSourceCount;
      break;
    case PartConvWordKind::kSourceGeneration:
      staged_input_action_ = InputAction::kSourceGeneration;
      break;
    case PartConvWordKind::kSourceRequestsDone:
      staged_input_action_ = InputAction::kSourceDone;
      break;
    case PartConvWordKind::kTileBegin:
      staged_input_action_ = InputAction::kTileBegin;
      break;
    case PartConvWordKind::kEdge:
      throw std::logic_error("PageRank edge bypassed timed reduction");
    case PartConvWordKind::kTileEnd:
      staged_input_action_ = InputAction::kTileEnd;
      break;
    case PartConvWordKind::kDiagnostic:
      staged_input_action_ = InputAction::kDiagnostic;
      break;
    case PartConvWordKind::kDoneAll:
      staged_input_action_ = InputAction::kDoneAll;
      break;
  }
}

void SpineSplitPageRankCompute::commit(const CycleContext &context) {
  if (done_) {
    return;
  }
  if (staged_memory_response_.has_value()) {
    const std::uint64_t transaction = staged_memory_response_->first;
    const auto found = inflight_memory_.find(transaction);
    if (found == inflight_memory_.end()) {
      failed_ = true;
      return;
    }
    consume_memory_response(found->second, staged_memory_response_->second);
    inflight_memory_.erase(found);
    ++counters_.memory_requests_completed;
  }
  if (staged_memory_issue_) {
    const std::uint64_t transaction = next_memory_transaction_++;
    inflight_memory_.emplace(transaction, std::move(memory_tasks_.front()));
    memory_tasks_.pop_front();
    ++counters_.memory_requests_issued;
    counters_.max_memory_requests_inflight =
        std::max(counters_.max_memory_requests_inflight,
                 inflight_memory_.size());
  }

  if (staged_source_request_.has_value()) {
    ++next_algorithm_transaction_;
    ++counters_.source_map_operations;
    phase_ = Phase::kSourceMapWait;
  }
  if (staged_source_response_.has_value()) {
    if (staged_source_response_->stage != AlgorithmPipelineStage::kSourceMap) {
      failed_ = true;
      return;
    }
    pending_source_result_ = staged_source_response_->source;
    if (pending_source_result_->primary_changed) {
      rank_words_.at(pending_source_) =
          pending_source_result_->state_after.primary;
      enqueue_write(primary_write_base_ + pending_source_ * kWordBytes,
                    pending_source_result_->state_after.primary,
                    MemoryPayloadKind::kSourcePrimaryWrite, pending_source_);
    }
    if (pending_source_result_->auxiliary_changed) {
      if (!state_layout_.auxiliary.has_value()) {
        failed_ = true;
        return;
      }
      residual_words_.at(pending_source_) =
          pending_source_result_->state_after.auxiliary;
      enqueue_write(state_layout_.auxiliary->base +
                        pending_source_ * kWordBytes,
                    pending_source_result_->state_after.auxiliary,
                    MemoryPayloadKind::kSourceAuxiliaryWrite, pending_source_);
    }
    phase_ = policy_.config().kind == GraphAlgorithmKind::kConnectedComponents
                 ? Phase::kSourceReply
                 : Phase::kDanglingReducePush;
  }
  if (staged_reduce_request_.has_value()) {
    const std::uint64_t transaction = next_algorithm_transaction_++;
    if (phase_ == Phase::kDanglingReducePush) {
      pending_dangling_transaction_ = transaction;
      ++counters_.dangling_reduce_operations;
      phase_ = Phase::kDanglingReduceWait;
    } else if (staged_input_action_ == InputAction::kEdge) {
      const std::uint32_t destination = staged_input_word_.first;
      edge_reductions_.emplace(transaction,
                               EdgeReduction{.destination = destination});
      pending_destinations_.insert(destination);
      ++counters_.edge_reduce_operations;
      counters_.max_edge_reductions_inflight =
          std::max(counters_.max_edge_reductions_inflight,
                   edge_reductions_.size());
    }
  }
  if (staged_reduce_response_.has_value()) {
    const std::uint64_t transaction = staged_reduce_response_->transaction_id;
    if (pending_dangling_transaction_ == transaction) {
      dangling_mass_word_ = staged_reduce_response_->reduced;
      pending_dangling_transaction_.reset();
      phase_ = policy_.config().kind == GraphAlgorithmKind::kResidualPageRank
                   ? Phase::kSourceStateWriteWait
                   : Phase::kSourceReply;
    } else {
      const auto found = edge_reductions_.find(transaction);
      if (found == edge_reductions_.end()) {
        failed_ = true;
        return;
      }
      const std::uint32_t destination = found->second.destination;
      tile_accumulators_.at(destination - tile_base_) =
          staged_reduce_response_->reduced;
      pending_destinations_.erase(destination);
      edge_reductions_.erase(found);
    }
  }

  if (staged_apply_read_vertex_.has_value()) {
    const std::uint32_t vertex = *staged_apply_read_vertex_;
    if (policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) {
      enqueue_read(state_layout_.auxiliary->base + vertex * kWordBytes,
                   MemoryPayloadKind::kApplyAuxiliary, vertex);
    } else {
      enqueue_read(primary_read_base_ + vertex * kWordBytes,
                   MemoryPayloadKind::kApplyPrimary, vertex);
    }
    ++apply_reads_issued_;
  }
  if (staged_apply_request_.has_value()) {
    const std::uint64_t transaction = next_algorithm_transaction_++;
    const ReadyApply ready = ready_apply_.front();
    ready_apply_.pop_front();
    apply_transactions_.emplace(transaction, ready.vertex);
    ++apply_operations_issued_;
    counters_.max_apply_operations_inflight =
        std::max(counters_.max_apply_operations_inflight,
                 apply_transactions_.size());
  }
  if (staged_apply_response_.has_value()) {
    const auto found =
        apply_transactions_.find(staged_apply_response_->transaction_id);
    if (found == apply_transactions_.end() ||
        staged_apply_response_->stage != AlgorithmPipelineStage::kApply) {
      failed_ = true;
      return;
    }
    const std::uint32_t vertex = found->second;
    const AlgorithmApplyResult &applied = staged_apply_response_->applied;
    rank_words_.at(vertex) = applied.state_after.primary;
    residual_words_.at(vertex) = applied.state_after.auxiliary;
    iteration_error_ += applied.error;
    if (policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) {
      enqueue_write(state_layout_.auxiliary->base + vertex * kWordBytes,
                    applied.state_after.auxiliary,
                    MemoryPayloadKind::kApplyAuxiliaryWrite, vertex);
      if (applied.active) {
        enqueue_active_output(next_active_.size(), vertex,
                              applied.state_after.auxiliary);
        next_active_.push_back(vertex);
        ++counters_.vertices_activated;
      }
    } else {
      enqueue_write(primary_write_base_ + vertex * kWordBytes,
                    applied.state_after.primary,
                    MemoryPayloadKind::kApplyPrimaryWrite, vertex);
      if (policy_.config().kind ==
              GraphAlgorithmKind::kConnectedComponents &&
          applied.active) {
        enqueue_active_output(next_active_.size(), vertex,
                              applied.state_after.primary);
        next_active_.push_back(vertex);
        ++counters_.vertices_activated;
      }
    }
    apply_transactions_.erase(found);
    ++apply_operations_completed_;
    ++counters_.vertices_applied;
  }

  if (staged_value_push_) {
    if (source_ack_pending_) {
      source_ack_pending_ = false;
      ++counters_.source_protocol_acks;
    } else {
      ++counters_.source_responses;
      pending_source_rank_.reset();
      pending_source_residual_.reset();
      pending_source_degree_.reset();
      pending_source_result_.reset();
    }
    phase_ = Phase::kInput;
  }

  switch (staged_input_action_) {
    case InputAction::kNone:
      break;
    case InputAction::kSourceRequest:
      if (tile_open_ || staged_input_word_.first >= vertices_ ||
          pending_source_rank_.has_value() ||
          pending_source_residual_.has_value() ||
          pending_source_degree_.has_value()) {
        set_protocol_status(SpineSourceProtocolStatus::kUnexpected);
        failed_ = true;
        return;
      }
      if (counters_.start_cycle == 0) {
        counters_.start_cycle = context.domain_cycle;
      }
      pending_source_ = staged_input_word_.first;
      enqueue_read(primary_read_base_ + pending_source_ * kWordBytes,
                   MemoryPayloadKind::kSourcePrimary, pending_source_);
      if (state_layout_.auxiliary.has_value()) {
        enqueue_read(state_layout_.auxiliary->base +
                         pending_source_ * kWordBytes,
                     MemoryPayloadKind::kSourceAuxiliary, pending_source_);
      }
      if (state_layout_.degree.has_value()) {
        enqueue_read(state_layout_.degree->base + pending_source_ * kWordBytes,
                     MemoryPayloadKind::kSourceDegree, pending_source_);
      }
      ++counters_.source_requests;
      phase_ = Phase::kSourceMemory;
      break;
    case InputAction::kSourceCount:
      ++counters_.source_protocol_markers;
      if (source_count_seen_) {
        set_protocol_status(SpineSourceProtocolStatus::kMetadataDuplicate);
      }
      source_count_seen_ = true;
      counters_.source_count = staged_input_word_.first;
      break;
    case InputAction::kSourceGeneration:
      ++counters_.source_protocol_markers;
      if (source_generation_seen_) {
        set_protocol_status(SpineSourceProtocolStatus::kMetadataDuplicate);
      }
      source_generation_seen_ = true;
      break;
    case InputAction::kSourceDone: {
      ++counters_.source_protocol_markers;
      if (!source_count_seen_ || !source_generation_seen_ ||
          counters_.source_count != counters_.source_requests ||
          (policy_.config().kind == GraphAlgorithmKind::kFullPageRank &&
           counters_.source_count != vertices_)) {
        set_protocol_status(SpineSourceProtocolStatus::kCount);
      }
      const float share =
          policy_.config().kind == GraphAlgorithmKind::kConnectedComponents
              ? 0.0F
              : policy_.config().damping * dangling_mass() /
                    static_cast<float>(vertices_);
      dangling_share_word_ = GraphAlgorithmPolicy::float_to_word(share);
      source_ack_pending_ = true;
      phase_ = Phase::kSourceReply;
      break;
    }
    case InputAction::kTileBegin:
      if (tile_open_ || staged_input_word_.first >= vertices_ ||
          staged_input_word_.first % tile_vertices_ != 0 ||
          tile_applied_.at(staged_input_word_.first / tile_vertices_)) {
        failed_ = true;
        return;
      }
      tile_open_ = true;
      tile_base_ = staged_input_word_.first;
      tile_size_ =
          std::min<std::size_t>(tile_vertices_, vertices_ - tile_base_);
      tile_accumulators_.assign(tile_size_, policy_.reduction_identity_word());
      ++counters_.tiles_received;
      break;
    case InputAction::kEdge:
      ++counters_.edges_received;
      break;
    case InputAction::kTileEnd:
      if (!tile_open_ || staged_input_word_.first != tile_base_) {
        failed_ = true;
        return;
      }
      tile_open_ = false;
      begin_apply_tile(tile_base_, false);
      break;
    case InputAction::kDiagnostic:
      break;
    case InputAction::kDoneAll: {
      if (tile_open_ || (staged_input_word_.second & 1U) != 0) {
        failed_ = true;
        return;
      }
      ++counters_.done_words;
      reader_done_seen_ = true;
      const std::optional<std::uint32_t> next = next_unapplied_tile();
      if (next.has_value()) {
        begin_apply_tile(*next, true);
      } else {
        phase_ = Phase::kFinish;
      }
      break;
    }
  }

  if (staged_apply_tile_complete_) {
    advance_after_apply_tile();
  }
  if (staged_phase_transition_.has_value()) {
    phase_ = *staged_phase_transition_;
  }
  if (staged_done_) {
    counters_.end_cycle = context.domain_cycle;
    done_ = true;
  }
}

}  // namespace spine::sim
