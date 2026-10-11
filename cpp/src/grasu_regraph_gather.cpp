#include "detail/grasu_regraph_compute.hpp"

#include <cmath>
#include <deque>
#include <limits>
#include <unordered_map>
#include <utility>

namespace spine::sim::detail {
namespace {

class ReGraphGather final : public ReGraphGatherEngine {
public:
  ReGraphGather(std::string name, ClockId clock_id, std::size_t vertices,
                GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                Fifo<PmaEdgeBatch> &input, Fifo<ReGraphGatherRow> &output,
                ReGraphReaderContext &reader)
      : ReGraphGatherEngine(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), reader_(reader), bank_rows_(config.gather_banks),
        bypass_(config.gather_banks,
                std::vector<BypassEntry>(config.gather_bypass_distance + 1)) {
    input_.bind_nonempty_notifier(this, &ReGraphGather::notify_input_nonempty);
    output_.bind_nonfull_notifier(this, &ReGraphGather::notify_output_nonfull);
    reader_.bind_done_notifier(this, &ReGraphGather::notify_reader_done);
    refresh_evaluate_ready();
  }

  ~ReGraphGather() override {
    input_.unbind_nonempty_notifier(this);
    output_.unbind_nonfull_notifier(this);
    reader_.unbind_done_notifier(this);
  }

