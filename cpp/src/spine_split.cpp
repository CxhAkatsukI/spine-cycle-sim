#include "spine_sim/spine_split.hpp"

#include <algorithm>
#include <bit>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "detail/spine_split_payload.hpp"

namespace spine::sim {

namespace {

using detail::split_payload::kActiveOutputBytes;
using detail::split_payload::kTileVertices;
using detail::split_payload::kActiveWordBits;
using detail::split_payload::kRangeTaskPathFallback;
using detail::split_payload::encode_u32;
using detail::split_payload::encode_u64;
using detail::split_payload::decode_u32;
using detail::split_payload::decode_u64;
using detail::split_payload::encode_u32_words;

constexpr std::uint64_t kActiveRecordBytes = 32;
constexpr std::uint64_t kMetadataWordBytes = 8;
constexpr std::uint64_t kDirtyResultOffset = 80 * 4;
constexpr std::size_t kDirtyResultWords = 16;
constexpr std::uint64_t kMetadataWordsPerSlice = 8;
constexpr std::uint64_t kLevelCount = 11;
constexpr std::uint64_t kPartitionCount = 16;
constexpr std::size_t kRangeTaskMaxTiles = 256;
constexpr std::size_t kFallbackTilesPerPartition = 16;
constexpr std::uint64_t kRangeTaskMaxStart = std::uint64_t{1} << 26;
constexpr std::uint32_t kRangeTaskMaxLength = std::uint32_t{1} << 24;
constexpr std::uint32_t kRangeTaskPathExact = 1;
constexpr std::uint32_t kRangeTaskPathError = 3;
constexpr std::uint32_t kRangeTaskFallbackActiveGate = 1;
constexpr std::uint32_t kRangeTaskFallbackCapacity = 2;
constexpr std::uint32_t kRangeTaskFallbackPayloadBudget = 3;
constexpr std::uint32_t kRangeTaskFallbackDirtyRequiresHost = 4;
constexpr std::uint32_t kRangeTaskErrorFormat = 1;
constexpr std::uint32_t kRangeTaskErrorActiveBounds = 2;
constexpr std::uint32_t kRangeTaskErrorMetadata = 3;
constexpr std::uint32_t kRangeTaskErrorDestination = 4;
constexpr std::uint32_t kRangeTaskErrorPrefix = 5;
constexpr std::uint32_t kRangeTaskErrorDescriptor = 6;
constexpr std::uint32_t kRangeTaskErrorProtocol = 7;
constexpr std::uint32_t kRangeTaskErrorDirtyState = 8;

}  // namespace

SpineSplitReader::SpineSplitReader(std::string name, ClockId clock_id,
                                   const SpineL0Maintenance &maintenance,
                                   SpineReaderPorts ports,
                                   std::vector<std::uint32_t> active_sources,
                                   Fifo<PartConvWord> &edge_out,
                                   Fifo<SourceValueWord> &value_in,
                                   SpineReaderMode mode,
                                   std::shared_ptr<const GraphAlgorithmPolicy>
                                       algorithm_policy)
    : Component(std::move(name), clock_id),
      maintenance_(maintenance),
      algorithm_policy_(
          algorithm_policy != nullptr
              ? std::move(algorithm_policy)
              : std::make_shared<const GraphAlgorithmPolicy>(
                    AlgorithmPolicyConfig{.vertices = 1, .source = 0})),
      ports_(ports),
      mode_(mode),
      active_sources_(std::move(active_sources)),
      edge_out_(edge_out),
      value_in_(value_in) {
  if (ports_.task_scratch == nullptr || ports_.active_bins == nullptr ||
      ports_.metadata == nullptr || ports_.result == nullptr ||
      edge_out_.clock_id() != clock_id ||
      value_in_.clock_id() != clock_id) {
    throw std::invalid_argument("invalid Spine split reader configuration");
  }
  for (FixedAxiPort *port : ports_.graph) {
    if (port == nullptr) {
      throw std::invalid_argument("Spine reader graph AXI port is null");
    }
  }
}

void SpineSplitReader::reset_round(std::vector<std::uint32_t> active_sources) {
  if (!done_ || failed_ || !inflight_memory_tasks_.empty() ||
      !memory_tasks_.empty() ||
      active_sources.empty()) {
    throw std::logic_error("reader round reset requires a successful drain");
  }
  mode_ = SpineReaderMode::kDeviceDirty;
  active_sources_ = std::move(active_sources);
  device_active_count_ = 0;
  reset_state();
}

void SpineSplitReader::reset_active_list_round(std::size_t active_count) {
  if (!done_ || failed_ || !inflight_memory_tasks_.empty() ||
      !memory_tasks_.empty() || ports_.active_out == nullptr ||
      active_count == 0 ||
      active_count > maintenance_.config().max_vertices) {
    throw std::logic_error(
        "reader active-list reset requires a successful drained list");
  }
  mode_ = SpineReaderMode::kDeviceActiveList;
  active_sources_.assign(active_count, 0);
  device_active_count_ = active_count;
  reset_state();
}

void SpineSplitReader::reset_full_domain_round() {
  if (!done_ || failed_ || !inflight_memory_tasks_.empty() ||
      !memory_tasks_.empty()) {
    throw std::logic_error(
        "reader full-domain reset requires a successful drain");
  }
  mode_ = SpineReaderMode::kFullDomain;
  active_sources_.clear();
  device_active_count_ = 0;
  reset_state();
}

void SpineSplitReader::reset_host_round(
    const SpineActiveBins &active_bins,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::vector<std::uint32_t> source_refresh) {
  if (!done_ || (failed_ && !recoverable_host_handoff()) ||
      !inflight_memory_tasks_.empty() || !memory_tasks_.empty()) {
    throw std::logic_error(
        "reader host-active reset requires a successful drain");
  }
  mode_ = SpineReaderMode::kHostActive;
  device_active_count_ = 0;
  initialize_host_payload(active_bins, host_coverage);
  validate_source_refresh(source_refresh);
  active_sources_ = std::move(source_refresh);
  reset_state();
}

void SpineSplitReader::configure_initial_active_list_round(
    std::size_t active_count, const bool *start_ready) {
  if (phase_ != Phase::kWaitMaintenance || done_ || failed_ ||
      ports_.active_out == nullptr || start_ready == nullptr ||
      initial_host_bins_.has_value() ||
      active_count > maintenance_.config().max_vertices) {
    throw std::logic_error(
        "initial DEVICE_ACTIVE_LIST input must be configured before execution");
  }
  mode_ = SpineReaderMode::kDeviceActiveList;
  active_sources_.assign(active_count, 0);
  device_active_count_ = active_count;
  initial_start_gate_ = start_ready;
}

void SpineSplitReader::configure_start_gate(const bool *start_ready) {
  if (phase_ != Phase::kWaitMaintenance || done_ || failed_ ||
      start_ready == nullptr) {
    throw std::logic_error(
        "reader start gate must be configured before execution");
  }
  initial_start_gate_ = start_ready;
}

void SpineSplitReader::configure_initial_host_round(
    SpineActiveBins active_bins,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::vector<std::uint32_t> source_refresh) {
  if (mode_ != SpineReaderMode::kHostActive ||
      phase_ != Phase::kWaitMaintenance || done_ || failed_ ||
      initial_host_bins_.has_value()) {
    throw std::logic_error(
        "initial HOST_ACTIVE input must be configured before execution");
  }
  validate_source_refresh(source_refresh);
  initial_host_bins_ = std::move(active_bins);
  initial_host_coverage_ = host_coverage;
  active_sources_ = std::move(source_refresh);
}

void SpineSplitReader::initialize_host_payload(
    const SpineActiveBins &active_bins,
    std::optional<SpineDirtyIdentity> host_coverage) {
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  std::uint64_t offset = 0;
  for (std::size_t partition = 0; partition < active_bins.bins.size();
       ++partition) {
    const auto &bin = active_bins.bins[partition];
    ports_.metadata->initialize_payload(
        maintenance_.config().metadata_base +
            (metadata.active_bin_offset_base + partition) * kMetadataWordBytes,
        encode_u64(offset));
    ports_.metadata->initialize_payload(
        maintenance_.config().metadata_base +
            (metadata.active_bin_count_base + partition) * kMetadataWordBytes,
        encode_u64(bin.size()));
    std::vector<std::uint8_t> payload;
    payload.reserve(bin.size() * kActiveRecordBytes);
    for (const SpineActiveRecord &record : bin) {
      const std::vector<std::uint8_t> encoded =
          encode_spine_active_record(record);
      payload.insert(payload.end(), encoded.begin(), encoded.end());
    }
    if (!payload.empty()) {
      ports_.active_bins->initialize_payload(offset * kActiveRecordBytes,
                                             payload);
    }
    offset += bin.size();
  }
  const auto write_metadata_word = [&](std::uint64_t word,
                                       std::uint64_t value) {
    ports_.metadata->initialize_payload(
        maintenance_.config().metadata_base + word * kMetadataWordBytes,
        encode_u64(value));
  };
  if (host_coverage.has_value()) {
    write_metadata_word(metadata.dirty_host_generation_word,
                        host_coverage->generation);
    write_metadata_word(metadata.dirty_host_count_word, host_coverage->count);
    write_metadata_word(metadata.dirty_host_hash_sum_word,
                        host_coverage->hash_sum);
    write_metadata_word(metadata.dirty_host_hash_xor_word,
                        host_coverage->hash_xor);
  }
  write_metadata_word(metadata.dirty_host_valid_word,
                      host_coverage.has_value() ? 1 : 0);
}

void SpineSplitReader::validate_source_refresh(
    const std::vector<std::uint32_t> &source_refresh) const {
  std::unordered_set<std::uint32_t> unique_sources;
  for (const std::uint32_t source : source_refresh) {
    if (source >= maintenance_.vertices() ||
        source >= maintenance_.config().max_vertices ||
        !unique_sources.insert(source).second) {
      throw std::invalid_argument(
          "host source-refresh list is duplicated or out of bounds");
    }
  }
}

bool SpineSplitReader::recoverable_host_handoff() const noexcept {
  return done_ && failed_ && mode_ == SpineReaderMode::kDeviceDirty &&
         counters_.dirty_status ==
             static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost) &&
         counters_.range_task_path == kRangeTaskPathFallback &&
         counters_.range_task_fallback_reason != 0 &&
         counters_.range_task_error == 0;
}

void SpineSplitReader::reset_state() {
  counters_ = {};
  for (std::size_t tile = 0; tile < tiles_.size(); ++tile) {
    tiles_[tile].tile_base = static_cast<std::uint32_t>(tile * kTileVertices);
    tiles_[tile].ranges.clear();
  }
  tile_counts_.fill(0);
  tile_offsets_.fill(0);
  tile_cursors_.fill(0);
  range_probes_.clear();
  range_tasks_.clear();
  active_records_.clear();
  host_active_bins_ = {};
  level_cache_ = {};
  clear_source_page_cache();
  level_cache_ready_ = false;
  source_values_.clear();
  fallback_lookup_ = {};
  fallback_touched_masks_.fill(0);
  fallback_force_dense_.fill(false);
  memory_tasks_.clear();
  inflight_memory_tasks_.clear();
  edge_response_buffer_.clear();
  phase_ = Phase::kWaitMaintenance;
  staged_action_ = Action::kNone;
  probe_index_ = 0;
  construction_position_ = 0;
  construction_run_valid_ = false;
  construction_run_tile_ = 0;
  construction_run_start_ = 0;
  construction_run_length_ = 0;
  construction_previous_dst_ = 0;
  construction_have_previous_dst_ = false;
  probe_lower_low_ = 0;
  probe_lower_high_ = 0;
  probe_lower_limit_ = 0;
  probe_clipped_start_ = 0;
  probe_lower_second_ = false;
  bin_index_ = 0;
  scatter_index_ = 0;
  tile_index_ = 0;
  range_index_ = 0;
  range_edge_index_ = 0;
  source_request_index_ = 0;
  source_response_index_ = 0;
  source_window_begin_ = 0;
  source_window_end_ = 0;
  diagnostic_index_ = 0;
  source_completion_index_ = 0;
  fallback_partition_ = 0;
  fallback_shard_ = 0;
  fallback_record_index_ = 0;
  fallback_level_ = 0;
  fallback_tile_local_ = 0;
  fallback_lower_low_ = 0;
  fallback_lower_high_ = 0;
  fallback_lower_limit_ = 0;
  fallback_clipped_start_ = 0;
  fallback_clipped_end_ = 0;
  fallback_replay_position_ = 0;
  fallback_discovery_ = true;
  fallback_hot_ = false;
  fallback_lower_second_ = false;
  fallback_active_record_valid_ = false;
  fallback_enabled_ = false;
  fallback_after_source_refresh_ = false;
  device_spooled_ = false;
  segmented_pass_ = SegmentedPass::kNone;
  refactor31_control_remaining_ = 0;
  refactor31_setup_remaining_ = 0;
  refactor31_validation_payload_base_ = 0;
  source_page_cache_current_hit_ = false;
  metadata_control_ = 0;
  dirty_count_ = 0;
  dirty_generation_ = 0;
  dirty_hash_sum_ = 0;
  dirty_hash_xor_ = 0;
  dirty_host_generation_ = 0;
  dirty_host_count_ = 0;
  dirty_host_hash_sum_ = 0;
  dirty_host_hash_xor_ = 0;
  dirty_host_valid_ = false;
  family_directory_valid_ = false;
  active_bin_offsets_.fill(0);
  active_bin_counts_.fill(0);
  dirty_payload_valid_ = true;
  staged_memory_issue_ = false;
  staged_memory_completion_ = false;
  staged_edge_issue_task_.reset();
  edge_pipeline_mode_ = EdgePipelineMode::kNone;
  edge_pipeline_port_ = nullptr;
  edge_pipeline_base_address_ = 0;
  edge_pipeline_length_ = 0;
  edge_pipeline_issue_index_ = 0;
  edge_pipeline_retire_index_ = 0;
  edge_pipeline_source_ = 0;
  edge_pipeline_source_value_ = 0;
  edge_pipeline_tile_base_ = 0;
  edge_pipeline_tile_end_ = 0;
  edge_pipeline_hot_ = false;
  edge_pipeline_abort_ = false;
  terminal_pending_ = false;
  terminal_overflow_ = false;
  terminal_failed_ = false;
  done_ = false;
  failed_ = false;
  failure_.clear();
}

std::vector<std::uint32_t> SpineSplitReader::active_source_ids() const {
  std::vector<std::uint32_t> sources = active_sources_;
  sources.reserve(sources.size() + active_records_.size());
  for (const SpineActiveRecord &record : active_records_) {
    sources.push_back(record.source);
  }
  std::sort(sources.begin(), sources.end());
  sources.erase(std::unique(sources.begin(), sources.end()), sources.end());
  return sources;
}

