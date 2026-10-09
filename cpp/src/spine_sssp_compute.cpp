#include "spine_sim/spine_split.hpp"

#include "detail/spine_split_payload.hpp"
#include "spine_sim/spine_owner.hpp"

#include <algorithm>
#include <bit>
#include <limits>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace spine::sim {

namespace {

using detail::split_payload::decode_u32;
using detail::split_payload::decode_u64;
using detail::split_payload::encode_u32;
using detail::split_payload::encode_u32_words;
using detail::split_payload::encode_u64;
using detail::split_payload::kActiveOutputBytes;
using detail::split_payload::kActiveWordBits;
using detail::split_payload::kRangeTaskPathFallback;
using detail::split_payload::kTileVertices;

constexpr std::uint64_t kOwnerWordBytes = sizeof(std::uint64_t);
constexpr std::uint64_t kOwnerBitmapWords = 16'777'216ULL / 64ULL;
constexpr std::uint64_t kOwnerControlBase = 5ULL * kOwnerBitmapWords;

constexpr std::uint64_t owner_region_address(std::uint64_t region,
                                             std::uint64_t word) {
  return (region * kOwnerBitmapWords + word) * kOwnerWordBytes;
}

constexpr std::uint64_t owner_control_address(std::uint64_t field) {
  return (kOwnerControlBase + field) * kOwnerWordBytes;
}

constexpr std::uint64_t kVertexWordBytes = 4;
constexpr std::uint64_t kResultBytes = 96 * 4;
constexpr std::size_t kTileActiveWords = kTileVertices / kActiveWordBits;

} // namespace

SpineSplitSsspCompute::SpineSplitSsspCompute(
    std::string name, ClockId clock_id, std::size_t vertices,
    std::uint32_t source, std::size_t tiny_threshold, SpineComputePorts ports,
    Fifo<PartConvWord> &edge_in, Fifo<SourceValueWord> &value_out,
    std::size_t memory_request_window, std::size_t writeonly_request_window,
    SpineOnChipMemoryProfile on_chip_profile,
    std::shared_ptr<const GraphAlgorithmPolicy> algorithm_policy,
    std::optional<AlgorithmInitialState> initial_state,
    SpineOwnerScheduler *owner_scheduler)
    : Component(std::move(name), clock_id), vertices_(vertices),
      source_(source),
      algorithm_policy_(algorithm_policy != nullptr
                            ? std::move(algorithm_policy)
                            : std::make_shared<const GraphAlgorithmPolicy>(
                                  AlgorithmPolicyConfig{
                                      .kind = GraphAlgorithmKind::kWeightedSssp,
                                      .vertices = vertices,
                                      .source = source,
                                  })),
      tiny_threshold_(tiny_threshold),
      memory_request_window_(memory_request_window),
      writeonly_request_window_(writeonly_request_window),
      on_chip_profile_(on_chip_profile), ports_(ports), edge_in_(edge_in),
      value_out_(value_out), owner_scheduler_(owner_scheduler),
      values_(vertices) {
  if (vertices_ == 0 || source_ >= vertices_ || tiny_threshold_ == 0 ||
      memory_request_window_ == 0 || writeonly_request_window_ == 0 ||
      on_chip_profile_.tiny_bram_read_latency == 0 ||
      on_chip_profile_.vs_uram_read_latency == 0 ||
      on_chip_profile_.active_bram_read_latency == 0 ||
      on_chip_profile_.pipeline_capacity == 0 ||
      on_chip_profile_.vs_bypass_depth == 0 || ports_.vertex_state == nullptr ||
      ports_.active_out == nullptr || ports_.active_bitmap == nullptr ||
      ports_.result == nullptr || edge_in_.clock_id() != clock_id ||
      value_out_.clock_id() != clock_id) {
    throw std::invalid_argument("invalid Spine split compute configuration");
  }
  if ((algorithm_policy_->config().kind != GraphAlgorithmKind::kWeightedSssp &&
       algorithm_policy_->config().kind !=
           GraphAlgorithmKind::kConnectedComponents) ||
      algorithm_policy_->config().vertices != vertices_ ||
      algorithm_policy_->config().source != source_) {
    throw std::invalid_argument(
        "timed Spine split compute requires a matching SSSP or CC policy");
  }
  if (initial_state.has_value()) {
    std::unordered_set<std::uint32_t> active;
    active.insert(initial_state->active_vertices.begin(),
                  initial_state->active_vertices.end());
    if (initial_state->primary.size() != vertices_ ||
        !initial_state->auxiliary.empty() ||
        active.size() != initial_state->active_vertices.size() ||
        std::any_of(active.begin(), active.end(), [this](std::uint32_t vertex) {
          return vertex >= vertices_;
        })) {
      throw std::invalid_argument("invalid Spine tiled algorithm warm state");
    }
    values_ = std::move(initial_state->primary);
  } else {
    for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
      values_[vertex] =
          algorithm_policy_->initial_state(static_cast<std::uint32_t>(vertex))
              .primary;
    }
  }
  std::vector<std::uint8_t> vertex_payload(vertices_ * kVertexWordBytes);
  for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
    const std::vector<std::uint8_t> encoded = encode_u32(values_[vertex]);
    std::copy(encoded.begin(), encoded.end(),
              vertex_payload.begin() +
                  static_cast<std::ptrdiff_t>(vertex * kVertexWordBytes));
  }
  ports_.vertex_state->initialize_payload(0, vertex_payload);
  owner_seed_epoch_ =
      owner_scheduler_ != nullptr && owner_scheduler_->work_credits() == 0;
}

bool SpineSplitSsspCompute::recoverable_host_handoff() const noexcept {
  return done_ && failed_ && counters_.done_overflow &&
         counters_.range_task_path == kRangeTaskPathFallback &&
         counters_.range_task_fallback_reason != 0 &&
         counters_.range_task_error == 0 &&
         counters_.source_protocol_status ==
             static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk) &&
         !tile_open_ && memory_tasks_.empty() &&
         inflight_memory_tasks_.empty() && on_chip_pipelines_drained() &&
         !source_reply_pending_;
}

void SpineSplitSsspCompute::reset_after_host_handoff() {
  if (!recoverable_host_handoff()) {
    throw std::logic_error(
        "compute host handoff reset requires REQUIRES_HOST completion");
  }
  failed_ = false;
  reset_round();
}

void SpineSplitSsspCompute::reset_round() {
  if (!done_ || failed_ || !memory_tasks_.empty() ||
      !inflight_memory_tasks_.empty() || !on_chip_pipelines_drained() ||
      source_reply_pending_) {
    throw std::logic_error("compute round reset requires a successful drain");
  }
  counters_ = {};
  next_active_.clear();
  reset_tile();
  phase_ = Phase::kInput;
  staged_action_ = Action::kNone;
  pending_source_ = 0;
  pending_source_value_ = kInfinity;
  pending_value_kind_ = SourceValueWord::Kind::kSourceValue;
  source_count_seen_ = false;
  source_generation_seen_ = false;
  source_protocol_overflow_ = false;
  owner_protocol_kind_ = OwnerProtocolKind::kNone;
  owner_protocol_return_phase_ = Phase::kInput;
  owner_protocol_index_ = 0;
  owner_protocol_subject_ = 0;
  owner_protocol_request_pending_ = false;
  owner_seed_epoch_ =
      owner_scheduler_ != nullptr && owner_scheduler_->work_credits() == 0;
  owner_round_started_ = false;
  deferred_active_ = false;
  deferred_active_word_index_ = 0;
  deferred_bitmap_chunk_.fill(0);
  deferred_sweep_base_word_ = 0;
  deferred_sweep_chunk_words_ = 0;
  deferred_sweep_word_index_ = 0;
  deferred_sweep_bit_index_ = 0;
  deferred_sweep_reads_pending_ = 0;
  deferred_sweep_scan_bits_ = 0;
  deferred_sweep_next_issue_cycle_ = 0;
  deferred_sweep_next_bit_cycle_ = 0;
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_output_base_ = 0;
  active_output_index_ = 0;
  active_scan_bits_ = 0;
  active_read_due_cycle_ = 0;
  last_on_chip_read_wait_cycle_ = ~std::uint64_t{0};
  last_on_chip_pipeline_stall_cycle_ = ~std::uint64_t{0};
  active_read_pending_ = false;
  active_read_ready_ = false;
  pending_tiny_reads_.clear();
  pending_vs_reads_.clear();
  reset_bypass();
  after_clear_phase_ = Phase::kRelax;
  done_ = false;
}

void SpineSplitSsspCompute::reset_for_full_recompute() {
  reset_round();
  for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
    values_[vertex] =
        algorithm_policy_->initial_state(static_cast<std::uint32_t>(vertex))
            .primary;
  }
  std::vector<std::uint8_t> payload(vertices_ * kVertexWordBytes, 0xffU);
  const std::vector<std::uint8_t> source_value = encode_u32(values_[source_]);
  std::copy(source_value.begin(), source_value.end(),
            payload.begin() +
                static_cast<std::ptrdiff_t>(source_ * kVertexWordBytes));
  const std::size_t payload_bytes = payload.size();
  enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite, 0,
                 payload_bytes, std::move(payload));
  enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite, 0, 8,
                 std::vector<std::uint8_t>(8, 0));
  counters_.full_recompute_reset_words = vertices_;
  counters_.full_recompute_reset_write_bytes = vertices_ * kVertexWordBytes;
  phase_ = Phase::kReinitialize;
}