  void start_partition(std::size_t destination_vertices, bool reset_tmp_prop) override {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("ReGraph gather round started while busy");
    }
    destination_vertices_ = destination_vertices;
    for (auto &rows : bank_rows_) {
      rows.clear();
    }
    for (auto &entries : bypass_) {
      std::fill(entries.begin(), entries.end(), BypassEntry{});
    }
    pending_physical_writes_.clear();
    if (reset_tmp_prop) {
      remaining_ = divide_ceil(config_.partition_vertices,
                               config_.gather_vertices_per_reset_cycle);
      phase_ = Phase::kReset;
    } else {
      remaining_ = 0;
      phase_ = Phase::kScan;
    }
    drain_cycles_remaining_ = 0;
    next_output_row_ = 0;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept override { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t slots_scanned() const noexcept override {
    return slots_scanned_;
  }
  [[nodiscard]] std::uint64_t batches_scanned() const noexcept override {
    return batches_scanned_;
  }
  [[nodiscard]] std::uint64_t live_edges() const noexcept override {
    return live_edges_;
  }
  [[nodiscard]] std::uint64_t active_edges() const noexcept override {
    return active_edges_;
  }
  [[nodiscard]] std::uint64_t reset_cycles() const noexcept override {
    return reset_cycles_;
  }
  [[nodiscard]] std::uint64_t merge_cycles() const noexcept override {
    return merge_cycles_;
  }
  [[nodiscard]] std::uint64_t pipeline_drain_cycles() const noexcept override {
    return pipeline_drain_cycles_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept override {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t rows_emitted() const noexcept override {
    return rows_emitted_;
  }
  [[nodiscard]] std::uint64_t conflict_cycles() const noexcept override { return 0; }
  [[nodiscard]] std::uint64_t bank_updates() const noexcept override {
    return bank_updates_;
  }
  [[nodiscard]] std::uint64_t bypass_hits() const noexcept override {
    return bypass_hits_;
  }
  [[nodiscard]] std::uint64_t bypass_misses() const noexcept override {
    return bypass_misses_;
  }
  [[nodiscard]] std::uint64_t cross_bank_reductions() const noexcept override {
    return cross_bank_reductions_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return staged_tick_ || staged_start_drain_ || staged_output_stall_ ||
           staged_row_output_ || staged_batch_.has_value();
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_output_stalls(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_tick_ = false;
    staged_start_drain_ = false;
    staged_output_stall_ = false;
    staged_row_output_ = false;
    staged_batch_.reset();
    staged_cross_bank_reductions_ = 0;
    switch (phase_) {
    case Phase::kReset:
      staged_tick_ = remaining_ != 0;
      break;
    case Phase::kMerge: {
      ReGraphGatherRow row{.row = next_output_row_};
      for (std::size_t half = 0; half < row.candidates.size(); ++half) {
        const std::size_t vertex = next_output_row_ * 2 + half;
        if (vertex >= destination_vertices_) {
          continue;
        }
        for (const auto &bank : bank_rows_) {
          const auto found = bank.find(next_output_row_);
          if (found == bank.end() || !found->second[half].has_value()) {
            continue;
          }
          if (row.candidates[half].has_value()) {
            ++staged_cross_bank_reductions_;
          }
          row.candidates[half] =
              policy_.reduce(row.candidates[half], *found->second[half]);
        }
      }
      staged_row_output_ = output_.try_push(std::move(row));
      staged_output_stall_ = !staged_row_output_;
      break;
    }
    case Phase::kScan:
      if (input_.front() != nullptr) {
        PmaEdgeBatch batch;
        if (input_.try_pop(batch)) {
          staged_batch_ = batch;
        }
      } else if (reader_.done()) {
        staged_start_drain_ = true;
      }
      break;
    case Phase::kDrain:
      staged_tick_ = true;
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
    set_latched_commit_ready(commit_ready());
    refresh_evaluate_ready();
  }

  void commit(const CycleContext &context) override {
    commit_physical_writes(context.domain_cycle);
    if (phase_ == Phase::kReset && staged_tick_) {
      --remaining_;
      ++reset_cycles_;
      if (remaining_ == 0) {
        phase_ = Phase::kScan;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ == Phase::kMerge) {
      if (staged_output_stall_) {
        ++output_stall_cycles_;
        suspended_output_stall_ = true;
      }
      if (!staged_row_output_) {
        clear_staged();
        refresh_evaluate_ready();
        return;
      }
      cross_bank_reductions_ += staged_cross_bank_reductions_;
      for (auto &bank : bank_rows_) {
        bank.erase(next_output_row_);
      }
      ++next_output_row_;
      ++rows_emitted_;
      ++merge_cycles_;
      if (next_output_row_ ==
          divide_ceil(config_.partition_vertices,
                      config_.gather_vertices_per_merge_cycle)) {
        phase_ = Phase::kDone;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ == Phase::kDrain && staged_tick_) {
      if (drain_cycles_remaining_ != 0) {
        --drain_cycles_remaining_;
        ++pipeline_drain_cycles_;
      }
      if (drain_cycles_remaining_ == 0) {
        if (!pending_physical_writes_.empty()) {
          throw std::logic_error(
              "ReGraph gather pipeline drained before URAM writes committed");
        }
        next_output_row_ = 0;
        phase_ = Phase::kMerge;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ != Phase::kScan) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_batch_.has_value()) {
      consume_batch(*staged_batch_, context.domain_cycle);
      staged_batch_.reset();
    }
    if (staged_start_drain_) {
      drain_cycles_remaining_ = config_.gather_pipeline_latency - 1;
      if (drain_cycles_remaining_ == 0) {
        next_output_row_ = 0;
        phase_ = Phase::kMerge;
      } else {
        phase_ = Phase::kDrain;
      }
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  enum class Phase { kIdle, kReset, kScan, kDrain, kMerge, kDone };

  using GatherRow = std::array<std::optional<std::uint32_t>, 2>;

  struct BypassEntry {
    std::size_t row{};
    GatherRow value{};
    bool valid{};
  };

  struct PendingPhysicalWrite {
    std::size_t bank{};
    std::size_t row{};
    GatherRow value{};
    std::uint64_t due_cycle{};
  };

  static std::size_t divide_ceil(std::size_t value, std::size_t divisor) {
    return (value + divisor - 1) / divisor;
  }

  static void notify_input_nonempty(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kScan) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  static void notify_reader_done(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kScan) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  static void notify_output_nonfull(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kMerge) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  void account_suspended_output_stalls(std::uint64_t cycle) {
    if (!suspended_output_stall_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph gather suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_evaluate_cycle_ - 1;
    output_stall_cycles_ += skipped;
    output_.account_push_stalls(skipped);
    suspended_output_stall_ = false;
  }

  void refresh_evaluate_ready() noexcept {
    switch (phase_) {
    case Phase::kReset:
    case Phase::kDrain:
      evaluate_ready_ = true;
      break;
    case Phase::kMerge:
      evaluate_ready_ = !suspended_output_stall_ || !output_.full();
      break;
    case Phase::kScan:
      evaluate_ready_ = input_.front() != nullptr || reader_.done();
      break;
    case Phase::kIdle:
    case Phase::kDone:
      evaluate_ready_ = false;
      break;
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_tick_ = false;
    staged_start_drain_ = false;
    staged_output_stall_ = false;
    staged_row_output_ = false;
    staged_batch_.reset();
    staged_cross_bank_reductions_ = 0;
    set_latched_commit_ready(false);
  }

  void commit_physical_writes(std::uint64_t cycle) {
    while (!pending_physical_writes_.empty() &&
           pending_physical_writes_.front().due_cycle <= cycle) {
      const PendingPhysicalWrite &write = pending_physical_writes_.front();
      bank_rows_[write.bank][write.row] = write.value;
      pending_physical_writes_.pop_front();
    }
  }

  void consume_batch(const PmaEdgeBatch &batch, std::uint64_t cycle) {
    ++batches_scanned_;
    slots_scanned_ += batch.lanes;
    for (std::size_t lane = 0; lane < batch.lanes; ++lane) {
      if (!batch.valid[lane]) {
        continue;
      }
      ++live_edges_;
      const std::uint32_t destination = batch.destinations[lane];
      if (destination >= destination_vertices_) {
        throw std::runtime_error("PMA edge exceeds ReGraph vertex range");
      }
      const bool source_active = batch.per_lane_source
                                     ? batch.source_actives[lane]
                                     : batch.source_active;
      if (!source_active) {
        continue;
      }
      ++active_edges_;
      const std::size_t bank = lane;
      const std::size_t row = destination >> 1;
      const std::size_t half = destination & 1U;
      GatherRow updated{};
      const auto physical = bank_rows_[bank].find(row);
      if (physical != bank_rows_[bank].end()) {
        updated = physical->second;
      }
      bool forwarded = false;
      for (const BypassEntry &entry : bypass_[bank]) {
        if (entry.valid && entry.row == row) {
          updated = entry.value;
          forwarded = true;
        }
      }
      if (forwarded) {
        ++bypass_hits_;
      } else {
        ++bypass_misses_;
      }
      const std::uint32_t source_payload = batch.per_lane_source
                                               ? batch.source_payloads[lane]
                                               : batch.source_payload;
      const std::uint32_t candidate =
          policy_.map_edge(source_payload, batch.weights[lane]);
      updated[half] = policy_.reduce(updated[half], candidate);
      auto &entries = bypass_[bank];
      std::move(entries.begin() + 1, entries.end(), entries.begin());
      entries.back() = BypassEntry{.row = row, .value = updated, .valid = true};
      pending_physical_writes_.push_back(PendingPhysicalWrite{
          .bank = bank,
          .row = row,
          .value = updated,
          .due_cycle = cycle + config_.gather_bypass_distance,
      });
      ++bank_updates_;
    }
  }

  std::size_t vertices_{};
  std::size_t destination_vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<PmaEdgeBatch> &input_;
  Fifo<ReGraphGatherRow> &output_;
  ReGraphReaderContext &reader_;
  std::vector<std::unordered_map<std::size_t, GatherRow>> bank_rows_;
  std::vector<std::vector<BypassEntry>> bypass_;
  std::deque<PendingPhysicalWrite> pending_physical_writes_;
  Phase phase_{Phase::kIdle};
  std::size_t remaining_{};
  std::size_t drain_cycles_remaining_{};
  std::size_t next_output_row_{};
  bool staged_tick_{};
  bool staged_start_drain_{};
  bool staged_output_stall_{};
  bool staged_row_output_{};
  std::optional<PmaEdgeBatch> staged_batch_;
  std::uint64_t staged_cross_bank_reductions_{};
  std::uint64_t batches_scanned_{};
  std::uint64_t slots_scanned_{};
  std::uint64_t live_edges_{};
  std::uint64_t active_edges_{};
  std::uint64_t reset_cycles_{};
  std::uint64_t merge_cycles_{};
  std::uint64_t pipeline_drain_cycles_{};
  std::uint64_t output_stall_cycles_{};
  std::uint64_t rows_emitted_{};
  std::uint64_t bank_updates_{};
  std::uint64_t bypass_hits_{};
  std::uint64_t bypass_misses_{};
  std::uint64_t cross_bank_reductions_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_output_stall_{};
  std::uint64_t last_evaluate_cycle_{};
};

} // namespace

std::unique_ptr<ReGraphGatherEngine> make_regraph_gather(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<PmaEdgeBatch> &input,
    Fifo<ReGraphGatherRow> &output, ReGraphReaderContext &reader) {
  return std::make_unique<ReGraphGather>(
      std::move(name), clock, vertices, std::move(policy), config, input, output, reader);
}

} // namespace spine::sim::detail
