#include "spine_sim/spine_system.hpp"

#include <algorithm>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace spine::sim {

namespace {

SpineActiveBins build_host_active_bins(
    const SpineL0State &state, const SpineL0Config &config,
    const std::vector<std::uint32_t> &sources,
    const std::vector<std::uint32_t> &values) {
  SpineActiveBins result;
  for (const std::uint32_t source : sources) {
    if (source >= values.size()) {
      throw std::logic_error("host active source has no vertex-state value");
    }
    SpineActiveRecord base{
        .source = source,
        .source_value = values[source],
    };
    std::array<std::uint16_t, 16> hot_by_partition{};
    std::uint16_t any_partition = 0;
    for (std::size_t level = 0; level < config.levels; ++level) {
      std::uint16_t cold_mask = 0;
      for (std::size_t family = 0; family < config.partitions; ++family) {
        for (const SpineEdgeRecord &edge : state.cold_levels[family][level]) {
          if (edge.src == source) {
            const std::size_t partition = std::min<std::size_t>(
                edge.dst / config.vertex_partition_size, config.partitions - 1);
            cold_mask |= static_cast<std::uint16_t>(1U << partition);
          }
        }
        if (!state.hot_enabled) {
          continue;
        }
        for (const SpineEdgeRecord &edge : state.hot_levels[family][level]) {
          if (edge.src == source) {
            const std::size_t partition = std::min<std::size_t>(
                edge.dst / config.vertex_partition_size, config.partitions - 1);
            hot_by_partition[partition] |=
                static_cast<std::uint16_t>(1U << family);
          }
        }
      }
      base.level_masks[level] = cold_mask;
      any_partition |= cold_mask;
    }
    for (std::size_t partition = 0; partition < config.partitions;
         ++partition) {
      if (hot_by_partition[partition] != 0) {
        any_partition |= static_cast<std::uint16_t>(1U << partition);
      }
      if (((any_partition >> partition) & 1U) == 0) {
        continue;
      }
      SpineActiveRecord record = base;
      record.hot_shard_mask = hot_by_partition[partition];
      result.bins[partition].push_back(record);
    }
  }
  return result;
}

struct PageRankHostInput {
  SpineActiveBins bins;
  std::vector<std::uint32_t> sources;
  std::vector<std::uint32_t> out_degrees;
  std::optional<SpineDirtyIdentity> coverage;
};

PageRankHostInput build_pagerank_host_input(const SpineEdgeSlice &workload,
                                             const SpineL0Config &config) {
  if (workload.vertices == 0 ||
      workload.vertices > std::numeric_limits<std::uint32_t>::max() ||
      config.partitions != 16 || config.levels > kSpineLevelCount) {
    throw std::invalid_argument("unsupported Spine PageRank graph shape");
  }
  PageRankHostInput result;
  result.sources.resize(workload.vertices);
  std::iota(result.sources.begin(), result.sources.end(), 0U);
  result.out_degrees.assign(workload.vertices, 0);
  struct SourcePartitionUse {
    bool cold{};
    std::uint16_t hot_shards{};
  };
  std::vector<std::array<SourcePartitionUse, 16>> source_partitions(
      workload.vertices);
  const std::unordered_set<std::uint32_t> hot_vertices(
      config.hot_vertices.begin(), config.hot_vertices.end());
  std::vector<std::uint32_t> dirty_sources;
  std::unordered_set<std::uint32_t> dirty_seen;
  for (const SpineEdgeRecord &edge : workload.edges) {
    if (edge.src >= workload.vertices || edge.dst >= workload.vertices ||
        edge.diff != 1 ||
        result.out_degrees[edge.src] ==
            std::numeric_limits<std::uint32_t>::max()) {
      throw std::invalid_argument(
          "initial PageRank vertical slice requires in-range insertion edges");
    }
    ++result.out_degrees[edge.src];
    const std::size_t partition = std::min<std::size_t>(
        edge.dst / config.vertex_partition_size, config.partitions - 1);
    SourcePartitionUse &use = source_partitions[edge.src][partition];
    if (hot_vertices.contains(edge.dst)) {
      use.hot_shards |=
          static_cast<std::uint16_t>(1U << spine_hot_shard(edge.dst));
    } else {
      use.cold = true;
    }
    if (dirty_seen.insert(edge.src).second) {
      dirty_sources.push_back(edge.src);
    }
  }
  std::sort(dirty_sources.begin(), dirty_sources.end());
  if (!dirty_sources.empty()) {
    result.coverage = spine_dirty_identity(1, dirty_sources);
  }
  for (std::uint32_t source = 0; source < workload.vertices; ++source) {
    for (std::size_t partition = 0; partition < config.partitions;
         ++partition) {
      const SourcePartitionUse &use = source_partitions[source][partition];
      if (!use.cold && use.hot_shards == 0) {
        continue;
      }
      SpineActiveRecord record{
          .source = source,
          .source_value = 0,
          .hot_shard_mask = use.hot_shards,
      };
      if (use.cold) {
        for (std::size_t level = 0; level < config.levels; ++level) {
          record.level_masks[level] =
              static_cast<std::uint16_t>(1U << partition);
        }
      }
      result.bins.bins[partition].push_back(record);
    }
  }
  return result;
}

}  // namespace