void SpineSplitSsspCompute::evaluate(const CycleContext &context) {
  staged_action_ = Action::kNone;
  staged_memory_issue_ = false;
  staged_full_tile_read_beat_valid_ = false;
  staged_owner_activation_ = false;
  staged_owner_publication_ = false;
  staged_owner_dispatch_ = false;
  staged_owner_completion_ = false;
  staged_responses_.clear();
  if (done_ || failed_) {
    return;
  }
  if (phase_ == Phase::kReinitialize) {
    if (counters_.full_recompute_reset_cycles == 0) {
      counters_.start_cycle = context.domain_cycle;
    }
    ++counters_.full_recompute_reset_cycles;
  }
  if (phase_ == Phase::kDeferredActiveClear) {
    ++counters_.deferred_active_clear_cycles;
  }
  if (phase_ == Phase::kDeferredMergeScan ||
      phase_ == Phase::kDeferredMergeWait) {
    ++counters_.deferred_active_merge_cycles;
  }
  if (phase_ == Phase::kDeferredSweepRead) {
    ++counters_.deferred_active_sweep_read_cycles;
  }
  if (phase_ == Phase::kDeferredSweepBits) {
    ++counters_.deferred_active_sweep_bit_cycles;
  }
  if (phase_ == Phase::kDeferredFinalClear) {
    ++counters_.deferred_active_final_clear_cycles;
  }
  staged_full_tile_read_beat_valid_ = stage_full_tile_read_beat();
  const bool staged_memory_completion = stage_memory_completions();
  const std::size_t active_ports = active_memory_ports();
  if (active_ports > 1) {
    ++counters_.memory_cross_port_overlap_cycles;
  }
  if (std::any_of(
          staged_responses_.begin(), staged_responses_.end(),
          [](const AxiResponse &response) { return !response.success; })) {
    return;
  }
  bool memory_issue_blocked = false;
  if (!memory_tasks_.empty()) {
    const MemoryTask &task = memory_tasks_.front();
    std::size_t inflight_on_port = inflight_memory_tasks_for_port(task.port);
    const bool same_port_completion =
        std::any_of(staged_responses_.begin(), staged_responses_.end(),
                    [&](const AxiResponse &response) {
                      const auto completing =
                          inflight_memory_tasks_.find(response.transaction_id);
                      return completing != inflight_memory_tasks_.end() &&
                             completing->second.port == task.port;
                    });
    if (same_port_completion) {
      --inflight_on_port;
    }
    if (inflight_on_port >= memory_request_window_for(task.port)) {
      ++counters_.memory_window_stall_cycles;
      memory_issue_blocked = true;
    } else if (memory_task_conflicts(task)) {
      ++counters_.memory_dependency_stall_cycles;
      memory_issue_blocked = true;
    } else if (task.port->requests().try_push(AxiRequest{
                   .transaction_id = next_transaction_id_,
                   .operation = task.operation,
                   .address = task.address,
                   .bytes = task.bytes,
                   .stream_read_beats = task.stream_read_beats,
                   .write_data = task.write_data,
               })) {
      staged_memory_issue_ = true;
    } else {
      ++counters_.memory_request_fifo_stall_cycles;
      memory_issue_blocked = true;
    }
  }
  const bool memory_active = !memory_tasks_.empty() ||
                             !inflight_memory_tasks_.empty() ||
                             staged_memory_completion;
  const bool cross_tile_write_overlap =
      (phase_ == Phase::kInput || phase_ == Phase::kClearTileActive) &&
      memory_active && memory_work_is_write_only();
  if (cross_tile_write_overlap) {
    ++counters_.cross_tile_write_overlap_cycles;
    counters_.max_cross_tile_writes_inflight =
        std::max(counters_.max_cross_tile_writes_inflight,
                 inflight_memory_tasks_.size());
  }
  if (phase_ == Phase::kFullLoad && memory_active &&
      !staged_full_tile_read_beat_valid_) {
    ++counters_.full_tile_read_wait_cycles;
  }
  if (controller_memory_overlap_phase() || cross_tile_write_overlap) {
    if (memory_issue_blocked && !cross_tile_write_overlap) {
      ++counters_.controller_memory_stall_cycles;
      return;
    }
    if (memory_active) {
      ++counters_.controller_memory_overlap_cycles;
    }
  } else if (memory_active) {
    return;
  }
  if (owner_scheduler_ != nullptr && !pending_vs_reads_.empty()) {
    const PendingVsRead &request = pending_vs_reads_.front();
    const bool memory_slot_available =
        memory_tasks_.empty() ||
        (memory_tasks_.size() == 1 && staged_memory_issue_);
    if (request.purpose == VsReadPurpose::kActiveEmit &&
        request.due_cycle <= context.domain_cycle && memory_slot_available) {
      ++counters_.owner_activation_attempts;
      staged_owner_activation_ = owner_scheduler_->try_activate(request.vertex);
      if (!staged_owner_activation_) {
        ++counters_.owner_activation_backpressure_cycles;
        return;
      }
      staged_owner_publication_ =
          owner_scheduler_->activation_will_publish(request.vertex);
    }
  }
  if (phase_ == Phase::kOwnerProtocol &&
      owner_protocol_index_ == owner_protocol_length() &&
      !owner_protocol_request_pending_) {
    if (owner_protocol_kind_ == OwnerProtocolKind::kDispatchSource) {
      staged_owner_dispatch_ = owner_scheduler_ != nullptr &&
                               owner_scheduler_->try_dispatch_source(
                                   owner_protocol_subject_, owner_seed_epoch_);
      if (!staged_owner_dispatch_) {
        ++counters_.owner_activation_backpressure_cycles;
        return;
      }
    } else if (owner_protocol_kind_ == OwnerProtocolKind::kCompleteSource) {
      staged_owner_completion_ =
          owner_scheduler_ != nullptr &&
          owner_scheduler_->try_complete(owner_protocol_subject_);
      if (!staged_owner_completion_) {
        ++counters_.owner_activation_backpressure_cycles;
        return;
      }
    }
  }
  if (source_reply_pending_) {
    staged_value_word_ = SourceValueWord{.kind = pending_value_kind_,
                                         .source = pending_source_,
                                         .value = pending_source_value_};
    if (value_out_.try_push(staged_value_word_)) {
      staged_action_ = Action::kPushValue;
    }
    return;
  }
  if (phase_ == Phase::kInput) {
    const PartConvWord *next = edge_in_.front();
    if (next != nullptr && next->kind == PartConvWordKind::kEdge &&
        full_path_ &&
        pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
      count_on_chip_pipeline_stall(context.domain_cycle);
      return;
    }
    if (edge_in_.try_pop(staged_edge_word_)) {
      staged_action_ = Action::kPopEdge;
    }
    return;
  }
  staged_action_ = Action::kAdvance;
}

void SpineSplitSsspCompute::commit(const CycleContext &context) {
  if (staged_full_tile_read_beat_valid_) {
    consume_full_tile_read_beat(staged_full_tile_read_beat_);
    if (failed_) {
      done_ = true;
      return;
    }
  }
  for (const AxiResponse &response : staged_responses_) {
    const auto found = inflight_memory_tasks_.find(response.transaction_id);
    if (found == inflight_memory_tasks_.end() || !response.success) {
      failed_ = true;
      done_ = true;
      return;
    }
    consume_memory_response(found->second, response);
    inflight_memory_tasks_.erase(found);
    ++counters_.memory_requests_completed;
  }
  if (staged_memory_issue_) {
    const std::uint64_t transaction_id = next_transaction_id_++;
    inflight_memory_tasks_.emplace(transaction_id,
                                   std::move(memory_tasks_.front()));
    memory_tasks_.pop_front();
    ++counters_.memory_requests_issued;
    counters_.max_memory_requests_inflight = std::max(
        counters_.max_memory_requests_inflight, inflight_memory_tasks_.size());
    counters_.max_vertex_requests_inflight =
        std::max(counters_.max_vertex_requests_inflight,
                 inflight_memory_tasks_for_port(ports_.vertex_state));
    counters_.max_active_out_requests_inflight =
        std::max(counters_.max_active_out_requests_inflight,
                 inflight_memory_tasks_for_port(ports_.active_out));
    counters_.max_active_memory_ports =
        std::max(counters_.max_active_memory_ports, active_memory_ports());
  }
  advance_on_chip_pipelines(context);
  if (failed_) {
    done_ = true;
    return;
  }
  switch (staged_action_) {
  case Action::kNone:
    return;
  case Action::kPopEdge:
    if (counters_.source_requests == 0 && counters_.start_cycle == 0) {
      counters_.start_cycle = context.domain_cycle;
    }
    handle_edge_word(staged_edge_word_, context);
    return;
  case Action::kPushValue:
    source_reply_pending_ = false;
    if (pending_value_kind_ == SourceValueWord::Kind::kProtocolAck) {
      ++counters_.source_protocol_acks;
    } else {
      ++counters_.source_responses;
    }
    pending_value_kind_ = SourceValueWord::Kind::kSourceValue;
    phase_ = Phase::kInput;
    return;
  case Action::kAdvance:
    advance(context);
    return;
  }
}