void SpineSplitReader::evaluate(const CycleContext &) {
  staged_action_ = Action::kNone;
  staged_memory_issue_ = false;
  staged_memory_completion_ = false;
  staged_edge_issue_task_.reset();
  if (done_ || failed_) {
    return;
  }
  staged_memory_completion_ = stage_memory_completion();
  if (active_memory_ports() > 1) {
    ++counters_.memory_cross_port_overlap_cycles;
  }
  if (edge_pipeline_active()) {
    evaluate_edge_pipeline();
    return;
  }
  if (!memory_tasks_.empty()) {
    const MemoryTask &task = memory_tasks_.front();
    const std::size_t window = maintenance_.config().memory_request_window;
    if (inflight_memory_tasks_for_port(task.port) >= window) {
      ++counters_.memory_window_stall_cycles;
    } else if (memory_task_conflicts(task)) {
      ++counters_.memory_dependency_stall_cycles;
    } else if (task.port->requests().try_push(AxiRequest{
                   .transaction_id = next_transaction_id_,
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
  if (!memory_tasks_.empty() || !inflight_memory_tasks_.empty() ||
      staged_memory_completion_) {
    return;
  }
  if (phase_ == Phase::kWaitSourceWindow ||
      phase_ == Phase::kWaitSourceAck) {
    if (value_in_.try_pop(staged_value_)) {
      staged_action_ = Action::kPopValue;
    }
    return;
  }
  if (phase_ == Phase::kRequestSourceWindow ||
      phase_ == Phase::kSendSourceCount ||
      phase_ == Phase::kSendSourceGeneration ||
      phase_ == Phase::kSendSourceDone ||
      phase_ == Phase::kSegmentedDeferActive ||
      phase_ == Phase::kTileBegin ||
      phase_ == Phase::kEdgeEmit || phase_ == Phase::kTileEnd ||
      phase_ == Phase::kFallbackTileBegin ||
      phase_ == Phase::kFallbackEdgeEmit || phase_ == Phase::kFallbackTileEnd ||
      phase_ == Phase::kDiagnostic ||
      phase_ == Phase::kSourceCompletion || phase_ == Phase::kDone) {
    staged_stream_word_ = current_stream_word();
    if (edge_out_.try_push(staged_stream_word_)) {
      staged_action_ = Action::kPush;
    }
    return;
  }
  staged_action_ = Action::kAdvance;
}

void SpineSplitReader::commit(const CycleContext &context) {
  if (staged_memory_completion_) {
    const auto found =
        inflight_memory_tasks_.find(staged_response_.transaction_id);
    if (found == inflight_memory_tasks_.end() || !staged_response_.success) {
      failed_ = true;
      done_ = true;
      failure_ = "reader AXI response failed or used an unknown transaction ID";
      return;
    }
    consume_memory_response(found->second, staged_response_);
    inflight_memory_tasks_.erase(found);
    ++counters_.memory_requests_completed;
  }
  if (staged_memory_issue_) {
    if (staged_edge_issue_task_.has_value()) {
      commit_edge_pipeline_issue();
    } else {
      const std::uint64_t transaction_id = next_transaction_id_++;
      inflight_memory_tasks_.emplace(transaction_id,
                                     std::move(memory_tasks_.front()));
      memory_tasks_.pop_front();
      ++counters_.memory_requests_issued;
      counters_.max_memory_requests_inflight =
          std::max(counters_.max_memory_requests_inflight,
                   inflight_memory_tasks_.size());
      update_memory_concurrency_counters(
          inflight_memory_tasks_.at(transaction_id).port);
    }
  }
  switch (staged_action_) {
    case Action::kNone:
      return;
    case Action::kPopValue:
      if (phase_ == Phase::kWaitSourceAck) {
        ++counters_.source_protocol_acks;
        counters_.source_protocol_status = staged_value_.value;
        if (staged_value_.kind != SourceValueWord::Kind::kProtocolAck ||
            staged_value_.value !=
                static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk)) {
          counters_.dirty_status =
              static_cast<std::uint32_t>(SpineDirtyStatus::kProtocolError);
        }
        if (counters_.dirty_status !=
                static_cast<std::uint32_t>(SpineDirtyStatus::kOk) ||
            counters_.source_protocol_status !=
                static_cast<std::uint32_t>(SpineSourceProtocolStatus::kOk)) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorProtocol;
          begin_terminal(
              true, "reader source-value protocol acknowledgement failed");
        } else if (fallback_after_source_refresh_) {
          fallback_after_source_refresh_ = false;
          start_host_fallback(kRangeTaskFallbackActiveGate);
        } else if (active_sources_.empty() &&
                   (algorithm_policy_->config().kind ==
                        GraphAlgorithmKind::kResidualPageRank ||
                    algorithm_policy_->config().kind ==
                        GraphAlgorithmKind::kConnectedComponents)) {
          begin_terminal(false);
        } else if (device_spooled_) {
          enqueue_device_source_spool_read();
          phase_ = Phase::kSourceSpoolValidationRead;
        } else {
          phase_ = Phase::kLevelOccupancyBegin;
        }
        return;
      }
      if (phase_ != Phase::kWaitSourceWindow ||
          source_response_index_ >= active_sources_.size() ||
          staged_value_.kind != SourceValueWord::Kind::kSourceValue ||
          staged_value_.source != active_sources_[source_response_index_]) {
        counters_.source_protocol_status = static_cast<std::uint32_t>(
            SpineSourceProtocolStatus::kResponseSource);
        counters_.dirty_status =
            static_cast<std::uint32_t>(SpineDirtyStatus::kProtocolError);
      } else {
        source_values_[staged_value_.source] = staged_value_.value;
      }
      ++counters_.source_responses;
      ++source_response_index_;
      if (source_response_index_ == source_window_end_) {
        if (device_source_mode()) {
          phase_ = Phase::kSourceDirectoryBegin;
        } else if (source_request_index_ == active_sources_.size()) {
          phase_ = Phase::kSendSourceCount;
        } else {
          source_window_end_ = std::min(
              source_request_index_ + kSpineDirtyRequestWindow,
              active_sources_.size());
          ++counters_.source_request_windows;
          phase_ = Phase::kRequestSourceWindow;
        }
      }
      return;
    case Action::kPush:
      switch (phase_) {
        case Phase::kRequestSourceWindow:
          ++counters_.source_requests;
          ++source_request_index_;
          if (source_request_index_ == source_window_end_) {
            phase_ = Phase::kWaitSourceWindow;
          }
          break;
        case Phase::kSendSourceCount:
          ++counters_.source_protocol_markers;
          phase_ = Phase::kSendSourceGeneration;
          break;
        case Phase::kSendSourceGeneration:
          ++counters_.source_protocol_markers;
          phase_ = Phase::kSendSourceDone;
          break;
        case Phase::kSendSourceDone:
          ++counters_.source_protocol_markers;
          phase_ = Phase::kWaitSourceAck;
          break;
        case Phase::kSegmentedDeferActive:
          refactor31_setup_remaining_ =
              maintenance_.config().segmented_fallback_setup_cycles;
          if (refactor31_setup_remaining_ == 0) {
            begin_refactor31_control();
          } else {
            phase_ = Phase::kRefactor31SegmentSetup;
          }
          break;
        case Phase::kTileBegin:
          ++counters_.tiles_emitted;
          range_index_ = 0;
          range_edge_index_ = 0;
          phase_ = Phase::kEdgeRead;
          break;
        case Phase::kEdgeEmit:
          retire_replay_edge();
          break;
        case Phase::kTileEnd:
          ++tile_index_;
          phase_ = terminal_pending_ ? Phase::kDiagnostic : Phase::kTileScan;
      break;
    case Phase::kFallbackTileBegin:
      ++counters_.tiles_emitted;
      fallback_hot_ = false;
      fallback_shard_ = 0;
      phase_ = Phase::kFallbackPassBegin;
      break;
    case Phase::kFallbackEdgeEmit:
      retire_replay_edge();
      break;
    case Phase::kFallbackTileEnd:
      ++fallback_tile_local_;
      phase_ =
          terminal_pending_ ? Phase::kDiagnostic : Phase::kFallbackTileScan;
          break;
        case Phase::kDiagnostic:
          ++counters_.diagnostic_words;
          ++diagnostic_index_;
          if (diagnostic_index_ == 8 && device_source_mode() &&
              !terminal_overflow_ && counters_.range_task_error == 0 &&
              !active_sources_.empty()) {
            source_completion_index_ = 0;
            phase_ = Phase::kSourceCompletion;
          } else if (diagnostic_index_ == kSpineReaderDiagnosticWords) {
            phase_ = Phase::kDone;
          }
          break;
        case Phase::kSourceCompletion:
          ++counters_.source_completion_markers;
          ++source_completion_index_;
          if (source_completion_index_ == active_sources_.size()) {
            phase_ = Phase::kDiagnostic;
          }
          break;
        case Phase::kDone:
          ++counters_.done_words;
          counters_.done_overflow = terminal_overflow_;
          counters_.end_cycle = context.domain_cycle;
          failed_ = terminal_failed_;
          done_ = true;
          break;
        default:
          throw std::logic_error(
              "reader pushed a word from a non-stream phase");
      }
      return;
    case Action::kAdvance:
      advance(context);
      return;
    case Action::kRetireConstruction:
      retire_construction_edge();
      return;
    case Action::kPipelineError:
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorDestination;
      edge_pipeline_abort_ = true;
      edge_response_buffer_.clear();
      begin_terminal(true,
                     "pipelined replay returned an edge outside its tile");
      return;
    case Action::kFinishPipelineAbort:
      finish_edge_pipeline();
      return;
  }
}

bool SpineSplitReader::memory_task_conflicts(const MemoryTask &task) const {
  const std::uint64_t task_end = task.address + task.bytes;
  for (const auto &[transaction_id, inflight] : inflight_memory_tasks_) {
    (void)transaction_id;
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

std::size_t SpineSplitReader::inflight_memory_tasks_for_port(
    const FixedAxiPort *port) const noexcept {
  return static_cast<std::size_t>(std::count_if(
      inflight_memory_tasks_.begin(), inflight_memory_tasks_.end(),
      [port](const auto &entry) { return entry.second.port == port; }));
}

std::size_t SpineSplitReader::active_memory_ports() const noexcept {
  std::size_t ports = 0;
  for (auto current = inflight_memory_tasks_.begin();
       current != inflight_memory_tasks_.end(); ++current) {
    bool already_seen = false;
    for (auto prior = inflight_memory_tasks_.begin(); prior != current;
         ++prior) {
      already_seen = already_seen ||
                     prior->second.port == current->second.port;
    }
    if (!already_seen) {
      ++ports;
    }
  }
  return ports;
}

void SpineSplitReader::update_memory_concurrency_counters(
    const FixedAxiPort *issued_port) {
  counters_.max_memory_requests_inflight_per_port =
      std::max(counters_.max_memory_requests_inflight_per_port,
               inflight_memory_tasks_for_port(issued_port));
  counters_.max_active_memory_ports =
      std::max(counters_.max_active_memory_ports, active_memory_ports());
}

bool SpineSplitReader::stage_memory_completion() {
  std::uint64_t selected = std::numeric_limits<std::uint64_t>::max();
  FixedAxiPort *selected_port = nullptr;
  for (const auto &[transaction_id, task] : inflight_memory_tasks_) {
    const AxiResponse *response = task.port->responses().front();
    if (response != nullptr && response->transaction_id == transaction_id &&
        transaction_id < selected) {
      selected = transaction_id;
      selected_port = task.port;
    }
  }
  return selected_port != nullptr &&
         selected_port->responses().try_pop(staged_response_);
}

bool SpineSplitReader::edge_pipeline_active() const noexcept {
  return edge_pipeline_mode_ != EdgePipelineMode::kNone;
}

void SpineSplitReader::begin_edge_pipeline(
    EdgePipelineMode mode, FixedAxiPort &port, std::uint64_t base_address,
    std::uint32_t length, std::uint32_t source, std::uint32_t source_value,
    std::uint32_t tile_base, std::uint32_t tile_end, bool hot) {
  if (mode == EdgePipelineMode::kNone || length == 0 ||
      edge_pipeline_active() || !memory_tasks_.empty() ||
      !inflight_memory_tasks_.empty() || !edge_response_buffer_.empty()) {
    throw std::logic_error("invalid edge-pipeline start state");
  }
  edge_pipeline_mode_ = mode;
  edge_pipeline_port_ = &port;
  edge_pipeline_base_address_ = base_address;
  edge_pipeline_length_ = length;
  edge_pipeline_issue_index_ = 0;
  edge_pipeline_retire_index_ = 0;
  edge_pipeline_source_ = source;
  edge_pipeline_source_value_ = source_value;
  edge_pipeline_tile_base_ = tile_base;
  edge_pipeline_tile_end_ = tile_end;
  edge_pipeline_hot_ = hot;
  edge_pipeline_abort_ = false;
}

const SpineSplitReader::BufferedPipelineEdge *
SpineSplitReader::next_pipeline_edge() const {
  const auto found = edge_response_buffer_.find(edge_pipeline_retire_index_);
  return found == edge_response_buffer_.end() ? nullptr : &found->second;
}

bool SpineSplitReader::next_pipeline_edge_valid() const {
  const BufferedPipelineEdge *buffered = next_pipeline_edge();
  if (buffered == nullptr) {
    return false;
  }
  if (edge_pipeline_mode_ == EdgePipelineMode::kConstruction) {
    return true;
  }
  return buffered->edge.dst >= buffered->tile_base &&
         buffered->edge.dst < buffered->tile_end &&
         buffered->edge.dst < maintenance_.vertices();
}

void SpineSplitReader::evaluate_edge_pipeline() {
  if (edge_pipeline_port_ == nullptr ||
      (!edge_pipeline_abort_ && !memory_tasks_.empty())) {
    throw std::logic_error("edge pipeline overlaps a generic memory phase");
  }
  if (edge_pipeline_abort_) {
    if (inflight_memory_tasks_.empty() && !staged_memory_completion_) {
      staged_action_ = Action::kFinishPipelineAbort;
    }
    return;
  }

  if (next_pipeline_edge() != nullptr) {
    if (edge_pipeline_mode_ == EdgePipelineMode::kConstruction) {
      staged_action_ = Action::kRetireConstruction;
    } else if (!next_pipeline_edge_valid()) {
      staged_action_ = Action::kPipelineError;
    } else {
      staged_stream_word_ = current_stream_word();
      if (edge_out_.try_push(staged_stream_word_)) {
        staged_action_ = Action::kPush;
      } else {
        ++counters_.edge_pipeline_axis_stall_cycles;
      }
    }
  }

  if (staged_action_ == Action::kPipelineError ||
      edge_pipeline_issue_index_ == edge_pipeline_length_) {
    return;
  }
  const std::size_t occupied =
      inflight_memory_tasks_.size() + edge_response_buffer_.size();
  if (inflight_memory_tasks_.size() >=
          maintenance_.config().reader_edge_pipeline_depth ||
      occupied >= maintenance_.config().reader_edge_response_capacity) {
    ++counters_.edge_pipeline_credit_stall_cycles;
    return;
  }

  MemoryPayloadKind payload_kind = MemoryPayloadKind::kConstructionEdge;
  if (edge_pipeline_mode_ == EdgePipelineMode::kExactReplay) {
    payload_kind = MemoryPayloadKind::kReplayEdge;
  } else if (edge_pipeline_mode_ == EdgePipelineMode::kFallbackReplay) {
    payload_kind = MemoryPayloadKind::kFallbackReplayEdge;
  }
  MemoryTask task{
      .port = edge_pipeline_port_,
      .operation = MemoryOperation::kRead,
      .address = edge_pipeline_base_address_ +
                 static_cast<std::uint64_t>(edge_pipeline_issue_index_) *
                     kSpineGraphWordBytes,
      .bytes = kSpineGraphWordBytes,
      .write_data = {},
      .edge_source = edge_pipeline_source_,
      .edge_source_value = edge_pipeline_source_value_,
      .edge_tile_base = edge_pipeline_tile_base_,
      .edge_tile_end = edge_pipeline_tile_end_,
      .item_index = probe_index_,
      .stream_sequence = edge_pipeline_issue_index_,
      .edge_hot = edge_pipeline_hot_,
      .payload_kind = payload_kind,
  };
  if (edge_pipeline_port_->requests().try_push(AxiRequest{
          .transaction_id = next_transaction_id_,
          .operation = MemoryOperation::kRead,
          .address = task.address,
          .bytes = task.bytes,
          .write_data = {},
      })) {
    staged_edge_issue_task_ = std::move(task);
    staged_memory_issue_ = true;
  } else {
    ++counters_.memory_request_fifo_stall_cycles;
    ++counters_.edge_pipeline_request_fifo_stall_cycles;
  }
}

void SpineSplitReader::commit_edge_pipeline_issue() {
  if (!staged_edge_issue_task_.has_value()) {
    throw std::logic_error("edge pipeline committed without a staged request");
  }
  const MemoryPayloadKind kind = staged_edge_issue_task_->payload_kind;
  const std::uint64_t transaction_id = next_transaction_id_++;
  inflight_memory_tasks_.emplace(transaction_id,
                                 std::move(*staged_edge_issue_task_));
  staged_edge_issue_task_.reset();
  ++edge_pipeline_issue_index_;
  ++counters_.memory_requests_issued;
  counters_.graph_read_bytes += kSpineGraphWordBytes;
  if (kind == MemoryPayloadKind::kConstructionEdge) {
    ++counters_.construction_pipeline_requests;
  } else {
    ++counters_.replay_pipeline_requests;
  }
  counters_.max_memory_requests_inflight = std::max(
      counters_.max_memory_requests_inflight, inflight_memory_tasks_.size());
  update_memory_concurrency_counters(
      inflight_memory_tasks_.at(transaction_id).port);
  counters_.edge_pipeline_max_inflight = std::max(
      counters_.edge_pipeline_max_inflight, inflight_memory_tasks_.size());
}

void SpineSplitReader::finish_edge_pipeline() {
  if (!inflight_memory_tasks_.empty()) {
    throw std::logic_error("edge pipeline finished with requests in flight");
  }
  edge_response_buffer_.clear();
  staged_edge_issue_task_.reset();
  edge_pipeline_mode_ = EdgePipelineMode::kNone;
  edge_pipeline_port_ = nullptr;
  edge_pipeline_base_address_ = 0;
  edge_pipeline_length_ = 0;
  edge_pipeline_issue_index_ = 0;
  edge_pipeline_retire_index_ = 0;
  edge_pipeline_source_ = 0;
  edge_pipeline_source_value_ = 0;
  edge_pipeline_tile_base_ = 0;
  edge_pipeline_tile_end_ = 0;
  edge_pipeline_hot_ = false;
  edge_pipeline_abort_ = false;
}

void SpineSplitReader::enqueue_read(FixedAxiPort &port, std::uint64_t address,
                                    std::uint64_t bytes,
                                    MemoryPayloadKind payload_kind,
                                    std::size_t item_index,
                                    std::uint32_t edge_source) {
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = MemoryOperation::kRead,
      .address = address,
      .bytes = bytes,
      .write_data = {},
      .edge_source = edge_source,
      .item_index = item_index,
      .payload_kind = payload_kind,
  });
  if (&port == ports_.task_scratch) {
    if (payload_kind == MemoryPayloadKind::kDirtyList) {
      counters_.dirty_list_read_bytes += bytes;
    } else if (payload_kind == MemoryPayloadKind::kDirtyBitmap) {
      counters_.dirty_bitmap_read_bytes += bytes;
    } else if (payload_kind == MemoryPayloadKind::kFamilyDirectory) {
      counters_.family_directory_read_bytes += bytes;
    }
  } else if (&port == ports_.active_out) {
    counters_.active_bin_read_bytes += bytes;
  } else if (&port == ports_.active_bins) {
    counters_.active_bin_read_bytes += bytes;
    if (payload_kind == MemoryPayloadKind::kDeviceSourceSpool) {
      counters_.device_source_spool_read_bytes += bytes;
    }
  } else if (&port == ports_.metadata) {
    counters_.metadata_read_bytes += bytes;
  } else {
    counters_.graph_read_bytes += bytes;
  }
}

void SpineSplitReader::enqueue_write(
    FixedAxiPort &port, std::uint64_t address,
    std::vector<std::uint8_t> write_data, MemoryPayloadKind payload_kind,
    std::size_t item_index) {
  const std::uint64_t bytes = write_data.size();
  if (bytes == 0) {
    throw std::invalid_argument("Spine reader write payload cannot be empty");
  }
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = MemoryOperation::kWrite,
      .address = address,
      .bytes = bytes,
      .write_data = std::move(write_data),
      .item_index = item_index,
      .payload_kind = payload_kind,
  });
  if (&port == ports_.metadata) {
    counters_.metadata_write_bytes += bytes;
  } else if (&port == ports_.result) {
    counters_.result_write_bytes += bytes;
  } else if (&port == ports_.active_bins &&
             payload_kind == MemoryPayloadKind::kDeviceSourceSpool) {
    counters_.device_source_spool_write_bytes += bytes;
  }
}

bool SpineSplitReader::device_source_mode() const noexcept {
  return mode_ == SpineReaderMode::kDeviceDirty ||
         mode_ == SpineReaderMode::kDeviceActiveList ||
         mode_ == SpineReaderMode::kFullDomain;
}