SpineAxiInterfaceProfile SpineAxiInterfaceProfile::legacy_uniform64() {
  return SpineAxiInterfaceProfile{
      .profile_id = "legacy_uniform64",
      .max_burst_beats = 16,
      .readwrite_max_pending_requests = 32,
      .writeonly_max_pending_requests = 32,
      .maintenance_readwrite_max_pending_requests = 0,
      .maintenance_writeonly_max_pending_requests = 0,
      .max_outstanding_bursts = 32,
      .response_beats_per_cycle = 4,
      .read_reorder_capacity = 32,
      .read_address_pipeline_cycles = 0,
      .read_data_pipeline_cycles = 0,
      .write_buffer_pipeline_cycles = 0,
      .serialize_write_bursts = false,
      .maintenance_read_reorder_capacity = 0,
      .maintenance_read_address_pipeline_cycles = 0,
      .maintenance_read_data_pipeline_cycles = 0,
      .maintenance_write_buffer_pipeline_cycles = 0,
      .maintenance_serialize_write_bursts = false,
      .burst_trace_limit = 0,
      .graph_bytes = 64,
      .sorted_edge_bytes = 64,
      .active_bin_bytes = 64,
      .metadata_bytes = 64,
      .result_bytes = 64,
      .maintenance_result_bytes = 0,
      .vertex_state_bytes = 64,
      .active_out_bytes = 64,
      .active_bitmap_bytes = 64,
  };
}

SpineAxiInterfaceProfile SpineAxiInterfaceProfile::candidate10_1e61fc0() {
  SpineAxiInterfaceProfile profile;
  profile.profile_id = "candidate10_gmem_1e61fc0";
  profile.maintenance_readwrite_max_pending_requests = 70;
  profile.maintenance_writeonly_max_pending_requests = 67;
  profile.maintenance_read_reorder_capacity = 256;
  profile.maintenance_read_address_pipeline_cycles = 7;
  profile.maintenance_read_data_pipeline_cycles = 1;
  profile.maintenance_write_buffer_pipeline_cycles = 10;
  profile.maintenance_serialize_write_bursts = true;
  profile.maintenance_result_bytes = 8;
  return profile;
}

FixedAxiPortConfig SpineAxiInterfaceProfile::port_config(
    SpineAxiPortKind kind, std::size_t memory_channels, std::size_t channel,
    std::uint32_t initiator_id) const {
  std::uint32_t width = 0;
  bool write_only = false;
  bool maintenance_port = true;
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    width = graph_bytes;
    break;
  case SpineAxiPortKind::kSortedEdges:
    width = sorted_edge_bytes;
    break;
  case SpineAxiPortKind::kActiveBins:
    width = active_bin_bytes;
    break;
  case SpineAxiPortKind::kMetadata:
    width = metadata_bytes;
    break;
  case SpineAxiPortKind::kMaintenanceResult:
    width = maintenance_result_bytes == 0 ? result_bytes
                                          : maintenance_result_bytes;
    write_only = true;
    break;
  case SpineAxiPortKind::kVertexState:
    width = vertex_state_bytes;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kActiveOut:
    width = active_out_bytes;
    write_only = true;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kActiveBitmap:
    width = active_bitmap_bytes;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kComputeResult:
    width = result_bytes;
    write_only = true;
    maintenance_port = false;
    break;
  }
  if (profile_id.empty() || width == 0 || max_burst_beats == 0 ||
      readwrite_max_pending_requests == 0 ||
      writeonly_max_pending_requests == 0 || max_outstanding_bursts == 0 ||
      response_beats_per_cycle == 0) {
    throw std::invalid_argument("invalid Spine AXI interface profile");
  }
  std::size_t max_pending = write_only ? writeonly_max_pending_requests
                                       : readwrite_max_pending_requests;
  if (maintenance_port) {
    const std::size_t override =
        write_only ? maintenance_writeonly_max_pending_requests
                   : maintenance_readwrite_max_pending_requests;
    if (override != 0) {
      max_pending = override;
    }
  }
  const std::size_t port_read_reorder_capacity =
      maintenance_port && maintenance_read_reorder_capacity != 0
          ? maintenance_read_reorder_capacity
          : read_reorder_capacity;
  const std::uint64_t port_read_address_pipeline_cycles =
      maintenance_port && maintenance_read_address_pipeline_cycles != 0
          ? maintenance_read_address_pipeline_cycles
          : read_address_pipeline_cycles;
  const std::uint64_t port_read_data_pipeline_cycles =
      maintenance_port && maintenance_read_data_pipeline_cycles != 0
          ? maintenance_read_data_pipeline_cycles
          : read_data_pipeline_cycles;
  const std::uint64_t port_write_buffer_pipeline_cycles =
      maintenance_port && maintenance_write_buffer_pipeline_cycles != 0
          ? maintenance_write_buffer_pipeline_cycles
          : write_buffer_pipeline_cycles;
  const bool port_serialize_write_bursts =
      maintenance_port && maintenance_serialize_write_bursts
          ? true
          : serialize_write_bursts;
  return FixedAxiPortConfig{
      .memory_channels = memory_channels,
      .channel = channel,
      .initiator_id = initiator_id,
      .data_width_bytes = width,
      .max_burst_beats = max_burst_beats,
      .read_reorder_capacity = port_read_reorder_capacity,
      .stream_read_beats =
          (kind == SpineAxiPortKind::kSortedEdges &&
           sorted_edge_bytes == kSpineSortWordBytes) ||
          kind == SpineAxiPortKind::kVertexState,
      .max_pending_requests = max_pending,
      .max_outstanding_bursts = max_outstanding_bursts,
      .response_beats_per_cycle = response_beats_per_cycle,
      .read_address_pipeline_cycles = port_read_address_pipeline_cycles,
      .read_data_pipeline_cycles = port_read_data_pipeline_cycles,
      .write_buffer_pipeline_cycles = port_write_buffer_pipeline_cycles,
      .serialize_write_bursts = port_serialize_write_bursts,
      .burst_trace_limit = burst_trace_limit,
  };
}