void SpineSplitSsspCompute::enqueue_memory(
    FixedAxiPort &port, MemoryOperation operation, std::uint64_t address,
    std::uint64_t bytes, std::vector<std::uint8_t> write_data,
    MemoryPayloadKind payload_kind, std::size_t item_index,
    std::uint64_t payload_value, bool stream_read_beats) {
  if ((operation == MemoryOperation::kRead && !write_data.empty()) ||
      (operation == MemoryOperation::kWrite && write_data.size() != bytes)) {
    throw std::invalid_argument("invalid Spine compute memory payload");
  }
  const std::size_t payload_bytes = write_data.size();
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .write_data = std::move(write_data),
      .payload_kind = payload_kind,
      .item_index = item_index,
      .payload_value = payload_value,
      .stream_read_beats = stream_read_beats,
      .streamed_read_bytes = 0,
  });
  if (&port == ports_.vertex_state) {
    if (operation == MemoryOperation::kRead) {
      counters_.vertex_read_bytes += bytes;
    } else {
      counters_.vertex_write_bytes += bytes;
      counters_.vertex_payload_write_bytes += payload_bytes;
    }
  } else if (&port == ports_.active_out) {
    counters_.active_out_write_bytes += bytes;
  } else if (&port == ports_.active_bitmap) {
    counters_.bitmap_bytes += bytes;
  } else if (&port == ports_.result) {
    counters_.result_write_bytes += bytes;
  }
  if (payload_kind == MemoryPayloadKind::kOwnerProtocol) {
    ++counters_.owner_hbm_requests_generated;
    if (operation == MemoryOperation::kRead) {
      ++counters_.owner_hbm_read_requests;
      counters_.owner_hbm_read_bytes += bytes;
    } else {
      ++counters_.owner_hbm_write_requests;
      counters_.owner_hbm_write_bytes += bytes;
    }
  }
}

bool SpineSplitSsspCompute::memory_task_conflicts(
    const MemoryTask &task) const {
  const std::uint64_t task_end = task.address + task.bytes;
  for (const auto &[transaction_id, inflight] : inflight_memory_tasks_) {
    (void)transaction_id;
    if (std::any_of(staged_responses_.begin(), staged_responses_.end(),
                    [&](const AxiResponse &response) {
                      return response.transaction_id == transaction_id;
                    })) {
      continue;
    }
    if (task.port != inflight.port ||
        (task.operation == MemoryOperation::kRead &&
         inflight.operation == MemoryOperation::kRead)) {
      continue;
    }
    const std::uint64_t inflight_end = inflight.address + inflight.bytes;
    if (task.address < inflight_end && inflight.address < task_end) {
      return true;
    }
  }
  return false;
}

std::size_t SpineSplitSsspCompute::inflight_memory_tasks_for_port(
    const FixedAxiPort *port) const noexcept {
  return static_cast<std::size_t>(std::count_if(
      inflight_memory_tasks_.begin(), inflight_memory_tasks_.end(),
      [port](const auto &entry) { return entry.second.port == port; }));
}

std::size_t SpineSplitSsspCompute::memory_request_window_for(
    const FixedAxiPort *port) const noexcept {
  return port == ports_.active_out || port == ports_.result
             ? writeonly_request_window_
             : memory_request_window_;
}

std::size_t SpineSplitSsspCompute::active_memory_ports() const noexcept {
  std::size_t ports = 0;
  for (auto current = inflight_memory_tasks_.begin();
       current != inflight_memory_tasks_.end(); ++current) {
    const bool already_seen = std::any_of(
        inflight_memory_tasks_.begin(), current, [&](const auto &prior) {
          return prior.second.port == current->second.port;
        });
    ports += already_seen ? 0 : 1;
  }
  return ports;
}

bool SpineSplitSsspCompute::memory_work_is_write_only() const noexcept {
  return memory_tasks_.empty() && !inflight_memory_tasks_.empty() &&
         std::all_of(inflight_memory_tasks_.begin(),
                     inflight_memory_tasks_.end(), [](const auto &entry) {
                       return entry.second.operation == MemoryOperation::kWrite;
                     });
}

bool SpineSplitSsspCompute::stage_memory_completions() {
  struct Candidate {
    std::uint64_t transaction_id{};
    FixedAxiPort *port{};
  };
  std::vector<Candidate> candidates;
  for (const auto &[transaction_id, task] : inflight_memory_tasks_) {
    if (task.stream_read_beats && task.streamed_read_bytes < task.bytes) {
      continue;
    }
    const AxiResponse *response = task.port->responses().front();
    if (response != nullptr && response->transaction_id == transaction_id &&
        std::none_of(candidates.begin(), candidates.end(),
                     [&](const Candidate &candidate) {
                       return candidate.port == task.port;
                     })) {
      candidates.push_back(Candidate{transaction_id, task.port});
    }
  }
  std::sort(candidates.begin(), candidates.end(),
            [](const Candidate &left, const Candidate &right) {
              return left.transaction_id < right.transaction_id;
            });
  for (const Candidate &candidate : candidates) {
    AxiResponse response;
    if (!candidate.port->responses().try_pop(response)) {
      throw std::logic_error("failed to stage ready compute AXI response");
    }
    staged_responses_.push_back(std::move(response));
  }
  counters_.max_memory_responses_completed_per_cycle =
      std::max(counters_.max_memory_responses_completed_per_cycle,
               staged_responses_.size());
  if (staged_responses_.size() > 1) {
    ++counters_.multi_port_response_cycles;
  }
  return !staged_responses_.empty();
}

bool SpineSplitSsspCompute::stage_full_tile_read_beat() {
  if (!ports_.vertex_state->read_beat_stream_enabled()) {
    return false;
  }
  const AxiReadBeatResponse *beat = ports_.vertex_state->read_beats().front();
  if (beat == nullptr) {
    return false;
  }
  const auto found = inflight_memory_tasks_.find(beat->transaction_id);
  if (found == inflight_memory_tasks_.end() ||
      found->second.port != ports_.vertex_state ||
      found->second.operation != MemoryOperation::kRead ||
      found->second.payload_kind != MemoryPayloadKind::kFullTile ||
      !found->second.stream_read_beats) {
    throw std::logic_error(
        "Spine full-tile read beat has no matching streamed request");
  }
  return ports_.vertex_state->read_beats().try_pop(staged_full_tile_read_beat_);
}

void SpineSplitSsspCompute::consume_full_tile_read_beat(
    const AxiReadBeatResponse &beat) {
  const auto found = inflight_memory_tasks_.find(beat.transaction_id);
  if (found == inflight_memory_tasks_.end()) {
    throw std::logic_error("Spine consumed an unknown full-tile read beat");
  }
  MemoryTask &task = found->second;
  const bool shape_valid =
      beat.success && beat.parent_offset == task.streamed_read_bytes &&
      beat.address == task.address + beat.parent_offset &&
      !beat.read_data.empty() &&
      beat.read_data.size() % kVertexWordBytes == 0 &&
      task.streamed_read_bytes + beat.read_data.size() <= task.bytes;
  if (!shape_valid) {
    ++counters_.full_tile_stream_error_count;
    failed_ = true;
    return;
  }
  const std::size_t first_word = beat.parent_offset / kVertexWordBytes;
  const std::size_t words = beat.read_data.size() / kVertexWordBytes;
  if (first_word + words > tile_values_.size()) {
    ++counters_.full_tile_stream_error_count;
    failed_ = true;
    return;
  }
  for (std::size_t word = 0; word < words; ++word) {
    const std::uint32_t value =
        decode_u32(beat.read_data, word * kVertexWordBytes);
    tile_values_[first_word + word] = value;
    values_.at(tile_base_ + first_word + word) = value;
  }
  task.streamed_read_bytes += beat.read_data.size();
  ++counters_.full_tile_read_beats;
  counters_.full_tile_read_words += words;
  counters_.vs_tile_writes += words;
  counters_.vs_uram_write_requests += words;
  if (beat.last != (task.streamed_read_bytes == task.bytes)) {
    ++counters_.full_tile_stream_error_count;
    failed_ = true;
  }
}

void SpineSplitSsspCompute::consume_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.payload_kind == MemoryPayloadKind::kOwnerProtocol) {
    if (!owner_protocol_request_pending_) {
      throw std::logic_error(
          "Spine owner-HBM response has no dependent request");
    }
    owner_protocol_request_pending_ = false;
    ++counters_.owner_hbm_requests_completed;
  }
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("Spine compute write response carried payload");
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine compute read response payload size mismatch");
  }
  if (task.payload_kind == MemoryPayloadKind::kNone) {
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kOwnerProtocol) {
    return;
  }
  if (task.port == ports_.vertex_state) {
    counters_.vertex_payload_read_bytes += response.read_data.size();
  }
  if (task.payload_kind == MemoryPayloadKind::kSourceValue) {
    const AlgorithmSourceResult prepared = algorithm_policy_->prepare_source(
        {.primary = decode_u32(response.read_data)}, 0);
    pending_source_value_ = prepared.edge_payload;
    values_.at(pending_source_) = prepared.state_after.primary;
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kGatherVertex) {
    const std::uint32_t vertex = gather_vertices_.at(task.item_index);
    const std::uint32_t value = decode_u32(response.read_data);
    gathered_values_[vertex] = value;
    values_.at(vertex) = value;
    ++counters_.gathered_vertex_words;
    ++counters_.vs_tile_writes;
    ++counters_.vs_uram_write_requests;
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kFullTile) {
    if (response.read_data.size() != tile_size_ * kVertexWordBytes) {
      throw std::logic_error("Spine full-tile payload size mismatch");
    }
    if (task.stream_read_beats) {
      if (task.streamed_read_bytes != task.bytes) {
        throw std::logic_error(
            "Spine full-tile parent completed before streamed words");
      }
      return;
    }
    tile_values_.resize(tile_size_);
    for (std::size_t index = 0; index < tile_size_; ++index) {
      tile_values_[index] =
          decode_u32(response.read_data, index * kVertexWordBytes);
      values_.at(tile_base_ + index) = tile_values_[index];
    }
    counters_.vs_tile_writes += kTileVertices;
    counters_.vs_uram_write_requests += kTileVertices;
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kDeferredMergeWord) {
    if (task.port != ports_.active_bitmap ||
        task.bytes != sizeof(std::uint64_t)) {
      throw std::logic_error("invalid deferred bitmap merge response");
    }
    const std::uint64_t merged =
        decode_u64(response.read_data) | task.payload_value;
    enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite, task.address,
                   sizeof(std::uint64_t), encode_u64(merged));
    ++counters_.deferred_active_merge_words;
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kDeferredSweepWord) {
    if (task.port != ports_.active_bitmap ||
        task.item_index >= deferred_bitmap_chunk_.size() ||
        task.bytes != sizeof(std::uint64_t) ||
        deferred_sweep_reads_pending_ == 0) {
      throw std::logic_error("invalid deferred bitmap sweep response");
    }
    deferred_bitmap_chunk_[task.item_index] = decode_u64(response.read_data);
    --deferred_sweep_reads_pending_;
    return;
  }
  if (task.payload_kind == MemoryPayloadKind::kDeferredPublishVertex) {
    if (task.port != ports_.vertex_state || task.item_index >= vertices_ ||
        task.bytes != kVertexWordBytes) {
      throw std::logic_error("invalid deferred active vertex response");
    }
    const std::uint32_t vertex = static_cast<std::uint32_t>(task.item_index);
    const std::uint32_t value = decode_u32(response.read_data);
    values_.at(vertex) = value;
    enqueue_active_output(vertex, value,
                          static_cast<std::size_t>(task.payload_value));
    return;
  }
  throw std::logic_error("unknown Spine compute memory payload kind");
}

