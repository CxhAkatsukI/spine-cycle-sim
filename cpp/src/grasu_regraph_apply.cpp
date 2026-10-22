#include "detail/grasu_regraph_compute.hpp"

#include <cmath>
#include <deque>
#include <limits>
#include <unordered_map>
#include <utility>

namespace spine::sim::detail {
namespace {

class ReGraphApply final : public ReGraphApplyEngine {
public:
  ReGraphApply(std::string name, ClockId clock_id, std::size_t vertices,
               GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
               Fifo<ReGraphMergedBurst> &input,
               Fifo<ReGraphAppliedBurst> &output, AxiEndpoint read_port,
               AxiEndpoint write_port, std::optional<AxiEndpoint> degree_port,
               const ReGraphReaderContext &iteration_context,
               std::optional<AxiEndpoint> auxiliary_read_port = std::nullopt,
               std::optional<AxiEndpoint> auxiliary_write_port = std::nullopt)
      : ReGraphApplyEngine(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), read_port_(read_port), write_port_(write_port),
        degree_port_(degree_port), iteration_context_(iteration_context),
        auxiliary_read_port_(auxiliary_read_port),
        auxiliary_write_port_(auxiliary_write_port) {
    if (uses_page_rank() && degree_port_ == std::nullopt) {
      throw std::invalid_argument("PageRank apply requires a degree AXI port");
    }
    if ((auxiliary_read_port_ == std::nullopt) !=
            (auxiliary_write_port_ == std::nullopt) ||
        (auxiliary_read_port_ != std::nullopt &&
         policy_.config().kind != GraphAlgorithmKind::kResidualPageRank)) {
      throw std::invalid_argument(
          "separate auxiliary state requires residual PageRank");
    }
    input_.bind_nonempty_notifier(this, &ReGraphApply::notify_work_available);
    read_port_.responses().bind_nonempty_notifier(
        this, &ReGraphApply::notify_work_available);
    write_port_.responses().bind_nonempty_notifier(
        this, &ReGraphApply::notify_work_available);
    if (auxiliary_read_port_ != std::nullopt) {
      auxiliary_read_port_->responses().bind_nonempty_notifier(
          this, &ReGraphApply::notify_work_available);
      auxiliary_write_port_->responses().bind_nonempty_notifier(
          this, &ReGraphApply::notify_work_available);
    }
    if (degree_port_ != std::nullopt) {
      degree_port_->responses().bind_nonempty_notifier(
          this, &ReGraphApply::notify_work_available);
    }
    refresh_evaluate_ready();
  }

  ~ReGraphApply() override {
    input_.unbind_nonempty_notifier(this);
    read_port_.responses().unbind_nonempty_notifier(this);
    write_port_.responses().unbind_nonempty_notifier(this);
    if (auxiliary_read_port_ != std::nullopt) {
      auxiliary_read_port_->responses().unbind_nonempty_notifier(this);
      auxiliary_write_port_->responses().unbind_nonempty_notifier(this);
    }
    if (degree_port_ != std::nullopt) {
      degree_port_->responses().unbind_nonempty_notifier(this);
    }
  }

