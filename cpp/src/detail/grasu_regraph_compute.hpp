#pragma once

#include "grasu_regraph_streams.hpp"
#include "spine_sim/axi_endpoint.hpp"

namespace spine::sim::detail {

class ReGraphGatherEngine : public Component {
public:
  using Component::Component;
  virtual void start_partition(std::size_t vertices, bool reset) = 0;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t slots_scanned() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t batches_scanned() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t live_edges() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t active_edges() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t reset_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t merge_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t pipeline_drain_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t output_stall_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t rows_emitted() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t conflict_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t bank_updates() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t bypass_hits() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t bypass_misses() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t cross_bank_reductions() const noexcept = 0;
};

class ReGraphMergerEngine : public Component {
public:
  using Component::Component;
  virtual void start_round() = 0;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t rows_consumed() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t bursts_emitted() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t output_stall_cycles() const noexcept = 0;
};

class ReGraphApplyEngine : public Component {
public:
  using Component::Component;
  virtual void start_partition(std::uint64_t round, std::size_t base,
                               std::size_t vertices, bool reset_totals) = 0;
  virtual void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) = 0;
  virtual void unbind_done_notifier(void *owner) noexcept = 0;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual std::size_t active_vertices() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t reads() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t writes() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t input_bursts() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t output_stall_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t total_activated() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t read_window_stalls() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t pipeline_capacity_stalls() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t write_window_stalls() const noexcept = 0;
  [[nodiscard]] virtual std::size_t max_reads_inflight() const noexcept = 0;
  [[nodiscard]] virtual std::size_t max_pipeline_occupancy() const noexcept = 0;
  [[nodiscard]] virtual std::size_t max_writes_inflight() const noexcept = 0;
  [[nodiscard]] virtual float iteration_error() const noexcept = 0;
  [[nodiscard]] virtual float next_dangling() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t degree_reads() const noexcept = 0;
};

class ReGraphWritebackEngine : public Component {
public:
  using Component::Component;
  virtual void start_partition(std::uint64_t round, std::size_t base) = 0;
  virtual void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) = 0;
  virtual void unbind_done_notifier(void *owner) noexcept = 0;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t input_bursts() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_writes() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t pipeline_capacity_stalls() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t write_window_stalls() const noexcept = 0;
  [[nodiscard]] virtual std::size_t max_pipeline_occupancy() const noexcept = 0;
  [[nodiscard]] virtual std::size_t max_writes_inflight() const noexcept = 0;
};

std::unique_ptr<ReGraphGatherEngine> make_regraph_gather(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<PmaEdgeBatch> &input,
    Fifo<ReGraphGatherRow> &output, ReGraphReaderContext &reader);
std::unique_ptr<ReGraphMergerEngine> make_regraph_merger(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    Fifo<ReGraphGatherRow> &input, Fifo<ReGraphMergedBurst> &output);

struct ReGraphApplyPorts {
  AxiEndpoint read;
  AxiEndpoint write;
  std::optional<AxiEndpoint> degree;
  std::optional<AxiEndpoint> auxiliary_read;
  std::optional<AxiEndpoint> auxiliary_write;
};

std::unique_ptr<ReGraphApplyEngine> make_regraph_apply(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<ReGraphMergedBurst> &input,
    Fifo<ReGraphAppliedBurst> &output, ReGraphApplyPorts ports,
    const ReGraphReaderContext &context);
std::unique_ptr<ReGraphApplyEngine> make_regraph_apply(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<ReGraphMergedBurst> &input,
    Fifo<ReGraphAppliedBurst> &output, FixedAxiPort &read, FixedAxiPort &write,
    FixedAxiPort *degree, const ReGraphReaderContext &context,
    FixedAxiPort *auxiliary_read = nullptr, FixedAxiPort *auxiliary_write = nullptr);
std::unique_ptr<ReGraphWritebackEngine> make_regraph_writeback(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    GraphAlgorithmPolicy policy, Fifo<ReGraphAppliedBurst> &input,
    AxiEndpoint primary, AxiEndpoint mirror);
std::unique_ptr<ReGraphWritebackEngine> make_regraph_writeback(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    GraphAlgorithmPolicy policy, Fifo<ReGraphAppliedBurst> &input,
    FixedAxiPort &primary, FixedAxiPort &mirror);

} // namespace spine::sim::detail