void SpineSplitSsspCompute::handle_edge_word(const PartConvWord &word,
                                             const CycleContext &context) {
  const auto set_protocol_status = [this](SpineSourceProtocolStatus status) {
    if (counters_.source_protocol_status ==
        static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk)) {
      counters_.source_protocol_status = static_cast<std::uint32_t>(status);
    }
  };
  switch (word.kind) {
  case PartConvWordKind::kSourceRequest:
    ++counters_.source_requests;
    pending_value_kind_ = SourceValueWord::Kind::kSourceValue;
    pending_source_ = word.first;
    if (word.first >= vertices_) {
      set_protocol_status(SpineSourceProtocolStatus::kSourceBounds);
      pending_source_value_ = kInfinity;
      source_reply_pending_ = true;
      phase_ = Phase::kSourceReply;
      return;
    }
    if (owner_scheduler_ != nullptr) {
      begin_owner_protocol(owner_round_started_
                               ? OwnerProtocolKind::kDispatchSource
                               : OwnerProtocolKind::kBeginRound,
                           pending_source_, Phase::kSourceRead);
    } else {
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                     pending_source_ * kVertexWordBytes, kVertexWordBytes, {},
                     MemoryPayloadKind::kSourceValue);
      phase_ = Phase::kSourceRead;
    }
    return;
  case PartConvWordKind::kSourceCount:
    ++counters_.source_protocol_markers;
    if (source_count_seen_) {
      set_protocol_status(SpineSourceProtocolStatus::kMetadataDuplicate);
    }
    source_count_seen_ = true;
    counters_.source_count = word.first;
    if (owner_scheduler_ != nullptr && !owner_round_started_) {
      begin_owner_protocol(OwnerProtocolKind::kBeginRound, 0, Phase::kInput);
    } else {
      phase_ = Phase::kInput;
    }
    return;
  case PartConvWordKind::kSourceGeneration:
    ++counters_.source_protocol_markers;
    if (source_generation_seen_) {
      set_protocol_status(SpineSourceProtocolStatus::kMetadataDuplicate);
    }
    source_generation_seen_ = true;
    counters_.source_generation = word.first;
    phase_ = Phase::kInput;
    return;
  case PartConvWordKind::kSourceRequestsDone:
    ++counters_.source_protocol_markers;
    if (!source_count_seen_ || !source_generation_seen_ ||
        counters_.source_count != counters_.source_requests) {
      set_protocol_status(SpineSourceProtocolStatus::kCount);
    }
    pending_value_kind_ = SourceValueWord::Kind::kProtocolAck;
    pending_source_ = 0;
    pending_source_value_ = counters_.source_protocol_status;
    source_reply_pending_ = true;
    source_protocol_overflow_ =
        counters_.source_protocol_status !=
        static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk);
    phase_ = Phase::kSourceReply;
    return;
  case PartConvWordKind::kDeferActiveBegin:
    if (deferred_active_ || source_count_seen_ || tile_open_ ||
        word.first != 1U) {
      source_protocol_overflow_ = true;
      failed_ = true;
      done_ = true;
      return;
    }
    deferred_active_ = true;
    deferred_active_word_index_ = 0;
    ++counters_.deferred_active_markers;
    phase_ = Phase::kDeferredActiveClear;
    return;
  case PartConvWordKind::kSourceCompletion:
    ++counters_.source_completion_markers;
    if (word.first >= vertices_) {
      set_protocol_status(SpineSourceProtocolStatus::kSourceBounds);
      source_protocol_overflow_ = true;
      phase_ = Phase::kInput;
    } else if (owner_scheduler_ != nullptr) {
      begin_owner_protocol(OwnerProtocolKind::kCompleteSource, word.first,
                           Phase::kInput);
    } else {
      phase_ = Phase::kInput;
    }
    return;
  case PartConvWordKind::kDiagnostic:
    ++counters_.diagnostic_words;
    switch (static_cast<SpineDiagnosticKind>(word.first)) {
    case SpineDiagnosticKind::kTaskStatus:
      counters_.range_task_path = word.second & 0xffU;
      counters_.range_task_fallback_reason = (word.second >> 8) & 0xffU;
      counters_.range_task_error = (word.second >> 16) & 0xffU;
      return;
    case SpineDiagnosticKind::kTaskCount:
      counters_.range_task_count = word.second;
      return;
    case SpineDiagnosticKind::kTaskRowLookups:
      counters_.range_task_row_lookups = word.second;
      return;
    case SpineDiagnosticKind::kTaskConstructionPayloads:
      counters_.range_task_construction_payloads = word.second;
      return;
    case SpineDiagnosticKind::kTaskReplayPayloads:
      counters_.range_task_replay_payloads = word.second;
      return;
    case SpineDiagnosticKind::kTaskActiveRecords:
      counters_.range_task_active_records = word.second;
      return;
    case SpineDiagnosticKind::kTaskFamilyProbes:
      counters_.range_task_family_probes = word.second;
      return;
    case SpineDiagnosticKind::kTaskFamilySkips:
      counters_.range_task_family_skips = word.second;
      return;
    case SpineDiagnosticKind::kDirtyCount:
      counters_.dirty_count = word.second;
      return;
    case SpineDiagnosticKind::kDirtyGeneration:
      counters_.dirty_generation = word.second;
      return;
    }
    source_protocol_overflow_ = true;
    return;
  case PartConvWordKind::kTileBegin:
    if (tile_open_ || word.first >= vertices_) {
      failed_ = true;
      done_ = true;
      return;
    }
    tile_base_ = word.first;
    tile_size_ = std::min<std::size_t>(kTileVertices, vertices_ - tile_base_);
    tile_edges_.clear();
    gather_vertices_.clear();
    gathered_values_.clear();
    changed_vertices_.clear();
    relax_index_ = 0;
    full_path_ = false;
    overflow_edge_pending_ = false;
    tile_open_ = true;
    if (word.second != 0) {
      full_path_ = true;
      ++counters_.full_path_tiles;
      ++counters_.forced_dense_tiles;
      counters_.swept_vertex_words += tile_size_;
      tile_values_.assign(tile_size_, kInfinity);
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                     tile_base_ * kVertexWordBytes,
                     tile_size_ * kVertexWordBytes, {},
                     MemoryPayloadKind::kFullTile, 0, 0,
                     ports_.vertex_state->read_beat_stream_enabled());
      phase_ = Phase::kFullLoad;
    } else {
      phase_ = Phase::kInput;
    }
    return;
  case PartConvWordKind::kEdge:
    if (!tile_open_ || word.first < tile_base_ ||
        static_cast<std::uint64_t>(word.first) >=
            static_cast<std::uint64_t>(tile_base_) + kTileVertices ||
        word.first >= vertices_) {
      failed_ = true;
      done_ = true;
      return;
    }
    if (full_path_) {
      issue_vs_read(word, VsReadPurpose::kRelax, context);
      ++counters_.full_stream_edges;
    } else if (tile_edges_.size() < tiny_threshold_) {
      tile_edges_.push_back(word);
      ++counters_.tiny_buffer_writes;
      ++counters_.tiny_bram_write_requests;
    } else {
      begin_full_path(word);
    }
    phase_ = Phase::kInput;
    if (full_path_ && overflow_edge_pending_) {
      phase_ = Phase::kFullLoad;
    }
    return;
  case PartConvWordKind::kTileEnd:
    if (!tile_open_) {
      failed_ = true;
      done_ = true;
      return;
    }
    ++counters_.touched_tiles;
    if (full_path_) {
      phase_ = Phase::kFullStreamDrain;
      return;
    }
    ++counters_.fast_path_tiles;
    counters_.tiny_buffered_edges += tile_edges_.size();
    prepare_gather();
    begin_tile_active_clear(Phase::kGatherBegin);
    return;
  case PartConvWordKind::kDoneAll:
    if (tile_open_) {
      failed_ = true;
      done_ = true;
      return;
    }
    ++counters_.done_words;
    counters_.done_overflow = (word.second & 1U) != 0;
    source_protocol_overflow_ =
        source_protocol_overflow_ || counters_.done_overflow;
    if (counters_.source_completion_markers != 0 &&
        counters_.source_completion_markers != counters_.source_requests) {
      set_protocol_status(SpineSourceProtocolStatus::kCount);
      source_protocol_overflow_ = true;
    }
    if (deferred_active_) {
      if (source_protocol_overflow_) {
        deferred_active_word_index_ = 0;
        phase_ = Phase::kDeferredFinalClear;
      } else {
        begin_deferred_sweep();
      }
    } else if (owner_scheduler_ != nullptr && owner_round_started_) {
      begin_owner_protocol(OwnerProtocolKind::kFinalizeRound, 0,
                           Phase::kFinish);
    } else {
      enqueue_memory(*ports_.result, MemoryOperation::kWrite, 0, kResultBytes,
                     std::vector<std::uint8_t>(kResultBytes, 0));
      phase_ = Phase::kFinish;
    }
    return;
  }
}