  void start_partition(std::uint64_t round, std::size_t destination_base,
                       std::size_t destination_vertices,
                       bool reset_iteration_totals) override {
    if (round == 0 || running_ || !read_inflight_.empty() ||
        !write_inflight_.empty() || !auxiliary_write_inflight_.empty() ||
        !ready_writes_.empty()) {
      throw std::logic_error("ReGraph apply round started while busy");
    }
    completed_writes_ = 0;
    completed_auxiliary_writes_ = 0;
    input_bursts_this_round_ = 0;
    next_write_offset_ = 0;
    round_ = round;
    destination_base_ = destination_base;
    destination_vertices_ = destination_vertices;
    if (reset_iteration_totals) {
      active_vertices_ = 0;
      iteration_error_ = 0.0F;
      next_dangling_ = 0.0F;
    }
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept override { return done_; }
  [[nodiscard]] std::size_t active_vertices() const noexcept override {
    return active_vertices_;
  }
  [[nodiscard]] std::uint64_t reads() const noexcept override { return reads_; }
  [[nodiscard]] std::uint64_t writes() const noexcept override { return writes_; }
  [[nodiscard]] std::uint64_t input_bursts() const noexcept override {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept override {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t total_activated() const noexcept override {
    return total_activated_;
  }
  [[nodiscard]] std::uint64_t read_window_stalls() const noexcept override {
    return read_window_stalls_;
  }
  [[nodiscard]] bool read_window_blocked() const noexcept override {
    return running_ && input_bursts_this_round_ < total_bursts() &&
           input_.front() != nullptr &&
           read_inflight_.size() >= config_.apply_request_window;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept override {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept override {
    return write_window_stalls_;
  }
  [[nodiscard]] std::size_t max_reads_inflight() const noexcept override {
    return max_reads_inflight_;
  }
  [[nodiscard]] std::size_t max_pipeline_occupancy() const noexcept override {
    return max_pipeline_occupancy_;
  }
  [[nodiscard]] std::size_t max_writes_inflight() const noexcept override {
    return max_writes_inflight_;
  }
  void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) override {
    done_signal_.bind(owner, notifier);
  }
  void unbind_done_notifier(void *owner) noexcept override {
    done_signal_.unbind(owner);
  }
  [[nodiscard]] float iteration_error() const noexcept override {
    return iteration_error_;
  }
  [[nodiscard]] float next_dangling() const noexcept override { return next_dangling_; }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept override {
    return degree_reads_;
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
    return running_ &&
           (staged_read_issue_.has_value() || staged_write_issue_.has_value() ||
            staged_read_response_.has_value() ||
            staged_auxiliary_read_response_.has_value() ||
            staged_degree_response_.has_value() ||
            staged_write_response_.has_value() ||
            staged_auxiliary_write_response_.has_value() ||
            staged_output_stall_);
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_read_window(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_read_response_.reset();
    staged_auxiliary_read_response_.reset();
    staged_degree_response_.reset();
    staged_write_response_.reset();
    staged_auxiliary_write_response_.reset();
    staged_output_stall_ = false;
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    if (read_port_.responses().front() != nullptr) {
      AxiResponse response;
      if (read_port_.responses().try_pop(response)) {
        staged_read_response_ = std::move(response);
      }
    }
    if (write_port_.responses().front() != nullptr) {
      AxiResponse response;
      if (write_port_.responses().try_pop(response)) {
        staged_write_response_ = std::move(response);
      }
    }
    if (auxiliary_read_port_ != std::nullopt &&
        auxiliary_read_port_->responses().front() != nullptr) {
      AxiResponse response;
      if (auxiliary_read_port_->responses().try_pop(response)) {
        staged_auxiliary_read_response_ = std::move(response);
      }
    }
    if (auxiliary_write_port_ != std::nullopt &&
        auxiliary_write_port_->responses().front() != nullptr) {
      AxiResponse response;
      if (auxiliary_write_port_->responses().try_pop(response)) {
        staged_auxiliary_write_response_ = std::move(response);
      }
    }
    if (degree_port_ != std::nullopt &&
        degree_port_->responses().front() != nullptr) {
      AxiResponse response;
      if (degree_port_->responses().try_pop(response)) {
        staged_degree_response_ = std::move(response);
      }
    }

    const auto ready =
        std::find_if(ready_writes_.begin(), ready_writes_.end(),
                     [&](const ReadyWrite &item) {
                       return item.offset == next_write_offset_ &&
                              item.due_cycle <= context.domain_cycle;
                     });
    if (ready != ready_writes_.end()) {
      if (write_inflight_.size() >= config_.apply_request_window) {
        ++write_window_stalls_;
      } else {
        const std::size_t index =
            static_cast<std::size_t>(ready - ready_writes_.begin());
        const ReadyWrite &item = ready_writes_[index];
        if (!write_port_.requests().full() &&
            (auxiliary_write_port_ == std::nullopt ||
             !auxiliary_write_port_->requests().full()) &&
            !output_.full()) {
          if (!write_port_.requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.offset),
                  .operation = MemoryOperation::kWrite,
                  .address = config_.vertex_state_base +
                             global_offset(item.offset) *
                                 (auxiliary_write_port_ == std::nullopt
                                      ? state_bytes_per_vertex(policy_)
                                      : sizeof(std::uint32_t)),
                  .bytes = static_cast<std::uint32_t>(item.data.size()),
                  .stream_read_beats = false,
                  .write_data = item.data,
              }) ||
              (auxiliary_write_port_ != std::nullopt &&
               !auxiliary_write_port_->requests().try_push(AxiRequest{
                   .transaction_id = transaction_id(item.offset),
                   .operation = MemoryOperation::kWrite,
                   .address =
                       config_.residual_state_base +
                       global_offset(item.offset) * sizeof(std::uint32_t),
                   .bytes =
                       static_cast<std::uint32_t>(item.auxiliary_data.size()),
                   .stream_read_beats = false,
                   .write_data = item.auxiliary_data,
               })) ||
              !output_.try_push(ReGraphAppliedBurst{
                  .offset = item.offset,
                  .data = item.data,
                  .source_data = item.source_data,
              })) {
            throw std::logic_error(
                "ReGraph apply atomic output staging failed");
          }
          staged_write_issue_ = index;
        } else {
          staged_output_stall_ = true;
        }
      }
    }

    if (input_bursts_this_round_ >= total_bursts() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (read_inflight_.size() >= config_.apply_request_window) {
      ++read_window_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (pipeline_occupancy() >= config_.apply_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    const ReGraphMergedBurst &next = *input_.front();
    const bool degree_ready =
        degree_port_ == std::nullopt || !degree_port_->requests().full();
    const bool auxiliary_ready = auxiliary_read_port_ == std::nullopt ||
                                 !auxiliary_read_port_->requests().full();
    const std::size_t primary_state_bytes =
        kStateWordsPerBurst * (auxiliary_read_port_ == std::nullopt
                                   ? state_bytes_per_vertex(policy_)
                                   : sizeof(std::uint32_t));
    if (degree_ready && auxiliary_ready && !read_port_.requests().full() &&
        read_port_.requests().try_push(AxiRequest{
            .transaction_id = transaction_id(next.offset),
            .operation = MemoryOperation::kRead,
            .address = config_.vertex_state_base +
                       global_offset(next.offset) *
                           (auxiliary_read_port_ == std::nullopt
                                ? state_bytes_per_vertex(policy_)
                                : sizeof(std::uint32_t)),
            .bytes = static_cast<std::uint32_t>(primary_state_bytes),
            .stream_read_beats = false,
            .write_data = {},
        })) {
      if (auxiliary_read_port_ != std::nullopt &&
          !auxiliary_read_port_->requests().try_push(AxiRequest{
              .transaction_id = transaction_id(next.offset),
              .operation = MemoryOperation::kRead,
              .address = config_.residual_state_base +
                         global_offset(next.offset) * sizeof(std::uint32_t),
              .bytes = static_cast<std::uint32_t>(kStateWordsPerBurst *
                                                  sizeof(std::uint32_t)),
              .stream_read_beats = false,
              .write_data = {},
          })) {
        throw std::logic_error(
            "ReGraph apply auxiliary request was not atomic");
      }
      if (degree_port_ != std::nullopt &&
          !degree_port_->requests().try_push(AxiRequest{
              .transaction_id = transaction_id(next.offset),
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + global_offset(next.offset) * 4,
              .bytes = static_cast<std::uint32_t>(kStateWordsPerBurst * 4),
              .stream_read_beats = false,
              .write_data = {},
          })) {
        throw std::logic_error("ReGraph apply degree request was not atomic");
      }
      ReGraphMergedBurst consumed;
      if (!input_.try_pop(consumed)) {
        throw std::logic_error("ReGraph apply input staging failed");
      }
      staged_read_issue_ = std::move(consumed);
    }
    refresh_evaluate_ready();
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_read_response_.has_value()) {
      consume_read_response(*staged_read_response_, context.domain_cycle,
                            ReadKind::kPrimary);
      staged_read_response_.reset();
    }
    if (staged_auxiliary_read_response_.has_value()) {
      consume_read_response(*staged_auxiliary_read_response_,
                            context.domain_cycle, ReadKind::kAuxiliary);
      staged_auxiliary_read_response_.reset();
    }
    if (staged_degree_response_.has_value()) {
      consume_read_response(*staged_degree_response_, context.domain_cycle,
                            ReadKind::kDegree);
      staged_degree_response_.reset();
    }
    if (staged_write_response_.has_value()) {
      consume_write_response(*staged_write_response_, false);
      staged_write_response_.reset();
    }
    if (staged_auxiliary_write_response_.has_value()) {
      consume_write_response(*staged_auxiliary_write_response_, true);
      staged_auxiliary_write_response_.reset();
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
    }
    if (staged_read_issue_.has_value()) {
      const std::uint64_t id = transaction_id(staged_read_issue_->offset);
      if (!read_inflight_
               .emplace(id, PendingRead{.burst = std::move(*staged_read_issue_),
                                        .state_data = std::nullopt,
                                        .auxiliary_data = std::nullopt,
                                        .degree_data = std::nullopt})
               .second) {
        throw std::logic_error("duplicate ReGraph apply read transaction");
      }
      ++input_bursts_this_round_;
      ++input_bursts_;
      reads_ += 1 + (auxiliary_read_port_ != std::nullopt ? 1 : 0);
      degree_reads_ += degree_port_ == std::nullopt ? 0 : 1;
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite item = std::move(ready_writes_[*staged_write_issue_]);
      ready_writes_.erase(ready_writes_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(item.offset);
      if (!write_inflight_.emplace(id, item.offset).second) {
        throw std::logic_error("duplicate ReGraph apply write transaction");
      }
      if (auxiliary_write_port_ != std::nullopt &&
          !auxiliary_write_inflight_.emplace(id, item.offset).second) {
        throw std::logic_error(
            "duplicate ReGraph apply auxiliary write transaction");
      }
      writes_ += 1 + (auxiliary_write_port_ != std::nullopt ? 1 : 0);
      next_write_offset_ += kStateWordsPerBurst;
    }
    max_reads_inflight_ = std::max(max_reads_inflight_, read_inflight_.size());
    max_writes_inflight_ =
        std::max(max_writes_inflight_, write_inflight_.size());
    max_pipeline_occupancy_ =
        std::max(max_pipeline_occupancy_, pipeline_occupancy());
    if (completed_writes_ == total_bursts() &&
        (auxiliary_write_port_ == std::nullopt ||
         completed_auxiliary_writes_ == total_bursts())) {
      running_ = false;
      done_ = true;
      done_signal_.notify();
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  enum class ReadKind { kPrimary, kAuxiliary, kDegree };

  struct PendingRead {
    ReGraphMergedBurst burst;
    std::optional<std::vector<std::uint8_t>> state_data;
    std::optional<std::vector<std::uint8_t>> auxiliary_data;
    std::optional<std::vector<std::uint8_t>> degree_data;
  };

  struct ReadyWrite {
    std::size_t offset{};
    std::uint64_t due_cycle{};
    std::vector<std::uint8_t> data;
    std::vector<std::uint8_t> auxiliary_data;
    std::vector<std::uint8_t> source_data;
  };

  static void notify_work_available(void *owner) noexcept {
    auto *apply = static_cast<ReGraphApply *>(owner);
    apply->evaluate_ready_ = apply->running_;
    apply->set_latched_evaluate_ready(apply->evaluate_ready_);
  }

  void account_suspended_read_window(std::uint64_t cycle) {
    if (!suspended_read_window_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph apply suspended-cycle accounting moved backwards");
    }
    read_window_stalls_ += cycle - last_evaluate_cycle_ - 1;
    suspended_read_window_ = false;
  }

  [[nodiscard]] bool response_available() const noexcept {
    return read_port_.responses().front() != nullptr ||
           write_port_.responses().front() != nullptr ||
           (auxiliary_read_port_ != std::nullopt &&
            (auxiliary_read_port_->responses().front() != nullptr ||
             auxiliary_write_port_->responses().front() != nullptr)) ||
           (degree_port_ != std::nullopt &&
            degree_port_->responses().front() != nullptr);
  }

  void refresh_evaluate_ready() noexcept {
    const bool input_available =
        input_bursts_this_round_ < total_bursts() && input_.front() != nullptr;
    const bool staged_response = staged_read_response_.has_value() ||
                                 staged_auxiliary_read_response_.has_value() ||
                                 staged_degree_response_.has_value() ||
                                 staged_write_response_.has_value() ||
                                 staged_auxiliary_write_response_.has_value();
    const bool pure_read_window_wait =
        running_ && input_available && ready_writes_.empty() &&
        read_inflight_.size() >= config_.apply_request_window &&
        !response_available() && !staged_response;
    suspended_read_window_ = pure_read_window_wait;
    evaluate_ready_ = running_ && !pure_read_window_wait &&
                      (response_available() || staged_response ||
                       !ready_writes_.empty() || input_available);
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_read_response_.reset();
    staged_auxiliary_read_response_.reset();
    staged_degree_response_.reset();
    staged_write_response_.reset();
    staged_auxiliary_write_response_.reset();
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_output_stall_ = false;
    set_latched_commit_ready(false);
  }

  [[nodiscard]] bool uses_page_rank() const noexcept {
    return policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
           policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
  }

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return global_offset(offset) / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t global_offset(std::size_t offset) const noexcept {
    return destination_base_ + offset;
  }

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t pipeline_occupancy() const noexcept {
    return read_inflight_.size() + ready_writes_.size();
  }

  void consume_read_response(const AxiResponse &response, std::uint64_t cycle,
                             ReadKind kind) {
    const auto found = read_inflight_.find(response.transaction_id);
    const std::size_t expected_bytes =
        kind == ReadKind::kPrimary && auxiliary_read_port_ == std::nullopt
            ? kStateWordsPerBurst * state_bytes_per_vertex(policy_)
            : kStateWordsPerBurst * sizeof(std::uint32_t);
    if (!response.success || found == read_inflight_.end() ||
        response.read_data.size() != expected_bytes) {
      throw std::runtime_error(
          "ReGraph apply received malformed read response");
    }
    if (kind == ReadKind::kDegree) {
      found->second.degree_data = response.read_data;
    } else if (kind == ReadKind::kAuxiliary) {
      found->second.auxiliary_data = response.read_data;
    } else {
      found->second.state_data = response.read_data;
    }
    if (!found->second.state_data.has_value() ||
        (auxiliary_read_port_ != std::nullopt &&
         !found->second.auxiliary_data.has_value()) ||
        (degree_port_ != std::nullopt && !found->second.degree_data.has_value())) {
      return;
    }
    PendingRead pending = std::move(found->second);
    read_inflight_.erase(found);
    complete_read(std::move(pending), cycle);
  }

  void complete_read(PendingRead pending, std::uint64_t cycle) {
    ReGraphMergedBurst &burst = pending.burst;
    const std::vector<std::uint8_t> &state_data = *pending.state_data;
    std::array<std::uint32_t, kStateWordsPerBurst> result{};
    std::array<std::uint32_t, kStateWordsPerBurst> auxiliary{};
    std::array<std::uint32_t, kStateWordsPerBurst> source_payload{};
    for (std::size_t lane = 0; lane < result.size(); ++lane) {
      const std::size_t local_vertex = burst.offset + lane;
      const std::size_t vertex = destination_base_ + local_vertex;
      const std::size_t byte_offset =
          lane * (auxiliary_read_port_ == std::nullopt
                      ? state_bytes_per_vertex(policy_)
                      : sizeof(std::uint32_t));
      const std::uint32_t encoded = decode_u32(state_data, byte_offset);
      if (local_vertex >= destination_vertices_ || vertex >= vertices_) {
        result[lane] =
            policy_.config().kind == GraphAlgorithmKind::kWeightedSssp ||
                    policy_.config().kind ==
                        GraphAlgorithmKind::kConnectedComponents
                ? kReGraphInfinity
                : GraphAlgorithmPolicy::float_to_word(0.0F);
        auxiliary[lane] = GraphAlgorithmPolicy::float_to_word(0.0F);
        source_payload[lane] = GraphAlgorithmPolicy::float_to_word(0.0F);
        continue;
      }
      AlgorithmVertexState old_state{
          .primary = decode_policy_value(policy_, encoded),
          .auxiliary = uses_auxiliary_state(policy_)
                           ? (auxiliary_read_port_ == std::nullopt
                                  ? decode_u32(state_data, byte_offset + 4)
                                  : decode_u32(*pending.auxiliary_data,
                                               lane * sizeof(std::uint32_t)))
                           : 0,
      };
      const bool correction_mode =
          config_.split_pagerank_state &&
          policy_.config().kind == GraphAlgorithmKind::kResidualPageRank &&
          round_ == 1;
      if (!correction_mode &&
          policy_.config().kind == GraphAlgorithmKind::kResidualPageRank &&
          std::fabs(GraphAlgorithmPolicy::word_to_float(old_state.auxiliary)) >
              GraphAlgorithmPolicy::word_to_float(
                  policy_.activation_threshold_word())) {
        old_state = policy_.prepare_source(old_state, 0).state_after;
      }
      AlgorithmApplyResult applied;
      if (correction_mode) {
        const AlgorithmIterationContext context =
            iteration_context_.iteration_context();
        const float incoming =
            GraphAlgorithmPolicy::word_to_float(burst.candidates[lane].value_or(
                GraphAlgorithmPolicy::float_to_word(0.0F)));
        const float correction =
            GraphAlgorithmPolicy::word_to_float(policy_.initial_base_word()) +
            GraphAlgorithmPolicy::word_to_float(context.dangling_share) +
            incoming - GraphAlgorithmPolicy::word_to_float(old_state.primary);
        applied = {
            .state_after =
                {
                    .primary = old_state.primary,
                    .auxiliary =
                        GraphAlgorithmPolicy::float_to_word(correction),
                },
            .active = std::fabs(correction) >
                      GraphAlgorithmPolicy::word_to_float(
                          policy_.activation_threshold_word()),
            .error = std::fabs(correction),
        };
      } else {
        applied = policy_.apply(old_state, burst.candidates[lane],
                                iteration_context_.iteration_context());
      }
      result[lane] = encode_policy_value(policy_, applied.state_after.primary,
                                         applied.active);
      auxiliary[lane] = applied.state_after.auxiliary;
      if (uses_page_rank()) {
        const std::uint32_t degree = decode_u32(*pending.degree_data, lane * 4);
        const float value = GraphAlgorithmPolicy::word_to_float(
            policy_.config().kind == GraphAlgorithmKind::kFullPageRank
                ? applied.state_after.primary
                : applied.state_after.auxiliary);
        const bool source_active =
            policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
            applied.active;
        source_payload[lane] = GraphAlgorithmPolicy::float_to_word(
            source_active && degree != 0
                ? policy_.config().damping * value / static_cast<float>(degree)
                : 0.0F);
        if (source_active && degree == 0) {
          next_dangling_ += value;
        }
      } else {
        source_payload[lane] = result[lane];
      }
      iteration_error_ += applied.error;
      if (applied.active) {
        ++active_vertices_;
        ++total_activated_;
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .offset = burst.offset,
        .due_cycle = cycle + config_.apply_pipeline_latency,
        .data = auxiliary_write_port_ == std::nullopt
                    ? encode_state_words(policy_, result, auxiliary)
                    : encode_words(result),
        .auxiliary_data = auxiliary_write_port_ == std::nullopt
                              ? std::vector<std::uint8_t>{}
                              : encode_words(auxiliary),
        .source_data = encode_words(source_payload),
    });
  }

  void consume_write_response(const AxiResponse &response, bool auxiliary) {
    auto &inflight = auxiliary ? auxiliary_write_inflight_ : write_inflight_;
    const auto found = inflight.find(response.transaction_id);
    if (!response.success || found == inflight.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "ReGraph apply received malformed write response");
    }
    inflight.erase(found);
    if (auxiliary) {
      ++completed_auxiliary_writes_;
    } else {
      ++completed_writes_;
    }
  }

  std::size_t vertices_{};
  std::uint64_t round_{};
  std::size_t destination_base_{};
  std::size_t destination_vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<ReGraphMergedBurst> &input_;
  Fifo<ReGraphAppliedBurst> &output_;
  AxiEndpoint read_port_;
  AxiEndpoint write_port_;
  std::optional<AxiEndpoint> degree_port_;
  const ReGraphReaderContext &iteration_context_;
  std::optional<AxiEndpoint> auxiliary_read_port_;
  std::optional<AxiEndpoint> auxiliary_write_port_;
  std::unordered_map<std::uint64_t, PendingRead> read_inflight_;
  std::unordered_map<std::uint64_t, std::size_t> write_inflight_;
  std::unordered_map<std::uint64_t, std::size_t> auxiliary_write_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<AxiResponse> staged_read_response_;
  std::optional<AxiResponse> staged_auxiliary_read_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::optional<AxiResponse> staged_write_response_;
  std::optional<AxiResponse> staged_auxiliary_write_response_;
  std::optional<ReGraphMergedBurst> staged_read_issue_;
  std::optional<std::size_t> staged_write_issue_;
  std::size_t completed_writes_{};
  std::size_t completed_auxiliary_writes_{};
  std::size_t input_bursts_this_round_{};
  std::size_t next_write_offset_{};
  std::size_t active_vertices_{};
  float iteration_error_{};
  float next_dangling_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_read_window_{};
  std::uint64_t last_evaluate_cycle_{};
  std::uint64_t reads_{};
  std::uint64_t degree_reads_{};
  std::uint64_t writes_{};
  std::uint64_t input_bursts_{};
  std::uint64_t output_stall_cycles_{};
  std::uint64_t total_activated_{};
  std::uint64_t read_window_stalls_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_reads_inflight_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
  ReGraphDoneSignal done_signal_;
};

} // namespace

std::unique_ptr<ReGraphApplyEngine> make_regraph_apply(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<ReGraphMergedBurst> &input,
    Fifo<ReGraphAppliedBurst> &output, ReGraphApplyPorts ports,
    const ReGraphReaderContext &context) {
  return std::make_unique<ReGraphApply>(
      std::move(name), clock, vertices, std::move(policy), config, input, output,
      ports.read, ports.write, ports.degree, context,
      ports.auxiliary_read, ports.auxiliary_write);
}

std::unique_ptr<ReGraphApplyEngine> make_regraph_apply(
    std::string name, ClockId clock, std::size_t vertices, GraphAlgorithmPolicy policy,
    const GraSuReGraphConfig &config, Fifo<ReGraphMergedBurst> &input,
    Fifo<ReGraphAppliedBurst> &output, FixedAxiPort &read, FixedAxiPort &write,
    FixedAxiPort *degree, const ReGraphReaderContext &context,
    FixedAxiPort *auxiliary_read, FixedAxiPort *auxiliary_write) {
  const auto optional_port = [](FixedAxiPort *port) -> std::optional<AxiEndpoint> {
    return port ? std::optional<AxiEndpoint>{*port} : std::nullopt;
  };
  return make_regraph_apply(
      std::move(name), clock, vertices, std::move(policy), config, input, output,
      ReGraphApplyPorts{read, write, optional_port(degree),
                       optional_port(auxiliary_read), optional_port(auxiliary_write)}, context);
}

} // namespace spine::sim::detail