SpineVerticalSliceSystem::SpineVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, std::uint32_t source, std::size_t tiny_threshold,
    SpineL0Config maintenance_config, SpineL0State initial_state,
    SpineAxiInterfaceProfile axi_profile,
    std::size_t compute_memory_request_window,
    std::size_t compute_writeonly_request_window,
    SpineOnChipMemoryProfile on_chip_profile)
    : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
      axi_profile_(std::move(axi_profile)),
      source_(source),
      edge_stream_("edge-axis", clock_id, 32),
      value_stream_("value-axis", clock_id, 32),
      state_(std::move(initial_state)), current_frontier_{source} {
  if (source >= workload.vertices) {
    throw std::invalid_argument("Spine vertical-slice source is out of range");
  }
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    graph_ports_[family] = make_port("graph" + std::to_string(family),
                                     static_cast<std::uint32_t>(family), family,
                                     SpineAxiPortKind::kGraph);
  }
  sorted_ = make_port("sorted-edges", 16, 16, SpineAxiPortKind::kSortedEdges);
  active_bins_ =
      make_port("active-bins", 18, 18, SpineAxiPortKind::kActiveBins);
  metadata_ = make_port("metadata", 20, 20, SpineAxiPortKind::kMetadata);
  maintenance_result_ = make_port("maintenance-result", 21, 21,
                                  SpineAxiPortKind::kMaintenanceResult);

  // Compute is a separate CU, so initiator IDs differ even when a pseudo-
  // channel is shared with the fused read-maintenance CU.
  vertex_state_ =
      make_port("vertex-state", 117, 17, SpineAxiPortKind::kVertexState);
  active_out_ = make_port("active-out", 119, 19, SpineAxiPortKind::kActiveOut);
  compute_result_ =
      make_port("compute-result", 121, 21, SpineAxiPortKind::kComputeResult);
  active_bitmap_ =
      make_port("active-bitmap", 122, 22, SpineAxiPortKind::kActiveBitmap);

  SpineL0Ports maintenance_ports;
  SpineReaderPorts reader_ports;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    maintenance_ports.graph[family] = graph_ports_[family].get();
    reader_ports.graph[family] = graph_ports_[family].get();
  }
  maintenance_ports.sorted_edges = sorted_.get();
  maintenance_ports.metadata = metadata_.get();
  maintenance_ports.result = maintenance_result_.get();
  reader_ports.task_scratch = sorted_.get();
  reader_ports.active_bins = active_bins_.get();
  reader_ports.metadata = metadata_.get();
  reader_ports.result = maintenance_result_.get();

  const std::size_t vertices = workload.vertices;
  const auto algorithm_policy = std::make_shared<const GraphAlgorithmPolicy>(
      AlgorithmPolicyConfig{
          .kind = GraphAlgorithmKind::kWeightedSssp,
          .vertices = vertices,
          .source = source,
      });
  maintenance_ = std::make_unique<SpineL0Maintenance>(
      "spine-l0-maintenance", clock_id_, std::move(maintenance_config),
      std::move(workload), maintenance_ports, state_);
  reader_ = std::make_unique<SpineSplitReader>(
      "spine-split-reader", clock_id_, *maintenance_, reader_ports,
      std::vector<std::uint32_t>{source}, edge_stream_, value_stream_,
      SpineReaderMode::kDeviceDirty, algorithm_policy);
  compute_ = std::make_unique<SpineSplitSsspCompute>(
      "spine-split-compute", clock_id_, vertices, source, tiny_threshold,
      SpineComputePorts{
          .vertex_state = vertex_state_.get(),
          .active_out = active_out_.get(),
          .active_bitmap = active_bitmap_.get(),
          .result = compute_result_.get(),
      },
      edge_stream_, value_stream_, compute_memory_request_window,
      compute_writeonly_request_window, on_chip_profile, algorithm_policy);
  dirty_ack_ = std::make_unique<SpineDirtyAck>(
      "spine-dirty-ack", clock_id_, maintenance_->config(),
      SpineDirtyAckPorts{
          .task_scratch = sorted_.get(),
          .metadata = metadata_.get(),
          .result = maintenance_result_.get(),
      });
}

