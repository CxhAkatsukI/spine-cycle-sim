#include "../detail/routed_regraph_transport.hpp"

namespace spine::sim::detail {
namespace { constexpr std::size_t kRowsPerPartition = 65536 / 2; }

RoutedGatherMux::RoutedGatherMux(std::string name, ClockId clock,
    std::array<Fifo<ReGraphGatherRow> *, 4> inputs,
    Fifo<ReGraphGatherRow> &output, std::size_t partitions, bool ready_bursts)
    : Component(std::move(name), clock), inputs_(inputs), output_(output), partitions_(partitions),
      ready_bursts_(ready_bursts) {
  if (!partitions || std::any_of(inputs.begin(), inputs.end(),
      [clock](auto *fifo) { return !fifo || fifo->clock_id() != clock; }))
    throw std::invalid_argument("invalid routed Gather mux shape");
}

void RoutedGatherMux::start_round() {
  if (started_ && !done()) throw std::logic_error("routed mux restarted while busy");
  partition_ = local_row_ = 0;
  round_rows_ = next_worker_ = 0;
  worker_partitions_ = {0, 1, 2, 3};
  worker_rows_.fill(0);
  locked_worker_.reset();
  started_ = true;
}

void RoutedGatherMux::evaluate(const CycleContext &) {
  staged_ = false;
  if (!started_ || done()) return;
  auto worker = partition_ % 4;
  if (ready_bursts_) {
    if (locked_worker_) worker = *locked_worker_;
    else {
      std::optional<std::size_t> ready;
      for (std::size_t i = 0; i < 4 && !ready; ++i) {
        const auto candidate = (next_worker_ + i) % 4;
        if (worker_partitions_[candidate] < partitions_ && inputs_[candidate]->front())
          ready = candidate;
      }
      if (!ready) return;
      worker = *ready;
    }
  }
  const auto *front = inputs_[worker]->front();
  if (!front) return;
  const auto local = ready_bursts_ ? worker_rows_[worker] : local_row_;
  const auto partition = ready_bursts_ ? worker_partitions_[worker] : partition_;
  if (front->row != local) throw std::logic_error("routed Gather row out of partition order");
  auto row = *front;
  row.row += partition * kRowsPerPartition;
  if (!output_.try_push(row)) return;
  ReGraphGatherRow consumed;
  if (!inputs_[worker]->try_pop(consumed)) throw std::logic_error("routed Gather row disappeared");
  staged_worker_ = worker;
  staged_ = true;
}

void RoutedGatherMux::commit(const CycleContext &) {
  if (!staged_) return;
  ++rows_;
  ++round_rows_;
  if (!ready_bursts_) {
    if (++local_row_ == kRowsPerPartition) { local_row_ = 0; ++partition_; }
    return;
  }
  auto& local = worker_rows_[staged_worker_];
  if (++local == kRowsPerPartition) {
    local = 0;
    worker_partitions_[staged_worker_] += 4;
  }
  if (local % 8) locked_worker_ = staged_worker_;
  else { locked_worker_.reset(); next_worker_ = (staged_worker_ + 1) % 4; }
}

RoutedStatusWriter::RoutedStatusWriter(std::string name, ClockId clock,
    AxiEndpoint memory, std::size_t channel, std::uint64_t address)
    : Component(std::move(name), clock), memory_(memory), channel_(channel), address_(address) {
  if (address % 4) throw std::invalid_argument("routed status is not word aligned");
}

void RoutedStatusWriter::start(std::uint32_t active) {
  if (phase_ != Phase::kIdle && phase_ != Phase::kDone)
    throw std::logic_error("routed status restarted while busy");
  active_ = active;
  phase_ = Phase::kIssue;
}

void RoutedStatusWriter::evaluate(const CycleContext &) {
  staged_ = false;
  if (phase_ == Phase::kIssue) {
    std::vector<std::uint8_t> bytes(4);
    for (std::size_t i = 0; i < 4; ++i) bytes[i] = active_ >> (i * 8);
    staged_ = memory_.requests().try_push(AxiRequest{.transaction_id = id_,
        .operation = MemoryOperation::kWrite, .address = address_, .bytes = 4,
        .target_channel = channel_, .write_data = std::move(bytes)});
  } else if (phase_ == Phase::kWait) {
    AxiResponse response;
    if (!memory_.responses().try_pop(response)) return;
    if (response.transaction_id != id_ || !response.success || response.operation != MemoryOperation::kWrite)
      throw std::logic_error("invalid routed status write acknowledgement");
    staged_ = true;
  }
}

void RoutedStatusWriter::commit(const CycleContext &) {
  if (!staged_) return;
  if (phase_ == Phase::kIssue) { phase_ = Phase::kWait; ++writes_; }
  else { phase_ = Phase::kDone; ++id_; }
}

} // namespace spine::sim::detail