void SpineSplitSsspCompute::issue_tiny_read(std::size_t item_index,
                                            TinyReadPurpose purpose,
                                            const CycleContext &context) {
  if (item_index >= tile_edges_.size() ||
      pending_tiny_reads_.size() >= on_chip_profile_.pipeline_capacity) {
    throw std::logic_error("invalid tiny-BRAM read issue");
  }
  pending_tiny_reads_.push_back(PendingTinyRead{
      .due_cycle =
          context.domain_cycle + on_chip_profile_.tiny_bram_read_latency,
      .item_index = item_index,
      .purpose = purpose,
      .edge = tile_edges_[item_index],
  });
  ++counters_.tiny_bram_read_requests;
  counters_.max_tiny_reads_inflight =
      std::max(counters_.max_tiny_reads_inflight, pending_tiny_reads_.size());
}

void SpineSplitSsspCompute::issue_vs_read(const PartConvWord &edge,
                                          VsReadPurpose purpose,
                                          const CycleContext &context) {
  if (purpose != VsReadPurpose::kRelax ||
      pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
    throw std::logic_error("invalid relax URAM read issue");
  }
  const std::uint32_t memory_value =
      full_path_ ? tile_values_.at(edge.first - tile_base_)
                 : gathered_values_.at(edge.first);
  pending_vs_reads_.push_back(PendingVsRead{
      .due_cycle = context.domain_cycle + on_chip_profile_.vs_uram_read_latency,
      .purpose = purpose,
      .edge = edge,
      .vertex = edge.first,
      .memory_value = memory_value,
  });
  ++counters_.vs_tile_reads;
  ++counters_.vs_uram_read_requests;
  counters_.max_vs_reads_inflight =
      std::max(counters_.max_vs_reads_inflight, pending_vs_reads_.size());
}

void SpineSplitSsspCompute::issue_vs_read(std::uint32_t vertex,
                                          VsReadPurpose purpose,
                                          const CycleContext &context) {
  if (purpose == VsReadPurpose::kRelax ||
      pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
    throw std::logic_error("invalid controller URAM read issue");
  }
  const std::uint32_t memory_value = full_path_
                                         ? tile_values_.at(vertex - tile_base_)
                                         : gathered_values_.at(vertex);
  pending_vs_reads_.push_back(PendingVsRead{
      .due_cycle = context.domain_cycle + on_chip_profile_.vs_uram_read_latency,
      .purpose = purpose,
      .edge = {},
      .vertex = vertex,
      .memory_value = memory_value,
  });
  ++counters_.vs_tile_reads;
  ++counters_.vs_uram_read_requests;
  counters_.max_vs_reads_inflight =
      std::max(counters_.max_vs_reads_inflight, pending_vs_reads_.size());
}

std::uint32_t SpineSplitSsspCompute::bypass_value(std::uint32_t vertex,
                                                  std::uint32_t memory_value) {
  const auto found = std::find_if(
      vs_bypass_.begin(), vs_bypass_.end(),
      [vertex](const VsBypassEntry &entry) { return entry.vertex == vertex; });
  if (found == vs_bypass_.end()) {
    ++counters_.vs_bypass_misses;
    return memory_value;
  }
  ++counters_.vs_bypass_hits;
  return found->value;
}

void SpineSplitSsspCompute::push_bypass(std::uint32_t vertex,
                                        std::uint32_t value) {
  vs_bypass_.push_front(VsBypassEntry{.vertex = vertex, .value = value});
  if (vs_bypass_.size() > on_chip_profile_.vs_bypass_depth) {
    vs_bypass_.pop_back();
  }
}

void SpineSplitSsspCompute::reset_bypass() { vs_bypass_.clear(); }

void SpineSplitSsspCompute::count_on_chip_read_wait(std::uint64_t cycle) {
  if (last_on_chip_read_wait_cycle_ != cycle) {
    last_on_chip_read_wait_cycle_ = cycle;
    ++counters_.on_chip_read_wait_cycles;
  }
}

void SpineSplitSsspCompute::count_on_chip_pipeline_stall(std::uint64_t cycle) {
  if (last_on_chip_pipeline_stall_cycle_ != cycle) {
    last_on_chip_pipeline_stall_cycle_ = cycle;
    ++counters_.on_chip_pipeline_stall_cycles;
  }
}

bool SpineSplitSsspCompute::on_chip_pipelines_drained() const noexcept {
  return pending_tiny_reads_.empty() && pending_vs_reads_.empty() &&
         !active_read_pending_ && !active_read_ready_;
}

void SpineSplitSsspCompute::complete_relax(const PendingVsRead &request) {
  const std::uint32_t old_value =
      bypass_value(request.vertex, request.memory_value);
  const std::uint32_t reduced =
      algorithm_policy_->reduce(std::nullopt, request.edge.second);
  const AlgorithmApplyResult applied =
      algorithm_policy_->apply({.primary = old_value}, reduced);
  if (applied.active) {
    const std::uint32_t new_value = applied.state_after.primary;
    if (full_path_) {
      tile_values_.at(request.vertex - tile_base_) = new_value;
    } else {
      gathered_values_.at(request.vertex) = new_value;
    }
    values_.at(request.vertex) = new_value;
    ++counters_.vs_tile_writes;
    ++counters_.vs_uram_write_requests;
    ++counters_.tile_active_mark_writes;
    const std::size_t local = request.vertex - tile_base_;
    tile_active_words_.at(local / 64) |= std::uint64_t{1}
                                         << static_cast<unsigned>(local % 64);
    ++counters_.active_bram_write_requests;
    push_bypass(request.vertex, new_value);
    if (std::find(changed_vertices_.begin(), changed_vertices_.end(),
                  request.vertex) == changed_vertices_.end()) {
      changed_vertices_.push_back(request.vertex);
      if (!deferred_active_ && owner_scheduler_ == nullptr) {
        next_active_.push_back(request.vertex);
      }
    }
  }
  ++counters_.processed_edges;
}

void SpineSplitSsspCompute::advance_on_chip_pipelines(
    const CycleContext &context) {
  if (active_read_pending_) {
    if (active_read_due_cycle_ <= context.domain_cycle) {
      active_read_pending_ = false;
      active_read_ready_ = true;
      active_scan_bits_ = tile_active_words_.at(active_word_index_);
    } else {
      count_on_chip_read_wait(context.domain_cycle);
    }
  }

  if (!pending_vs_reads_.empty()) {
    const PendingVsRead &request = pending_vs_reads_.front();
    if (request.due_cycle > context.domain_cycle) {
      count_on_chip_read_wait(context.domain_cycle);
    } else if (request.purpose == VsReadPurpose::kRelax) {
      complete_relax(request);
      pending_vs_reads_.pop_front();
    } else if (memory_tasks_.empty()) {
      if (request.purpose == VsReadPurpose::kSparseStore) {
        enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite,
                       request.vertex * kVertexWordBytes, kVertexWordBytes,
                       encode_u32(request.memory_value));
        ++counters_.scattered_vertex_words;
        ++counters_.sparse_store_writes_generated;
      } else {
        if (owner_scheduler_ != nullptr && !staged_owner_activation_) {
          count_on_chip_pipeline_stall(context.domain_cycle);
          return;
        }
        if (owner_scheduler_ != nullptr) {
          if (staged_owner_publication_) {
            enqueue_active_output(request.vertex);
            next_active_.push_back(request.vertex);
            ++counters_.owner_activations_accepted;
          } else {
            ++counters_.owner_activations_coalesced;
          }
        } else {
          enqueue_active_output(request.vertex);
        }
      }
      pending_vs_reads_.pop_front();
    } else {
      count_on_chip_pipeline_stall(context.domain_cycle);
    }
  }

  if (!pending_tiny_reads_.empty()) {
    const PendingTinyRead &request = pending_tiny_reads_.front();
    if (request.due_cycle > context.domain_cycle) {
      count_on_chip_read_wait(context.domain_cycle);
    } else if (request.purpose == TinyReadPurpose::kGather) {
      if (memory_tasks_.empty()) {
        enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                       request.edge.first * kVertexWordBytes, kVertexWordBytes,
                       {}, MemoryPayloadKind::kGatherVertex,
                       request.item_index);
        pending_tiny_reads_.pop_front();
      } else {
        count_on_chip_pipeline_stall(context.domain_cycle);
      }
    } else if (pending_vs_reads_.size() < on_chip_profile_.pipeline_capacity) {
      const PartConvWord edge = request.edge;
      pending_tiny_reads_.pop_front();
      issue_vs_read(edge, VsReadPurpose::kRelax, context);
    } else {
      count_on_chip_pipeline_stall(context.domain_cycle);
    }
  }
}

void SpineSplitSsspCompute::prepare_gather() {
  gather_vertices_.clear();
  gather_vertices_.reserve(tile_edges_.size());
  for (const PartConvWord &edge : tile_edges_) {
    gather_vertices_.push_back(edge.first);
  }
  gathered_values_.clear();
  changed_vertices_.clear();
  relax_index_ = 0;
}

