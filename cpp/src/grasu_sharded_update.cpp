#include "spine_sim/grasu_regraph.hpp"

#include "spine_sim/grasu_native.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim {

class GraSuShardedPmaUpdateSystem::Impl {
public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPartitionedPmaLayout layout, std::vector<GraSuEdge> updates,
       GraSuNativeConfig config, std::size_t runtime_channel_capacity_bytes)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), config_(config),
        start_cycle_(scheduler.clock(clock_id).completed_cycles) {
    updates_by_shard_.resize(layout_.partitions.size());
    for (const GraSuEdge &edge : updates) {
      updates_by_shard_.at(layout_.partition_for_destination(edge.destination))
          .push_back(edge);
    }
    std::vector<std::size_t> counts;
    counts.reserve(updates_by_shard_.size());
    for (const auto &shard_updates : updates_by_shard_) {
      counts.push_back(shard_updates.size());
    }
    runtime_plan_ = build_grasu_regraph_runtime_plan(
        layout_, counts, config_.cache_segments_per_half,
        kGraSuReGraphU55cGraphChannels, runtime_channel_capacity_bytes);
    if (config_.maintain_out_degree && config_.initialize_degree_payload) {
      initialize_degree_payload();
    }
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error(
          "sharded GraSU update engine registered more than once");
    }
    registered_ = true;
    launch_next_shard();
  }

  void unregister_components() {
    if (!registered_ || !done()) {
      throw std::logic_error(
          "sharded GraSU update engine can only unregister after completion");
    }
    registered_ = false;
  }

  bool advance_if_complete() {
    if (!registered_ || current_ == nullptr || current_->failed() ||
        !current_->done() || backend_.outstanding() != 0) {
      return false;
    }
    merge_counters(current_->counters());
    const GraSuPartitionedPmaLayout materialized =
        current_->materialized_partitioned_layout();
    layout_.partitions.at(current_shard_) = materialized.partitions.front();
    current_->unregister_components();
    current_.reset();
    ++current_shard_;
    launch_next_shard();
    return true;
  }

  [[nodiscard]] bool done() const noexcept {
    return registered_ && current_ == nullptr &&
           current_shard_ >= updates_by_shard_.size();
  }

  [[nodiscard]] bool failed() const noexcept {
    return current_ != nullptr && current_->failed();
  }

  [[nodiscard]] const std::string &failure() const noexcept {
    if (current_ != nullptr) {
      return current_->failure();
    }
    static const std::string empty;
    return empty;
  }

  [[nodiscard]] GraSuUpdateCounters counters() const {
    GraSuUpdateCounters result = completed_counters_;
    if (current_ != nullptr) {
      merge_counters_into(result, current_->counters());
    }
    result.start_cycle = start_cycle_;
    result.end_cycle =
        done() ? end_cycle_ : scheduler_.clock(clock_id_).completed_cycles;
    return result;
  }

  [[nodiscard]] std::vector<GraSuEdge> live_edges() const {
    return layout_.live_edges();
  }

  [[nodiscard]] GraSuPartitionedPmaLayout
  materialized_partitioned_layout() const {
    return layout_;
  }

  [[nodiscard]] const GraSuReGraphRuntimePlan &runtime_plan() const noexcept {
    return runtime_plan_;
  }