void SpineSplitReader::store_device_source_record(std::size_t index,
                                                  std::uint32_t mask) {
  if (index >= active_sources_.size() || index >= active_records_.size()) {
    throw std::logic_error("device source record index is out of bounds");
  }
  const std::uint32_t source = active_sources_.at(index);
  const auto value = source_values_.find(source);
  if (value == source_values_.end()) {
    throw std::logic_error("device source record has no source value");
  }
  SpineActiveRecord record{
      .source = source,
      .source_value = value->second,
      .hot_shard_mask = static_cast<std::uint16_t>(mask >> 16),
  };
  record.level_masks.fill(static_cast<std::uint16_t>(mask));
  active_records_[index] = record;
  if (mask == 0) {
    ++counters_.family_directory_empty_masks;
  }
  if (device_spooled_) {
    enqueue_write(*ports_.active_bins, index * kActiveRecordBytes,
                  encode_spine_active_record(record),
                  MemoryPayloadKind::kDeviceSourceSpool, index);
  }
}

void SpineSplitReader::begin_source_directory_window() {
  if (!device_source_mode() || source_window_begin_ > source_window_end_ ||
      source_window_end_ > active_sources_.size()) {
    throw std::logic_error("invalid device source-directory window");
  }
  for (std::size_t index = source_window_begin_; index < source_window_end_;
       ++index) {
    if (!family_directory_valid_) {
      store_device_source_record(index, 0xffffffffU);
      continue;
    }
    const std::uint32_t source = active_sources_.at(index);
    enqueue_read(*ports_.task_scratch,
                 maintenance_.config().persistent_family_directory_base +
                     (source >> 2) * kSpineSortWordBytes,
                 kSpineSortWordBytes, MemoryPayloadKind::kFamilyDirectory,
                 index, source);
  }
  phase_ = Phase::kSourceDirectoryResolve;
}

void SpineSplitReader::enqueue_device_source_spool_read() {
  if (!device_spooled_ || active_sources_.empty()) {
    throw std::logic_error("invalid device source-spool read");
  }
  const std::size_t window = maintenance_.config().range_task_active_gate;
  for (std::size_t base = 0; base < active_sources_.size(); base += window) {
    const std::size_t count =
        std::min(window, active_sources_.size() - base);
    enqueue_read(*ports_.active_bins, base * kActiveRecordBytes,
                 count * kActiveRecordBytes,
                 MemoryPayloadKind::kDeviceSourceSpool, base);
  }
}

void SpineSplitReader::enqueue_terminal_writes() {
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  const std::uint32_t mode = mode_ == SpineReaderMode::kHostActive
                                 ? 1U
                                 : mode_ == SpineReaderMode::kFullDomain ? 4U
                                                                         : 2U;
  enqueue_write(*ports_.metadata,
                maintenance_.config().metadata_base +
                    metadata.dirty_last_mode_word * kMetadataWordBytes,
                encode_u64(mode));
  enqueue_write(*ports_.metadata,
                maintenance_.config().metadata_base +
                    metadata.dirty_last_status_word * kMetadataWordBytes,
                encode_u64(counters_.dirty_status));

  std::vector<std::uint32_t> words(kDirtyResultWords, 0);
  words[0] = mode;
  words[1] = counters_.dirty_status;
  words[2] = counters_.dirty_count;
  words[3] = counters_.dirty_generation;
  words[4] = static_cast<std::uint32_t>(counters_.dirty_hash_sum);
  words[5] = static_cast<std::uint32_t>(counters_.dirty_hash_sum >> 32);
  words[6] = static_cast<std::uint32_t>(counters_.dirty_hash_xor);
  words[7] = static_cast<std::uint32_t>(counters_.dirty_hash_xor >> 32);
  words[8] = static_cast<std::uint32_t>(counters_.source_requests);
  words[9] = static_cast<std::uint32_t>(counters_.source_responses);
  words[10] = counters_.acknowledgement_eligible ? 1U : 0U;
  words[11] = counters_.host_coverage_match ? 1U : 0U;
  enqueue_write(*ports_.result,
                maintenance_.config().result_base + kDirtyResultOffset,
                encode_u32_words(words));
}

void SpineSplitReader::consume_memory_response(const MemoryTask &task,
                                               const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("Spine reader write response carried a payload");
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine reader payload size mismatch");
  }
  const bool probe_payload =
      task.payload_kind == MemoryPayloadKind::kPageEpoch ||
      task.payload_kind == MemoryPayloadKind::kIndexBitmapPage ||
      task.payload_kind == MemoryPayloadKind::kIndexBitmapSelected ||
      task.payload_kind == MemoryPayloadKind::kIndexBitmapPrefix ||
      task.payload_kind == MemoryPayloadKind::kIndexPageBase ||
      task.payload_kind == MemoryPayloadKind::kIndexRow ||
      task.payload_kind == MemoryPayloadKind::kIndexNextRow;
  if (probe_payload && task.item_index >= range_probes_.size()) {
    throw std::logic_error("Spine reader response references an invalid probe");
  }
  switch (task.payload_kind) {
    case MemoryPayloadKind::kNone:
      return;
    case MemoryPayloadKind::kMetadataControl:
      metadata_control_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyCount:
      dirty_count_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyGeneration:
      dirty_generation_ =
          static_cast<std::uint32_t>(decode_u64(response.read_data));
      return;
    case MemoryPayloadKind::kDirtyHashSum:
      dirty_hash_sum_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyHashXor:
      dirty_hash_xor_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyHostGeneration:
      dirty_host_generation_ =
          static_cast<std::uint32_t>(decode_u64(response.read_data));
      return;
    case MemoryPayloadKind::kDirtyHostCount:
      dirty_host_count_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyHostHashSum:
      dirty_host_hash_sum_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyHostHashXor:
      dirty_host_hash_xor_ = decode_u64(response.read_data);
      return;
    case MemoryPayloadKind::kDirtyHostValid:
      dirty_host_valid_ = decode_u64(response.read_data) != 0;
      return;
    case MemoryPayloadKind::kFamilyDirectoryValid:
      family_directory_valid_ = decode_u64(response.read_data) != 0;
      return;
    case MemoryPayloadKind::kDirtyList: {
      if (task.item_index >= active_sources_.size()) {
        throw std::logic_error("dirty-list response index is out of bounds");
      }
      active_sources_[task.item_index] = decode_u32(
          response.read_data, (task.item_index & 3U) * sizeof(std::uint32_t));
      return;
    }
    case MemoryPayloadKind::kDirtyBitmap: {
      const std::uint32_t source = task.edge_source;
      const std::size_t byte = (source & 127U) >> 3;
      const std::uint8_t bit = static_cast<std::uint8_t>(1U << (source & 7U));
      if (byte >= response.read_data.size() ||
          (response.read_data[byte] & bit) == 0) {
        dirty_payload_valid_ = false;
      }
      return;
    }
    case MemoryPayloadKind::kFamilyDirectory: {
      if (task.item_index >= active_records_.size()) {
        throw std::logic_error(
            "family-directory response index is out of bounds");
      }
      const std::size_t lane = task.edge_source & 3U;
      const std::uint32_t mask =
          decode_u32(response.read_data, lane * sizeof(std::uint32_t));
      ++counters_.family_directory_mask_reads;
      store_device_source_record(task.item_index, mask);
      return;
    }
    case MemoryPayloadKind::kDeviceSourceSpool: {
      if (response.read_data.size() % kActiveRecordBytes != 0) {
        throw std::logic_error("device source-spool payload is misaligned");
      }
      const std::size_t count = response.read_data.size() / kActiveRecordBytes;
      if (task.item_index > active_records_.size() ||
          count > active_records_.size() - task.item_index) {
        throw std::logic_error("device source-spool response exceeds domain");
      }
      for (std::size_t offset = 0; offset < count; ++offset) {
        active_records_[task.item_index + offset] = decode_spine_active_record(
            std::span<const std::uint8_t>(response.read_data)
                .subspan(offset * kActiveRecordBytes, kActiveRecordBytes));
      }
      return;
    }
    case MemoryPayloadKind::kDeviceActiveOutput: {
      if (task.item_index >= active_sources_.size() ||
          response.read_data.size() != kActiveOutputBytes) {
        throw std::logic_error("device active-list payload shape is invalid");
      }
      const std::uint32_t value = decode_u32(response.read_data, 0);
      const std::uint32_t source = decode_u32(response.read_data, 4);
      active_sources_[task.item_index] = source;
      source_values_[source] = value;
      return;
    }
    case MemoryPayloadKind::kActiveBinMetadata: {
      const std::size_t partition = task.item_index % kPartitionCount;
      if (task.item_index < kPartitionCount) {
        active_bin_offsets_[partition] = decode_u64(response.read_data);
      } else {
        active_bin_counts_[partition] = decode_u64(response.read_data);
      }
      return;
    }
    case MemoryPayloadKind::kActiveRecords: {
      if (task.item_index >= host_active_bins_.bins.size() ||
          response.read_data.size() % kActiveRecordBytes != 0) {
        throw std::logic_error("active-record payload shape is invalid");
      }
      auto &bin = host_active_bins_.bins[task.item_index];
      for (std::size_t offset = 0; offset < response.read_data.size();
           offset += kActiveRecordBytes) {
        const SpineActiveRecord record = decode_spine_active_record(
            std::span<const std::uint8_t>(response.read_data)
                .subspan(offset, kActiveRecordBytes));
        bin.push_back(record);
        active_records_.push_back(record);
      }
      return;
    }
    case MemoryPayloadKind::kLevelOccupied:
      if (task.item_index >= level_cache_.size()) {
        throw std::logic_error("level occupancy index is out of bounds");
      }
      level_cache_[task.item_index].occupied =
          decode_u64(response.read_data) != 0;
      return;
    case MemoryPayloadKind::kLevelFields: {
      if (task.item_index >= level_cache_.size() ||
          response.read_data.size() != 7 * kMetadataWordBytes) {
        throw std::logic_error("level metadata response shape is invalid");
      }
      LevelCacheEntry &entry = level_cache_[task.item_index];
      entry.edge_count = decode_u64(response.read_data, 0);
      entry.row_count = decode_u64(response.read_data, 8);
      entry.layout.bitmap_offset_words = decode_u64(response.read_data, 16);
      entry.layout.page_base_offset_words = decode_u64(response.read_data, 24);
      entry.layout.row_offset_offset_words = decode_u64(response.read_data, 32);
      entry.layout.mask_offset_words = decode_u64(response.read_data, 40);
      entry.layout.edge_offset_words = decode_u64(response.read_data, 48);
      return;
    }
    case MemoryPayloadKind::kSliceEpoch: {
      if (task.item_index >= level_cache_.size()) {
        throw std::logic_error("slice epoch index is out of bounds");
      }
      const std::uint64_t packed = decode_u64(response.read_data);
      level_cache_[task.item_index].slice_epoch = static_cast<std::uint32_t>(
          (packed >> ((task.item_index & 1U) * 32)) & 0xffffffffULL);
      return;
    }
    case MemoryPayloadKind::kPageEpoch: {
      const std::uint64_t packed = decode_u64(response.read_data);
      const RangeProbe &probe = range_probes_[task.item_index];
      range_probes_[task.item_index].page_epoch = static_cast<std::uint32_t>(
          (packed >> ((probe.page & 1U) * 32)) & 0xffffffffULL);
      return;
    }
    case MemoryPayloadKind::kIndexBitmapPage: {
      RangeProbe &probe = range_probes_[task.item_index];
      if (response.read_data.size() != 4 * kSpineGraphWordBytes) {
        throw std::logic_error("source-page bitmap cache fill has wrong size");
      }
      probe.bitmap_words.resize(4);
      for (std::size_t word = 0; word < 4; ++word) {
        probe.bitmap_words[word] =
            decode_u64(response.read_data, word * kSpineGraphWordBytes);
      }
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      counters_.graph_index_bitmap_words += 4;
      return;
    }
    case MemoryPayloadKind::kIndexBitmapSelected: {
      RangeProbe &probe = range_probes_[task.item_index];
      probe.bitmap_words.assign(probe.lane_word + 1, 0);
      probe.bitmap_words[probe.lane_word] = decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      ++counters_.graph_index_bitmap_words;
      return;
    }
    case MemoryPayloadKind::kIndexBitmapPrefix: {
      RangeProbe &probe = range_probes_[task.item_index];
      const std::size_t words =
          response.read_data.size() / kSpineGraphWordBytes;
      if (probe.bitmap_words.size() != probe.lane_word + 1 ||
          words != probe.lane_word) {
        throw std::logic_error("Spine bitmap-rank prefix has wrong length");
      }
      for (std::size_t word = 0; word < words; ++word) {
        probe.bitmap_words[word] =
            decode_u64(response.read_data, word * kSpineGraphWordBytes);
      }
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      counters_.graph_index_bitmap_words += words;
      return;
    }
    case MemoryPayloadKind::kIndexPageBase:
      range_probes_[task.item_index].page_base_word =
          decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kIndexRow:
      range_probes_[task.item_index].row_word = decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kIndexNextRow:
      range_probes_[task.item_index].next_row_word =
          decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kProbeBinaryEdge:
      probe_binary_edge_ =
          decode_spine_level_edge(response.read_data, task.edge_source);
      counters_.graph_edge_payload_read_bytes += response.read_data.size();
      ++counters_.range_task_hot_lower_bound_reads;
      return;
    case MemoryPayloadKind::kConstructionEdge: {
      const SpineEdgeRecord edge =
          decode_spine_level_edge(response.read_data, task.edge_source);
      counters_.graph_edge_payload_read_bytes += response.read_data.size();
      counters_.graph_construction_payload_read_bytes +=
          response.read_data.size();
      ++counters_.range_task_construction_payloads;
      if (!edge_pipeline_abort_) {
        const auto [iterator, inserted] = edge_response_buffer_.emplace(
            task.stream_sequence, BufferedPipelineEdge{
                                      .edge = edge,
                                      .source_value = task.edge_source_value,
                                      .tile_base = task.edge_tile_base,
                                      .tile_end = task.edge_tile_end,
                                      .hot = task.edge_hot,
                                  });
        (void)iterator;
        if (!inserted) {
          throw std::logic_error(
              "construction pipeline received a duplicate sequence");
        }
        counters_.edge_pipeline_max_buffered = std::max(
            counters_.edge_pipeline_max_buffered, edge_response_buffer_.size());
      }
      return;
    }
    case MemoryPayloadKind::kReplayEdge: {
      const SpineEdgeRecord edge =
          decode_spine_level_edge(response.read_data, task.edge_source);
      counters_.graph_edge_payload_read_bytes += response.read_data.size();
      counters_.graph_replay_payload_read_bytes += response.read_data.size();
      ++counters_.range_task_replay_payloads;
      if (segmented_pass_ == SegmentedPass::kExecution) {
        ++counters_.segmented_replay_payloads;
      }
      if (!edge_pipeline_abort_) {
        const auto [iterator, inserted] = edge_response_buffer_.emplace(
            task.stream_sequence, BufferedPipelineEdge{
                                      .edge = edge,
                                      .source_value = task.edge_source_value,
                                      .tile_base = task.edge_tile_base,
                                      .tile_end = task.edge_tile_end,
                                      .hot = task.edge_hot,
                                  });
        (void)iterator;
        if (!inserted) {
          throw std::logic_error(
              "exact replay pipeline received a duplicate sequence");
        }
        counters_.edge_pipeline_max_buffered = std::max(
            counters_.edge_pipeline_max_buffered, edge_response_buffer_.size());
      }
      return;
    }
  case MemoryPayloadKind::kFallbackActiveRecord:
    if (response.read_data.size() != kActiveRecordBytes) {
      throw std::logic_error("fallback active-record payload has wrong size");
    }
    fallback_lookup_.record = decode_spine_active_record(response.read_data);
    fallback_active_record_valid_ = true;
    return;
  case MemoryPayloadKind::kFallbackOccupied:
    fallback_lookup_.occupied = decode_u64(response.read_data) != 0;
    return;
  case MemoryPayloadKind::kFallbackSliceEpoch: {
    const std::size_t logical_family =
        fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                             : fallback_lookup_.family;
    const std::size_t slice =
        logical_family * kLevelCount + fallback_lookup_.level;
    const std::uint64_t packed = decode_u64(response.read_data);
    fallback_lookup_.slice_epoch =
        static_cast<std::uint32_t>(packed >> ((slice & 1U) * 32));
    return;
  }
  case MemoryPayloadKind::kFallbackPageEpoch: {
    const std::uint64_t packed = decode_u64(response.read_data);
    fallback_lookup_.page_epoch = static_cast<std::uint32_t>(
        packed >> ((fallback_lookup_.page & 1U) * 32));
    return;
  }
  case MemoryPayloadKind::kFallbackBitmapPage:
    if (response.read_data.size() != 4 * kSpineGraphWordBytes) {
      throw std::logic_error("fallback page-cache bitmap fill has wrong size");
    }
    fallback_lookup_.bitmap_words.resize(4);
    for (std::size_t word = 0; word < 4; ++word) {
      fallback_lookup_.bitmap_words[word] =
          decode_u64(response.read_data, word * kSpineGraphWordBytes);
    }
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    counters_.graph_index_bitmap_words += 4;
    return;
  case MemoryPayloadKind::kFallbackBitmapOffset:
    fallback_lookup_.layout.bitmap_offset_words =
        decode_u64(response.read_data);
    return;
  case MemoryPayloadKind::kFallbackPageBaseOffset:
    fallback_lookup_.layout.page_base_offset_words =
        decode_u64(response.read_data);
    return;
  case MemoryPayloadKind::kFallbackRowOffset:
    fallback_lookup_.layout.row_offset_offset_words =
        decode_u64(response.read_data);
    return;
  case MemoryPayloadKind::kFallbackEdgeOffset:
    fallback_lookup_.layout.edge_offset_words = decode_u64(response.read_data);
    return;
  case MemoryPayloadKind::kFallbackBitmapSelected:
    fallback_lookup_.bitmap_words.assign(fallback_lookup_.lane_word + 1, 0);
    fallback_lookup_.bitmap_words[fallback_lookup_.lane_word] =
        decode_u64(response.read_data);
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    ++counters_.graph_index_bitmap_words;
    return;
  case MemoryPayloadKind::kFallbackBitmapPrefix: {
    const std::size_t words = response.read_data.size() / kSpineGraphWordBytes;
    if (fallback_lookup_.bitmap_words.size() !=
            fallback_lookup_.lane_word + 1 ||
        words != fallback_lookup_.lane_word) {
      throw std::logic_error("fallback bitmap-rank prefix has wrong length");
    }
    for (std::size_t word = 0; word < words; ++word) {
      fallback_lookup_.bitmap_words[word] =
          decode_u64(response.read_data, word * kSpineGraphWordBytes);
    }
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    counters_.graph_index_bitmap_words += words;
    return;
  }
  case MemoryPayloadKind::kFallbackPageBase:
    fallback_lookup_.page_base_word = decode_u64(response.read_data);
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    return;
  case MemoryPayloadKind::kFallbackRow:
    fallback_lookup_.row_word = decode_u64(response.read_data);
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    return;
  case MemoryPayloadKind::kFallbackNextRow:
    fallback_lookup_.next_row_word = decode_u64(response.read_data);
    counters_.graph_index_payload_read_bytes += response.read_data.size();
    return;
  case MemoryPayloadKind::kFallbackBinaryEdge:
    fallback_binary_edge_ =
        decode_spine_level_edge(response.read_data, task.edge_source);
    counters_.graph_edge_payload_read_bytes += response.read_data.size();
    ++counters_.fallback_lower_bound_reads;
    return;
  case MemoryPayloadKind::kFallbackFirstEdge:
    fallback_first_edge_ =
        decode_spine_level_edge(response.read_data, task.edge_source);
    counters_.graph_edge_payload_read_bytes += response.read_data.size();
    ++counters_.fallback_endpoint_reads;
    return;
  case MemoryPayloadKind::kFallbackLastEdge:
    fallback_last_edge_ =
        decode_spine_level_edge(response.read_data, task.edge_source);
    counters_.graph_edge_payload_read_bytes += response.read_data.size();
    ++counters_.fallback_endpoint_reads;
    return;
  case MemoryPayloadKind::kFallbackReplayEdge: {
    const SpineEdgeRecord edge =
        decode_spine_level_edge(response.read_data, task.edge_source);
    counters_.graph_edge_payload_read_bytes += response.read_data.size();
    counters_.graph_replay_payload_read_bytes += response.read_data.size();
    ++counters_.range_task_replay_payloads;
    ++counters_.fallback_replay_edges;
    if (!edge_pipeline_abort_) {
      const auto [iterator, inserted] = edge_response_buffer_.emplace(
          task.stream_sequence, BufferedPipelineEdge{
                                    .edge = edge,
                                    .source_value = task.edge_source_value,
                                    .tile_base = task.edge_tile_base,
                                    .tile_end = task.edge_tile_end,
                                    .hot = task.edge_hot,
                                });
      (void)iterator;
      if (!inserted) {
        throw std::logic_error(
            "fallback replay pipeline received a duplicate sequence");
      }
      counters_.edge_pipeline_max_buffered = std::max(
          counters_.edge_pipeline_max_buffered, edge_response_buffer_.size());
    }
    return;
  }
  }
}