std::unique_ptr<FixedAxiPort> SpineVerticalSliceSystem::make_port(
    const std::string &name, std::uint32_t initiator_id, std::size_t channel,
    SpineAxiPortKind kind) {
  return std::make_unique<FixedAxiPort>(
      name, clock_id_,
      axi_profile_.port_config(kind, 32, channel, initiator_id), backend_);
}

void SpineVerticalSliceSystem::register_components() {
  if (registered_) {
    throw std::logic_error(
        "Spine vertical-slice components already registered");
  }
  registered_ = true;
  scheduler_.add_component(*maintenance_);
  scheduler_.add_component(*reader_);
  scheduler_.add_component(*compute_);
  scheduler_.add_component(*dirty_ack_);
  scheduler_.add_component(edge_stream_);
  scheduler_.add_component(value_stream_);
  for (auto &port : graph_ports_) {
    port->register_components(scheduler_);
  }
  sorted_->register_components(scheduler_);
  active_bins_->register_components(scheduler_);
  metadata_->register_components(scheduler_);
  maintenance_result_->register_components(scheduler_);
  vertex_state_->register_components(scheduler_);
  active_out_->register_components(scheduler_);
  compute_result_->register_components(scheduler_);
  active_bitmap_->register_components(scheduler_);
}

void SpineVerticalSliceSystem::restart_read_compute(
    std::vector<std::uint32_t> active_sources,
    std::optional<SpineDirtyIdentity> host_coverage) {
  if (!registered_ || !done() || !idle() || failed() ||
      active_sources.empty()) {
    throw std::logic_error(
        "Spine read/compute restart requires a successful drained round");
  }
  const SpineActiveBins bins = build_host_active_bins(
      state_, maintenance_->config(), active_sources, compute_->values());
  restart_read_compute_bins(bins, host_coverage);
  current_frontier_ = std::move(active_sources);
}

