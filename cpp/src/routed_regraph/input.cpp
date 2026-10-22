#include "../detail/routed_regraph_input.hpp"

namespace spine::sim::detail {

RoutedPmaInput::RoutedPmaInput(std::string name, ClockId clock,
    const RoutedReGraphConfig& config, FixedAxiPort& memory, Fifo<ReGraphPmaPacket>& output,
    FixedAxiPort* odd_memory, FixedAxiPort* directory_memory)
    : Component(name, clock), memory_(memory), odd_memory_(odd_memory),
      directory_memory_(directory_memory), output_(output),
      read_delay_(config.adapter.read_pipeline_cycles),
      pipeline_capacity_(config.input_path == RoutedInputPath::kDualPrefetchElasticExperimental ||
                         config.input_path == RoutedInputPath::kTriplePrefetchElasticExperimental ? 3 : 2),
      segments_(name + "-segments", clock, 16) {
  if ((odd_memory_ != nullptr) !=
      (config.input_path == RoutedInputPath::kDualPrefetchElasticExperimental ||
       config.input_path == RoutedInputPath::kTriplePrefetchElasticExperimental) ||
      (directory_memory_ != nullptr) !=
      (config.input_path == RoutedInputPath::kTriplePrefetchElasticExperimental))
    throw std::invalid_argument("experimental input topology requires its explicit physical ports");
  if (config.input_path == RoutedInputPath::kPhysicalSlots)
    legacy_ = std::make_unique<ReGraphPmaAdapter>(std::move(name), clock, config.adapter, memory, output);
}

bool RoutedPmaInput::done() const noexcept {
  return legacy_ ? legacy_->done() :
      (!reader_ || (reader_->done() && compactor_->done() && segments_.empty()));
}

void RoutedPmaInput::start_partition(ReGraphPmaPartition partition) {
  if (legacy_) { legacy_->start_partition(partition); return; }
  if (!done() || !memory_.idle() || (odd_memory_ && !odd_memory_->idle()) ||
      (directory_memory_ && !directory_memory_->idle()))
    throw std::logic_error("prefetch input restart requires drained finite state and AXI");
  completed_ = counters();
  reader_ = std::make_unique<prefetch_compact::Reader>(clock_id(), memory_, segments_, partition,
      read_delay_, odd_memory_, prefetch_compact::RefillPolicy::kAvailableSpace, pipeline_capacity_,
      directory_memory_);
  compactor_ = std::make_unique<prefetch_compact::Compactor>(clock_id(), segments_, output_,
                                                         partition.destination_vertices, pipeline_capacity_);
}

ReGraphPmaAdapterCounters RoutedPmaInput::counters() const {
  if (legacy_) return legacy_->counters();
  auto result = completed_;
  if (!reader_) return result;
  const auto& r = reader_->stats();
  const auto& c = compactor_->stats();
  // Read counters are physical cache lines; packet dummies are post-compaction.
  result.extent_reads += r.extent_beats;
  result.row_reads += r.directory_beats;
  result.segment_reads += r.pma_beats;
  result.rows_visited += r.rows;
  result.empty_rows += r.empty_rows;
  result.responses += r.responses;
  result.packets += c.packets;
  result.live_edges += c.live_edges;
  result.dummy_edges += c.output_dummy;
  result.output_stalls += r.output_stalls + c.output_stalls;
  result.max_pending_reads = std::max(result.max_pending_reads, r.max_parents);
  result.max_buffered_segments = std::max(result.max_buffered_segments, r.max_bank_lines * 2);
  return result;
}

void RoutedPmaInput::evaluate(const CycleContext& context) {
  if (legacy_) { legacy_->evaluate(context); return; }
  if (reader_) { reader_->evaluate(context); compactor_->evaluate(context); }
}

void RoutedPmaInput::commit(const CycleContext& context) {
  if (legacy_) { legacy_->commit(context); return; }
  if (reader_) { reader_->commit(context); compactor_->commit(context); }
  // This internal SPSC FIFO is committed once, after both evaluate phases.
  segments_.commit(context);
}

}  // namespace spine::sim::detail
