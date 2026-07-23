#include "spine_sim/spine_system.hpp"

#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace spine::sim {

SpineVerticalSliceSystem::SpineVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, std::uint32_t source, std::size_t tiny_threshold,
    SpineL0Config maintenance_config, SpineL0State initial_state)
    : scheduler_(scheduler),
      clock_id_(clock_id),
      backend_(backend),
      edge_stream_("edge-axis", clock_id, 32),
      value_stream_("value-axis", clock_id, 32),
      state_(std::move(initial_state)),
      current_frontier_{source} {
  if (source >= workload.vertices) {
    throw std::invalid_argument("Spine vertical-slice source is out of range");
  }
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    graph_ports_[family] =
        make_port("graph" + std::to_string(family),
                  static_cast<std::uint32_t>(family), family);
  }
  sorted_ = make_port("sorted-edges", 16, 16);
  active_bins_ = make_port("active-bins", 18, 18);
  metadata_ = make_port("metadata", 20, 20);
  maintenance_result_ = make_port("maintenance-result", 21, 21);

  // Compute is a separate CU, so initiator IDs differ even when a pseudo-
  // channel is shared with the fused read-maintenance CU.
  vertex_state_ = make_port("vertex-state", 117, 17);
  active_out_ = make_port("active-out", 119, 19);
  compute_result_ = make_port("compute-result", 121, 21);
  active_bitmap_ = make_port("active-bitmap", 122, 22);

  SpineL0Ports maintenance_ports;
  SpineReaderPorts reader_ports;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    maintenance_ports.graph[family] = graph_ports_[family].get();
    reader_ports.graph[family] = graph_ports_[family].get();
  }
  maintenance_ports.sorted_edges = sorted_.get();
  maintenance_ports.metadata = metadata_.get();
  maintenance_ports.result = maintenance_result_.get();
  reader_ports.active_bins = active_bins_.get();
  reader_ports.metadata = metadata_.get();

  const std::size_t vertices = workload.vertices;
  maintenance_ = std::make_unique<SpineL0Maintenance>(
      "spine-l0-maintenance", clock_id_, std::move(maintenance_config),
      std::move(workload), maintenance_ports, state_);
  reader_ = std::make_unique<SpineSplitReader>(
      "spine-split-reader", clock_id_, *maintenance_, state_, reader_ports,
      std::vector<std::uint32_t>{source}, edge_stream_, value_stream_);
  compute_ = std::make_unique<SpineSplitSsspCompute>(
      "spine-split-compute", clock_id_, vertices, source, tiny_threshold,
      SpineComputePorts{
          .vertex_state = vertex_state_.get(),
          .active_out = active_out_.get(),
          .active_bitmap = active_bitmap_.get(),
          .result = compute_result_.get(),
      },
      edge_stream_, value_stream_);
}

std::unique_ptr<FixedAxiPort> SpineVerticalSliceSystem::make_port(
    const std::string &name, std::uint32_t initiator_id, std::size_t channel) {
  return std::make_unique<FixedAxiPort>(name, clock_id_,
                                        FixedAxiPortConfig{
                                            .memory_channels = 32,
                                            .channel = channel,
                                            .initiator_id = initiator_id,
                                        },
                                        backend_);
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
    std::vector<std::uint32_t> active_sources) {
  if (!registered_ || !done() || !idle() || failed() ||
      active_sources.empty()) {
    throw std::logic_error(
        "Spine read/compute restart requires a successful drained round");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  reader_->reset_round(active_sources);
  compute_->reset_round();
  current_frontier_ = std::move(active_sources);
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
    scheduler_.run_until([this] { return done() && idle(); },
                         max_events_per_round);
    const std::uint64_t end_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> active_out = compute_->next_active();
    result.rounds.push_back(SpineSsspRoundEvidence{
        .round = round,
        .active_in = current_frontier_,
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
  return maintenance_->done() && reader_->done() && compute_->done();
}

bool SpineVerticalSliceSystem::failed() const noexcept {
  return maintenance_->failed() || reader_->failed() || compute_->failed();
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

const SpineComputeCounters &SpineVerticalSliceSystem::compute_counters()
    const noexcept {
  return compute_->counters();
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

}  // namespace spine::sim