void SpineSplitSsspCompute::sort_changed_vertices_for_emit() {
  if (changed_vertices_.empty()) {
    return;
  }
  std::sort(changed_vertices_.begin(), changed_vertices_.end());
  if (!deferred_active_ && owner_scheduler_ == nullptr) {
    const std::size_t active_base =
        next_active_.size() - changed_vertices_.size();
    std::copy(changed_vertices_.begin(), changed_vertices_.end(),
              next_active_.begin() + static_cast<std::ptrdiff_t>(active_base));
  }
}

void SpineSplitSsspCompute::prepare_vertex_store() {
  sort_changed_vertices_for_emit();
  if (full_path_ && !changed_vertices_.empty()) {
    enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite,
                   tile_base_ * kVertexWordBytes, tile_size_ * kVertexWordBytes,
                   encode_u32_words(tile_values_));
    counters_.swept_vertex_words += tile_size_;
    counters_.vs_tile_reads += kTileVertices;
    counters_.vs_uram_read_requests += kTileVertices;
  }
}

void SpineSplitSsspCompute::enqueue_active_output(std::uint32_t vertex) {
  enqueue_active_output(vertex, values_.at(vertex),
                        active_output_base_ + active_output_index_);
  ++active_output_index_;
}

void SpineSplitSsspCompute::enqueue_active_output(std::uint32_t vertex,
                                                  std::uint32_t value,
                                                  std::size_t output_index) {
  std::vector<std::uint8_t> payload(kActiveOutputBytes, 0);
  const std::vector<std::uint8_t> encoded_value = encode_u32(value);
  const std::vector<std::uint8_t> encoded_vertex = encode_u32(vertex);
  std::copy(encoded_value.begin(), encoded_value.end(), payload.begin());
  std::copy(encoded_vertex.begin(), encoded_vertex.end(),
            payload.begin() + sizeof(std::uint32_t));
  enqueue_memory(*ports_.active_out, MemoryOperation::kWrite,
                 output_index * kActiveOutputBytes, kActiveOutputBytes,
                 std::move(payload));
  ++counters_.active_emit_writes_generated;
}

void SpineSplitSsspCompute::begin_tile_active_clear(Phase next_phase) {
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_scan_bits_ = 0;
  active_read_pending_ = false;
  active_read_ready_ = false;
  after_clear_phase_ = next_phase;
  phase_ = Phase::kClearTileActive;
}

std::optional<std::uint32_t>
SpineSplitSsspCompute::current_active_vertex() const {
  const std::size_t local_index =
      active_word_index_ * kActiveWordBits + active_bit_index_;
  if (local_index >= tile_size_) {
    return std::nullopt;
  }
  const std::uint32_t vertex =
      tile_base_ + static_cast<std::uint32_t>(local_index);
  return ((active_scan_bits_ >> active_bit_index_) & 1U) != 0
             ? std::optional<std::uint32_t>(vertex)
             : std::nullopt;
}

bool SpineSplitSsspCompute::controller_memory_overlap_phase() const noexcept {
  return phase_ == Phase::kGatherBegin || phase_ == Phase::kGatherAdvance ||
         phase_ == Phase::kRelax || phase_ == Phase::kSparseStoreScan ||
         phase_ == Phase::kSparseStoreBits ||
         (!full_path_ && phase_ == Phase::kStore) ||
         phase_ == Phase::kEmitActiveScan || phase_ == Phase::kEmitActiveBits ||
         phase_ == Phase::kEmitStore || phase_ == Phase::kDeferredMergeScan ||
         phase_ == Phase::kDeferredSweepRead ||
         phase_ == Phase::kDeferredSweepScan ||
         phase_ == Phase::kDeferredSweepBits ||
         phase_ == Phase::kDeferredFinalClear;
}

void SpineSplitSsspCompute::begin_sparse_store_scan() {
  sort_changed_vertices_for_emit();
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_scan_bits_ = 0;
  active_read_pending_ = false;
  active_read_ready_ = false;
  phase_ = Phase::kSparseStoreScan;
}

void SpineSplitSsspCompute::begin_active_emit_scan() {
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_output_base_ = owner_scheduler_ == nullptr
                            ? next_active_.size() - changed_vertices_.size()
                            : next_active_.size();
  active_output_index_ = 0;
  active_scan_bits_ = 0;
  active_read_pending_ = false;
  active_read_ready_ = false;
  phase_ = Phase::kEmitActiveScan;
}

void SpineSplitSsspCompute::begin_deferred_merge_scan() {
  sort_changed_vertices_for_emit();
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_scan_bits_ = 0;
  active_read_pending_ = false;
  active_read_ready_ = false;
  phase_ = Phase::kDeferredMergeScan;
}

void SpineSplitSsspCompute::begin_deferred_sweep() {
  deferred_bitmap_chunk_.fill(0);
  deferred_sweep_base_word_ = 0;
  deferred_sweep_chunk_words_ = 0;
  deferred_sweep_word_index_ = 0;
  deferred_sweep_bit_index_ = 0;
  deferred_sweep_reads_pending_ = 0;
  deferred_sweep_scan_bits_ = 0;
  deferred_sweep_next_issue_cycle_ = 0;
  deferred_sweep_next_bit_cycle_ = 0;
  active_output_base_ = 0;
  active_output_index_ = 0;
  next_active_.clear();
  phase_ = Phase::kDeferredSweepRead;
}

void SpineSplitSsspCompute::finish_active_word_scan(Phase scan_phase) {
  active_bit_index_ = 0;
  ++active_word_index_;
  active_scan_bits_ = 0;
  phase_ = scan_phase;
}

void SpineSplitSsspCompute::begin_full_path(const PartConvWord &overflow_edge) {
  full_path_ = true;
  overflow_edge_ = overflow_edge;
  overflow_edge_pending_ = true;
  ++counters_.full_path_tiles;
  counters_.swept_vertex_words += tile_size_;
  changed_vertices_.clear();
  relax_index_ = 0;
  tile_values_.assign(tile_size_, kInfinity);
  enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                 tile_base_ * kVertexWordBytes, tile_size_ * kVertexWordBytes,
                 {}, MemoryPayloadKind::kFullTile, 0, 0,
                 ports_.vertex_state->read_beat_stream_enabled());
}

void SpineSplitSsspCompute::reset_tile() {
  tile_edges_.clear();
  gather_vertices_.clear();
  gathered_values_.clear();
  changed_vertices_.clear();
  tile_values_.clear();
  relax_index_ = 0;
  active_word_index_ = 0;
  active_bit_index_ = 0;
  active_output_base_ = 0;
  active_output_index_ = 0;
  active_scan_bits_ = 0;
  active_read_due_cycle_ = 0;
  active_read_pending_ = false;
  active_read_ready_ = false;
  tile_size_ = 0;
  tile_open_ = false;
  full_path_ = false;
  overflow_edge_pending_ = false;
}