void SpineSplitReader::begin_source_header_reads() {
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.hot_enabled_word * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kMetadataControl);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.dirty_count_word * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kDirtyCount);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.dirty_generation_word * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kDirtyGeneration);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.dirty_hash_sum_word * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kDirtyHashSum);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.dirty_hash_xor_word * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kDirtyHashXor);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   metadata.family_directory_valid_word * kMetadataWordBytes,
               kMetadataWordBytes,
               MemoryPayloadKind::kFamilyDirectoryValid);
  if (mode_ == SpineReaderMode::kHostActive) {
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     metadata.dirty_host_generation_word * kMetadataWordBytes,
                 kMetadataWordBytes,
                 MemoryPayloadKind::kDirtyHostGeneration);
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     metadata.dirty_host_count_word * kMetadataWordBytes,
                 kMetadataWordBytes, MemoryPayloadKind::kDirtyHostCount);
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     metadata.dirty_host_hash_sum_word * kMetadataWordBytes,
                 kMetadataWordBytes, MemoryPayloadKind::kDirtyHostHashSum);
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     metadata.dirty_host_hash_xor_word * kMetadataWordBytes,
                 kMetadataWordBytes, MemoryPayloadKind::kDirtyHostHashXor);
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     metadata.dirty_host_valid_word * kMetadataWordBytes,
                 kMetadataWordBytes, MemoryPayloadKind::kDirtyHostValid);
    for (std::size_t partition = 0; partition < kPartitionCount; ++partition) {
      enqueue_read(*ports_.metadata,
                   maintenance_.config().metadata_base +
                       (metadata.active_bin_offset_base + partition) *
                           kMetadataWordBytes,
                   kMetadataWordBytes, MemoryPayloadKind::kActiveBinMetadata,
                   partition);
      enqueue_read(
          *ports_.metadata,
          maintenance_.config().metadata_base +
              (metadata.active_bin_count_base + partition) * kMetadataWordBytes,
          kMetadataWordBytes, MemoryPayloadKind::kActiveBinMetadata,
          kPartitionCount + partition);
    }
  }
}

void SpineSplitReader::validate_control() {
  if (!spine_metadata_control_valid(
          metadata_control_, maintenance_.config().maintenance_architecture)) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorFormat;
    begin_terminal(
        true,
        "reader metadata control word has the wrong magic/version/features");
  }
}

void SpineSplitReader::prepare_range_probes() {
  if (!device_source_mode() && !source_values_.empty()) {
    for (SpineActiveRecord &record : active_records_) {
      const auto found = source_values_.find(record.source);
      if (found != source_values_.end()) {
        record.source_value = found->second;
      }
    }
    for (auto &bin : host_active_bins_.bins) {
      for (SpineActiveRecord &record : bin) {
        const auto found = source_values_.find(record.source);
        if (found != source_values_.end()) {
          record.source_value = found->second;
        }
      }
    }
  }
  counters_.range_task_active_records = active_records_.size();
  if (device_spooled_ ||
      active_records_.size() > maintenance_.config().range_task_active_gate) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackActiveGate;
    if (device_spooled_ || maintenance_.config().segmented_fallback) {
      if (segmented_pass_ == SegmentedPass::kNone) {
        segmented_pass_ = SegmentedPass::kValidation;
      }
    } else if (mode_ == SpineReaderMode::kHostActive) {
      start_host_fallback(kRangeTaskFallbackActiveGate);
      return;
    } else {
      begin_terminal(true,
                     "device active exact path exceeded the active-record gate");
      return;
    }
  }
  for (const SpineActiveRecord &record : active_records_) {
    if (record.source >= maintenance_.vertices() ||
        record.source >= maintenance_.config().max_vertices) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorActiveBounds;
      begin_terminal(true, "active source is outside the configured graph");
      return;
    }
  }

  const auto visit_record = [&](const SpineActiveRecord &record,
                                std::size_t family, bool hot,
                                std::size_t destination_partition,
                                bool all_families,
                                bool clip_hot_to_partition) {
    if (terminal_pending_) {
      return;
    }
    bool family_enabled = all_families;
    if (!all_families) {
      if (hot) {
        family_enabled = ((record.hot_shard_mask >> family) & 1U) != 0;
      } else {
        for (const std::uint16_t mask : record.level_masks) {
          family_enabled =
              family_enabled || ((mask >> destination_partition) & 1U) != 0;
        }
      }
    }
    if (!family_enabled) {
      ++counters_.range_task_family_skips;
      return;
    }
    ++counters_.range_task_family_probes;
    const std::size_t logical_family = hot ? 16 + family : family;
    for (std::size_t level_index = 0; level_index < kLevelCount;
         ++level_index) {
      ++counters_.range_task_level_checks;
      if (!all_families && !hot &&
          ((record.level_masks[level_index] >> destination_partition) & 1U) ==
              0) {
        continue;
      }
      const LevelCacheEntry &level =
          level_cache_[logical_family * kLevelCount + level_index];
      if (!level.occupied) {
        continue;
      }
      if (!level.valid) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorMetadata;
        begin_terminal(
            true,
            "occupied level metadata failed HLS range-cache validation");
        return;
      }
      if (level.edge_count > std::numeric_limits<std::uint32_t>::max()) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorMetadata;
        begin_terminal(
            true, "occupied level exceeds the range-task edge-count field");
        return;
      }
      const std::uint32_t lane =
          record.source % maintenance_.config().page_vertices;
      range_probes_.push_back(RangeProbe{
          .source = record.source,
          .source_value = record.source_value,
          .family = family,
          .level = level_index,
          .destination_partition = destination_partition,
          .hot = hot,
          .clip_hot_to_partition = hot && clip_hot_to_partition,
          .layout = level.layout,
          .edge_count = static_cast<std::uint32_t>(level.edge_count),
          .slice_epoch = level.slice_epoch,
          .page_epoch = 0,
          .page = record.source / maintenance_.config().page_vertices,
          .lane_word = lane / 64,
          .lane_bit = lane % 64,
          .bitmap_words = {},
          .page_base_word = 0,
          .row_word = 0,
          .next_row_word = 0,
          .rank = 0,
          .row = 0,
          .start = 0,
          .end = 0,
      });
      ++counters_.range_task_row_lookups;
    }
  };

  if (device_source_mode()) {
    for (std::size_t family = 0; family < kPartitionCount; ++family) {
      for (const SpineActiveRecord &record : active_records_) {
        visit_record(record, family, false, family,
                     !family_directory_valid_, false);
      }
    }
    if ((metadata_control_ & 1U) != 0) {
      for (std::size_t shard = 0; shard < kPartitionCount; ++shard) {
        for (const SpineActiveRecord &record : active_records_) {
          const bool scan_every_family = !family_directory_valid_;
          visit_record(record, shard, true, 0, scan_every_family, false);
        }
      }
    }
  } else {
    for (std::size_t partition = 0; partition < kPartitionCount; ++partition) {
      for (const SpineActiveRecord &record :
           host_active_bins_.bins[partition]) {
        visit_record(record, partition, false, partition, false, false);
        if ((metadata_control_ & 1U) != 0) {
          for (std::size_t shard = 0; shard < kPartitionCount; ++shard) {
            visit_record(record, shard, true, partition, false, true);
          }
        }
      }
    }
  }
}

void SpineSplitReader::begin_refactor31_control() {
  const std::uint64_t active = active_records_.size();
  refactor31_control_remaining_ =
      active * maintenance_.config().reader_active_record_control_cycles;
  if (refactor31_control_remaining_ == 0) {
    bin_index_ = 0;
    phase_ = Phase::kBinClear;
  } else {
    phase_ = Phase::kRefactor31Control;
  }
}

void SpineSplitReader::finish_refactor31_validation_pass() {
  if (segmented_pass_ != SegmentedPass::kValidation) {
    throw std::logic_error("segmented validation completed from wrong pass");
  }
  counters_.segmented_validation_payloads +=
      counters_.range_task_construction_payloads -
      refactor31_validation_payload_base_;
  counters_.range_task_construction_payloads = 0;
  counters_.range_task_count = 0;
  range_tasks_.clear();
  range_probes_.clear();
  clear_source_page_cache();
  for (TileTask &tile : tiles_) {
    tile.ranges.clear();
  }
  segmented_pass_ = SegmentedPass::kExecution;
  if (device_spooled_) {
    enqueue_device_source_spool_read();
    phase_ = Phase::kSourceSpoolExecutionRead;
    return;
  }
  prepare_range_probes();
  if (terminal_pending_ || fallback_enabled_) {
    return;
  }
  phase_ = Phase::kSegmentedDeferActive;
}

void SpineSplitReader::start_host_fallback(std::uint32_t reason) {
  if (mode_ != SpineReaderMode::kHostActive || reason == 0 ||
      terminal_pending_) {
    throw std::logic_error("invalid HOST_ACTIVE fallback transition");
  }
  counters_.range_task_path = kRangeTaskPathFallback;
  counters_.range_task_fallback_reason = reason;
  if (edge_pipeline_active()) {
    edge_pipeline_abort_ = true;
    edge_response_buffer_.clear();
  }
  fallback_enabled_ = true;
  fallback_after_source_refresh_ = false;
  fallback_partition_ = 0;
  fallback_discovery_ = true;
  fallback_hot_ = false;
  fallback_shard_ = 0;
  fallback_record_index_ = 0;
  fallback_level_ = 0;
  fallback_tile_local_ = 0;
  fallback_touched_masks_.fill(0);
  fallback_force_dense_.fill(false);
  fallback_lookup_ = {};
  fallback_active_record_valid_ = false;
  range_probes_.clear();
  range_tasks_.clear();
  for (TileTask &tile : tiles_) {
    tile.ranges.clear();
  }
  phase_ = maintenance_.config().fallback_level_cache_reuse &&
                   !level_cache_ready_
               ? Phase::kFallbackLevelCacheBegin
               : Phase::kFallbackPartitionBegin;
}

std::uint32_t SpineSplitReader::fallback_partition_base() const {
  const std::uint64_t base =
      fallback_partition_ * maintenance_.config().vertex_partition_size;
  return static_cast<std::uint32_t>(base);
}

std::uint32_t SpineSplitReader::fallback_partition_end() const {
  return static_cast<std::uint32_t>(std::min<std::uint64_t>(
      maintenance_.vertices(),
      static_cast<std::uint64_t>(fallback_partition_base()) +
          maintenance_.config().vertex_partition_size));
}

std::uint32_t SpineSplitReader::fallback_tile_base() const {
  return fallback_partition_base() +
         static_cast<std::uint32_t>(fallback_tile_local_ * kTileVertices);
}

std::uint32_t SpineSplitReader::fallback_tile_end() const {
  return std::min<std::uint32_t>(fallback_partition_end(),
                                 fallback_tile_base() + kTileVertices);
}

void SpineSplitReader::begin_fallback_pass() {
  clear_source_page_cache();
  fallback_record_index_ = 0;
  fallback_level_ = 0;
  fallback_active_record_valid_ = false;
  phase_ = Phase::kFallbackRecordRead;
}

void SpineSplitReader::advance_fallback_pass() {
  if (!fallback_hot_ && (metadata_control_ & 1U) != 0) {
    fallback_hot_ = true;
    fallback_shard_ = 0;
    phase_ = Phase::kFallbackPassBegin;
    return;
  }
  if (fallback_hot_ && fallback_shard_ + 1 < kPartitionCount) {
    ++fallback_shard_;
    phase_ = Phase::kFallbackPassBegin;
    return;
  }
  if (fallback_discovery_) {
    finish_fallback_discovery();
  } else {
    phase_ = Phase::kFallbackTileEnd;
  }
}

void SpineSplitReader::enqueue_fallback_lookup_header() {
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  const std::size_t logical_family =
      fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                           : fallback_lookup_.family;
  const std::size_t slice =
      logical_family * kLevelCount + fallback_lookup_.level;
  const std::size_t page_epoch_index =
      slice * metadata.page_count + fallback_lookup_.page;
  const auto enqueue_metadata = [&](std::uint64_t word,
                                    MemoryPayloadKind kind) {
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     word * kMetadataWordBytes,
                 kMetadataWordBytes, kind);
    counters_.fallback_metadata_read_bytes += kMetadataWordBytes;
    counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
  };
  enqueue_metadata(slice * kMetadataWordsPerSlice + 7,
                   MemoryPayloadKind::kFallbackOccupied);
  enqueue_metadata(metadata.slice_epoch_base + (slice >> 1),
                   MemoryPayloadKind::kFallbackSliceEpoch);
  enqueue_metadata(metadata.page_epoch_base + (page_epoch_index >> 1),
                   MemoryPayloadKind::kFallbackPageEpoch);
}

void SpineSplitReader::resolve_fallback_lookup_header() {
  if (!fallback_lookup_.occupied) {
    phase_ = Phase::kFallbackLevelAdvance;
    return;
  }
  if (fallback_lookup_.slice_epoch == 0 ||
      fallback_lookup_.page_epoch != fallback_lookup_.slice_epoch) {
    ++counters_.graph_index_epoch_misses;
    if (maintenance_.config().source_page_index_cache) {
      fill_fallback_page_cache(false);
    }
    phase_ = Phase::kFallbackLevelAdvance;
    return;
  }
  if (maintenance_.config().source_page_index_cache) {
    fallback_lookup_.bitmap_words.clear();
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.bitmap_offset_words +
                  static_cast<std::uint64_t>(fallback_lookup_.page) * 4) *
                     kSpineGraphWordBytes,
                 4 * kSpineGraphWordBytes,
                 MemoryPayloadKind::kFallbackBitmapPage);
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.page_base_offset_words +
                  (fallback_lookup_.page >> 1)) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kFallbackPageBase);
    phase_ = Phase::kFallbackLookupIndexResolve;
    return;
  }
  if (maintenance_.config().fallback_level_cache_reuse) {
    phase_ = Phase::kFallbackLookupBitmapOffsetResolve;
    return;
  }
  const std::size_t logical_family =
      fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                           : fallback_lookup_.family;
  const std::size_t slice =
      logical_family * kLevelCount + fallback_lookup_.level;
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   (slice * kMetadataWordsPerSlice + 2) * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kFallbackBitmapOffset);
  counters_.fallback_metadata_read_bytes += kMetadataWordBytes;
  counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
  phase_ = Phase::kFallbackLookupBitmapOffsetResolve;
}

void SpineSplitReader::resolve_fallback_lookup_bitmap_offset() {
  fallback_lookup_.bitmap_words.clear();
  enqueue_read(*ports_.graph[fallback_lookup_.family],
               (fallback_lookup_.layout.bitmap_offset_words +
                static_cast<std::uint64_t>(fallback_lookup_.page) * 4 +
                fallback_lookup_.lane_word) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes,
               MemoryPayloadKind::kFallbackBitmapSelected);
  phase_ = Phase::kFallbackLookupIndexResolve;
}

void SpineSplitReader::resolve_fallback_lookup_index() {
  if (fallback_lookup_.bitmap_words.size() < fallback_lookup_.lane_word + 1) {
    throw std::logic_error("fallback bitmap lookup has wrong payload shape");
  }
  const std::uint64_t selected =
      fallback_lookup_.bitmap_words[fallback_lookup_.lane_word];
  if (maintenance_.config().source_page_index_cache &&
      !source_page_cache_current_hit_) {
    fill_fallback_page_cache(true);
  }
  if ((selected & (std::uint64_t{1} << fallback_lookup_.lane_bit)) == 0) {
    ++counters_.graph_index_bitmap_misses;
    phase_ = Phase::kFallbackLevelAdvance;
    return;
  }
  if (maintenance_.config().source_page_index_cache) {
    resolve_fallback_lookup_rank();
    return;
  }
  if (fallback_lookup_.lane_word != 0) {
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.bitmap_offset_words +
                  static_cast<std::uint64_t>(fallback_lookup_.page) * 4) *
                     kSpineGraphWordBytes,
                 static_cast<std::uint64_t>(fallback_lookup_.lane_word) *
                     kSpineGraphWordBytes,
                 MemoryPayloadKind::kFallbackBitmapPrefix);
    phase_ = Phase::kFallbackLookupRankResolve;
    return;
  }
  resolve_fallback_lookup_rank();
}