void SpineVerticalSliceSystem::restart_read_compute_bins(
    const SpineActiveBins &active_bins,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::vector<std::uint32_t> source_refresh) {
  const bool recovering = recoverable_host_handoff();
  if (!registered_ || !done() || !idle() || (failed() && !recovering)) {
    throw std::logic_error(
        "Spine host-bin restart requires a successful drained round");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  reader_->reset_host_round(active_bins, host_coverage, source_refresh);
  if (recovering) {
    compute_->reset_after_host_handoff();
  } else {
    compute_->reset_round();
  }
  current_frontier_.clear();
  std::unordered_set<std::uint32_t> seen;
  for (const std::uint32_t source : source_refresh) {
    if (seen.insert(source).second) {
      current_frontier_.push_back(source);
    }
  }
  for (const auto &bin : active_bins.bins) {
    for (const SpineActiveRecord &record : bin) {
      if (seen.insert(record.source).second) {
        current_frontier_.push_back(record.source);
      }
    }
  }
}

void SpineVerticalSliceSystem::restart_incremental_update(
    SpineEdgeSlice workload) {
  if (!registered_ || !done() || failed() || !idle() ||
      !dirty_ack_->done() || dirty_ack_->failed() ||
      workload.vertices != maintenance_->vertices() ||
      workload.edges.empty() ||
      std::any_of(workload.edges.begin(), workload.edges.end(),
                  [](const SpineEdgeRecord &edge) { return edge.diff <= 0; })) {
    throw std::logic_error(
        "Spine incremental update requires a positive drained batch");
  }
  std::vector<std::uint32_t> changed_sources;
  changed_sources.reserve(workload.edges.size());
  for (const SpineEdgeRecord &edge : workload.edges) {
    changed_sources.push_back(edge.src);
  }
  std::sort(changed_sources.begin(), changed_sources.end());
  changed_sources.erase(
      std::unique(changed_sources.begin(), changed_sources.end()),
      changed_sources.end());

  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  dirty_ack_->reset();
  reader_->reset_round(changed_sources);
  compute_->reset_round();
  maintenance_->reset_batch(std::move(workload));
  current_frontier_ = std::move(changed_sources);
  convergence_run_started_ = false;
}

void SpineVerticalSliceSystem::restart_full_rebuild(SpineEdgeSlice snapshot) {
  if (!registered_ || !done() || failed() || !idle() ||
      !dirty_ack_->done() || dirty_ack_->failed() ||
      snapshot.vertices != maintenance_->vertices() || snapshot.edges.empty() ||
      std::any_of(snapshot.edges.begin(), snapshot.edges.end(),
                  [](const SpineEdgeRecord &edge) { return edge.diff <= 0; })) {
    throw std::logic_error(
        "Spine full rebuild requires a positive drained graph snapshot");
  }

  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  dirty_ack_->reset();
  reader_->reset_round({source_});
  compute_->reset_for_full_recompute();
  maintenance_->reset_full_rebuild(std::move(snapshot));
  current_frontier_ = {source_};
  convergence_run_started_ = false;
}

bool SpineVerticalSliceSystem::recoverable_host_handoff() const noexcept {
  return registered_ && maintenance_->done() && !maintenance_->failed() &&
         reader_->recoverable_host_handoff() &&
         compute_->recoverable_host_handoff() && idle();
}

std::vector<std::uint32_t>
SpineVerticalSliceSystem::restart_device_dirty_host_fallback() {
  if (!recoverable_host_handoff()) {
    throw std::logic_error(
        "device-dirty host fallback requires a drained REQUIRES_HOST result");
  }
  const SpineReaderCounters &reader = reader_->counters();
  const std::size_t count = reader.dirty_count;
  const std::size_t bytes = ((count + 3) / 4) * kSpineSortWordBytes;
  const std::vector<std::uint8_t> payload = backend_.inspect_payload(
      sorted_->channel(), maintenance_->config().persistent_dirty_list_base,
      bytes);
  std::vector<std::uint32_t> sources(count, 0);
  for (std::size_t index = 0; index < count; ++index) {
    const std::size_t offset = index * sizeof(std::uint32_t);
    sources[index] = static_cast<std::uint32_t>(payload[offset]) |
                     (static_cast<std::uint32_t>(payload[offset + 1]) << 8) |
                     (static_cast<std::uint32_t>(payload[offset + 2]) << 16) |
                     (static_cast<std::uint32_t>(payload[offset + 3]) << 24);
  }
  const SpineDirtyIdentity coverage =
      spine_dirty_identity(reader.dirty_generation, sources);
  if (coverage.count != reader.dirty_count ||
      coverage.hash_sum != reader.dirty_hash_sum ||
      coverage.hash_xor != reader.dirty_hash_xor) {
    throw std::logic_error(
        "host handoff list does not match the captured dirty identity");
  }
  const SpineActiveBins bins = build_host_active_bins(
      state_, maintenance_->config(), sources, compute_->values());
  restart_read_compute_bins(bins, coverage);
  current_frontier_ = sources;
  return sources;
}

void SpineVerticalSliceSystem::start_dirty_ack() {
  if (!registered_ || !maintenance_->done() || !reader_->done() ||
      !compute_->done() || !idle() || dirty_ack_->started()) {
    throw std::logic_error(
        "dirty ACK requires a drained successful convergence round");
  }
  const auto &reader = reader_->counters();
  const auto &compute = compute_->counters();
  const bool can_ack =
      !failed() &&
      reader.dirty_status ==
          static_cast<std::uint32_t>(SpineDirtyStatus::kOk) &&
      reader.acknowledgement_eligible && !compute.done_overflow &&
      compute.range_task_error == 0 && compute.source_protocol_status == 0 &&
      compute.dirty_generation == reader.dirty_generation &&
      compute.dirty_count == reader.dirty_count;
  if (!can_ack) {
    throw std::logic_error(
        "failed convergence result cannot publish a dirty ACK candidate");
  }
  dirty_ack_->start(
      compute.dirty_generation,
      SpineDirtyIdentity{
          .generation = compute.dirty_generation,
          .count = compute.dirty_count,
          .hash_sum = reader.dirty_hash_sum,
          .hash_xor = reader.dirty_hash_xor,
      });
}

bool SpineVerticalSliceSystem::dirty_ack_started() const noexcept {
  return dirty_ack_->started();
}

bool SpineVerticalSliceSystem::dirty_ack_done() const noexcept {
  return dirty_ack_->done();
}

SpineSsspRunResult SpineVerticalSliceSystem::run_sssp_to_convergence(
    std::size_t max_rounds, std::uint64_t max_events_per_round) {
  if (!registered_ || convergence_run_started_ || done() || max_rounds == 0 ||
      max_events_per_round == 0) {
    throw std::logic_error("invalid Spine convergence-run state or limits");
  }
  convergence_run_started_ = true;
  SpineSsspRunResult result;
  result.start_cycle = scheduler_.clock(clock_id_).completed_cycles;
  for (std::size_t round = 0; round < max_rounds; ++round) {
    const std::uint64_t start_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> attempted_active_in = current_frontier_;
    scheduler_.run_until([this] { return done() && idle(); },
                         max_events_per_round);
    if (recoverable_host_handoff()) {
      const std::uint64_t device_end_cycle =
          scheduler_.clock(clock_id_).completed_cycles;
      SpineSsspRoundEvidence device_attempt{
          .round = round,
          .active_in = attempted_active_in,
          .reader_sources = reader_->active_source_ids(),
          .active_out = compute_->next_active(),
          .reader = reader_->counters(),
          .compute = compute_->counters(),
          .edge_axis = edge_stream_.stats(),
          .value_axis = value_stream_.stats(),
          .start_cycle = start_cycle,
          .end_cycle = device_end_cycle,
      };
      const std::uint32_t fallback_reason =
          reader_->counters().range_task_fallback_reason;
      const std::vector<std::uint32_t> sources =
          restart_device_dirty_host_fallback();
      result.host_handoffs.push_back(SpineHostHandoffEvidence{
          .logical_round = round,
          .fallback_reason = fallback_reason,
          .source_count = sources.size(),
          .host_list_read_bytes =
              ((sources.size() + 3) / 4) * kSpineSortWordBytes,
          .host_control_cycles = 0,
          .host_control_timed = false,
          .device_attempt = std::move(device_attempt),
      });
      scheduler_.run_until([this] { return done() && idle(); },
                           max_events_per_round);
    }
    const std::uint64_t end_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> active_out = compute_->next_active();
    result.rounds.push_back(SpineSsspRoundEvidence{
        .round = round,
        .active_in = attempted_active_in,
        .reader_sources = reader_->active_source_ids(),
        .active_out = active_out,
        .reader = reader_->counters(),
        .compute = compute_->counters(),
        .edge_axis = edge_stream_.stats(),
        .value_axis = value_stream_.stats(),
        .start_cycle = start_cycle,
        .end_cycle = end_cycle,
    });
    if (failed()) {
      result.failed = true;
      break;
    }
    if (round == 0) {
      start_dirty_ack();
      scheduler_.run_until(
          [this] { return dirty_ack_->done() && idle(); },
          max_events_per_round);
      result.dirty_ack = dirty_ack_->counters();
      if (dirty_ack_->failed()) {
        result.failed = true;
        break;
      }
    }
    if (active_out.empty()) {
      result.converged = true;
      break;
    }
    if (round + 1 < max_rounds) {
      restart_read_compute(active_out);
    }
  }
  result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
  return result;
}

bool SpineVerticalSliceSystem::done() const noexcept {
  return maintenance_->done() && reader_->done() && compute_->done() &&
         (!dirty_ack_->started() || dirty_ack_->done());
}

bool SpineVerticalSliceSystem::failed() const noexcept {
  return maintenance_->failed() || reader_->failed() || compute_->failed() ||
         (dirty_ack_->started() && dirty_ack_->failed());
}

bool SpineVerticalSliceSystem::idle() const noexcept {
  for (const auto &port : graph_ports_) {
    if (!port->idle()) {
      return false;
    }
  }
  return sorted_->idle() && active_bins_->idle() && metadata_->idle() &&
         maintenance_result_->idle() && vertex_state_->idle() &&
         active_out_->idle() && compute_result_->idle() &&
         active_bitmap_->idle() && edge_stream_.empty() &&
         value_stream_.empty();
}

const SpineL0Counters &SpineVerticalSliceSystem::maintenance_counters()
    const noexcept {
  return maintenance_->counters();
}

const SpineReaderCounters &SpineVerticalSliceSystem::reader_counters()
    const noexcept {
  return reader_->counters();
}

std::vector<std::uint32_t> SpineVerticalSliceSystem::reader_source_ids() const {
  return reader_->active_source_ids();
}

const SpineComputeCounters &SpineVerticalSliceSystem::compute_counters()
    const noexcept {
  return compute_->counters();
}

const SpineDirtyAckCounters &SpineVerticalSliceSystem::dirty_ack_counters()
    const noexcept {
  return dirty_ack_->counters();
}

const SpineSplitSsspCompute &SpineVerticalSliceSystem::compute()
    const noexcept {
  return *compute_;
}

const SpineL0State &SpineVerticalSliceSystem::level_state() const noexcept {
  return state_;
}

const FifoStats &SpineVerticalSliceSystem::edge_stream_stats() const noexcept {
  return edge_stream_.stats();
}

const FifoStats &SpineVerticalSliceSystem::value_stream_stats() const noexcept {
  return value_stream_.stats();
}

const AxiConfig &
SpineVerticalSliceSystem::axi_config(SpineAxiPortKind kind) const {
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    return graph_ports_[0]->master().config();
  case SpineAxiPortKind::kSortedEdges:
    return sorted_->master().config();
  case SpineAxiPortKind::kActiveBins:
    return active_bins_->master().config();
  case SpineAxiPortKind::kMetadata:
    return metadata_->master().config();
  case SpineAxiPortKind::kMaintenanceResult:
    return maintenance_result_->master().config();
  case SpineAxiPortKind::kVertexState:
    return vertex_state_->master().config();
  case SpineAxiPortKind::kActiveOut:
    return active_out_->master().config();
  case SpineAxiPortKind::kActiveBitmap:
    return active_bitmap_->master().config();
  case SpineAxiPortKind::kComputeResult:
    return compute_result_->master().config();
  }
  throw std::logic_error("unknown Spine AXI port kind");
}