void SpineSplitSsspCompute::advance(const CycleContext &context) {
  switch (phase_) {
  case Phase::kReinitialize:
    phase_ = Phase::kInput;
    return;
  case Phase::kOwnerProtocol:
    advance_owner_protocol();
    return;
  case Phase::kSourceRead:
    source_reply_pending_ = true;
    phase_ = Phase::kSourceReply;
    return;
  case Phase::kSourceReply:
    return;
  case Phase::kDeferredActiveClear: {
    const std::size_t active_words =
        (vertices_ + kActiveWordBits - 1) / kActiveWordBits;
    if (deferred_active_word_index_ == active_words) {
      phase_ = Phase::kInput;
      return;
    }
    enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite,
                   deferred_active_word_index_ * sizeof(std::uint64_t),
                   sizeof(std::uint64_t),
                   std::vector<std::uint8_t>(sizeof(std::uint64_t), 0));
    ++deferred_active_word_index_;
    ++counters_.deferred_active_clear_words;
    return;
  }
  case Phase::kGatherBegin:
    if (relax_index_ < tile_edges_.size()) {
      if (pending_tiny_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_tiny_read(relax_index_, TinyReadPurpose::kGather, context);
      ++counters_.tiny_buffer_reads;
      ++relax_index_;
      return;
    }
    if (pending_tiny_reads_.empty() && memory_tasks_.empty() &&
        inflight_memory_tasks_.empty()) {
      phase_ = Phase::kGatherAdvance;
    }
    return;
  case Phase::kGatherAdvance:
    if (!pending_tiny_reads_.empty() || !pending_vs_reads_.empty() ||
        !memory_tasks_.empty() || !inflight_memory_tasks_.empty()) {
      return;
    }
    relax_index_ = 0;
    phase_ = Phase::kRelax;
    return;
  case Phase::kClearTileActive:
    tile_active_words_.at(active_word_index_) = 0;
    ++counters_.tile_active_clear_words;
    counters_.tile_active_clear_lane_writes += kActiveWordBits;
    ++counters_.active_bram_write_requests;
    ++counters_.on_chip_controller_cycles;
    ++active_word_index_;
    if (active_word_index_ == kTileActiveWords) {
      active_word_index_ = 0;
      reset_bypass();
      phase_ = after_clear_phase_;
    }
    return;
  case Phase::kRelax:
    if (relax_index_ < tile_edges_.size()) {
      if (pending_tiny_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_tiny_read(relax_index_, TinyReadPurpose::kRelax, context);
      ++counters_.tiny_buffer_reads;
      ++relax_index_;
      return;
    }
    if (pending_tiny_reads_.empty() && pending_vs_reads_.empty()) {
      if (changed_vertices_.empty()) {
        if (deferred_active_) {
          begin_deferred_merge_scan();
        } else {
          begin_active_emit_scan();
        }
      } else {
        begin_sparse_store_scan();
      }
    }
    return;
  case Phase::kFullLoad:
    relax_index_ = 0;
    begin_tile_active_clear(Phase::kFullReplay);
    return;
  case Phase::kFullReplay:
    if (relax_index_ < tile_edges_.size()) {
      if (pending_tiny_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_tiny_read(relax_index_, TinyReadPurpose::kRelax, context);
      ++counters_.tiny_buffer_reads;
      ++counters_.full_buffer_replay_edges;
      ++relax_index_;
      return;
    }
    if (overflow_edge_pending_) {
      if (pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_vs_read(overflow_edge_, VsReadPurpose::kRelax, context);
      ++counters_.full_overflow_edges;
      overflow_edge_pending_ = false;
      return;
    }
    phase_ = Phase::kFullReplayDrain;
    return;
  case Phase::kFullReplayDrain:
    if (!pending_tiny_reads_.empty() || !pending_vs_reads_.empty()) {
      return;
    }
    tile_edges_.clear();
    phase_ = Phase::kInput;
    return;
  case Phase::kFullStreamDrain:
    if (!pending_vs_reads_.empty()) {
      return;
    }
    prepare_vertex_store();
    phase_ = Phase::kStore;
    return;
  case Phase::kSparseStoreScan: {
    const std::size_t tile_words =
        (tile_size_ + kActiveWordBits - 1) / kActiveWordBits;
    if (active_word_index_ >= tile_words) {
      phase_ = Phase::kStore;
      return;
    }
    if (!active_read_ready_) {
      if (!active_read_pending_) {
        active_read_pending_ = true;
        active_read_due_cycle_ =
            context.domain_cycle + on_chip_profile_.active_bram_read_latency;
        ++counters_.active_bram_read_requests;
        ++counters_.sparse_store_scan_words;
        counters_.sparse_store_lane_reads += kActiveWordBits;
        ++counters_.on_chip_controller_cycles;
      } else {
        count_on_chip_pipeline_stall(context.domain_cycle);
      }
      return;
    }
    active_read_ready_ = false;
    if (active_scan_bits_ != 0) {
      active_bit_index_ = 0;
      phase_ = Phase::kSparseStoreBits;
    } else {
      ++active_word_index_;
    }
    return;
  }
  case Phase::kSparseStoreBits: {
    const std::optional<std::uint32_t> vertex = current_active_vertex();
    if (vertex.has_value()) {
      if (pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_vs_read(*vertex, VsReadPurpose::kSparseStore, context);
    }
    ++counters_.sparse_store_bit_cycles;
    ++counters_.on_chip_controller_cycles;
    ++active_bit_index_;
    if (active_bit_index_ == kActiveWordBits) {
      finish_active_word_scan(Phase::kSparseStoreScan);
    }
    return;
  }
  case Phase::kStore:
    if (!pending_vs_reads_.empty()) {
      return;
    }
    if (deferred_active_) {
      begin_deferred_merge_scan();
    } else {
      begin_active_emit_scan();
    }
    return;
  case Phase::kEmitActiveScan: {
    const std::size_t tile_words =
        (tile_size_ + kActiveWordBits - 1) / kActiveWordBits;
    if (active_word_index_ >= tile_words) {
      phase_ = Phase::kEmitStore;
      return;
    }
    if (!active_read_ready_) {
      if (!active_read_pending_) {
        active_read_pending_ = true;
        active_read_due_cycle_ =
            context.domain_cycle + on_chip_profile_.active_bram_read_latency;
        ++counters_.active_bram_read_requests;
        ++counters_.active_emit_scan_words;
        counters_.active_emit_lane_reads += kActiveWordBits;
        counters_.active_emit_lane_writes += kActiveWordBits;
        ++counters_.on_chip_controller_cycles;
      } else {
        count_on_chip_pipeline_stall(context.domain_cycle);
      }
      return;
    }
    active_read_ready_ = false;
    tile_active_words_.at(active_word_index_) = 0;
    ++counters_.active_bram_write_requests;
    if (active_scan_bits_ != 0) {
      active_bit_index_ = 0;
      if (owner_scheduler_ != nullptr) {
        const std::uint32_t global_word = static_cast<std::uint32_t>(
            tile_base_ / kActiveWordBits + active_word_index_);
        begin_owner_protocol(OwnerProtocolKind::kActivateWord, global_word,
                             Phase::kEmitActiveBits);
      } else {
        phase_ = Phase::kEmitActiveBits;
      }
    } else {
      ++active_word_index_;
    }
    return;
  }
  case Phase::kEmitActiveBits: {
    const std::optional<std::uint32_t> vertex = current_active_vertex();
    if (vertex.has_value()) {
      if (pending_vs_reads_.size() >= on_chip_profile_.pipeline_capacity) {
        count_on_chip_pipeline_stall(context.domain_cycle);
        return;
      }
      issue_vs_read(*vertex, VsReadPurpose::kActiveEmit, context);
    }
    ++counters_.active_emit_bit_cycles;
    ++counters_.on_chip_controller_cycles;
    ++active_bit_index_;
    if (active_bit_index_ == kActiveWordBits) {
      finish_active_word_scan(Phase::kEmitActiveScan);
    }
    return;
  }
  case Phase::kEmitStore:
    if (!pending_vs_reads_.empty()) {
      return;
    }
    if (owner_scheduler_ == nullptr &&
        active_output_index_ != changed_vertices_.size()) {
      failed_ = true;
      done_ = true;
      return;
    }
    reset_tile();
    phase_ = Phase::kInput;
    return;
  case Phase::kDeferredMergeScan: {
    const std::size_t tile_words =
        (tile_size_ + kActiveWordBits - 1) / kActiveWordBits;
    if (active_word_index_ >= tile_words) {
      phase_ = Phase::kDeferredMergeWait;
      return;
    }
    if (!active_read_ready_) {
      if (!active_read_pending_) {
        active_read_pending_ = true;
        active_read_due_cycle_ =
            context.domain_cycle + on_chip_profile_.active_bram_read_latency;
        ++counters_.active_bram_read_requests;
        ++counters_.on_chip_controller_cycles;
      } else {
        count_on_chip_pipeline_stall(context.domain_cycle);
      }
      return;
    }
    active_read_ready_ = false;
    tile_active_words_.at(active_word_index_) = 0;
    ++counters_.active_bram_write_requests;
    if (active_scan_bits_ != 0) {
      const std::size_t global_word =
          tile_base_ / kActiveWordBits + active_word_index_;
      enqueue_memory(*ports_.active_bitmap, MemoryOperation::kRead,
                     global_word * sizeof(std::uint64_t), sizeof(std::uint64_t),
                     {}, MemoryPayloadKind::kDeferredMergeWord, global_word,
                     active_scan_bits_);
    }
    ++active_word_index_;
    active_scan_bits_ = 0;
    return;
  }
  case Phase::kDeferredMergeWait:
    if (!memory_tasks_.empty() || !inflight_memory_tasks_.empty() ||
        !on_chip_pipelines_drained()) {
      return;
    }
    reset_tile();
    phase_ = Phase::kInput;
    return;
  case Phase::kDeferredSweepRead: {
    const std::size_t active_words =
        (vertices_ + kActiveWordBits - 1) / kActiveWordBits;
    if (deferred_sweep_base_word_ >= active_words) {
      phase_ = Phase::kDeferredSweepDrain;
      return;
    }
    if (deferred_sweep_chunk_words_ == 0) {
      deferred_sweep_chunk_words_ =
          std::min<std::size_t>(deferred_bitmap_chunk_.size(),
                                active_words - deferred_sweep_base_word_);
      deferred_sweep_word_index_ = 0;
      deferred_sweep_reads_pending_ = 0;
      deferred_bitmap_chunk_.fill(0);
    }
    // The HLS read loop always executes the full 128-entry LUTRAM chunk.
    // Entries beyond the final valid HBM word are zero-filled without an
    // AXI request, but they still consume the loop's II=4 control schedule.
    if (deferred_sweep_word_index_ < deferred_bitmap_chunk_.size()) {
      if (context.domain_cycle < deferred_sweep_next_issue_cycle_) {
        return;
      }
      const std::size_t local_word = deferred_sweep_word_index_;
      if (local_word < deferred_sweep_chunk_words_) {
        const std::size_t global_word = deferred_sweep_base_word_ + local_word;
        enqueue_memory(*ports_.active_bitmap, MemoryOperation::kRead,
                       global_word * sizeof(std::uint64_t),
                       sizeof(std::uint64_t), {},
                       MemoryPayloadKind::kDeferredSweepWord, local_word);
        ++deferred_sweep_reads_pending_;
        ++counters_.deferred_active_sweep_read_words;
      }
      ++deferred_sweep_word_index_;
      deferred_sweep_next_issue_cycle_ = context.domain_cycle + 4;
      return;
    }
    if (deferred_sweep_reads_pending_ == 0) {
      deferred_sweep_word_index_ = 0;
      phase_ = Phase::kDeferredSweepScan;
    }
    return;
  }
  case Phase::kDeferredSweepScan:
    if (deferred_sweep_word_index_ >= deferred_sweep_chunk_words_) {
      deferred_sweep_base_word_ += deferred_sweep_chunk_words_;
      deferred_sweep_chunk_words_ = 0;
      deferred_sweep_word_index_ = 0;
      phase_ = Phase::kDeferredSweepRead;
      return;
    }
    deferred_sweep_scan_bits_ =
        deferred_bitmap_chunk_.at(deferred_sweep_word_index_);
    if (deferred_sweep_scan_bits_ == 0) {
      ++deferred_sweep_word_index_;
      return;
    }
    ++counters_.deferred_active_sweep_nonzero_words;
    deferred_sweep_bit_index_ = 0;
    deferred_sweep_next_bit_cycle_ = context.domain_cycle;
    phase_ = Phase::kDeferredSweepBits;
    return;
  case Phase::kDeferredSweepBits: {
    if (context.domain_cycle < deferred_sweep_next_bit_cycle_) {
      return;
    }
    const std::size_t global_word =
        deferred_sweep_base_word_ + deferred_sweep_word_index_;
    if (((deferred_sweep_scan_bits_ >> deferred_sweep_bit_index_) & 1U) != 0) {
      const std::size_t vertex =
          global_word * kActiveWordBits + deferred_sweep_bit_index_;
      if (vertex < vertices_) {
        const std::size_t output_index = active_output_index_++;
        next_active_.push_back(static_cast<std::uint32_t>(vertex));
        enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                       vertex * kVertexWordBytes, kVertexWordBytes, {},
                       MemoryPayloadKind::kDeferredPublishVertex, vertex,
                       output_index);
        ++counters_.deferred_active_published_vertices;
      }
    }
    ++deferred_sweep_bit_index_;
    deferred_sweep_next_bit_cycle_ = context.domain_cycle + 2;
    if (deferred_sweep_bit_index_ == kActiveWordBits) {
      ++deferred_sweep_word_index_;
      deferred_sweep_scan_bits_ = 0;
      phase_ = Phase::kDeferredSweepScan;
    }
    return;
  }
  case Phase::kDeferredSweepDrain:
    if (!memory_tasks_.empty() || !inflight_memory_tasks_.empty()) {
      return;
    }
    deferred_active_word_index_ = 0;
    phase_ = Phase::kDeferredFinalClear;
    return;
  case Phase::kDeferredFinalClear: {
    const std::size_t active_words =
        (vertices_ + kActiveWordBits - 1) / kActiveWordBits;
    if (deferred_active_word_index_ == active_words) {
      phase_ = Phase::kDeferredFinalDrain;
      return;
    }
    enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite,
                   deferred_active_word_index_ * sizeof(std::uint64_t),
                   sizeof(std::uint64_t),
                   std::vector<std::uint8_t>(sizeof(std::uint64_t), 0));
    ++deferred_active_word_index_;
    ++counters_.deferred_active_final_clear_words;
    return;
  }
  case Phase::kDeferredFinalDrain:
    if (!memory_tasks_.empty() || !inflight_memory_tasks_.empty()) {
      return;
    }
    enqueue_memory(*ports_.result, MemoryOperation::kWrite, 0, kResultBytes,
                   std::vector<std::uint8_t>(kResultBytes, 0));
    phase_ = Phase::kFinish;
    return;
  case Phase::kFinish:
    counters_.end_cycle = context.domain_cycle;
    done_ = true;
    failed_ = source_protocol_overflow_;
    return;
  case Phase::kInput:
    return;
  }
}

void SpineSplitSsspCompute::begin_owner_protocol(OwnerProtocolKind kind,
                                                 std::uint32_t subject,
                                                 Phase return_phase) {
  if (owner_scheduler_ == nullptr || kind == OwnerProtocolKind::kNone ||
      owner_protocol_kind_ != OwnerProtocolKind::kNone) {
    throw std::logic_error("invalid overlapping Spine owner-HBM protocol");
  }
  // A source-completion marker can follow the last edge while vertex writes
  // remain in flight.  Entering kOwnerProtocol stalls on those requests in
  // evaluate(), then serializes the owner transaction on the shared port.
  owner_protocol_kind_ = kind;
  owner_protocol_subject_ = subject;
  owner_protocol_return_phase_ = return_phase;
  owner_protocol_index_ = 0;
  owner_protocol_request_pending_ = false;
  phase_ = Phase::kOwnerProtocol;
}

std::size_t SpineSplitSsspCompute::owner_protocol_length() const {
  switch (owner_protocol_kind_) {
  case OwnerProtocolKind::kBeginRound:
    return 2;
  case OwnerProtocolKind::kDispatchSource:
    return 7;
  case OwnerProtocolKind::kCompleteSource:
    return 6;
  case OwnerProtocolKind::kActivateWord:
    return 8;
  case OwnerProtocolKind::kFinalizeRound:
    return 9;
  case OwnerProtocolKind::kNone:
    return 0;
  }
  throw std::logic_error("unknown Spine owner-HBM protocol kind");
}

void SpineSplitSsspCompute::enqueue_owner_protocol_operation(
    std::size_t index) {
  const std::uint64_t word = owner_protocol_subject_ >> 6;
  const auto read = [this](std::uint64_t address) {
    enqueue_memory(*ports_.active_bitmap, MemoryOperation::kRead, address,
                   kOwnerWordBytes, {}, MemoryPayloadKind::kOwnerProtocol);
  };
  const auto write = [this](std::uint64_t address) {
    enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite, address,
                   kOwnerWordBytes,
                   std::vector<std::uint8_t>(kOwnerWordBytes, 0),
                   MemoryPayloadKind::kOwnerProtocol);
  };
  switch (owner_protocol_kind_) {
  case OwnerProtocolKind::kBeginRound:
    read(owner_control_address(index == 0 ? 0 : 2));
    return;
  case OwnerProtocolKind::kDispatchSource:
    switch (index) {
    case 0:
      read(owner_control_address(0));
      return;
    case 1:
      read(owner_control_address(1));
      return;
    case 2:
      read(owner_region_address(4, word));
      return;
    case 3:
      read(owner_region_address(1, word));
      return;
    case 4:
      read(owner_region_address(2, word));
      return;
    case 5:
      write(owner_region_address(1, word));
      return;
    case 6:
      write(owner_region_address(2, word));
      return;
    }
    break;
  case OwnerProtocolKind::kCompleteSource:
    if (index < 3) {
      read(owner_region_address(1 + index, word));
    } else {
      write(owner_region_address(index - 2, word));
    }
    return;
  case OwnerProtocolKind::kActivateWord:
    switch (index) {
    case 0:
      read(owner_control_address(0));
      return;
    case 1:
      read(owner_control_address(1));
      return;
    case 2:
      read(owner_region_address(4, owner_protocol_subject_));
      return;
    case 3:
      read(owner_region_address(1, owner_protocol_subject_));
      return;
    case 4:
      read(owner_region_address(2, owner_protocol_subject_));
      return;
    case 5:
      read(owner_region_address(3, owner_protocol_subject_));
      return;
    case 6:
      write(owner_region_address(3, owner_protocol_subject_));
      return;
    case 7:
      write(owner_region_address(1, owner_protocol_subject_));
      return;
    }
    break;
  case OwnerProtocolKind::kFinalizeRound:
    switch (index) {
    case 0:
      write(owner_control_address(2));
      return;
    case 1:
      read(owner_control_address(3));
      return;
    case 2:
      read(owner_control_address(4));
      return;
    case 3:
      read(owner_control_address(5));
      return;
    case 4:
      write(owner_control_address(3));
      return;
    case 5:
      write(owner_control_address(4));
      return;
    case 6:
      write(owner_control_address(5));
      return;
    case 7:
      write(owner_control_address(6));
      return;
    case 8:
      write(owner_control_address(7));
      return;
    }
    break;
  case OwnerProtocolKind::kNone:
    break;
  }
  throw std::logic_error("Spine owner-HBM protocol index is out of range");
}

void SpineSplitSsspCompute::advance_owner_protocol() {
  if (owner_protocol_request_pending_) {
    return;
  }
  if (owner_protocol_index_ < owner_protocol_length()) {
    enqueue_owner_protocol_operation(owner_protocol_index_++);
    owner_protocol_request_pending_ = true;
    return;
  }
  const OwnerProtocolKind completed = owner_protocol_kind_;
  const std::uint32_t subject = owner_protocol_subject_;
  const Phase return_phase = owner_protocol_return_phase_;
  owner_protocol_kind_ = OwnerProtocolKind::kNone;
  owner_protocol_index_ = 0;
  switch (completed) {
  case OwnerProtocolKind::kBeginRound:
    owner_seed_epoch_ = owner_scheduler_->work_credits() == 0;
    owner_round_started_ = true;
    ++counters_.owner_round_begins;
    if (return_phase == Phase::kSourceRead) {
      begin_owner_protocol(OwnerProtocolKind::kDispatchSource, subject,
                           Phase::kSourceRead);
    } else {
      phase_ = return_phase;
    }
    return;
  case OwnerProtocolKind::kDispatchSource:
    if (!staged_owner_dispatch_) {
      throw std::logic_error(
          "Spine owner-HBM source dispatch lacked logical ownership");
    }
    ++counters_.owner_source_dispatches;
    enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                   pending_source_ * kVertexWordBytes, kVertexWordBytes, {},
                   MemoryPayloadKind::kSourceValue);
    phase_ = Phase::kSourceRead;
    return;
  case OwnerProtocolKind::kCompleteSource:
    if (!staged_owner_completion_) {
      throw std::logic_error(
          "Spine owner-HBM completion lacked logical owner retirement");
    }
    ++counters_.owner_source_completions;
    phase_ = return_phase;
    return;
  case OwnerProtocolKind::kActivateWord:
    ++counters_.owner_activation_words;
    phase_ = return_phase;
    return;
  case OwnerProtocolKind::kFinalizeRound:
    if (counters_.owner_source_dispatches !=
            counters_.owner_source_completions ||
        owner_scheduler_->work_credits() != next_active_.size() ||
        !owner_scheduler_->ledger_closed()) {
      failed_ = true;
      owner_round_started_ = false;
      phase_ = return_phase;
      return;
    }
    ++counters_.owner_round_finalizes;
    owner_round_started_ = false;
    enqueue_memory(*ports_.result, MemoryOperation::kWrite, 0, kResultBytes,
                   std::vector<std::uint8_t>(kResultBytes, 0));
    phase_ = return_phase;
    return;
  case OwnerProtocolKind::kNone:
    break;
  }
  throw std::logic_error("Spine owner-HBM protocol completed without a kind");
}

} // namespace spine::sim