void SpineSplitReader::resolve_fallback_lookup_rank() {
  const std::uint64_t selected =
      fallback_lookup_.bitmap_words.at(fallback_lookup_.lane_word);
  std::uint32_t rank = 0;
  for (std::size_t word = 0; word < fallback_lookup_.lane_word; ++word) {
    rank += std::popcount(fallback_lookup_.bitmap_words[word]);
  }
  if (fallback_lookup_.lane_bit != 0) {
    rank += std::popcount(
        selected & ((std::uint64_t{1} << fallback_lookup_.lane_bit) - 1));
  }
  fallback_lookup_.rank = rank;
  if (maintenance_.config().source_page_index_cache) {
    phase_ = Phase::kFallbackLookupPageResolve;
    return;
  }
  if (maintenance_.config().fallback_level_cache_reuse) {
    phase_ = Phase::kFallbackLookupOffsetsResolve;
    return;
  }
  const std::size_t logical_family =
      fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                           : fallback_lookup_.family;
  const std::size_t slice =
      logical_family * kLevelCount + fallback_lookup_.level;
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   (slice * kMetadataWordsPerSlice + 3) * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kFallbackPageBaseOffset);
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   (slice * kMetadataWordsPerSlice + 4) * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kFallbackRowOffset);
  counters_.fallback_metadata_read_bytes += 2 * kMetadataWordBytes;
  counters_.row_lookup_metadata_bytes += 2 * kMetadataWordBytes;
  phase_ = Phase::kFallbackLookupOffsetsResolve;
}

void SpineSplitReader::resolve_fallback_lookup_offsets() {
  enqueue_read(*ports_.graph[fallback_lookup_.family],
               (fallback_lookup_.layout.page_base_offset_words +
                (fallback_lookup_.page >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kFallbackPageBase);
  phase_ = Phase::kFallbackLookupPageResolve;
}

void SpineSplitReader::resolve_fallback_lookup_page() {
  const std::uint32_t page_base =
      (fallback_lookup_.page & 1U) == 0
          ? static_cast<std::uint32_t>(fallback_lookup_.page_base_word)
          : static_cast<std::uint32_t>(fallback_lookup_.page_base_word >> 32);
  const std::uint64_t row =
      static_cast<std::uint64_t>(page_base) + fallback_lookup_.rank;
  if (row > std::numeric_limits<std::uint32_t>::max()) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    begin_terminal(true, "fallback row index overflowed");
    return;
  }
  fallback_lookup_.row = static_cast<std::uint32_t>(row);
  enqueue_read(*ports_.graph[fallback_lookup_.family],
               (fallback_lookup_.layout.row_offset_offset_words +
                (fallback_lookup_.row >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kFallbackRow);
  if ((fallback_lookup_.row & 1U) != 0) {
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.row_offset_offset_words +
                  (fallback_lookup_.row >> 1) + 1) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kFallbackNextRow);
  }
  phase_ = Phase::kFallbackLookupRowResolve;
}

void SpineSplitReader::resolve_fallback_lookup_row() {
  if ((fallback_lookup_.row & 1U) == 0) {
    fallback_lookup_.start =
        static_cast<std::uint32_t>(fallback_lookup_.row_word);
    fallback_lookup_.end =
        static_cast<std::uint32_t>(fallback_lookup_.row_word >> 32);
  } else {
    fallback_lookup_.start =
        static_cast<std::uint32_t>(fallback_lookup_.row_word >> 32);
    fallback_lookup_.end =
        static_cast<std::uint32_t>(fallback_lookup_.next_row_word);
  }
  if (fallback_lookup_.end < fallback_lookup_.start) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    begin_terminal(true, "fallback row offsets are reversed");
    return;
  }
  if (fallback_lookup_.end == fallback_lookup_.start) {
    phase_ = Phase::kFallbackLevelAdvance;
    return;
  }
  if (maintenance_.config().fallback_level_cache_reuse) {
    phase_ = Phase::kFallbackRangeResolve;
    return;
  }
  const std::size_t logical_family =
      fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                           : fallback_lookup_.family;
  const std::size_t slice =
      logical_family * kLevelCount + fallback_lookup_.level;
  enqueue_read(*ports_.metadata,
               maintenance_.config().metadata_base +
                   (slice * kMetadataWordsPerSlice + 6) * kMetadataWordBytes,
               kMetadataWordBytes, MemoryPayloadKind::kFallbackEdgeOffset);
  counters_.fallback_metadata_read_bytes += kMetadataWordBytes;
  counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
  phase_ = Phase::kFallbackRangeResolve;
}

void SpineSplitReader::begin_fallback_lower_bound(std::uint32_t low,
                                                  std::uint32_t high,
                                                  std::uint32_t limit,
                                                  bool second) {
  fallback_lower_low_ = low;
  fallback_lower_high_ = high;
  fallback_lower_limit_ = limit;
  fallback_lower_second_ = second;
  phase_ = Phase::kFallbackLowerBoundRead;
}

void SpineSplitReader::begin_fallback_range() {
  if (fallback_discovery_ && !fallback_lookup_.hot) {
    fallback_clipped_start_ = fallback_lookup_.start;
    fallback_clipped_end_ = fallback_lookup_.end;
    enqueue_read(
        *ports_.graph[fallback_lookup_.family],
        (fallback_lookup_.layout.edge_offset_words + fallback_clipped_start_) *
            kSpineGraphWordBytes,
        kSpineGraphWordBytes, MemoryPayloadKind::kFallbackFirstEdge, 0,
        fallback_lookup_.record.source);
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.edge_offset_words +
                  fallback_clipped_end_ - 1) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kFallbackLastEdge, 0,
                 fallback_lookup_.record.source);
    phase_ = Phase::kFallbackEndpointResolve;
    return;
  }
  begin_fallback_lower_bound(fallback_lookup_.start, fallback_lookup_.end,
                             fallback_discovery_ ? fallback_partition_base()
                                                 : fallback_tile_base(),
                             false);
}

void SpineSplitReader::finish_fallback_range() {
  phase_ = Phase::kFallbackLevelAdvance;
}

void SpineSplitReader::finish_fallback_discovery() {
  const std::uint32_t partition_size =
      fallback_partition_end() - fallback_partition_base();
  const std::size_t valid_tiles =
      (partition_size + kTileVertices - 1) / kTileVertices;
  std::uint16_t mask = fallback_touched_masks_[fallback_partition_];
  if (mask == 0) {
    ++fallback_partition_;
    phase_ = Phase::kFallbackPartitionBegin;
    return;
  }
  const std::uint64_t discovered = std::popcount(mask);
  if (active_bin_counts_[fallback_partition_] * discovered >
      maintenance_.config().fallback_replay_threshold) {
    mask =
        valid_tiles == kFallbackTilesPerPartition
            ? std::numeric_limits<std::uint16_t>::max()
            : static_cast<std::uint16_t>((std::uint32_t{1} << valid_tiles) - 1);
    fallback_touched_masks_[fallback_partition_] = mask;
    fallback_force_dense_[fallback_partition_] = true;
    ++counters_.fallback_forced_dense_partitions;
  }
  fallback_discovery_ = false;
  fallback_tile_local_ = 0;
  while (((mask >> fallback_tile_local_) & 1U) == 0) {
    ++fallback_tile_local_;
  }
  fallback_hot_ = false;
  fallback_shard_ = 0;
  phase_ = Phase::kFallbackTileBegin;
}

void SpineSplitReader::advance_fallback() {
  switch (phase_) {
  case Phase::kFallbackLevelCacheBegin:
    enqueue_level_cache_reads();
    phase_ = Phase::kFallbackLevelCacheDetails;
    return;
  case Phase::kFallbackLevelCacheDetails:
    enqueue_level_detail_reads();
    phase_ = Phase::kFallbackLevelCacheResolve;
    return;
  case Phase::kFallbackLevelCacheResolve:
    finalize_level_cache();
    phase_ = Phase::kFallbackPartitionBegin;
    return;
  case Phase::kFallbackPartitionBegin:
    if (fallback_partition_ == kPartitionCount ||
        fallback_partition_base() >= maintenance_.vertices()) {
      begin_terminal(false);
      return;
    }
    if (active_bin_counts_[fallback_partition_] == 0) {
      ++fallback_partition_;
      return;
    }
    ++counters_.fallback_partitions;
    fallback_discovery_ = true;
    fallback_hot_ = false;
    fallback_shard_ = 0;
    fallback_touched_masks_[fallback_partition_] = 0;
    phase_ = Phase::kFallbackPassBegin;
    return;
  case Phase::kFallbackPassBegin:
    begin_fallback_pass();
    return;
  case Phase::kFallbackRecordRead:
    if (fallback_record_index_ >= active_bin_counts_[fallback_partition_]) {
      phase_ = Phase::kFallbackPassAdvance;
      return;
    }
    fallback_active_record_valid_ = false;
    enqueue_read(
        *ports_.active_bins,
        (active_bin_offsets_[fallback_partition_] + fallback_record_index_) *
            kActiveRecordBytes,
        kActiveRecordBytes, MemoryPayloadKind::kFallbackActiveRecord);
    ++counters_.fallback_active_record_reads;
    counters_.fallback_active_record_read_bytes += kActiveRecordBytes;
    phase_ = Phase::kFallbackRecordResolve;
    return;
  case Phase::kFallbackRecordResolve:
    if (!fallback_active_record_valid_ ||
        fallback_lookup_.record.source >= maintenance_.vertices() ||
        fallback_lookup_.record.source >= maintenance_.config().max_vertices) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorActiveBounds;
      begin_terminal(true, "fallback active record exceeds graph bounds");
      return;
    }
    if (algorithm_policy_->config().kind == GraphAlgorithmKind::kFullPageRank ||
        algorithm_policy_->config().kind ==
            GraphAlgorithmKind::kResidualPageRank ||
        algorithm_policy_->config().kind ==
            GraphAlgorithmKind::kConnectedComponents) {
      const auto source_value =
          source_values_.find(fallback_lookup_.record.source);
      if (source_value == source_values_.end()) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorProtocol;
        begin_terminal(true,
                       "PageRank fallback record has no refreshed source value");
        return;
      }
      fallback_lookup_.record.source_value = source_value->second;
    }
    if (fallback_hot_ &&
        ((fallback_lookup_.record.hot_shard_mask >> fallback_shard_) & 1U) ==
            0) {
      phase_ = Phase::kFallbackRecordAdvance;
      return;
    }
    fallback_level_ = 0;
    phase_ = Phase::kFallbackLevelBegin;
    return;
  case Phase::kFallbackLevelBegin: {
    if (fallback_level_ == kLevelCount) {
      phase_ = Phase::kFallbackRecordAdvance;
      return;
    }
    if (!fallback_hot_ &&
        ((fallback_lookup_.record.level_masks[fallback_level_] >>
          fallback_partition_) &
         1U) == 0) {
      phase_ = Phase::kFallbackLevelAdvance;
      return;
    }
    const SpineActiveRecord record = fallback_lookup_.record;
    fallback_lookup_ = {};
    fallback_lookup_.record = record;
    fallback_lookup_.partition = fallback_partition_;
    fallback_lookup_.family =
        fallback_hot_ ? fallback_shard_ : fallback_partition_;
    fallback_lookup_.level = fallback_level_;
    fallback_lookup_.hot = fallback_hot_;
    fallback_lookup_.page = record.source / maintenance_.config().page_vertices;
    fallback_lookup_.lane_word =
        (record.source % maintenance_.config().page_vertices) / 64;
    fallback_lookup_.lane_bit =
        (record.source % maintenance_.config().page_vertices) % 64;
    source_page_cache_current_hit_ = false;
    ++counters_.fallback_row_lookups;
    if (maintenance_.config().fallback_level_cache_reuse) {
      const std::size_t logical_family =
          fallback_lookup_.hot ? kPartitionCount + fallback_lookup_.family
                               : fallback_lookup_.family;
      const std::size_t slice =
          logical_family * kLevelCount + fallback_lookup_.level;
      const LevelCacheEntry &entry = level_cache_.at(slice);
      ++counters_.fallback_level_cache_reuses;
      if (!entry.occupied) {
        ++counters_.fallback_level_cache_empty_skips;
        phase_ = Phase::kFallbackLevelAdvance;
        return;
      }
      if (!entry.valid) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorMetadata;
        begin_terminal(true, "cached fallback level metadata is invalid");
        return;
      }
      fallback_lookup_.occupied = true;
      fallback_lookup_.slice_epoch = entry.slice_epoch;
      fallback_lookup_.layout = entry.layout;
      if (maintenance_.config().source_page_index_cache) {
        if (use_cached_fallback_page()) {
          if (fallback_lookup_.page_epoch != fallback_lookup_.slice_epoch) {
            ++counters_.graph_index_epoch_misses;
            phase_ = Phase::kFallbackLevelAdvance;
          } else {
            phase_ = Phase::kFallbackLookupIndexResolve;
          }
          return;
        }
        ++counters_.source_page_cache_misses;
      }
      const SpineMetadataLayout metadata =
          spine_metadata_layout(maintenance_.config());
      const std::size_t page_epoch_index =
          slice * metadata.page_count + fallback_lookup_.page;
      enqueue_read(
          *ports_.metadata,
          maintenance_.config().metadata_base +
              (metadata.page_epoch_base + (page_epoch_index >> 1)) *
                  kMetadataWordBytes,
          kMetadataWordBytes, MemoryPayloadKind::kFallbackPageEpoch);
      counters_.fallback_metadata_read_bytes += kMetadataWordBytes;
      counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
      phase_ = Phase::kFallbackLookupHeaderResolve;
      return;
    }
    enqueue_fallback_lookup_header();
    phase_ = Phase::kFallbackLookupHeaderResolve;
    return;
  }
  case Phase::kFallbackLookupHeaderResolve:
    resolve_fallback_lookup_header();
    return;
  case Phase::kFallbackLookupBitmapOffsetResolve:
    resolve_fallback_lookup_bitmap_offset();
    return;
  case Phase::kFallbackLookupIndexResolve:
    resolve_fallback_lookup_index();
    return;
  case Phase::kFallbackLookupRankResolve:
    resolve_fallback_lookup_rank();
    return;
  case Phase::kFallbackLookupOffsetsResolve:
    resolve_fallback_lookup_offsets();
    return;
  case Phase::kFallbackLookupPageResolve:
    resolve_fallback_lookup_page();
    return;
  case Phase::kFallbackLookupRowResolve:
    resolve_fallback_lookup_row();
    return;
  case Phase::kFallbackRangeResolve:
    begin_fallback_range();
    return;
  case Phase::kFallbackLowerBoundRead:
    if (fallback_lower_low_ >= fallback_lower_high_) {
      if (!fallback_lower_second_) {
        fallback_clipped_start_ = fallback_lower_low_;
        begin_fallback_lower_bound(
            fallback_clipped_start_, fallback_lookup_.end,
            fallback_discovery_ ? fallback_partition_end()
                                : fallback_tile_end(),
            true);
      } else {
        fallback_clipped_end_ = fallback_lower_low_;
        if (fallback_clipped_end_ <= fallback_clipped_start_) {
          finish_fallback_range();
        } else if (fallback_discovery_) {
          enqueue_read(*ports_.graph[fallback_lookup_.family],
                       (fallback_lookup_.layout.edge_offset_words +
                        fallback_clipped_start_) *
                           kSpineGraphWordBytes,
                       kSpineGraphWordBytes,
                       MemoryPayloadKind::kFallbackFirstEdge, 0,
                       fallback_lookup_.record.source);
          enqueue_read(*ports_.graph[fallback_lookup_.family],
                       (fallback_lookup_.layout.edge_offset_words +
                        fallback_clipped_end_ - 1) *
                           kSpineGraphWordBytes,
                       kSpineGraphWordBytes,
                       MemoryPayloadKind::kFallbackLastEdge, 0,
                       fallback_lookup_.record.source);
          phase_ = Phase::kFallbackEndpointResolve;
        } else {
          fallback_replay_position_ = fallback_clipped_start_;
          phase_ = Phase::kFallbackEdgeRead;
        }
      }
      return;
    }
    enqueue_read(*ports_.graph[fallback_lookup_.family],
                 (fallback_lookup_.layout.edge_offset_words +
                  fallback_lower_low_ +
                  ((fallback_lower_high_ - fallback_lower_low_) >> 1)) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kFallbackBinaryEdge,
                 0, fallback_lookup_.record.source);
    phase_ = Phase::kFallbackLowerBoundResolve;
    return;
  case Phase::kFallbackLowerBoundResolve: {
    const std::uint32_t mid =
        fallback_lower_low_ +
        ((fallback_lower_high_ - fallback_lower_low_) >> 1);
    if (fallback_binary_edge_.dst < fallback_lower_limit_) {
      fallback_lower_low_ = mid + 1;
    } else {
      fallback_lower_high_ = mid;
    }
    phase_ = Phase::kFallbackLowerBoundRead;
    return;
  }
  case Phase::kFallbackEndpointResolve: {
    const std::uint32_t partition_base = fallback_partition_base();
    const std::uint32_t partition_end = fallback_partition_end();
    if (fallback_first_edge_.dst > fallback_last_edge_.dst ||
        fallback_first_edge_.dst < partition_base ||
        fallback_last_edge_.dst >= partition_end) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorDestination;
      begin_terminal(true, "fallback discovery endpoints exceed the partition");
      return;
    }
    const std::size_t first_tile =
        (fallback_first_edge_.dst - partition_base) / kTileVertices;
    const std::size_t last_tile =
        (fallback_last_edge_.dst - partition_base) / kTileVertices;
    if (last_tile >= kFallbackTilesPerPartition) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorDestination;
      begin_terminal(true, "fallback discovery tile index overflowed");
      return;
    }
    for (std::size_t tile = first_tile; tile <= last_tile; ++tile) {
      fallback_touched_masks_[fallback_partition_] |=
          static_cast<std::uint16_t>(1U << tile);
    }
    finish_fallback_range();
    return;
  }
  case Phase::kFallbackLevelAdvance:
    ++fallback_level_;
    phase_ = Phase::kFallbackLevelBegin;
    return;
  case Phase::kFallbackRecordAdvance:
    ++fallback_record_index_;
    phase_ = Phase::kFallbackRecordRead;
    return;
  case Phase::kFallbackPassAdvance:
    advance_fallback_pass();
    return;
  case Phase::kFallbackTileScan:
    while (fallback_tile_local_ < kFallbackTilesPerPartition &&
           ((fallback_touched_masks_[fallback_partition_] >>
             fallback_tile_local_) &
            1U) == 0) {
      ++fallback_tile_local_;
    }
    if (fallback_tile_local_ == kFallbackTilesPerPartition ||
        fallback_tile_base() >= fallback_partition_end()) {
      ++fallback_partition_;
      phase_ = Phase::kFallbackPartitionBegin;
    } else {
      fallback_hot_ = false;
      fallback_shard_ = 0;
      phase_ = Phase::kFallbackTileBegin;
    }
    return;
  case Phase::kFallbackEdgeRead:
    if (fallback_replay_position_ >= fallback_clipped_end_) {
      finish_fallback_range();
      return;
    }
    begin_edge_pipeline(
        EdgePipelineMode::kFallbackReplay,
        *ports_.graph[fallback_lookup_.family],
        (fallback_lookup_.layout.edge_offset_words +
         fallback_replay_position_) *
            kSpineGraphWordBytes,
        fallback_clipped_end_ - fallback_replay_position_,
        fallback_lookup_.record.source, fallback_lookup_.record.source_value,
        fallback_tile_base(), fallback_tile_end(), fallback_lookup_.hot);
    phase_ = Phase::kFallbackEdgeEmit;
    return;
  case Phase::kFallbackTileBegin:
  case Phase::kFallbackEdgeEmit:
  case Phase::kFallbackTileEnd:
    return;
  default:
    throw std::logic_error("non-fallback phase reached fallback engine");
  }
}