const AxiStats &
SpineVerticalSliceSystem::axi_stats(SpineAxiPortKind kind) const {
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    return graph_ports_[0]->master().stats();
  case SpineAxiPortKind::kSortedEdges:
    return sorted_->master().stats();
  case SpineAxiPortKind::kActiveBins:
    return active_bins_->master().stats();
  case SpineAxiPortKind::kMetadata:
    return metadata_->master().stats();
  case SpineAxiPortKind::kMaintenanceResult:
    return maintenance_result_->master().stats();
  case SpineAxiPortKind::kVertexState:
    return vertex_state_->master().stats();
  case SpineAxiPortKind::kActiveOut:
    return active_out_->master().stats();
  case SpineAxiPortKind::kActiveBitmap:
    return active_bitmap_->master().stats();
  case SpineAxiPortKind::kComputeResult:
    return compute_result_->master().stats();
  }
  throw std::logic_error("unknown Spine AXI port kind");
}

AxiStats SpineVerticalSliceSystem::maintenance_axi_stats() const noexcept {
  AxiStats total;
  for (const auto &port : graph_ports_) {
    accumulate_axi_stats(total, port->master().stats());
  }
  accumulate_axi_stats(total, sorted_->master().stats());
  accumulate_axi_stats(total, metadata_->master().stats());
  accumulate_axi_stats(total, maintenance_result_->master().stats());
  return total;
}

