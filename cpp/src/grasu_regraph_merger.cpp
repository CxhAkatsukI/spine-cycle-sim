#include "detail/grasu_regraph_compute.hpp"

#include <cmath>
#include <deque>
#include <limits>
#include <unordered_map>
#include <utility>

namespace spine::sim::detail {
namespace {

class ReGraphMerger final : public ReGraphMergerEngine {
public:
  ReGraphMerger(std::string name, ClockId clock_id,
                const GraSuReGraphConfig &config, Fifo<ReGraphGatherRow> &input,
                Fifo<ReGraphMergedBurst> &output, ReGraphBurstOrder order)
      : ReGraphMergerEngine(std::move(name), clock_id), config_(config), input_(input),
        output_(output), coverage_(order) {
    input_.bind_nonempty_notifier(this, &ReGraphMerger::notify_input_nonempty);
    output_.bind_nonfull_notifier(this, &ReGraphMerger::notify_output_nonfull);
    refresh_evaluate_ready();
  }

  ~ReGraphMerger() override {
    input_.unbind_nonempty_notifier(this);
    output_.unbind_nonfull_notifier(this);
  }

  void start_round() override {
    if (running_ || pending_output_.has_value() || packed_rows_ != 0) {
      throw std::logic_error("ReGraph merger round started while busy");
    }
    consumed_rows_this_round_ = 0;
    coverage_.reset(config_.partition_vertices);
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept override { return done_; }
  [[nodiscard]] std::uint64_t rows_consumed() const noexcept override {
    return rows_consumed_;
  }
  [[nodiscard]] std::uint64_t bursts_emitted() const noexcept override {
    return bursts_emitted_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept override {
    return output_stall_cycles_;
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
    return running_ && (staged_input_.has_value() || staged_output_ ||
                        staged_output_stall_);
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_output_stalls(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_input_.reset();
    staged_output_ = false;
    staged_output_stall_ = false;
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    if (pending_output_.has_value()) {
      staged_output_ = output_.try_push(*pending_output_);
      if (!staged_output_) {
        staged_output_stall_ = true;
        set_latched_commit_ready(true);
        return;
      }
    }
    if (consumed_rows_this_round_ == rows_per_round() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    ReGraphGatherRow row;
    if (input_.try_pop(row)) {
      staged_input_ = std::move(row);
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &) override {
    if (!running_) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
      suspended_output_stall_ = true;
    }
    if (staged_output_) {
      pending_output_.reset();
      ++bursts_emitted_;
    }
    if (staged_input_.has_value()) {
      if (packed_rows_ == 0) {
        coverage_.accept(staged_input_->row * 2);
        burst_base_row_ = staged_input_->row;
      }
      if (staged_input_->row != burst_base_row_ + packed_rows_) {
        throw std::runtime_error("ReGraph merger received a row out of order");
      }
      const std::size_t base = packed_rows_ * 2;
      packed_candidates_[base] = staged_input_->candidates[0];
      packed_candidates_[base + 1] = staged_input_->candidates[1];
      ++packed_rows_;
      ++consumed_rows_this_round_;
      ++rows_consumed_;
      if (packed_rows_ == kRowsPerBurst) {
        pending_output_ = ReGraphMergedBurst{
            .offset = burst_base_row_ * 2,
            .candidates = packed_candidates_,
        };
        packed_candidates_.fill(std::nullopt);
        packed_rows_ = 0;
      }
    }
    if (consumed_rows_this_round_ == rows_per_round() &&
        !pending_output_.has_value()) {
      running_ = false;
      done_ = true;
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  static constexpr std::size_t kRowsPerBurst = kStateWordsPerBurst / 2;

  static void notify_input_nonempty(void *owner) noexcept {
    auto *merger = static_cast<ReGraphMerger *>(owner);
    merger->refresh_evaluate_ready();
  }

  static void notify_output_nonfull(void *owner) noexcept {
    auto *merger = static_cast<ReGraphMerger *>(owner);
    merger->refresh_evaluate_ready();
  }

  void account_suspended_output_stalls(std::uint64_t cycle) {
    if (!suspended_output_stall_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph merger suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_evaluate_cycle_ - 1;
    output_stall_cycles_ += skipped;
    output_.account_push_stalls(skipped);
    suspended_output_stall_ = false;
  }

  void refresh_evaluate_ready() noexcept {
    if (!running_) {
      evaluate_ready_ = false;
    } else if (pending_output_.has_value()) {
      evaluate_ready_ = !suspended_output_stall_ || !output_.full();
    } else {
      evaluate_ready_ = consumed_rows_this_round_ != rows_per_round() &&
                        input_.front() != nullptr;
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_input_.reset();
    staged_output_ = false;
    staged_output_stall_ = false;
    set_latched_commit_ready(false);
  }

  [[nodiscard]] std::size_t rows_per_round() const noexcept {
    return config_.partition_vertices / 2;
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphGatherRow> &input_;
  Fifo<ReGraphMergedBurst> &output_;
  ReGraphBurstCoverage coverage_;
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst>
      packed_candidates_{};
  std::optional<ReGraphGatherRow> staged_input_;
  std::optional<ReGraphMergedBurst> pending_output_;
  std::size_t consumed_rows_this_round_{};
  std::size_t packed_rows_{};
  std::size_t burst_base_row_{};
  bool staged_output_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_output_stall_{};
  std::uint64_t last_evaluate_cycle_{};
  std::uint64_t rows_consumed_{};
  std::uint64_t bursts_emitted_{};
  std::uint64_t output_stall_cycles_{};
};

} // namespace

std::unique_ptr<ReGraphMergerEngine> make_regraph_merger(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    Fifo<ReGraphGatherRow> &input, Fifo<ReGraphMergedBurst> &output,
    ReGraphBurstOrder order) {
  return std::make_unique<ReGraphMerger>(
      std::move(name), clock, config, input, output, order);
}

} // namespace spine::sim::detail