std::size_t SpineSplitReader::source_page_cache_index(
    std::size_t family, std::size_t level, bool hot) const {
  const std::size_t logical_family = hot ? kPartitionCount + family : family;
  return logical_family * kLevelCount + level;
}

void SpineSplitReader::clear_source_page_cache() {
  source_page_cache_ = {};
}

bool SpineSplitReader::use_cached_probe_page(RangeProbe &probe) {
  SourcePageCacheEntry &entry = source_page_cache_.at(
      source_page_cache_index(probe.family, probe.level, probe.hot));
  if (!entry.valid || entry.page != probe.page ||
      entry.slice_epoch != probe.slice_epoch) {
    return false;
  }
  probe.page_epoch = entry.page_epoch;
  probe.bitmap_words.assign(entry.bitmap_words.begin(),
                            entry.bitmap_words.end());
  probe.page_base_word = entry.page_base_word;
  source_page_cache_current_hit_ = true;
  ++counters_.source_page_cache_hits;
  if (!entry.epoch_matches) {
    ++counters_.source_page_cache_negative_hits;
  }
  return true;
}

bool SpineSplitReader::use_cached_fallback_page() {
  SourcePageCacheEntry &entry = source_page_cache_.at(source_page_cache_index(
      fallback_lookup_.family, fallback_lookup_.level,
      fallback_lookup_.hot));
  if (!entry.valid || entry.page != fallback_lookup_.page ||
      entry.slice_epoch != fallback_lookup_.slice_epoch) {
    return false;
  }
  fallback_lookup_.page_epoch = entry.page_epoch;
  fallback_lookup_.bitmap_words.assign(entry.bitmap_words.begin(),
                                       entry.bitmap_words.end());
  fallback_lookup_.page_base_word = entry.page_base_word;
  source_page_cache_current_hit_ = true;
  ++counters_.source_page_cache_hits;
  if (!entry.epoch_matches) {
    ++counters_.source_page_cache_negative_hits;
  }
  return true;
}

void SpineSplitReader::fill_probe_page_cache(const RangeProbe &probe,
                                              bool epoch_matches) {
  SourcePageCacheEntry &entry = source_page_cache_.at(
      source_page_cache_index(probe.family, probe.level, probe.hot));
  entry.valid = true;
  entry.epoch_matches = epoch_matches;
  entry.page = probe.page;
  entry.slice_epoch = probe.slice_epoch;
  entry.page_epoch = probe.page_epoch;
  if (epoch_matches) {
    if (probe.bitmap_words.size() != entry.bitmap_words.size()) {
      throw std::logic_error("probe page-cache fill has incomplete bitmap");
    }
    std::copy(probe.bitmap_words.begin(), probe.bitmap_words.end(),
              entry.bitmap_words.begin());
    entry.page_base_word = probe.page_base_word;
  } else {
    entry.bitmap_words.fill(0);
    entry.page_base_word = 0;
  }
  ++counters_.source_page_cache_fills;
}

void SpineSplitReader::fill_fallback_page_cache(bool epoch_matches) {
  SourcePageCacheEntry &entry = source_page_cache_.at(source_page_cache_index(
      fallback_lookup_.family, fallback_lookup_.level,
      fallback_lookup_.hot));
  entry.valid = true;
  entry.epoch_matches = epoch_matches;
  entry.page = fallback_lookup_.page;
  entry.slice_epoch = fallback_lookup_.slice_epoch;
  entry.page_epoch = fallback_lookup_.page_epoch;
  if (epoch_matches) {
    if (fallback_lookup_.bitmap_words.size() != entry.bitmap_words.size()) {
      throw std::logic_error("fallback page-cache fill has incomplete bitmap");
    }
    std::copy(fallback_lookup_.bitmap_words.begin(),
              fallback_lookup_.bitmap_words.end(),
              entry.bitmap_words.begin());
    entry.page_base_word = fallback_lookup_.page_base_word;
  } else {
    entry.bitmap_words.fill(0);
    entry.page_base_word = 0;
  }
  ++counters_.source_page_cache_fills;
}

void SpineSplitReader::enqueue_probe_index_reads() {
  if (probe_index_ >= range_probes_.size()) {
    throw std::logic_error("range probe index is out of bounds");
  }
  RangeProbe &probe = range_probes_[probe_index_];
  probe.bitmap_words.clear();
  probe.page_base_word = 0;
  probe.row_word = 0;
  probe.next_row_word = 0;
  probe.rank = 0;
  probe.page_epoch = 0;
  source_page_cache_current_hit_ = false;
  if (maintenance_.config().source_page_index_cache) {
    if (use_cached_probe_page(probe)) {
      if (probe.page_epoch != probe.slice_epoch) {
        ++counters_.graph_index_epoch_misses;
        phase_ = Phase::kProbeAdvance;
      } else {
        phase_ = Phase::kProbeIndexResolve;
      }
      return;
    }
    ++counters_.source_page_cache_misses;
  }
  const std::uint64_t logical_family =
      probe.hot ? 16 + probe.family : probe.family;
  const std::uint64_t slice = logical_family * kLevelCount + probe.level;
  const std::uint64_t page_epoch_index =
      slice * spine_metadata_layout(maintenance_.config()).page_count +
      probe.page;
  enqueue_read(
      *ports_.metadata,
      maintenance_.config().metadata_base +
          (spine_metadata_layout(maintenance_.config()).page_epoch_base +
           (page_epoch_index >> 1)) *
              kMetadataWordBytes,
      kMetadataWordBytes, MemoryPayloadKind::kPageEpoch, probe_index_);
  counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
  phase_ = Phase::kProbeEpochResolve;
}

void SpineSplitReader::resolve_probe_epoch() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if (probe.slice_epoch == 0 || probe.page_epoch != probe.slice_epoch) {
    ++counters_.graph_index_epoch_misses;
    if (maintenance_.config().source_page_index_cache) {
      fill_probe_page_cache(probe, false);
    }
    phase_ = Phase::kProbeAdvance;
    return;
  }
  if (maintenance_.config().source_page_index_cache) {
    enqueue_read(*ports_.graph[probe.family],
                 (probe.layout.bitmap_offset_words +
                  static_cast<std::uint64_t>(probe.page) * 4) *
                     kSpineGraphWordBytes,
                 4 * kSpineGraphWordBytes,
                 MemoryPayloadKind::kIndexBitmapPage, probe_index_);
    enqueue_read(*ports_.graph[probe.family],
                 (probe.layout.page_base_offset_words + (probe.page >> 1)) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kIndexPageBase,
                 probe_index_);
    phase_ = Phase::kProbeIndexResolve;
    return;
  }
  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.bitmap_offset_words +
                static_cast<std::uint64_t>(probe.page) * 4 + probe.lane_word) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexBitmapSelected,
               probe_index_);
  phase_ = Phase::kProbeIndexResolve;
}

void SpineSplitReader::resolve_probe_index() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if (probe.bitmap_words.size() < probe.lane_word + 1) {
    throw std::logic_error("range probe bitmap prefix has the wrong length");
  }
  const std::uint64_t selected = probe.bitmap_words[probe.lane_word];
  if (maintenance_.config().source_page_index_cache &&
      !source_page_cache_current_hit_) {
    fill_probe_page_cache(probe, true);
  }
  if ((selected & (std::uint64_t{1} << probe.lane_bit)) == 0) {
    ++counters_.graph_index_bitmap_misses;
    phase_ = Phase::kProbeAdvance;
    return;
  }
  if (maintenance_.config().source_page_index_cache) {
    resolve_probe_rank();
    return;
  }
  if (probe.lane_word != 0) {
    enqueue_read(
        *ports_.graph[probe.family],
        (probe.layout.bitmap_offset_words +
         static_cast<std::uint64_t>(probe.page) * 4) *
            kSpineGraphWordBytes,
        static_cast<std::uint64_t>(probe.lane_word) * kSpineGraphWordBytes,
        MemoryPayloadKind::kIndexBitmapPrefix, probe_index_);
    phase_ = Phase::kProbeRankResolve;
    return;
  }
  resolve_probe_rank();
}

void SpineSplitReader::resolve_probe_rank() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint64_t selected = probe.bitmap_words.at(probe.lane_word);
  std::uint32_t rank = 0;
  for (std::size_t word = 0; word < probe.lane_word; ++word) {
    rank += std::popcount(probe.bitmap_words[word]);
  }
  if (probe.lane_bit != 0) {
    rank +=
        std::popcount(selected & ((std::uint64_t{1} << probe.lane_bit) - 1));
  }
  probe.rank = rank;
  if (maintenance_.config().source_page_index_cache) {
    phase_ = Phase::kProbePageResolve;
    return;
  }
  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.page_base_offset_words + (probe.page >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexPageBase,
               probe_index_);
  phase_ = Phase::kProbePageResolve;
}

void SpineSplitReader::resolve_probe_page() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint32_t page_base =
      (probe.page & 1U) == 0
          ? static_cast<std::uint32_t>(probe.page_base_word)
          : static_cast<std::uint32_t>(probe.page_base_word >> 32);
  const std::uint64_t row = static_cast<std::uint64_t>(page_base) + probe.rank;
  if (row > std::numeric_limits<std::uint32_t>::max()) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    begin_terminal(true, "range probe row index overflowed");
    return;
  }
  probe.row = static_cast<std::uint32_t>(row);
  enqueue_probe_row_reads();
  phase_ = Phase::kProbeRowResolve;
}

void SpineSplitReader::enqueue_probe_row_reads() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.row_offset_offset_words + (probe.row >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexRow,
               probe_index_);
  if ((probe.row & 1U) != 0) {
    enqueue_read(*ports_.graph[probe.family],
                 (probe.layout.row_offset_offset_words + (probe.row >> 1) + 1) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kIndexNextRow,
                 probe_index_);
  }
}

void SpineSplitReader::resolve_probe_row() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if ((probe.row & 1U) == 0) {
    probe.start = static_cast<std::uint32_t>(probe.row_word);
    probe.end = static_cast<std::uint32_t>(probe.row_word >> 32);
  } else {
    probe.start = static_cast<std::uint32_t>(probe.row_word >> 32);
    probe.end = static_cast<std::uint32_t>(probe.next_row_word);
  }
  if (probe.end < probe.start || probe.end > probe.edge_count) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    begin_terminal(true,
                   "HBM row offsets do not fit the cached level edge count");
    return;
  }
  if (probe.end == probe.start) {
    phase_ = Phase::kProbeAdvance;
    return;
  }
  if (probe.clip_hot_to_partition) {
    const std::uint64_t partition_base =
        static_cast<std::uint64_t>(probe.destination_partition) *
        maintenance_.config().vertex_partition_size;
    const std::uint64_t partition_end = std::min<std::uint64_t>(
        maintenance_.vertices(),
        partition_base + maintenance_.config().vertex_partition_size);
    if (partition_base >= partition_end ||
        partition_end > std::numeric_limits<std::uint32_t>::max()) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorDestination;
      begin_terminal(true, "hot range probe has an invalid destination partition");
      return;
    }
    begin_probe_lower_bound(
        probe.start, probe.end, static_cast<std::uint32_t>(partition_base),
        false);
    return;
  }
  begin_probe_construction();
}

void SpineSplitReader::begin_probe_lower_bound(std::uint32_t low,
                                                std::uint32_t high,
                                                std::uint32_t limit,
                                                bool second) {
  probe_lower_low_ = low;
  probe_lower_high_ = high;
  probe_lower_limit_ = limit;
  probe_lower_second_ = second;
  phase_ = Phase::kProbeLowerBoundRead;
}

void SpineSplitReader::advance_probe_lower_bound() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if (phase_ == Phase::kProbeLowerBoundRead) {
    if (probe_lower_low_ >= probe_lower_high_) {
      if (!probe_lower_second_) {
        probe_clipped_start_ = probe_lower_low_;
        const std::uint64_t partition_end = std::min<std::uint64_t>(
            maintenance_.vertices(),
            (static_cast<std::uint64_t>(probe.destination_partition) + 1) *
                maintenance_.config().vertex_partition_size);
        begin_probe_lower_bound(
            probe_clipped_start_, probe.end,
            static_cast<std::uint32_t>(partition_end), true);
      } else {
        probe.start = probe_clipped_start_;
        probe.end = probe_lower_low_;
        begin_probe_construction();
      }
      return;
    }
    const std::uint32_t mid =
        probe_lower_low_ + ((probe_lower_high_ - probe_lower_low_) >> 1);
    enqueue_read(*ports_.graph[probe.family],
                 (probe.layout.edge_offset_words + mid) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kProbeBinaryEdge,
                 probe_index_, probe.source);
    phase_ = Phase::kProbeLowerBoundResolve;
    return;
  }
  const std::uint32_t mid =
      probe_lower_low_ + ((probe_lower_high_ - probe_lower_low_) >> 1);
  if (probe_binary_edge_.dst < probe_lower_limit_) {
    probe_lower_low_ = mid + 1;
  } else {
    probe_lower_high_ = mid;
  }
  phase_ = Phase::kProbeLowerBoundRead;
}

void SpineSplitReader::begin_probe_construction() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if (probe.end == probe.start) {
    phase_ = Phase::kProbeAdvance;
    return;
  }
  const std::uint64_t row_length = probe.end - probe.start;
  const std::uint64_t payload_budget =
      maintenance_.config().range_task_payload_budget;
  if (counters_.range_task_construction_payloads >= payload_budget ||row_length >
          payload_budget - counters_.range_task_construction_payloads) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackPayloadBudget;
    if (mode_ == SpineReaderMode::kHostActive) {
      start_host_fallback(kRangeTaskFallbackPayloadBudget);
    } else {
    begin_terminal(
        true, "device-dirty exact path exceeded its construction budget");
    }
    return;
  }
  construction_position_ = probe.start;
  construction_run_valid_ = false;
  construction_run_length_ = 0;
  construction_have_previous_dst_ = false;
  begin_edge_pipeline(
      EdgePipelineMode::kConstruction, *ports_.graph[probe.family],
      (probe.layout.edge_offset_words + probe.start) * kSpineGraphWordBytes,
      probe.end - probe.start, probe.source, probe.source_value, 0, 0,
      probe.hot);
  phase_ = Phase::kConstructionConsume;
}

void SpineSplitReader::flush_construction_run() {
  if (!construction_run_valid_ || construction_run_length_ == 0) {
    return;
  }
  if (construction_run_tile_ >= kRangeTaskMaxTiles ||
      construction_run_start_ >= kRangeTaskMaxStart ||
      construction_run_length_ >= kRangeTaskMaxLength) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorDescriptor;
    begin_terminal(
        true, "constructed range does not fit the 128-bit descriptor");
    return;
  }
  if (range_tasks_.size() >= maintenance_.config().range_task_capacity) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackCapacity;
    if (mode_ == SpineReaderMode::kHostActive) {
      start_host_fallback(kRangeTaskFallbackCapacity);
    } else {
    begin_terminal(true,
                   "device-dirty exact path exhausted range descriptors");
    }
    return;
  }
  const RangeProbe &probe = range_probes_.at(probe_index_);
  range_tasks_.push_back(RangeTask{
      .absolute_word = construction_run_start_,
      .length = construction_run_length_,
      .source = probe.source,
      .source_value = probe.source_value,
      .tile = construction_run_tile_,
      .graph_bank = static_cast<std::uint8_t>(probe.family),
      .hot = probe.hot,
  });
  ++tile_counts_[construction_run_tile_];
  ++counters_.range_task_count;
  construction_run_valid_ = false;
  construction_run_length_ = 0;
}