SpinePageRankVerticalSliceSystem::SpinePageRankVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, float damping,
    SpineL0Config maintenance_config, SpineAxiInterfaceProfile axi_profile,
    AlgorithmPipelineConfig pipeline_config,
    std::size_t compute_memory_request_window, SpineL0State initial_state,
    std::optional<SpineEdgeSlice> execution_graph,
    std::optional<SpineDirtyIdentity> host_coverage)
    : SpinePageRankVerticalSliceSystem(
          scheduler, clock_id, backend, workload,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = workload.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(maintenance_config), std::move(axi_profile),
          std::move(pipeline_config), compute_memory_request_window,
          std::move(initial_state), std::move(execution_graph),
          host_coverage) {}

SpinePageRankVerticalSliceSystem::SpinePageRankVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, GraphAlgorithmPolicy policy,
    SpineL0Config maintenance_config, SpineAxiInterfaceProfile axi_profile,
    AlgorithmPipelineConfig pipeline_config,
    std::size_t compute_memory_request_window, SpineL0State initial_state,
    std::optional<SpineEdgeSlice> execution_graph,
    std::optional<SpineDirtyIdentity> host_coverage)
    : scheduler_(scheduler),
      clock_id_(clock_id),
      backend_(backend),
      axi_profile_(std::move(axi_profile)),
      maintenance_config_(maintenance_config),
      edge_stream_("pagerank-edge-axis", clock_id, 32),
      value_stream_("pagerank-value-axis", clock_id, 32),
      state_(std::move(initial_state)) {
  const SpineEdgeSlice &logical_graph =
      execution_graph.has_value() ? *execution_graph : workload;
  if (logical_graph.vertices != workload.vertices ||
      policy.config().vertices != logical_graph.vertices ||
      (policy.config().kind != GraphAlgorithmKind::kFullPageRank &&
       policy.config().kind != GraphAlgorithmKind::kResidualPageRank)) {
    throw std::invalid_argument("invalid Spine PageRank system policy");
  }
  PageRankHostInput host =
      build_pagerank_host_input(logical_graph, maintenance_config);
  if (host_coverage.has_value()) {
    host.coverage = host_coverage;
  }
  active_bins_payload_ = host.bins;
  source_refresh_ = host.sources;
  host_coverage_ = host.coverage;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    graph_ports_[family] = make_port(
        "pagerank-graph" + std::to_string(family),
        static_cast<std::uint32_t>(family), family, SpineAxiPortKind::kGraph);
  }
  sorted_ = make_port("pagerank-sorted-edges", 16, 16,
                      SpineAxiPortKind::kSortedEdges);
  active_bins_ =
      make_port("pagerank-active-bins", 18, 18,
                SpineAxiPortKind::kActiveBins);
  metadata_ =
      make_port("pagerank-metadata", 20, 20, SpineAxiPortKind::kMetadata);
  maintenance_result_ = make_port("pagerank-maintenance-result", 21, 21,
                                  SpineAxiPortKind::kMaintenanceResult);
  vertex_state_ = make_port("pagerank-vertex-state", 117, 17,
                            SpineAxiPortKind::kVertexState);

  SpineL0Ports maintenance_ports;
  SpineReaderPorts reader_ports;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    maintenance_ports.graph[family] = graph_ports_[family].get();
    reader_ports.graph[family] = graph_ports_[family].get();
  }
  maintenance_ports.sorted_edges = sorted_.get();
  maintenance_ports.metadata = metadata_.get();
  maintenance_ports.result = maintenance_result_.get();
  reader_ports.task_scratch = sorted_.get();
  reader_ports.active_bins = active_bins_.get();
  reader_ports.metadata = metadata_.get();
  reader_ports.result = maintenance_result_.get();

  algorithm_policy_ =
      std::make_shared<const GraphAlgorithmPolicy>(std::move(policy));
  maintenance_ = std::make_unique<SpineL0Maintenance>(
      "pagerank-maintenance", clock_id_, std::move(maintenance_config),
      std::move(workload), maintenance_ports, state_);
  reader_ = std::make_unique<SpineSplitReader>(
      "pagerank-reader", clock_id_, *maintenance_, reader_ports, host.sources,
      edge_stream_, value_stream_, SpineReaderMode::kHostActive,
      algorithm_policy_);
  reader_->configure_initial_host_round(host.bins, host.coverage, host.sources);
  compute_ = std::make_unique<SpineSplitPageRankCompute>(
      "pagerank-compute", clock_id_, *algorithm_policy_, host.out_degrees,
      *vertex_state_, edge_stream_, value_stream_, pipeline_config,
      compute_memory_request_window);
}