private:
  void initialize_degree_payload() {
    std::vector<std::uint32_t> degrees(layout_.vertices);
    for (const GraSuEdge &edge : layout_.live_edges()) {
      ++degrees.at(edge.source);
    }
    std::vector<std::uint8_t> bytes;
    bytes.reserve(degrees.size() * sizeof(std::uint32_t));
    for (const std::uint32_t degree : degrees) {
      for (std::size_t byte = 0; byte < sizeof(degree); ++byte) {
        bytes.push_back(static_cast<std::uint8_t>(degree >> (byte * 8)));
      }
    }
    backend_.initialize_payload(config_.degree_channel, config_.degree_base,
                                bytes);
  }

  void launch_next_shard() {
    while (current_shard_ < updates_by_shard_.size() &&
           updates_by_shard_[current_shard_].empty()) {
      ++current_shard_;
    }
    if (current_shard_ >= updates_by_shard_.size()) {
      end_cycle_ = scheduler_.clock(clock_id_).completed_cycles;
      return;
    }

    GraSuNativeConfig shard_config = config_;
    shard_config.explicit_runtime_regions = true;
    shard_config.packed_partition_addresses = false;
    shard_config.initialize_degree_payload = false;
    shard_config.initiator_base =
        static_cast<std::uint32_t>(10'000 + current_shard_ * 32);
    const std::string row_name = "row";
    const std::string binary_name = "binary";
    const GraSuReGraphBufferRegion &row = find_grasu_regraph_runtime_region(
        runtime_plan_, current_shard_, row_name);
    const GraSuReGraphBufferRegion &binary = find_grasu_regraph_runtime_region(
        runtime_plan_, current_shard_, binary_name);
    shard_config.row_offset_base = row.channel_offset_bytes;
    shard_config.binary_base = binary.channel_offset_bytes;
    shard_config.row_channels.fill(row.channel);
    shard_config.binary_channels.fill(binary.channel);
    for (std::size_t lane = 0; lane < 4; ++lane) {
      const std::string update_name = "update" + std::to_string(lane);
      const std::string pma_name = "pma" + std::to_string(lane);
      const GraSuReGraphBufferRegion &update =
          find_grasu_regraph_runtime_region(runtime_plan_, current_shard_,
                                            update_name);
      const GraSuReGraphBufferRegion &pma = find_grasu_regraph_runtime_region(
          runtime_plan_, current_shard_, pma_name);
      shard_config.update_channels[lane] = update.channel;
      shard_config.update_bases[lane] = update.channel_offset_bytes;
      shard_config.pma_channels[lane] = pma.channel;
      shard_config.pma_bases[lane] = pma.channel_offset_bytes;
    }
    shard_config.pma_base = shard_config.pma_bases[0];
    current_ = std::make_unique<GraSuPmaUpdateSystem>(
        scheduler_, clock_id_, backend_, layout_.partitions[current_shard_],
        updates_by_shard_[current_shard_], shard_config);
    current_->register_components();
  }

  static void merge_counters_into(GraSuUpdateCounters &target,
                                  const GraSuUpdateCounters &source) {
#define SUM_COUNTER(field) target.field += source.field
    SUM_COUNTER(updates);
    target.update_record_bytes =
        std::max(target.update_record_bytes, source.update_record_bytes);
    SUM_COUNTER(destination_partitions_touched);
    SUM_COUNTER(touched_shard_pma_slots);
    target.max_touched_shard_pma_slots = std::max(
        target.max_touched_shard_pma_slots,
        source.max_touched_shard_pma_slots);
    SUM_COUNTER(partition_routes);
    SUM_COUNTER(inserts);
    SUM_COUNTER(deletes);
    SUM_COUNTER(weight_decreases);
    SUM_COUNTER(weight_increases);
    SUM_COUNTER(row_reads);
    SUM_COUNTER(binary_probes);
    SUM_COUNTER(cache_updates);
    SUM_COUNTER(ddr_updates);
    SUM_COUNTER(pma_reads);
    SUM_COUNTER(pma_writes);
    SUM_COUNTER(degree_reads);
    SUM_COUNTER(degree_writes);
    SUM_COUNTER(update_read_bytes);
    SUM_COUNTER(row_read_bytes);
    SUM_COUNTER(binary_read_bytes);
    SUM_COUNTER(pma_read_bytes);
    SUM_COUNTER(pma_write_bytes);
    SUM_COUNTER(degree_read_bytes);
    SUM_COUNTER(degree_write_bytes);
    SUM_COUNTER(degree_fifo_stalls);
    target.degree_fifo_max_occupancy = std::max(
        target.degree_fifo_max_occupancy, source.degree_fifo_max_occupancy);
    target.degree_reorder_max_occupancy =
        std::max(target.degree_reorder_max_occupancy,
                 source.degree_reorder_max_occupancy);
    SUM_COUNTER(axi_request_fifo_stalls);
    SUM_COUNTER(axi_backend_submit_stalls);
    SUM_COUNTER(axis_push_stalls);
    SUM_COUNTER(lane_queue_stalls);
#undef SUM_COUNTER
  }

  void merge_counters(const GraSuUpdateCounters &source) {
    merge_counters_into(completed_counters_, source);
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPartitionedPmaLayout layout_;
  GraSuNativeConfig config_;
  std::vector<std::vector<GraSuEdge>> updates_by_shard_;
  GraSuReGraphRuntimePlan runtime_plan_;
  std::unique_ptr<GraSuPmaUpdateSystem> current_;
  std::size_t current_shard_{};
  GraSuUpdateCounters completed_counters_;
  std::uint64_t start_cycle_{};
  std::uint64_t end_cycle_{};
  bool registered_{};
};

GraSuShardedPmaUpdateSystem::GraSuShardedPmaUpdateSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::vector<GraSuEdge> updates,
    GraSuNativeConfig config, std::size_t runtime_channel_capacity_bytes)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend,
                                   std::move(layout), std::move(updates),
                                   config, runtime_channel_capacity_bytes)) {}

GraSuShardedPmaUpdateSystem::~GraSuShardedPmaUpdateSystem() = default;

void GraSuShardedPmaUpdateSystem::register_components() {
  impl_->register_components();
}

void GraSuShardedPmaUpdateSystem::unregister_components() {
  impl_->unregister_components();
}

bool GraSuShardedPmaUpdateSystem::advance_if_complete() {
  return impl_->advance_if_complete();
}

bool GraSuShardedPmaUpdateSystem::done() const noexcept {
  return impl_->done();
}

bool GraSuShardedPmaUpdateSystem::failed() const noexcept {
  return impl_->failed();
}

const std::string &GraSuShardedPmaUpdateSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuUpdateCounters GraSuShardedPmaUpdateSystem::counters() const {
  return impl_->counters();
}

std::vector<GraSuEdge> GraSuShardedPmaUpdateSystem::live_edges() const {
  return impl_->live_edges();
}

GraSuPartitionedPmaLayout
GraSuShardedPmaUpdateSystem::materialized_partitioned_layout() const {
  return impl_->materialized_partitioned_layout();
}

const GraSuReGraphRuntimePlan &
GraSuShardedPmaUpdateSystem::runtime_plan() const noexcept {
  return impl_->runtime_plan();
}

} // namespace spine::sim