void SpineSplitReader::consume_construction_edge() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint64_t destination = construction_edge_.dst;
  const std::uint64_t partition_base =
      static_cast<std::uint64_t>(probe.hot && probe.clip_hot_to_partition
                                     ? probe.destination_partition
                                     : probe.family) *
      maintenance_.config().vertex_partition_size;
  const std::uint64_t partition_end = std::min<std::uint64_t>(
      maintenance_.vertices(),
      partition_base + maintenance_.config().vertex_partition_size);
  const bool partition_scoped = !probe.hot || probe.clip_hot_to_partition;
  const bool invalid_partition =
      partition_scoped &&
      (destination < partition_base || destination >= partition_end);
  if (destination >= maintenance_.vertices() || invalid_partition ||
      (construction_have_previous_dst_ &&
       construction_edge_.dst < construction_previous_dst_)) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorDestination;
    begin_terminal(
        true, "construction scan found an invalid or unsorted destination");
    return;
  }
  construction_previous_dst_ = construction_edge_.dst;
  construction_have_previous_dst_ = true;
  const auto tile = static_cast<std::uint16_t>(destination / kTileVertices);
  const std::uint64_t absolute =
      probe.layout.edge_offset_words + construction_position_;
  if (!construction_run_valid_) {
    construction_run_valid_ = true;
    construction_run_tile_ = tile;
    construction_run_start_ = absolute;
    construction_run_length_ = 1;
  } else if (tile == construction_run_tile_) {
    ++construction_run_length_;
  } else {
    flush_construction_run();
    if (terminal_pending_ || fallback_enabled_) {
      return;
    }
    construction_run_valid_ = true;
    construction_run_tile_ = tile;
    construction_run_start_ = absolute;
    construction_run_length_ = 1;
  }

  ++construction_position_;
  if (construction_position_ == probe.end) {
    flush_construction_run();
  }
}

void SpineSplitReader::retire_construction_edge() {
  const auto found = edge_response_buffer_.find(edge_pipeline_retire_index_);
  if (edge_pipeline_mode_ != EdgePipelineMode::kConstruction ||
      found == edge_response_buffer_.end()) {
    throw std::logic_error("construction pipeline retired a missing edge");
  }
  if (probe_index_ >= range_probes_.size()) {
    throw std::logic_error("construction pipeline lost its range probe");
  }
  const RangeProbe &probe = range_probes_[probe_index_];
  construction_position_ = probe.start + edge_pipeline_retire_index_;
  construction_edge_ = found->second.edge;
  edge_response_buffer_.erase(found);
  ++edge_pipeline_retire_index_;
  ++counters_.construction_pipeline_retires;
  consume_construction_edge();

  if (terminal_pending_ || fallback_enabled_) {
    edge_pipeline_abort_ = true;
    edge_response_buffer_.clear();
    return;
  }
  if (edge_pipeline_retire_index_ == edge_pipeline_length_) {
    finish_edge_pipeline();
    phase_ = Phase::kProbeAdvance;
  } else {
    phase_ = Phase::kConstructionConsume;
  }
}

void SpineSplitReader::retire_replay_edge() {
  const auto found = edge_response_buffer_.find(edge_pipeline_retire_index_);
  if ((edge_pipeline_mode_ != EdgePipelineMode::kExactReplay &&
       edge_pipeline_mode_ != EdgePipelineMode::kFallbackReplay) ||
      found == edge_response_buffer_.end()) {
    throw std::logic_error("replay pipeline retired a missing edge");
  }
  const EdgePipelineMode completed_mode = edge_pipeline_mode_;
  loaded_edge_ = found->second.edge;
  const bool hot = found->second.hot;
  edge_response_buffer_.erase(found);
  ++edge_pipeline_retire_index_;
  ++counters_.replay_pipeline_retires;
  ++counters_.edges_emitted;
  if (hot) {
    ++counters_.hot_edges_emitted;
  } else {
    ++counters_.cold_edges_emitted;
  }

  if (completed_mode == EdgePipelineMode::kExactReplay) {
    ++range_edge_index_;
  } else {
    ++fallback_replay_position_;
  }
  if (edge_pipeline_retire_index_ != edge_pipeline_length_) {
    return;
  }

  finish_edge_pipeline();
  if (completed_mode == EdgePipelineMode::kExactReplay) {
    phase_ = Phase::kEdgeRead;
  } else {
    finish_fallback_range();
  }
}

void SpineSplitReader::enqueue_level_cache_reads() {
  level_cache_ = {};
  for (std::size_t slice = 0; slice < level_cache_.size(); ++slice) {
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     (slice * kMetadataWordsPerSlice + 7) * kMetadataWordBytes,
                 kMetadataWordBytes, MemoryPayloadKind::kLevelOccupied, slice);
    counters_.level_cache_read_bytes += kMetadataWordBytes;
  }
}

void SpineSplitReader::enqueue_level_detail_reads() {
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  for (std::size_t slice = 0; slice < level_cache_.size(); ++slice) {
    if (!level_cache_[slice].occupied) {
      continue;
    }
    ++counters_.occupied_levels;
    enqueue_read(*ports_.metadata,
                 maintenance_.config().metadata_base +
                     slice * kMetadataWordsPerSlice * kMetadataWordBytes,
                 7 * kMetadataWordBytes, MemoryPayloadKind::kLevelFields,
                 slice);
    enqueue_read(
        *ports_.metadata,
        maintenance_.config().metadata_base +
            (metadata.slice_epoch_base + (slice >> 1)) * kMetadataWordBytes,
        kMetadataWordBytes, MemoryPayloadKind::kSliceEpoch, slice);
    counters_.level_cache_read_bytes += 8 * kMetadataWordBytes;
  }
}

void SpineSplitReader::finalize_level_cache() {
  constexpr std::uint64_t kGraphBankWords = 512ULL * 1024ULL * 1024ULL / 8;
  const SpineMetadataLayout metadata =
      spine_metadata_layout(maintenance_.config());
  const auto span_valid = [](std::uint64_t offset, std::uint64_t words) {
    return offset <= kGraphBankWords && words <= kGraphBankWords - offset;
  };
  for (std::size_t slice = 0; slice < level_cache_.size(); ++slice) {
    LevelCacheEntry &entry = level_cache_[slice];
    if (!entry.occupied) {
      entry.valid = true;
      continue;
    }
    const std::size_t level = slice % kLevelCount;
    const bool hot = slice / kLevelCount >= kPartitionCount;
    const SpineLevelLayout expected =
        spine_level_layout(maintenance_.config(), hot, level);
    entry.layout.edge_capacity = expected.edge_capacity;
    entry.layout.row_capacity_words = expected.row_capacity_words;
    entry.layout.mask_capacity_words = expected.mask_capacity_words;
    const std::uint64_t bitmap_words = metadata.page_count * 4;
    const std::uint64_t page_base_words = (metadata.page_count + 2) / 2;
    const std::uint64_t row_words = (entry.row_count + 2) >> 1;
    const std::uint64_t mask_words = (entry.row_count + 3) >> 2;
    entry.valid =
        entry.edge_count != 0 && entry.row_count != 0 &&
        entry.edge_count <= expected.edge_capacity &&
        entry.row_count <= expected.edge_capacity &&
        entry.row_count <= maintenance_.config().max_vertices &&
        span_valid(entry.layout.bitmap_offset_words, bitmap_words) &&
        span_valid(entry.layout.page_base_offset_words, page_base_words) &&
        span_valid(entry.layout.row_offset_offset_words, row_words) &&
        span_valid(entry.layout.mask_offset_words, mask_words) &&
        span_valid(entry.layout.edge_offset_words, entry.edge_count);
  }
  level_cache_ready_ = true;
}

void SpineSplitReader::begin_terminal(bool overflow, std::string failure) {
  if (terminal_pending_) {
    terminal_overflow_ = terminal_overflow_ || overflow;
    if (!failure.empty() && failure_.empty()) {
      failure_ = std::move(failure);
      terminal_failed_ = true;
    }
    return;
  }
  terminal_pending_ = true;
  if (edge_pipeline_active()) {
    edge_pipeline_abort_ = true;
    edge_response_buffer_.clear();
  }
  terminal_overflow_ = overflow;
  terminal_failed_ = overflow || !failure.empty();
  failure_ = std::move(failure);
  diagnostic_index_ = 0;
  source_completion_index_ = 0;
  counters_.dirty_count = static_cast<std::uint32_t>(dirty_count_);
  counters_.dirty_generation = dirty_generation_;
  counters_.dirty_hash_sum = dirty_hash_sum_;
  counters_.dirty_hash_xor = dirty_hash_xor_;
  counters_.host_coverage_match =
      mode_ == SpineReaderMode::kHostActive && dirty_host_valid_ &&
      dirty_host_generation_ == dirty_generation_ &&
      dirty_host_count_ == dirty_count_ &&
      dirty_host_hash_sum_ == dirty_hash_sum_ &&
      dirty_host_hash_xor_ == dirty_hash_xor_;
  counters_.acknowledgement_eligible =
      !terminal_overflow_ && counters_.range_task_error == 0 &&
      ((mode_ == SpineReaderMode::kDeviceDirty &&
        (counters_.range_task_fallback_reason == 0 ||
         (device_spooled_ && counters_.range_task_fallback_reason ==
                                  kRangeTaskFallbackActiveGate))) ||
       (mode_ == SpineReaderMode::kHostActive &&
        counters_.host_coverage_match));
  if (mode_ == SpineReaderMode::kDeviceDirty &&
      counters_.dirty_status ==
          static_cast<std::uint32_t>(SpineDirtyStatus::kOk) &&
      terminal_overflow_) {
    counters_.dirty_status =
        counters_.range_task_fallback_reason != 0
            ? static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost)
            : static_cast<std::uint32_t>(SpineDirtyStatus::kTaskError);
  }
  enqueue_terminal_writes();
  const bool exact_tile_open = phase_ == Phase::kEdgeRead ||
                         phase_ == Phase::kEdgeEmit ||
                         phase_ == Phase::kTileEnd;
  const bool fallback_tile_open =
      !fallback_discovery_ &&
      (phase_ == Phase::kFallbackPassBegin ||
       phase_ == Phase::kFallbackRecordRead ||
       phase_ == Phase::kFallbackRecordResolve ||
       phase_ == Phase::kFallbackLevelBegin ||
       phase_ == Phase::kFallbackLookupHeaderResolve ||
       phase_ == Phase::kFallbackLookupBitmapOffsetResolve ||
       phase_ == Phase::kFallbackLookupIndexResolve ||
       phase_ == Phase::kFallbackLookupRankResolve ||
       phase_ == Phase::kFallbackLookupOffsetsResolve ||
       phase_ == Phase::kFallbackLookupPageResolve ||
       phase_ == Phase::kFallbackLookupRowResolve ||
       phase_ == Phase::kFallbackRangeResolve ||
       phase_ == Phase::kFallbackLowerBoundRead ||
       phase_ == Phase::kFallbackLowerBoundResolve ||
       phase_ == Phase::kFallbackEndpointResolve ||
       phase_ == Phase::kFallbackLevelAdvance ||
       phase_ == Phase::kFallbackRecordAdvance ||
       phase_ == Phase::kFallbackPassAdvance ||
       phase_ == Phase::kFallbackEdgeRead ||
       phase_ == Phase::kFallbackEdgeEmit || phase_ == Phase::kFallbackTileEnd);
  phase_ = exact_tile_open ? Phase::kTileEnd : (fallback_tile_open ? Phase::kFallbackTileEnd
                                                 : Phase::kDiagnostic);
}

PartConvWord SpineSplitReader::current_diagnostic_word() const {
  const std::uint32_t status =
      (counters_.range_task_path & 0xffU) |
      ((counters_.range_task_fallback_reason & 0xffU) << 8) |
      ((counters_.range_task_error & 0xffU) << 16);
  switch (diagnostic_index_) {
    case 0:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(SpineDiagnosticKind::kTaskStatus),
          .second = status,
      };
    case 1:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(SpineDiagnosticKind::kTaskCount),
          .second = static_cast<std::uint32_t>(counters_.range_task_count),
      };
    case 2:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first =
              static_cast<std::uint32_t>(SpineDiagnosticKind::kTaskRowLookups),
          .second =
              static_cast<std::uint32_t>(counters_.range_task_row_lookups),
      };
    case 3:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(
              SpineDiagnosticKind::kTaskConstructionPayloads),
          .second = static_cast<std::uint32_t>(
              counters_.range_task_construction_payloads),
      };
    case 4:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(
              SpineDiagnosticKind::kTaskReplayPayloads),
          .second =
              static_cast<std::uint32_t>(counters_.range_task_replay_payloads),
      };
    case 5:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(
              SpineDiagnosticKind::kTaskActiveRecords),
          .second =
              static_cast<std::uint32_t>(counters_.range_task_active_records),
      };
    case 6:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(
              SpineDiagnosticKind::kTaskFamilyProbes),
          .second =
              static_cast<std::uint32_t>(counters_.range_task_family_probes),
      };
    case 7:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(
              SpineDiagnosticKind::kTaskFamilySkips),
          .second =
              static_cast<std::uint32_t>(counters_.range_task_family_skips),
      };
    case 8:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first = static_cast<std::uint32_t>(SpineDiagnosticKind::kDirtyCount),
          .second = static_cast<std::uint32_t>(dirty_count_),
      };
    case 9:
      return PartConvWord{
          .kind = PartConvWordKind::kDiagnostic,
          .first =
              static_cast<std::uint32_t>(SpineDiagnosticKind::kDirtyGeneration),
          .second = dirty_generation_,
      };
    default:
      throw std::logic_error("reader diagnostic index is out of range");
  }
}

PartConvWord SpineSplitReader::current_stream_word() const {
  switch (phase_) {
    case Phase::kRequestSourceWindow:
      return PartConvWord{.kind = PartConvWordKind::kSourceRequest,
                          .first =
                              active_sources_.at(source_request_index_)};
    case Phase::kSendSourceCount:
      return PartConvWord{.kind = PartConvWordKind::kSourceCount,
                          .first = static_cast<std::uint32_t>(
                              mode_ != SpineReaderMode::kDeviceDirty
                                  ? active_sources_.size()
                                  : dirty_count_)};
    case Phase::kSendSourceGeneration:
      return PartConvWord{.kind = PartConvWordKind::kSourceGeneration,
                          .first = dirty_generation_};
    case Phase::kSendSourceDone:
      return PartConvWord{.kind = PartConvWordKind::kSourceRequestsDone};
    case Phase::kSegmentedDeferActive:
      return PartConvWord{.kind = PartConvWordKind::kDeferActiveBegin,
                          .first = 1U};
    case Phase::kTileBegin:
      return PartConvWord{.kind = PartConvWordKind::kTileBegin,
                          .first = tiles_.at(tile_index_).tile_base};
    case Phase::kEdgeEmit: {
      const BufferedPipelineEdge *buffered = next_pipeline_edge();
      if (buffered == nullptr ||
          edge_pipeline_mode_ != EdgePipelineMode::kExactReplay) {
        throw std::logic_error("exact replay has no ordered edge to emit");
      }
      return PartConvWord{
          .kind = PartConvWordKind::kEdge,
          .first = buffered->edge.dst,
          .second = algorithm_policy_->map_edge(buffered->source_value,
                                                buffered->edge.weight),
      };
    }
    case Phase::kTileEnd:
      return PartConvWord{.kind = PartConvWordKind::kTileEnd,
                          .first = tiles_.at(tile_index_).tile_base};
    case Phase::kFallbackTileBegin:
    return PartConvWord{
        .kind = PartConvWordKind::kTileBegin,
        .first = fallback_tile_base(),
        .second = fallback_force_dense_[fallback_partition_] ? 1U : 0U,
    };
  case Phase::kFallbackEdgeEmit:
    if (next_pipeline_edge() == nullptr ||
        edge_pipeline_mode_ != EdgePipelineMode::kFallbackReplay) {
      throw std::logic_error("fallback replay has no ordered edge to emit");
    }
    return PartConvWord{
        .kind = PartConvWordKind::kEdge,
        .first = next_pipeline_edge()->edge.dst,
        .second = algorithm_policy_->map_edge(
            next_pipeline_edge()->source_value,
            next_pipeline_edge()->edge.weight),
    };
  case Phase::kFallbackTileEnd:
    return PartConvWord{.kind = PartConvWordKind::kTileEnd,
                        .first = fallback_tile_base()};
  case Phase::kDiagnostic:
      return current_diagnostic_word();
    case Phase::kSourceCompletion:
      return PartConvWord{
          .kind = PartConvWordKind::kSourceCompletion,
          .first = active_sources_.at(source_completion_index_),
      };
    case Phase::kDone:
      return PartConvWord{.kind = PartConvWordKind::kDoneAll,
                          .second = terminal_overflow_ ? 1U : 0U};
    default:
      throw std::logic_error("reader phase does not produce a stream word");
  }
}