std::unique_ptr<FixedAxiPort> SpinePageRankVerticalSliceSystem::make_port(
    const std::string &name, std::uint32_t initiator_id, std::size_t channel,
    SpineAxiPortKind kind) {
  return std::make_unique<FixedAxiPort>(
      name, clock_id_,
      axi_profile_.port_config(kind, 32, channel, initiator_id), backend_);
}

void SpinePageRankVerticalSliceSystem::register_components() {
  if (registered_) {
    throw std::logic_error("Spine PageRank system already registered");
  }
  registered_ = true;
  scheduler_.add_component(*maintenance_);
  scheduler_.add_component(*reader_);
  compute_->register_components(scheduler_);
  scheduler_.add_component(edge_stream_);
  scheduler_.add_component(value_stream_);
  for (auto &port : graph_ports_) {
    port->register_components(scheduler_);
  }
  sorted_->register_components(scheduler_);
  active_bins_->register_components(scheduler_);
  metadata_->register_components(scheduler_);
  maintenance_result_->register_components(scheduler_);
  vertex_state_->register_components(scheduler_);
}

void SpinePageRankVerticalSliceSystem::restart_iteration() {
  if (!registered_ || !done() || failed() || !idle()) {
    throw std::logic_error(
        "PageRank iteration restart requires a successful system drain");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  if (algorithm_policy_->config().kind ==
      GraphAlgorithmKind::kResidualPageRank) {
    source_refresh_ = compute_->next_active();
    if (source_refresh_.empty()) {
      throw std::logic_error("converged residual PageRank cannot restart");
    }
    active_bins_payload_ = build_host_active_bins(
        state_, maintenance_config_, source_refresh_, compute_->rank_words());
  }
  reader_->reset_host_round(active_bins_payload_, host_coverage_,
                            source_refresh_);
  compute_->reset_iteration();
}

bool SpinePageRankVerticalSliceSystem::maintenance_done() const noexcept {
  return maintenance_->done();
}

bool SpinePageRankVerticalSliceSystem::done() const noexcept {
  return maintenance_->done() && reader_->done() && compute_->done();
}

bool SpinePageRankVerticalSliceSystem::failed() const noexcept {
  return maintenance_->failed() || reader_->failed() || compute_->failed();
}

std::string SpinePageRankVerticalSliceSystem::failure() const {
  if (maintenance_->failed()) {
    return "maintenance: " + maintenance_->failure();
  }
  if (reader_->failed()) {
    return "reader: " + reader_->failure();
  }
  if (compute_->failed()) {
    return "compute: protocol or memory failure";
  }
  return {};
}

bool SpinePageRankVerticalSliceSystem::idle() const noexcept {
  for (const auto &port : graph_ports_) {
    if (!port->idle()) {
      return false;
    }
  }
  return sorted_->idle() && active_bins_->idle() && metadata_->idle() &&
         maintenance_result_->idle() && vertex_state_->idle() &&
         edge_stream_.empty() && value_stream_.empty();
}

const SpineL0Counters &
SpinePageRankVerticalSliceSystem::maintenance_counters() const noexcept {
  return maintenance_->counters();
}

const SpineReaderCounters &
SpinePageRankVerticalSliceSystem::reader_counters() const noexcept {
  return reader_->counters();
}

const SpinePageRankCounters &
SpinePageRankVerticalSliceSystem::compute_counters() const noexcept {
  return compute_->counters();
}

const SpineSplitPageRankCompute &
SpinePageRankVerticalSliceSystem::compute() const noexcept {
  return *compute_;
}

const SpineL0State &
SpinePageRankVerticalSliceSystem::level_state() const noexcept {
  return state_;
}

const FifoStats &
SpinePageRankVerticalSliceSystem::edge_stream_stats() const noexcept {
  return edge_stream_.stats();
}

const FifoStats &
SpinePageRankVerticalSliceSystem::value_stream_stats() const noexcept {
  return value_stream_.stats();
}

} // namespace spine::sim