void SpineSplitReader::advance(const CycleContext &context) {
  switch (phase_) {
    case Phase::kWaitMaintenance:
      if (maintenance_.done()) {
        if (maintenance_.failed()) {
          failed_ = true;
          done_ = true;
          failure_ = "reader cannot start after failed maintenance";
          return;
        }
        if (initial_start_gate_ != nullptr && !*initial_start_gate_) {
          return;
        }
        if (mode_ == SpineReaderMode::kHostActive &&
            initial_host_bins_.has_value()) {
          initialize_host_payload(*initial_host_bins_, initial_host_coverage_);
          initial_host_bins_.reset();
          initial_host_coverage_.reset();
        }
        counters_.start_cycle = context.domain_cycle;
        if (mode_ == SpineReaderMode::kDeviceDirty) {
          active_sources_.clear();
        } else if (mode_ == SpineReaderMode::kFullDomain) {
          active_sources_.resize(maintenance_.vertices());
          std::iota(active_sources_.begin(), active_sources_.end(), 0U);
          dirty_count_ = active_sources_.size();
          dirty_generation_ = 0;
          dirty_hash_sum_ = 0;
          dirty_hash_xor_ = 0;
        }
        active_records_.clear();
        host_active_bins_ = {};
        source_request_index_ = 0;
        source_response_index_ = 0;
        source_window_end_ = 0;
        begin_source_header_reads();
        phase_ = Phase::kSourceHeaderResolve;
      }
      return;
    case Phase::kSourceHeaderResolve: {
      validate_control();
      if (terminal_pending_) {
        return;
      }
      if (mode_ == SpineReaderMode::kFullDomain) {
        active_records_.assign(active_sources_.size(), SpineActiveRecord{});
        device_spooled_ = true;
        source_request_index_ = 0;
        source_response_index_ = 0;
        source_window_begin_ = 0;
        source_window_end_ = std::min<std::size_t>(
            kSpineDirtyRequestWindow, active_sources_.size());
        if (source_window_end_ == 0) {
          phase_ = Phase::kSendSourceCount;
        } else {
          ++counters_.source_request_windows;
          phase_ = Phase::kRequestSourceWindow;
        }
      } else if (mode_ == SpineReaderMode::kDeviceDirty) {
        if (dirty_count_ > maintenance_.config().max_vertices) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorDirtyState;
          counters_.dirty_status =
              static_cast<std::uint32_t>(SpineDirtyStatus::kInvalidState);
          begin_terminal(true, "dirty frontier count exceeds MAX_N");
          return;
        }
        if (dirty_count_ > maintenance_.config().device_dirty_source_limit) {
          counters_.range_task_path = kRangeTaskPathFallback;
          counters_.range_task_fallback_reason =
              kRangeTaskFallbackDirtyRequiresHost;
          counters_.dirty_status =
              static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost);
          begin_terminal(
              true, "device dirty frontier requires host-active fallback");
          return;
        }
        active_sources_.assign(static_cast<std::size_t>(dirty_count_), 0);
        for (std::size_t index = 0; index < active_sources_.size(); ++index) {
          enqueue_read(*ports_.task_scratch,
                       maintenance_.config().persistent_dirty_list_base +
                           (index >> 2) * kSpineSortWordBytes,
                       kSpineSortWordBytes, MemoryPayloadKind::kDirtyList,
                       index);
        }
        phase_ = Phase::kDirtyListResolve;
      } else if (mode_ == SpineReaderMode::kDeviceActiveList) {
        if (device_active_count_ > maintenance_.config().max_vertices) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorActiveBounds;
          begin_terminal(true, "device active-list count exceeds MAX_ACTIVE");
          return;
        }
        active_sources_.assign(device_active_count_, 0);
        for (std::size_t index = 0; index < active_sources_.size(); ++index) {
          enqueue_read(*ports_.active_out, index * kActiveOutputBytes,
                       kActiveOutputBytes,
                       MemoryPayloadKind::kDeviceActiveOutput, index);
        }
        phase_ = Phase::kDeviceActiveResolve;
      } else {
        counters_.host_coverage_match =
            dirty_host_valid_ &&
            dirty_host_generation_ == dirty_generation_ &&
            dirty_host_count_ == dirty_count_ &&
            dirty_host_hash_sum_ == dirty_hash_sum_ &&
            dirty_host_hash_xor_ == dirty_hash_xor_;
        if (!counters_.host_coverage_match && dirty_count_ != 0) {
          counters_.dirty_status = static_cast<std::uint32_t>(
              SpineDirtyStatus::kCoverageMismatch);
        }
        std::uint64_t total = 0;
        for (std::size_t partition = 0; partition < kPartitionCount;
             ++partition) {
          const std::uint64_t offset = active_bin_offsets_[partition];
          const std::uint64_t count = active_bin_counts_[partition];
          if (offset > maintenance_.config().max_vertices ||
              count > maintenance_.config().max_vertices - offset ||
              total > maintenance_.config().max_vertices - count) {
            counters_.range_task_path = kRangeTaskPathError;
            counters_.range_task_error = kRangeTaskErrorActiveBounds;
            begin_terminal(true,
                           "host active-bin metadata exceeds MAX_ACTIVE");
            return;
          }
          total += count;
      }
      counters_.range_task_active_records = total;
      if (total > maintenance_.config().range_task_active_gate &&
          !maintenance_.config().segmented_fallback) {
        const GraphAlgorithmKind kind = algorithm_policy_->config().kind;
        const bool needs_source_refresh =
            kind == GraphAlgorithmKind::kFullPageRank ||
            kind == GraphAlgorithmKind::kResidualPageRank ||
            kind == GraphAlgorithmKind::kConnectedComponents;
        if (!needs_source_refresh || active_sources_.empty()) {
          start_host_fallback(kRangeTaskFallbackActiveGate);
          return;
        }
        fallback_after_source_refresh_ = true;
        source_request_index_ = 0;
        source_response_index_ = 0;
        source_window_end_ = std::min<std::size_t>(
            kSpineDirtyRequestWindow, active_sources_.size());
        ++counters_.source_request_windows;
        phase_ = Phase::kRequestSourceWindow;
        return;
      }
      for (std::size_t partition = 0; partition < kPartitionCount;
           ++partition) {
        const std::uint64_t count = active_bin_counts_[partition];
          if (count != 0) {
            enqueue_read(*ports_.active_bins,
                       active_bin_offsets_[partition] * kActiveRecordBytes,
                         count * kActiveRecordBytes,
                         MemoryPayloadKind::kActiveRecords, partition);
          }
        }
        phase_ = Phase::kHostActiveResolve;
      }
      return;
    }
    case Phase::kDeviceActiveResolve: {
      std::unordered_set<std::uint32_t> unique_sources;
      bool active_payload_valid = true;
      for (const std::uint32_t source : active_sources_) {
        active_payload_valid =
            active_payload_valid && source < maintenance_.vertices() &&
            source < maintenance_.config().max_vertices &&
            unique_sources.insert(source).second;
      }
      if (!active_payload_valid ||
          source_values_.size() != active_sources_.size()) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorActiveBounds;
        begin_terminal(true, "device active-list payload is invalid");
        return;
      }
      active_records_.assign(active_sources_.size(), SpineActiveRecord{});
      device_spooled_ =
          active_sources_.size() > maintenance_.config().range_task_active_gate;
      source_request_index_ = 0;
      source_response_index_ = 0;
      source_window_end_ = std::min<std::size_t>(
          kSpineDirtyRequestWindow, active_sources_.size());
      if (source_window_end_ == 0) {
        phase_ = Phase::kSendSourceCount;
      } else {
        ++counters_.source_request_windows;
        phase_ = Phase::kRequestSourceWindow;
      }
      return;
    }
    case Phase::kDirtyListResolve:
      for (const std::uint32_t source : active_sources_) {
        if (source >= maintenance_.vertices() ||
            source >= maintenance_.config().max_vertices) {
          dirty_payload_valid_ = false;
          continue;
        }
        enqueue_read(*ports_.task_scratch,
                     maintenance_.config().persistent_dirty_bitmap_base +
                         (source >> 7) * kSpineSortWordBytes,
                     kSpineSortWordBytes, MemoryPayloadKind::kDirtyBitmap, 0,
                     source);
      }
      phase_ = Phase::kDirtyBitmapResolve;
      return;
    case Phase::kDirtyBitmapResolve: {
      std::uint64_t hash_sum = 0;
      std::uint64_t hash_xor = 0;
      for (const std::uint32_t source : active_sources_) {
        hash_sum += spine_dirty_hash_sum_term(source);
        hash_xor ^= spine_dirty_hash_xor_term(source);
      }
      if (!dirty_payload_valid_ || hash_sum != dirty_hash_sum_ ||
          hash_xor != dirty_hash_xor_) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorDirtyState;
        counters_.dirty_status =
            static_cast<std::uint32_t>(SpineDirtyStatus::kInvalidState);
        begin_terminal(true, "dirty list/bitmap/hash payloads disagree");
        return;
      }
      active_records_.assign(active_sources_.size(), SpineActiveRecord{});
      device_spooled_ =
          active_sources_.size() > maintenance_.config().range_task_active_gate;
      source_request_index_ = 0;
      source_response_index_ = 0;
      if (active_sources_.empty()) {
        phase_ = Phase::kSendSourceCount;
      } else {
        source_window_end_ = std::min<std::size_t>(
            kSpineDirtyRequestWindow, active_sources_.size());
        ++counters_.source_request_windows;
        phase_ = Phase::kRequestSourceWindow;
      }
      return;
    }
    case Phase::kHostActiveResolve:
      for (const SpineActiveRecord &record : active_records_) {
        if (record.source >= maintenance_.vertices() ||
            record.source >= maintenance_.config().max_vertices) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorActiveBounds;
          begin_terminal(true,
                         "active-record payload source exceeds the graph");
          return;
        }
      }
      source_request_index_ = 0;
      source_response_index_ = 0;
      if (active_sources_.empty()) {
        phase_ = Phase::kLevelOccupancyBegin;
      } else {
        source_window_end_ = std::min<std::size_t>(
            kSpineDirtyRequestWindow, active_sources_.size());
        ++counters_.source_request_windows;
        phase_ = Phase::kRequestSourceWindow;
      }
      return;
    case Phase::kSourceDirectoryBegin:
      begin_source_directory_window();
      return;
    case Phase::kSourceDirectoryResolve:
      if (source_request_index_ == active_sources_.size()) {
        phase_ = Phase::kSendSourceCount;
      } else {
        source_window_begin_ = source_request_index_;
        source_window_end_ = std::min(
            source_request_index_ + kSpineDirtyRequestWindow,
            active_sources_.size());
        ++counters_.source_request_windows;
        phase_ = Phase::kRequestSourceWindow;
      }
      return;
    case Phase::kSourceSpoolValidationRead:
      phase_ = Phase::kLevelOccupancyBegin;
      return;
    case Phase::kSourceSpoolExecutionRead:
      prepare_range_probes();
      if (terminal_pending_ || fallback_enabled_) {
        return;
      }
      phase_ = Phase::kSegmentedDeferActive;
      return;
    case Phase::kLevelOccupancyBegin:
      enqueue_level_cache_reads();
      phase_ = Phase::kLevelDetailsBegin;
      return;
    case Phase::kLevelDetailsBegin:
      enqueue_level_detail_reads();
      phase_ = Phase::kSetupReads;
      return;
    case Phase::kSetupReads:
      finalize_level_cache();
      prepare_range_probes();
      if (terminal_pending_) {
        return;
      }
      refactor31_validation_payload_base_ =
          counters_.range_task_construction_payloads;
      begin_refactor31_control();
      return;
    case Phase::kRefactor31Control:
      if (refactor31_control_remaining_ != 0) {
        --refactor31_control_remaining_;
        ++counters_.range_task_control_cycles;
      } else {
        bin_index_ = 0;
        phase_ = Phase::kBinClear;
      }
      return;
    case Phase::kRefactor31SegmentSetup:
      if (refactor31_setup_remaining_ != 0) {
        --refactor31_setup_remaining_;
        ++counters_.segmented_setup_cycles;
      } else {
        begin_refactor31_control();
      }
      return;
    case Phase::kSegmentedDeferActive:
      return;
    case Phase::kBinClear:
      tile_counts_[bin_index_] = 0;
      tile_offsets_[bin_index_] = 0;
      tile_cursors_[bin_index_] = 0;
      tiles_[bin_index_].tile_base =
          static_cast<std::uint32_t>(bin_index_ * kTileVertices);
      tiles_[bin_index_].ranges.clear();
      ++counters_.range_task_clear_cycles;
      ++bin_index_;
      if (bin_index_ == kRangeTaskMaxTiles) {
        probe_index_ = 0;
        phase_ = Phase::kProbeBegin;
      }
      return;
    case Phase::kProbeBegin:
      if (probe_index_ == range_probes_.size()) {
        if (segmented_pass_ == SegmentedPass::kValidation) {
          finish_refactor31_validation_pass();
          return;
        }
        bin_index_ = 0;
        phase_ = Phase::kBinPrefix;
        return;
      }
      enqueue_probe_index_reads();
      return;
    case Phase::kProbeEpochResolve:
      resolve_probe_epoch();
      return;
    case Phase::kProbeIndexResolve:
      resolve_probe_index();
      return;
    case Phase::kProbeRankResolve:
      resolve_probe_rank();
      return;
    case Phase::kProbePageResolve:
      resolve_probe_page();
      return;
    case Phase::kProbeRowResolve:
      resolve_probe_row();
      return;
    case Phase::kProbeLowerBoundRead:
    case Phase::kProbeLowerBoundResolve:
      advance_probe_lower_bound();
      return;
    case Phase::kConstructionRead:
    case Phase::kConstructionConsume:
      return;
    case Phase::kProbeAdvance:
      ++probe_index_;
      phase_ = Phase::kProbeBegin;
      return;
    case Phase::kBinPrefix: {
      const std::uint32_t prefix =
          bin_index_ == 0
              ? 0
              : tile_offsets_[bin_index_ - 1] + tile_counts_[bin_index_ - 1];
      const std::uint64_t next =
          static_cast<std::uint64_t>(prefix) + tile_counts_[bin_index_];
      tile_offsets_[bin_index_] = prefix;
      tile_cursors_[bin_index_] = prefix;
      ++counters_.range_task_prefix_cycles;
      ++bin_index_;
      if (next > range_tasks_.size() || next > maintenance_.config().range_task_capacity) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorPrefix;
        begin_terminal(true,
                       "range-task prefix sum exceeded the task count");
        return;
      }
      if (bin_index_ == kRangeTaskMaxTiles) {
        if (next != range_tasks_.size()) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorPrefix;
          begin_terminal(true, "range-task prefix sum did not close");
          return;
        }
        scatter_index_ = 0;
        phase_ = Phase::kBinScatter;
      }
      return;
    }
    case Phase::kBinScatter:
      if (scatter_index_ == range_tasks_.size()) {
        bin_index_ = 0;
        phase_ = Phase::kBinVerify;
        return;
      } else {
        const RangeTask &task = range_tasks_[scatter_index_];
        if (task.tile >= kRangeTaskMaxTiles) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorDescriptor;
          begin_terminal(true,
                         "range-task scatter received an invalid tile");
          return;
        }
        const std::uint32_t limit =
            tile_offsets_[task.tile] + tile_counts_[task.tile];
        if (tile_cursors_[task.tile] >= limit ||
            tile_cursors_[task.tile] >=
              maintenance_.config().range_task_capacity) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorPrefix;
          begin_terminal(
              true, "range-task scatter cursor exceeded its tile bin");
          return;
        }
        tiles_[task.tile].ranges.push_back(task);
        ++tile_cursors_[task.tile];
        ++scatter_index_;
        ++counters_.range_task_scatter_cycles;
      }
      return;
    case Phase::kBinVerify:
      if (tile_cursors_[bin_index_] !=
              tile_offsets_[bin_index_] + tile_counts_[bin_index_] ||
          tiles_[bin_index_].ranges.size() != tile_counts_[bin_index_]) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorPrefix;
        begin_terminal(true,
                       "range-task tile cursor verification failed");
        return;
      }
      ++counters_.range_task_verify_cycles;
      ++bin_index_;
      if (bin_index_ == kRangeTaskMaxTiles) {
        tile_index_ = 0;
        if (segmented_pass_ == SegmentedPass::kExecution) {
          counters_.range_task_path = kRangeTaskPathFallback;
          counters_.segmented_task_count = range_tasks_.size();
          ++counters_.segmented_segment_count;
        } else {
          counters_.range_task_path = kRangeTaskPathExact;
        }
        phase_ = Phase::kTileScan;
      }
      return;
    case Phase::kTileScan:
      if (tile_index_ == tiles_.size()) {
        begin_terminal(false);
      } else if (tiles_[tile_index_].ranges.empty()) {
        ++tile_index_;
      } else {
        phase_ = Phase::kTileBegin;
      }
      return;
    case Phase::kEdgeRead: {
      if (range_index_ == tiles_.at(tile_index_).ranges.size()) {
        phase_ = Phase::kTileEnd;
        return;
      }
      if (range_edge_index_ ==
          tiles_[tile_index_].ranges[range_index_].length) {
        ++range_index_;
        range_edge_index_ = 0;
        return;
      }
      const RangeTask &range = tiles_[tile_index_].ranges[range_index_];
      if (range.graph_bank >= ports_.graph.size() || range.length == 0) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorDescriptor;
        begin_terminal(true,
                       "range-task replay received an invalid descriptor");
        return;
      }
      const std::uint32_t tile_base = tiles_[tile_index_].tile_base;
      const std::uint32_t tile_end =
          static_cast<std::uint32_t>(std::min<std::uint64_t>(
              maintenance_.vertices(),
              static_cast<std::uint64_t>(tile_base) + kTileVertices));
      begin_edge_pipeline(
          EdgePipelineMode::kExactReplay, *ports_.graph[range.graph_bank],
          (range.absolute_word + range_edge_index_) * kSpineGraphWordBytes,
          range.length - range_edge_index_, range.source, range.source_value,
          tile_base, tile_end, range.hot);
      phase_ = Phase::kEdgeEmit;
      return;
    }
    case Phase::kRequestSourceWindow:
    case Phase::kWaitSourceWindow:
    case Phase::kSendSourceCount:
    case Phase::kSendSourceGeneration:
    case Phase::kSendSourceDone:
    case Phase::kWaitSourceAck:
    case Phase::kSourceCompletion:
    case Phase::kTileBegin:
    case Phase::kEdgeEmit:
    case Phase::kTileEnd:
    return;
  case Phase::kFallbackPartitionBegin:
  case Phase::kFallbackLevelCacheBegin:
  case Phase::kFallbackLevelCacheDetails:
  case Phase::kFallbackLevelCacheResolve:
  case Phase::kFallbackPassBegin:
  case Phase::kFallbackRecordRead:
  case Phase::kFallbackRecordResolve:
  case Phase::kFallbackLevelBegin:
  case Phase::kFallbackLookupHeaderResolve:
  case Phase::kFallbackLookupBitmapOffsetResolve:
  case Phase::kFallbackLookupIndexResolve:
  case Phase::kFallbackLookupRankResolve:
  case Phase::kFallbackLookupOffsetsResolve:
  case Phase::kFallbackLookupPageResolve:
  case Phase::kFallbackLookupRowResolve:
  case Phase::kFallbackRangeResolve:
  case Phase::kFallbackLowerBoundRead:
  case Phase::kFallbackLowerBoundResolve:
  case Phase::kFallbackEndpointResolve:
  case Phase::kFallbackLevelAdvance:
  case Phase::kFallbackRecordAdvance:
  case Phase::kFallbackPassAdvance:
  case Phase::kFallbackTileScan:
  case Phase::kFallbackTileBegin:
  case Phase::kFallbackEdgeRead:
  case Phase::kFallbackEdgeEmit:
  case Phase::kFallbackTileEnd:
    advance_fallback();
    return;
    case Phase::kDiagnostic:
    case Phase::kDone:
      return;
  }
}

}  // namespace spine::sim
