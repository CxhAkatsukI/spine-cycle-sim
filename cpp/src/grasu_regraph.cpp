#include "spine_sim/grasu_regraph.hpp"

#include "spine_sim/grasu_native.hpp"
#include "detail/grasu_regraph_streams.hpp"
#include "detail/grasu_regraph_compute.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <limits>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace {

using namespace detail;


FixedAxiPortConfig port_config(const GraSuReGraphConfig &config,
                               std::size_t channel, std::uint32_t initiator_id,
                               std::uint32_t width) {
  return FixedAxiPortConfig{
      .memory_channels = config.memory_channels,
      .channel = channel,
      .initiator_id = initiator_id,
      .data_width_bytes = width,
      .max_burst_beats = 16,
      .request_fifo_depth = config.max_pending_requests,
      .response_fifo_depth = config.max_pending_requests,
      .read_beat_fifo_depth = config.max_pending_requests,
      .read_reorder_capacity = config.max_outstanding_bursts,
      .stream_read_beats = false,
      .max_pending_requests = config.max_pending_requests,
      .max_outstanding_bursts = config.max_outstanding_bursts,
      .address_accepts_per_cycle = 1,
      .beat_issues_per_cycle = 1,
      .response_beats_per_cycle = config.response_beats_per_cycle,
  };
}


class ReGraphIterationContext final : public ReGraphReaderContext {
public:
  explicit ReGraphIterationContext(GraphAlgorithmPolicy policy)
      : policy_(std::move(policy)) {}

  [[nodiscard]] bool done() const noexcept override { return true; }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    return context_;
  }

  void set_dangling(float dangling) noexcept {
    context_.base = policy_.config().kind == GraphAlgorithmKind::kFullPageRank
                        ? policy_.initial_base_word()
                        : GraphAlgorithmPolicy::float_to_word(0.0F);
    context_.dangling_share = GraphAlgorithmPolicy::float_to_word(
        policy_.config().damping * dangling /
        static_cast<float>(policy_.config().vertices));
  }

private:
  GraphAlgorithmPolicy policy_;
  AlgorithmIterationContext context_{};
};

class ReGraphPageRankSourcePrepare final : public Component {
public:
  ReGraphPageRankSourcePrepare(
      std::string name, ClockId clock_id, std::size_t vertices,
      GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
      FixedAxiPort &state_read, FixedAxiPort &degree_read,
      FixedAxiPort &primary_write, FixedAxiPort &mirror_write,
      ReGraphIterationContext &iteration_context)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), state_read_(state_read),
        degree_read_(degree_read), writes_{&primary_write, &mirror_write},
        iteration_context_(iteration_context) {}

  void start() {
    if (running_ || done_) {
      throw std::logic_error("PageRank source prepare started twice");
    }
    running_ = true;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t cycles() const noexcept { return cycles_; }
  [[nodiscard]] std::uint64_t state_reads() const noexcept {
    return state_reads_;
  }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept {
    return degree_reads_;
  }
  void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) {
    done_signal_.bind(owner, notifier);
  }
  void unbind_done_notifier(void *owner) noexcept {
    done_signal_.unbind(owner);
  }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_issued_; }

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
    return running_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override { return running_; }

  void evaluate(const CycleContext &context) override {
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_state_response_.reset();
    staged_degree_response_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    if (!running_) {
      set_latched_commit_ready(false);
      return;
    }
    if (state_read_.responses().front() != nullptr) {
      AxiResponse response;
      if (state_read_.responses().try_pop(response)) {
        staged_state_response_ = std::move(response);
      }
    }
    if (degree_read_.responses().front() != nullptr) {
      AxiResponse response;
      if (degree_read_.responses().try_pop(response)) {
        staged_degree_response_ = std::move(response);
      }
    }
    for (std::size_t port = 0; port < writes_.size(); ++port) {
      if (writes_[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (writes_[port]->responses().try_pop(response)) {
          staged_write_responses_[port] = std::move(response);
        }
      }
    }
    const auto ready =
        std::find_if(ready_writes_.begin(), ready_writes_.end(),
                     [&](const ReadyWrite &write) {
                       return write.due_cycle <= context.domain_cycle;
                     });
    if (ready != ready_writes_.end() && write_window_available() &&
        write_fifos_available()) {
      const std::size_t index =
          static_cast<std::size_t>(ready - ready_writes_.begin());
      const ReadyWrite &write = ready_writes_[index];
      for (FixedAxiPort *port : writes_) {
        if (!port->requests().try_push(AxiRequest{
                .transaction_id = transaction_id(write.burst),
                .operation = MemoryOperation::kWrite,
                .address = config_.source_state_base + write.burst * 64,
                .bytes = 64,
                .stream_read_beats = false,
                .write_data = write.data,
            })) {
          throw std::logic_error(
              "PageRank source prepare write pair was not atomic");
        }
      }
      staged_write_issue_ = index;
    }
    if (next_read_burst_ < total_bursts() &&
        reads_inflight_.size() < config_.apply_request_window &&
        !state_read_.requests().full() && !degree_read_.requests().full()) {
      const std::size_t burst = next_read_burst_;
      const std::size_t state_bytes =
          kStateWordsPerBurst * (config_.split_pagerank_state
                                     ? sizeof(std::uint32_t)
                                     : state_bytes_per_vertex(policy_));
      if (!state_read_.requests().try_push(AxiRequest{
              .transaction_id = transaction_id(burst),
              .operation = MemoryOperation::kRead,
              .address = config_.vertex_state_base + burst * state_bytes,
              .bytes = static_cast<std::uint32_t>(state_bytes),
              .stream_read_beats = false,
              .write_data = {},
          }) ||
          !degree_read_.requests().try_push(AxiRequest{
              .transaction_id = transaction_id(burst),
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + burst * 64,
              .bytes = 64,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        throw std::logic_error(
            "PageRank source prepare read pair was not atomic");
      }
      staged_read_issue_ = burst;
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      return;
    }
    ++cycles_;
    if (staged_state_response_.has_value()) {
      consume_read_response(*staged_state_response_, false,
                            context.domain_cycle);
    }
    if (staged_degree_response_.has_value()) {
      consume_read_response(*staged_degree_response_, true,
                            context.domain_cycle);
    }
    for (std::size_t port = 0; port < staged_write_responses_.size(); ++port) {
      if (staged_write_responses_[port].has_value()) {
        consume_write_response(*staged_write_responses_[port], port);
      }
    }
    if (staged_read_issue_.has_value()) {
      const std::size_t burst = *staged_read_issue_;
      if (!reads_inflight_
               .emplace(transaction_id(burst),
                        PendingRead{.burst = burst,
                                    .state_data = std::nullopt,
                                    .degree_data = std::nullopt})
               .second) {
        throw std::logic_error("duplicate PageRank source prepare read");
      }
      ++next_read_burst_;
      ++state_reads_;
      ++degree_reads_;
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite write = std::move(ready_writes_[*staged_write_issue_]);
      ready_writes_.erase(ready_writes_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(write.burst);
      for (auto &inflight : writes_inflight_) {
        if (!inflight.emplace(id, write.burst).second) {
          throw std::logic_error("duplicate PageRank source prepare write");
        }
      }
      writes_issued_ += 2;
    }
    if (completed_writes_ == total_bursts() * 2 &&
        reduction_cycles_remaining_ == 0) {
      reduction_cycles_remaining_ = kStateWordsPerBurst * 8;
    } else if (reduction_cycles_remaining_ != 0) {
      --reduction_cycles_remaining_;
      if (reduction_cycles_remaining_ == 0) {
        iteration_context_.set_dangling(dangling_);
        running_ = false;
        done_ = true;
        done_signal_.notify();
      }
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(running_);
  }

private:
  struct PendingRead {
    std::size_t burst{};
    std::optional<std::vector<std::uint8_t>> state_data;
    std::optional<std::vector<std::uint8_t>> degree_data;
  };
  struct ReadyWrite {
    std::size_t burst{};
    std::uint64_t due_cycle{};
    std::vector<std::uint8_t> data;
  };

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return (vertices_ + kStateWordsPerBurst - 1) / kStateWordsPerBurst;
  }
  [[nodiscard]] std::uint64_t transaction_id(std::size_t burst) const {
    return 0x7400'0000'0000'0000ULL | burst;
  }
  [[nodiscard]] bool write_window_available() const noexcept {
    return std::all_of(writes_inflight_.begin(), writes_inflight_.end(),
                       [&](const auto &inflight) {
                         return inflight.size() < config_.apply_request_window;
                       });
  }
  [[nodiscard]] bool write_fifos_available() const noexcept {
    return std::all_of(writes_.begin(), writes_.end(), [](const auto *port) {
      return !port->requests().full();
    });
  }

  void consume_read_response(const AxiResponse &response, bool degree,
                             std::uint64_t cycle) {
    const auto found = reads_inflight_.find(response.transaction_id);
    const std::size_t expected =
        degree ? 64
               : kStateWordsPerBurst * (config_.split_pagerank_state
                                            ? sizeof(std::uint32_t)
                                            : state_bytes_per_vertex(policy_));
    if (!response.success || found == reads_inflight_.end() ||
        response.read_data.size() != expected) {
      throw std::runtime_error("malformed PageRank source prepare response");
    }
    if (degree) {
      found->second.degree_data = response.read_data;
    } else {
      found->second.state_data = response.read_data;
    }
    if (!found->second.state_data.has_value() ||
        !found->second.degree_data.has_value()) {
      return;
    }
    PendingRead pending = std::move(found->second);
    reads_inflight_.erase(found);
    std::array<std::uint32_t, kStateWordsPerBurst> payload{};
    for (std::size_t lane = 0; lane < payload.size(); ++lane) {
      const std::size_t vertex = pending.burst * kStateWordsPerBurst + lane;
      if (vertex >= vertices_) {
        continue;
      }
      const std::size_t state_offset =
          lane * (config_.split_pagerank_state
                      ? sizeof(std::uint32_t)
                      : state_bytes_per_vertex(policy_));
      const std::uint32_t value_word =
          policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
                  config_.split_pagerank_state
              ? decode_u32(*pending.state_data, state_offset)
              : decode_u32(*pending.state_data, state_offset + 4);
      const float value = GraphAlgorithmPolicy::word_to_float(value_word);
      const std::uint32_t out_degree =
          decode_u32(*pending.degree_data, lane * 4);
      const bool active =
          policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
          config_.split_pagerank_state ||
          std::fabs(value) > GraphAlgorithmPolicy::word_to_float(
                                 policy_.activation_threshold_word());
      payload[lane] = GraphAlgorithmPolicy::float_to_word(
          active && out_degree != 0 ? policy_.config().damping * value /
                                          static_cast<float>(out_degree)
                                    : 0.0F);
      if (active) {
        ++active_vertices_;
        if (out_degree == 0) {
          dangling_ += value;
        }
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .burst = pending.burst,
        .due_cycle = cycle + config_.pagerank_source_map_latency,
        .data = encode_words(payload),
    });
  }

  void consume_write_response(const AxiResponse &response, std::size_t port) {
    auto &inflight = writes_inflight_.at(port);
    const auto found = inflight.find(response.transaction_id);
    if (!response.success || found == inflight.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "malformed PageRank source prepare write response");
    }
    inflight.erase(found);
    ++completed_writes_;
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  FixedAxiPort &state_read_;
  FixedAxiPort &degree_read_;
  std::array<FixedAxiPort *, 2> writes_;
  ReGraphIterationContext &iteration_context_;
  std::unordered_map<std::uint64_t, PendingRead> reads_inflight_;
  std::array<std::unordered_map<std::uint64_t, std::size_t>, 2>
      writes_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<std::size_t> staged_read_issue_;
  std::optional<std::size_t> staged_write_issue_;
  std::optional<AxiResponse> staged_state_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::array<std::optional<AxiResponse>, 2> staged_write_responses_;
  std::size_t next_read_burst_{};
  std::size_t completed_writes_{};
  std::size_t reduction_cycles_remaining_{};
  float dangling_{};
  std::size_t active_vertices_{};
  bool running_{};
  bool done_{};
  std::uint64_t cycles_{};
  std::uint64_t state_reads_{};
  std::uint64_t degree_reads_{};
  std::uint64_t writes_issued_{};
  ReGraphDoneSignal done_signal_;
};

GraSuPartitionedPmaLayout one_partition_layout(GraSuPmaLayout layout,
                                               std::size_t partition_vertices) {
  GraSuPartitionedPmaLayout result;
  result.vertices = layout.vertices;
  result.partition_vertices = partition_vertices;
  result.partitions.push_back(std::move(layout));
  return result;
}

class ReGraphSourceHbmReader final : public Component {
public:
  ReGraphSourceHbmReader(std::string name, ClockId clock_id,
                         const GraSuReGraphConfig &config,
                         GraphAlgorithmPolicy policy,
                         Fifo<ReGraphSourceCacheRequest> &input,
                         Fifo<ReGraphSourceCacheResponse> &output,
                         FixedAxiPort &port)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        output_(output), port_(port), policy_(std::move(policy)) {}

  void start_partition(std::uint64_t round, std::size_t partition) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("ReGraph source HBM reader started while busy");
    }
    algorithm_round_ = round;
    partition_ = partition;
    source_state_base_ =
        config_.source_state_base +
        ((round - 1) & 1U) * config_.source_state_buffer_stride;
    active_source_round_ = 0;
    lines_emitted_this_request_ = 0;
    phase_ = Phase::kIdle;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t requests() const noexcept { return requests_; }
  [[nodiscard]] std::uint64_t request_markers() const noexcept {
    return request_markers_;
  }
  [[nodiscard]] std::uint64_t lines() const noexcept { return lines_; }
  [[nodiscard]] std::uint64_t response_markers() const noexcept {
    return response_markers_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t read_bytes() const noexcept {
    return requests_ * source_round_bytes();
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
    return phase_ != Phase::kDone;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return phase_ != Phase::kDone &&
           (staged_input_.has_value() || staged_axi_issue_ ||
            staged_line_.has_value() || staged_parent_.has_value() ||
            staged_end_response_);
  }

  void evaluate(const CycleContext &) override {
    staged_input_.reset();
    staged_axi_issue_ = false;
    staged_line_.reset();
    staged_parent_.reset();
    staged_end_response_ = false;
    switch (phase_) {
    case Phase::kIdle: {
      ReGraphSourceCacheRequest request;
      if (input_.try_pop(request)) {
        staged_input_ = request;
      }
      break;
    }
    case Phase::kNeedIssue:
      staged_axi_issue_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(active_source_round_),
          .operation = MemoryOperation::kRead,
          .address =
              source_state_base_ + active_source_round_ * source_round_bytes(),
          .bytes = source_round_bytes(),
          .stream_read_beats = true,
          .write_data = {},
      });
      break;
    case Phase::kStream: {
      const AxiReadBeatResponse *beat = port_.read_beats().front();
      if (beat == nullptr) {
        break;
      }
      if (output_.full()) {
        ++output_stall_cycles_;
        break;
      }
      validate_beat(*beat);
      ReGraphSourceCacheResponse response{
          .source_round = active_source_round_,
          .line = static_cast<std::size_t>(beat->parent_offset / 64),
          .vertices = source_vertices_per_beat(),
      };
      for (std::size_t word = 0; word < response.vertices; ++word) {
        const std::size_t offset = word * source_bytes_per_vertex();
        response.words[word] = decode_u32(beat->read_data, offset);
        if (uses_auxiliary_state(policy_) &&
            !config_.pagerank_prepared_source) {
          response.auxiliary_words[word] =
              decode_u32(beat->read_data, offset + 4);
        }
      }
      AxiReadBeatResponse consumed;
      if (!port_.read_beats().try_pop(consumed) ||
          !output_.try_push(response)) {
        throw std::logic_error(
            "ReGraph source cacheline atomic transfer failed");
      }
      staged_line_ = std::move(consumed);
      break;
    }
    case Phase::kWaitParent:
      if (port_.responses().front() != nullptr) {
        AxiResponse response;
        if (port_.responses().try_pop(response)) {
          staged_parent_ = std::move(response);
        }
      }
      break;
    case Phase::kEmitEnd:
      staged_end_response_ =
          output_.try_push(ReGraphSourceCacheResponse{.end = true});
      if (!staged_end_response_) {
        ++output_stall_cycles_;
      }
      break;
    case Phase::kDone:
      break;
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &) override {
    if (staged_input_.has_value()) {
      if (staged_input_->end) {
        ++request_markers_;
        phase_ = Phase::kEmitEnd;
      } else {
        active_source_round_ = staged_input_->source_round;
        lines_emitted_this_request_ = 0;
        phase_ = Phase::kNeedIssue;
      }
    }
    if (staged_axi_issue_) {
      ++requests_;
      phase_ = Phase::kStream;
    }
    if (staged_line_.has_value()) {
      ++lines_emitted_this_request_;
      ++lines_;
      if (staged_line_->last) {
        if (lines_emitted_this_request_ != lines_per_round()) {
          throw std::runtime_error(
              "ReGraph source HBM request ended at the wrong cacheline");
        }
        phase_ = Phase::kWaitParent;
      }
    }
    if (staged_parent_.has_value()) {
      if (!staged_parent_->success ||
          staged_parent_->transaction_id !=
              transaction_id(active_source_round_) ||
          staged_parent_->read_data.size() != source_round_bytes()) {
        throw std::runtime_error(
            "ReGraph source HBM reader received malformed parent response");
      }
      phase_ = Phase::kIdle;
    }
    if (staged_end_response_) {
      ++response_markers_;
      phase_ = Phase::kDone;
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(evaluate_ready());
  }

private:
  enum class Phase { kIdle, kNeedIssue, kStream, kWaitParent, kEmitEnd, kDone };

  [[nodiscard]] std::size_t lines_per_round() const noexcept {
    return config_.source_buffer_vertices / source_vertices_per_beat();
  }
  [[nodiscard]] std::uint64_t source_round_bytes() const noexcept {
    return config_.source_buffer_vertices * source_bytes_per_vertex();
  }
  [[nodiscard]] std::size_t source_bytes_per_vertex() const noexcept {
    return config_.pagerank_prepared_source ? 4
                                            : state_bytes_per_vertex(policy_);
  }
  [[nodiscard]] std::size_t source_vertices_per_beat() const noexcept {
    return 64 / source_bytes_per_vertex();
  }
  [[nodiscard]] std::uint64_t transaction_id(std::size_t source_round) const {
    return (algorithm_round_ << 52) |
           (static_cast<std::uint64_t>(partition_) << 44) | (1ULL << 43) |
           source_round;
  }

  void validate_beat(const AxiReadBeatResponse &beat) const {
    if (!beat.success ||
        beat.transaction_id != transaction_id(active_source_round_) ||
        beat.parent_offset % 64 != 0 || beat.read_data.size() != 64 ||
        beat.parent_offset / 64 != lines_emitted_this_request_ ||
        beat.last != (lines_emitted_this_request_ + 1 == lines_per_round())) {
      throw std::runtime_error(
          "ReGraph source HBM reader received malformed cacheline response");
    }
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphSourceCacheRequest> &input_;
  Fifo<ReGraphSourceCacheResponse> &output_;
  FixedAxiPort &port_;
  GraphAlgorithmPolicy policy_;
  Phase phase_{Phase::kDone};
  std::uint64_t algorithm_round_{};
  std::size_t partition_{};
  std::uint64_t source_state_base_{};
  std::size_t active_source_round_{};
  std::size_t lines_emitted_this_request_{};
  std::optional<ReGraphSourceCacheRequest> staged_input_;
  bool staged_axi_issue_{};
  std::optional<AxiReadBeatResponse> staged_line_;
  std::optional<AxiResponse> staged_parent_;
  bool staged_end_response_{};
  std::uint64_t requests_{};
  std::uint64_t request_markers_{};
  std::uint64_t lines_{};
  std::uint64_t response_markers_{};
  std::uint64_t output_stall_cycles_{};
};


struct NativeEdgeArrayBurst {
  std::uint64_t index{};
  std::array<std::uint32_t, 8> sources{};
  std::array<std::uint32_t, 8> destinations{};
};

class NativeEdgeArrayHbmReader final : public Component {
public:
  NativeEdgeArrayHbmReader(std::string name, ClockId clock_id,
                           std::size_t compact_edge_slots,
                           const GraSuReGraphConfig &config,
                           Fifo<NativeEdgeArrayBurst> &output,
                           FixedAxiPort &port)
      : Component(std::move(name), clock_id),
        compact_edge_slots_(compact_edge_slots), config_(config),
        output_(output), port_(port) {}

  void start_round(std::uint64_t round) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("native edge-array reader started while busy");
    }
    round_ = round;
    bursts_emitted_this_round_ = 0;
    phase_ = Phase::kNeedIssue;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t requests() const noexcept { return requests_; }
  [[nodiscard]] std::uint64_t bursts() const noexcept { return bursts_; }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }

  void evaluate(const CycleContext &) override {
    staged_issue_ = false;
    staged_beat_.reset();
    staged_parent_.reset();
    if (phase_ == Phase::kNeedIssue) {
      staged_issue_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(),
          .operation = MemoryOperation::kRead,
          .address = config_.edge_array_base,
          .bytes = static_cast<std::uint32_t>(compact_edge_slots_ * 8),
          .stream_read_beats = true,
          .write_data = {},
      });
    } else if (phase_ == Phase::kStream) {
      const AxiReadBeatResponse *beat = port_.read_beats().front();
      if (beat == nullptr) {
        return;
      }
      if (output_.full()) {
        ++output_stall_cycles_;
        return;
      }
      NativeEdgeArrayBurst burst;
      burst.index = beat->parent_offset / 64;
      validate_beat(*beat, burst.index);
      for (std::size_t lane = 0; lane < 8; ++lane) {
        burst.sources[lane] = decode_u32(beat->read_data, lane * 8);
        burst.destinations[lane] = decode_u32(beat->read_data, lane * 8 + 4);
      }
      AxiReadBeatResponse consumed;
      if (!port_.read_beats().try_pop(consumed) ||
          !output_.try_push(std::move(burst))) {
        throw std::logic_error(
            "native edge-array beat transfer was not atomic");
      }
      staged_beat_ = std::move(consumed);
    } else if (phase_ == Phase::kWaitParent &&
               port_.responses().front() != nullptr) {
      AxiResponse response;
      if (port_.responses().try_pop(response)) {
        staged_parent_ = std::move(response);
      }
    }
  }

  void commit(const CycleContext &) override {
    if (staged_issue_) {
      ++requests_;
      phase_ = Phase::kStream;
    }
    if (staged_beat_.has_value()) {
      ++bursts_emitted_this_round_;
      ++bursts_;
      if (staged_beat_->last) {
        phase_ = Phase::kWaitParent;
      }
    }
    if (staged_parent_.has_value()) {
      if (!staged_parent_->success ||
          staged_parent_->transaction_id != transaction_id() ||
          staged_parent_->read_data.size() != compact_edge_slots_ * 8 ||
          bursts_emitted_this_round_ != compact_edge_slots_ / 8) {
        throw std::runtime_error(
            "native edge-array reader received malformed parent response");
      }
      phase_ = Phase::kDone;
    }
  }

private:
  enum class Phase { kIdle, kNeedIssue, kStream, kWaitParent, kDone };

  [[nodiscard]] std::uint64_t transaction_id() const {
    return 0x7200'0000'0000'0000ULL | round_;
  }

  void validate_beat(const AxiReadBeatResponse &beat,
                     std::uint64_t index) const {
    if (!beat.success || beat.transaction_id != transaction_id() ||
        beat.parent_offset % 64 != 0 || beat.read_data.size() != 64 ||
        index != bursts_emitted_this_round_ ||
        beat.last != (index + 1 == compact_edge_slots_ / 8)) {
      throw std::runtime_error("native edge-array beat is malformed");
    }
  }

  std::size_t compact_edge_slots_{};
  GraSuReGraphConfig config_;
  Fifo<NativeEdgeArrayBurst> &output_;
  FixedAxiPort &port_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::size_t bursts_emitted_this_round_{};
  bool staged_issue_{};
  std::optional<AxiReadBeatResponse> staged_beat_;
  std::optional<AxiResponse> staged_parent_;
  std::uint64_t requests_{};
  std::uint64_t bursts_{};
  std::uint64_t output_stall_cycles_{};
};

class NativeEdgeArrayScatter final : public Component,
                                     public ReGraphReaderContext {
public:
  NativeEdgeArrayScatter(std::string name, ClockId clock_id,
                         std::size_t vertices, const GraSuReGraphConfig &config,
                         Fifo<NativeEdgeArrayBurst> &input,
                         Fifo<PmaEdgeBatch> &output,
                         Fifo<ReGraphSourceCacheRequest> &source_requests,
                         Fifo<ReGraphSourceCacheResponse> &source_responses,
                         const NativeEdgeArrayHbmReader &edge_reader)
      : Component(std::move(name), clock_id), vertices_(vertices),
        config_(config), input_(input), output_(output),
        source_requests_(source_requests), source_responses_(source_responses),
        edge_reader_(edge_reader) {
    for (auto &slot : source_cache_) {
      slot.words.assign(config_.source_buffer_vertices, 0);
    }
  }

  void start_round(std::uint64_t round) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("native edge-array scatter started while busy");
    }
    round_ = round;
    pending_burst_.reset();
    pp_read_round_ = 0;
    pp_write_round_ = 0;
    pp_request_round_ = 0;
    source_end_sent_ = false;
    for (auto &slot : source_cache_) {
      slot.round = std::numeric_limits<std::size_t>::max();
      slot.lines_received = 0;
      std::fill(slot.words.begin(), slot.words.end(), 0);
    }
    phase_ = Phase::kRun;
  }

  [[nodiscard]] bool done() const noexcept override {
    return phase_ == Phase::kDone;
  }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    return {};
  }
  [[nodiscard]] std::uint64_t source_requests() const noexcept {
    return source_requests_count_;
  }
  [[nodiscard]] std::uint64_t source_request_markers() const noexcept {
    return source_request_markers_;
  }
  [[nodiscard]] std::uint64_t source_lines() const noexcept {
    return source_lines_;
  }
  [[nodiscard]] std::uint64_t source_lane_writes() const noexcept {
    return source_lane_writes_;
  }
  [[nodiscard]] std::uint64_t source_response_markers() const noexcept {
    return source_response_markers_;
  }
  [[nodiscard]] std::uint64_t source_wait_cycles() const noexcept {
    return source_wait_cycles_;
  }
  [[nodiscard]] std::uint64_t cross_source_round_bursts() const noexcept {
    return cross_source_round_bursts_;
  }

  void evaluate(const CycleContext &) override {
    staged_input_.reset();
    staged_source_response_.reset();
    staged_source_request_.reset();
    staged_output_ = false;
    staged_end_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return;
    }
    stage_source_response();
    stage_source_request();
    if (phase_ == Phase::kWaitEnd) {
      return;
    }
    if (!pending_burst_.has_value() && input_.front() != nullptr) {
      NativeEdgeArrayBurst burst;
      if (input_.try_pop(burst)) {
        staged_input_ = std::move(burst);
      }
      return;
    }
    if (pending_burst_.has_value()) {
      const std::size_t source_round = first_source_round(*pending_burst_);
      pp_read_round_ = source_round;
      if (!source_cache_ready(source_round)) {
        ++source_wait_cycles_;
        return;
      }
      staged_output_ =
          output_.try_push(build_batch(*pending_burst_, source_round));
      return;
    }
    if (edge_reader_.done() && input_.empty() && !source_end_sent_) {
      staged_end_ =
          source_requests_.try_push(ReGraphSourceCacheRequest{.end = true});
    }
  }

  void commit(const CycleContext &) override {
    if (staged_source_response_.has_value()) {
      consume_source_response(*staged_source_response_);
    }
    if (staged_source_request_.has_value()) {
      pp_request_round_ = *staged_source_request_ + 1;
      ++source_requests_count_;
    }
    if (staged_input_.has_value()) {
      pending_burst_ = std::move(staged_input_);
    }
    if (staged_output_) {
      const std::size_t first = first_source_round(*pending_burst_);
      bool crosses_source_round = false;
      for (std::size_t lane = 0; lane < pending_burst_->sources.size();
           ++lane) {
        const std::uint32_t source = pending_burst_->sources[lane];
        const std::uint32_t destination = pending_burst_->destinations[lane];
        if ((source & kReGraphActive) == 0 &&
            (destination & kReGraphActive) == 0 &&
            (source & kReGraphValueMask) / config_.source_buffer_vertices !=
                first) {
          crosses_source_round = true;
          break;
        }
      }
      if (crosses_source_round) {
        ++cross_source_round_bursts_;
      }
      pending_burst_.reset();
    }
    if (staged_end_) {
      source_end_sent_ = true;
      ++source_request_markers_;
      phase_ = Phase::kWaitEnd;
    }
  }

private:
  enum class Phase { kIdle, kRun, kWaitEnd, kDone };
  struct SourceCacheSlot {
    std::size_t round{std::numeric_limits<std::size_t>::max()};
    std::size_t lines_received{};
    std::vector<std::uint32_t> words;
  };

  [[nodiscard]] std::size_t source_lines_per_round() const noexcept {
    return config_.source_buffer_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t
  first_source_round(const NativeEdgeArrayBurst &burst) const {
    return (burst.sources[0] & kReGraphValueMask) /
           config_.source_buffer_vertices;
  }

  [[nodiscard]] bool source_cache_ready(std::size_t source_round) const {
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    return pp_write_round_ > source_round && slot.round == source_round &&
           slot.lines_received == source_lines_per_round();
  }

  void stage_source_request() {
    if (phase_ == Phase::kWaitEnd || source_end_sent_) {
      return;
    }
    const std::size_t request_round =
        std::max(pp_request_round_, pp_read_round_);
    if (request_round - pp_read_round_ > 1) {
      return;
    }
    if (source_requests_.try_push(
            ReGraphSourceCacheRequest{.source_round = request_round})) {
      staged_source_request_ = request_round;
    }
  }

  void stage_source_response() {
    if (source_responses_.front() == nullptr) {
      return;
    }
    ReGraphSourceCacheResponse response;
    if (source_responses_.try_pop(response)) {
      staged_source_response_ = std::move(response);
    }
  }

  void consume_source_response(const ReGraphSourceCacheResponse &response) {
    if (response.end) {
      if (phase_ != Phase::kWaitEnd) {
        throw std::runtime_error(
            "native edge scatter received source end out of phase");
      }
      ++source_response_markers_;
      phase_ = Phase::kDone;
      notify_done();
      return;
    }
    if (response.line >= source_lines_per_round() ||
        response.vertices != kStateWordsPerBurst) {
      throw std::runtime_error("native source-cache response is malformed");
    }
    SourceCacheSlot &slot = source_cache_[response.source_round & 1U];
    if (response.line == 0) {
      slot.round = response.source_round;
      slot.lines_received = 0;
    }
    if (slot.round != response.source_round ||
        slot.lines_received != response.line) {
      throw std::runtime_error("native source-cache response is out of order");
    }
    const std::size_t offset = response.line * kStateWordsPerBurst;
    std::copy_n(response.words.begin(), kStateWordsPerBurst,
                slot.words.begin() + static_cast<std::ptrdiff_t>(offset));
    ++slot.lines_received;
    pp_write_round_ = response.source_round;
    ++source_lines_;
    source_lane_writes_ += 8;
  }

  [[nodiscard]] PmaEdgeBatch build_batch(const NativeEdgeArrayBurst &burst,
                                         std::size_t source_round) const {
    PmaEdgeBatch batch{.per_lane_source = true, .lanes = 8};
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    for (std::size_t lane = 0; lane < 8; ++lane) {
      const std::uint32_t encoded_source = burst.sources[lane];
      const std::uint32_t encoded_destination = burst.destinations[lane];
      const std::uint32_t source = encoded_source & kReGraphValueMask;
      const std::size_t source_offset = source % config_.source_buffer_vertices;
      const std::uint32_t source_state = slot.words.at(source_offset);
      batch.valid[lane] = (encoded_source & kReGraphActive) == 0 &&
                          (encoded_destination & kReGraphActive) == 0 &&
                          source < vertices_;
      batch.source_payloads[lane] = policy_distance(source_state);
      batch.source_actives[lane] = (source_state & kReGraphActive) != 0;
      batch.destinations[lane] = encoded_destination & kGraSuPmaDestinationMask;
      batch.weights[lane] = static_cast<std::uint16_t>(
          (encoded_destination >> kGraSuPmaWeightShift) & kGraSuPmaWeightMask);
    }
    return batch;
  }

  std::size_t vertices_{};
  GraSuReGraphConfig config_;
  Fifo<NativeEdgeArrayBurst> &input_;
  Fifo<PmaEdgeBatch> &output_;
  Fifo<ReGraphSourceCacheRequest> &source_requests_;
  Fifo<ReGraphSourceCacheResponse> &source_responses_;
  const NativeEdgeArrayHbmReader &edge_reader_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::array<SourceCacheSlot, 2> source_cache_;
  std::size_t pp_read_round_{};
  std::size_t pp_write_round_{};
  std::size_t pp_request_round_{};
  bool source_end_sent_{};
  std::optional<NativeEdgeArrayBurst> pending_burst_;
  std::optional<NativeEdgeArrayBurst> staged_input_;
  std::optional<ReGraphSourceCacheResponse> staged_source_response_;
  std::optional<std::size_t> staged_source_request_;
  bool staged_output_{};
  bool staged_end_{};
  std::uint64_t source_requests_count_{};
  std::uint64_t source_request_markers_{};
  std::uint64_t source_lines_{};
  std::uint64_t source_lane_writes_{};
  std::uint64_t source_response_markers_{};
  std::uint64_t source_wait_cycles_{};
  std::uint64_t cross_source_round_bursts_{};
};

struct GraSuReGraphWorker {
  ReGraphSourceHbmReader *source_hbm{};
  ReGraphPartitionReader *reader{};
  ReGraphGatherEngine *gather{};
  ReGraphMergerEngine *merger{};
  ReGraphApplyEngine *apply{};
  ReGraphWritebackEngine *wrapper{};
  std::optional<std::size_t> partition;
  bool downstream_started{};

  [[nodiscard]] bool done() const noexcept {
    return partition.has_value() && downstream_started && source_hbm->done() &&
           reader->done() && gather->done() && merger->done() &&
           apply->done() && wrapper->done();
  }
};

class GraSuReGraphController final : public Component {
public:
  GraSuReGraphController(std::string name, ClockId clock_id,
                         GraphAlgorithmKind algorithm, std::size_t round_limit,
                         bool fixed_round_limit,
                         std::vector<ReGraphPartitionPlan> partitions,
                         std::vector<GraSuReGraphWorker> workers,
                         ReGraphIterationContext *iteration_context,
                         ReGraphPageRankSourcePrepare *source_prepare,
                         bool shared_downstream,
                         bool fixed_shard_lane_assignment)
      : Component(std::move(name), clock_id), algorithm_(algorithm),
        round_limit_(round_limit), fixed_round_limit_(fixed_round_limit),
        partitions_(std::move(partitions)), workers_(std::move(workers)),
        iteration_context_(iteration_context), source_prepare_(source_prepare),
        shared_downstream_(shared_downstream),
        fixed_shard_lane_assignment_(fixed_shard_lane_assignment),
        next_partition_per_worker_(workers_.size()),
        worker_partition_passes_(workers_.size()) {
    if (partitions_.empty() || workers_.empty()) {
      throw std::invalid_argument(
          "ReGraph controller requires partitions and compute workers");
    }
    const bool malformed = std::any_of(
        workers_.begin(), workers_.end(), [](const GraSuReGraphWorker &worker) {
          return worker.source_hbm == nullptr || worker.reader == nullptr ||
                 worker.gather == nullptr || worker.merger == nullptr ||
                 worker.apply == nullptr || worker.wrapper == nullptr;
        });
    if (malformed) {
      throw std::invalid_argument("ReGraph controller received a null worker");
    }
    if ((algorithm_ == GraphAlgorithmKind::kFullPageRank ||
         algorithm_ == GraphAlgorithmKind::kResidualPageRank) &&
        iteration_context_ == nullptr) {
      throw std::invalid_argument(
          "PageRank controller requires a shared iteration context");
    }
    for (GraSuReGraphWorker &worker : workers_) {
      worker.apply->bind_done_notifier(
          this, &GraSuReGraphController::notify_worker_done);
      worker.wrapper->bind_done_notifier(
          this, &GraSuReGraphController::notify_worker_done);
    }
    if (source_prepare_ != nullptr) {
      source_prepare_->bind_done_notifier(
          this, &GraSuReGraphController::notify_worker_done);
    }
    refresh_evaluate_ready();
  }

  ~GraSuReGraphController() override {
    for (GraSuReGraphWorker &worker : workers_) {
      worker.apply->unbind_done_notifier(this);
      worker.wrapper->unbind_done_notifier(this);
    }
    if (source_prepare_ != nullptr) {
      source_prepare_->unbind_done_notifier(this);
    }
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t supersteps() const noexcept { return round_; }
  [[nodiscard]] std::uint64_t partition_passes() const noexcept {
    return partition_passes_;
  }
  [[nodiscard]] const std::vector<std::uint64_t> &
  worker_partition_passes() const noexcept {
    return worker_partition_passes_;
  }
  [[nodiscard]] std::uint64_t pipeline_busy_cycles() const noexcept {
    return pipeline_busy_cycles_;
  }
  [[nodiscard]] std::size_t max_parallel_partitions() const noexcept {
    return max_parallel_partitions_;
  }
  [[nodiscard]] std::size_t
  max_parallel_downstream_partitions() const noexcept {
    return max_parallel_downstream_partitions_;
  }
  [[nodiscard]] std::uint64_t downstream_busy_cycles() const noexcept {
    return downstream_busy_cycles_;
  }
  [[nodiscard]] float iteration_error() const noexcept {
    return last_iteration_error_;
  }
  [[nodiscard]] const std::vector<std::size_t> &
  frontier_out_sizes() const noexcept {
    return frontier_out_sizes_;
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
    return !failed() && !done() &&
           (staged_ != Action::kNone || !staged_completed_workers_.empty());
  }

  void evaluate(const CycleContext &) override {
    staged_ = Action::kNone;
    staged_completed_workers_.clear();
    if (failed() || done()) {
      set_latched_commit_ready(false);
      return;
    }
    if (phase_ == Phase::kStart) {
      staged_ = source_prepare_ == nullptr ? Action::kStartSuperstep
                                           : Action::kStartPrepare;
    } else if (phase_ == Phase::kPrepare && source_prepare_->done()) {
      staged_ = Action::kStartSuperstep;
    } else if (phase_ == Phase::kRound) {
      for (std::size_t worker = 0; worker < workers_.size(); ++worker) {
        if (workers_[worker].done()) {
          staged_completed_workers_.push_back(worker);
        }
      }
      const std::size_t remaining_busy =
          busy_worker_count() - staged_completed_workers_.size();
      if (remaining_busy != 0 || has_pending_partition()) {
        refresh_evaluate_ready();
        set_latched_commit_ready(commit_ready());
        return;
      }
      std::size_t prospective_active = iteration_active_vertices_;
      for (const std::size_t worker : staged_completed_workers_) {
        prospective_active += workers_[worker].apply->active_vertices();
      }
      if (fixed_round_limit_ ||
          algorithm_ == GraphAlgorithmKind::kFullPageRank) {
        staged_ =
            round_ == round_limit_ ? Action::kFinish : Action::kNextSuperstep;
      } else {
        staged_ =
            prospective_active == 0 ? Action::kFinish : Action::kNextSuperstep;
      }
    }
    refresh_evaluate_ready();
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    account_suspended_busy_cycles(context.domain_cycle);
    for (const std::size_t worker_index : staged_completed_workers_) {
      GraSuReGraphWorker &worker = workers_.at(worker_index);
      iteration_active_vertices_ += worker.apply->active_vertices();
      iteration_error_ += worker.apply->iteration_error();
      iteration_dangling_ += worker.apply->next_dangling();
      ++completed_partitions_;
      worker.partition.reset();
      worker.downstream_started = false;
    }
    if (staged_ == Action::kNextSuperstep || staged_ == Action::kFinish) {
      frontier_out_sizes_.push_back(iteration_active_vertices_);
    }
    if (staged_ == Action::kStartPrepare) {
      source_prepare_->start();
      phase_ = Phase::kPrepare;
    } else if (staged_ == Action::kStartSuperstep ||
               staged_ == Action::kNextSuperstep) {
      if (round_ == round_limit_) {
        failure_ = "ReGraph algorithm exceeded configured round limit";
        staged_ = Action::kNone;
        staged_completed_workers_.clear();
        set_latched_commit_ready(false);
        return;
      }
      if (round_ != 0 && iteration_context_ != nullptr) {
        iteration_context_->set_dangling(iteration_dangling_);
      }
      ++round_;
      next_partition_ = 0;
      for (std::size_t worker = 0; worker < workers_.size(); ++worker) {
        next_partition_per_worker_[worker] = worker;
      }
      completed_partitions_ = 0;
      iteration_active_vertices_ = 0;
      iteration_error_ = 0.0F;
      iteration_dangling_ = 0.0F;
      dispatch_available_workers();
      start_waiting_downstream();
      phase_ = Phase::kRound;
    } else if (staged_ == Action::kFinish) {
      last_iteration_error_ = iteration_error_;
      phase_ = Phase::kDone;
    }
    if (!staged_completed_workers_.empty() && staged_ == Action::kNone) {
      dispatch_available_workers();
      start_waiting_downstream();
      if (completed_partitions_ == partitions_.size()) {
        last_iteration_error_ = iteration_error_;
      }
    }
    const std::size_t busy = busy_worker_count();
    pipeline_busy_cycles_ += busy;
    max_parallel_partitions_ = std::max(max_parallel_partitions_, busy);
    const std::size_t downstream_busy = downstream_busy_worker_count();
    downstream_busy_cycles_ += downstream_busy;
    max_parallel_downstream_partitions_ =
        std::max(max_parallel_downstream_partitions_, downstream_busy);
    last_busy_workers_ = busy;
    last_downstream_busy_workers_ = downstream_busy;
    last_commit_cycle_ = context.domain_cycle;
    committed_once_ = true;
    staged_ = Action::kNone;
    staged_completed_workers_.clear();
    set_latched_commit_ready(false);
    refresh_evaluate_ready();
  }

private:
  enum class Phase { kStart, kPrepare, kRound, kDone };
  enum class Action {
    kNone,
    kStartPrepare,
    kStartSuperstep,
    kNextSuperstep,
    kFinish
  };

  static void notify_worker_done(void *owner) noexcept {
    static_cast<GraSuReGraphController *>(owner)->refresh_evaluate_ready();
  }

  void account_suspended_busy_cycles(std::uint64_t cycle) {
    if (!committed_once_) {
      return;
    }
    if (cycle <= last_commit_cycle_) {
      throw std::logic_error(
          "ReGraph controller suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_commit_cycle_ - 1;
    pipeline_busy_cycles_ += skipped * last_busy_workers_;
    downstream_busy_cycles_ += skipped * last_downstream_busy_workers_;
  }

  void refresh_evaluate_ready() noexcept {
    evaluate_ready_ = false;
    if (failed() || done()) {
      set_latched_evaluate_ready(false);
      return;
    }
    if (phase_ == Phase::kStart) {
      evaluate_ready_ = true;
    } else if (phase_ == Phase::kPrepare) {
      evaluate_ready_ = source_prepare_->done();
    } else if (phase_ == Phase::kRound) {
      evaluate_ready_ = std::any_of(
          workers_.begin(), workers_.end(),
          [](const GraSuReGraphWorker &worker) { return worker.done(); });
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  [[nodiscard]] std::size_t busy_worker_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(
        workers_.begin(), workers_.end(), [](const GraSuReGraphWorker &worker) {
          return worker.partition.has_value();
        }));
  }

  [[nodiscard]] std::size_t downstream_busy_worker_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(
        workers_.begin(), workers_.end(), [](const GraSuReGraphWorker &worker) {
          return worker.partition.has_value() && worker.downstream_started;
        }));
  }

  void start_downstream(GraSuReGraphWorker &worker) {
    if (!worker.partition.has_value() || worker.downstream_started) {
      throw std::logic_error("invalid ReGraph shared-downstream dispatch");
    }
    const ReGraphPartitionPlan &plan = partitions_.at(*worker.partition);
    worker.merger->start_round();
    worker.apply->start_partition(round_, plan.destination_base,
                                  plan.destination_vertices, true);
    worker.wrapper->start_partition(round_, plan.destination_base);
    worker.downstream_started = true;
  }

  void start_waiting_downstream() {
    if (!shared_downstream_ || downstream_busy_worker_count() != 0) {
      return;
    }
    GraSuReGraphWorker *selected = nullptr;
    for (GraSuReGraphWorker &worker : workers_) {
      if (!worker.partition.has_value() || worker.downstream_started) {
        continue;
      }
      if (selected == nullptr || *worker.partition < *selected->partition) {
        selected = &worker;
      }
    }
    if (selected != nullptr) {
      start_downstream(*selected);
    }
  }

  void start_partition(std::size_t worker_index, std::size_t partition) {
    GraSuReGraphWorker &worker = workers_.at(worker_index);
    const ReGraphPartitionPlan &plan = partitions_.at(partition);
    worker.partition = partition;
    worker.downstream_started = false;
    worker.source_hbm->start_partition(round_, partition);
    worker.reader->start_partition(
        round_, plan, partition == 0 && !uses_prepared_page_rank_source());
    worker.gather->start_partition(plan.destination_vertices, round_ == 1);
    if (!shared_downstream_) {
      start_downstream(worker);
    }
    ++partition_passes_;
    ++worker_partition_passes_.at(worker_index);
  }

  void dispatch_available_workers() {
    for (std::size_t worker = 0; worker < workers_.size(); ++worker) {
      if (workers_[worker].partition.has_value()) {
        continue;
      }
      if (fixed_shard_lane_assignment_) {
        const std::size_t partition = next_partition_per_worker_[worker];
        if (partition >= partitions_.size()) {
          continue;
        }
        start_partition(worker, partition);
        next_partition_per_worker_[worker] += workers_.size();
      } else if (next_partition_ < partitions_.size()) {
        start_partition(worker, next_partition_++);
      }
    }
  }

  [[nodiscard]] bool has_pending_partition() const noexcept {
    if (!fixed_shard_lane_assignment_) {
      return next_partition_ < partitions_.size();
    }
    return std::any_of(
        next_partition_per_worker_.begin(), next_partition_per_worker_.end(),
        [&](std::size_t partition) { return partition < partitions_.size(); });
  }

  [[nodiscard]] bool uses_prepared_page_rank_source() const noexcept {
    return iteration_context_ != nullptr;
  }

  GraphAlgorithmKind algorithm_{GraphAlgorithmKind::kWeightedSssp};
  std::size_t round_limit_{};
  bool fixed_round_limit_{};
  std::vector<ReGraphPartitionPlan> partitions_;
  std::vector<GraSuReGraphWorker> workers_;
  ReGraphIterationContext *iteration_context_{};
  ReGraphPageRankSourcePrepare *source_prepare_{};
  bool shared_downstream_{};
  bool fixed_shard_lane_assignment_{};
  Phase phase_{Phase::kStart};
  Action staged_{Action::kNone};
  std::vector<std::size_t> staged_completed_workers_;
  std::uint64_t round_{};
  std::size_t next_partition_{};
  std::vector<std::size_t> next_partition_per_worker_;
  std::size_t completed_partitions_{};
  std::size_t iteration_active_vertices_{};
  float iteration_error_{};
  float iteration_dangling_{};
  float last_iteration_error_{};
  std::uint64_t partition_passes_{};
  std::vector<std::uint64_t> worker_partition_passes_;
  std::uint64_t pipeline_busy_cycles_{};
  std::size_t max_parallel_partitions_{};
  std::uint64_t downstream_busy_cycles_{};
  std::size_t max_parallel_downstream_partitions_{};
  std::size_t last_busy_workers_{};
  std::size_t last_downstream_busy_workers_{};
  std::uint64_t last_commit_cycle_{};
  bool committed_once_{};
  bool evaluate_ready_{};
  std::vector<std::size_t> frontier_out_sizes_;
  std::string failure_;
};

class GraSuNativeReGraphController final : public Component {
public:
  GraSuNativeReGraphController(std::string name, ClockId clock_id,
                               std::size_t supersteps, std::size_t vertices,
                               ReGraphSourceHbmReader &source_hbm,
                               NativeEdgeArrayHbmReader &edge_reader,
                               NativeEdgeArrayScatter &scatter,
                               ReGraphGatherEngine &gather, ReGraphMergerEngine &merger,
                               ReGraphApplyEngine &apply, ReGraphWritebackEngine &wrapper)
      : Component(std::move(name), clock_id), supersteps_(supersteps),
        vertices_(vertices), source_hbm_(source_hbm), edge_reader_(edge_reader),
        scatter_(scatter), gather_(gather), merger_(merger), apply_(apply),
        wrapper_(wrapper) {}

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t rounds() const noexcept { return round_; }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return !done();
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return !done() && (staged_start_ || staged_finish_);
  }

  void evaluate(const CycleContext &) override {
    staged_start_ = false;
    staged_finish_ = false;
    if (phase_ == Phase::kStart) {
      staged_start_ = true;
    } else if (phase_ == Phase::kRound && source_hbm_.done() &&
               edge_reader_.done() && scatter_.done() && gather_.done() &&
               merger_.done() && apply_.done() && wrapper_.done()) {
      if (round_ == supersteps_) {
        staged_finish_ = true;
      } else {
        staged_start_ = true;
      }
    }
  }

  void commit(const CycleContext &) override {
    if (staged_finish_) {
      phase_ = Phase::kDone;
      return;
    }
    if (!staged_start_) {
      return;
    }
    ++round_;
    source_hbm_.start_partition(round_, 0);
    edge_reader_.start_round(round_);
    scatter_.start_round(round_);
    gather_.start_partition(vertices_, round_ == 1);
    merger_.start_round();
    apply_.start_partition(round_, 0, vertices_, true);
    wrapper_.start_partition(round_, 0);
    phase_ = Phase::kRound;
  }

private:
  enum class Phase { kStart, kRound, kDone };

  std::size_t supersteps_{};
  std::size_t vertices_{};
  ReGraphSourceHbmReader &source_hbm_;
  NativeEdgeArrayHbmReader &edge_reader_;
  NativeEdgeArrayScatter &scatter_;
  ReGraphGatherEngine &gather_;
  ReGraphMergerEngine &merger_;
  ReGraphApplyEngine &apply_;
  ReGraphWritebackEngine &wrapper_;
  Phase phase_{Phase::kStart};
  bool staged_start_{};
  bool staged_finish_{};
  std::uint64_t round_{};
};

} // namespace

class GraSuReGraphSsspSystem::Impl {
  struct Pipeline {
    std::unique_ptr<Fifo<PmaEdgeBatch>> edge_axis;
    std::unique_ptr<Fifo<ReGraphSourceCacheRequest>> source_request_axis;
    std::unique_ptr<Fifo<ReGraphSourceCacheResponse>> source_response_axis;
    std::unique_ptr<Fifo<ReGraphGatherRow>> gather_axis;
    std::unique_ptr<Fifo<ReGraphMergedBurst>> merger_axis;
    std::unique_ptr<Fifo<ReGraphAppliedBurst>> wrapper_axis;
    std::unique_ptr<FixedAxiPort> row_port;
    std::unique_ptr<FixedAxiPort> source_state_port;
    std::unique_ptr<FixedAxiPort> degree_port;
    std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports;
    std::unique_ptr<FixedAxiPort> apply_state_read_port;
    std::unique_ptr<FixedAxiPort> apply_state_write_port;
    std::unique_ptr<FixedAxiPort> apply_auxiliary_read_port;
    std::unique_ptr<FixedAxiPort> apply_auxiliary_write_port;
    std::unique_ptr<FixedAxiPort> source_state_primary_write_port;
    std::unique_ptr<FixedAxiPort> source_state_mirror_write_port;
    std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader;
    std::unique_ptr<ReGraphPartitionReader> reader;
    std::unique_ptr<ReGraphGatherEngine> gather;
    std::unique_ptr<ReGraphMergerEngine> merger;
    std::unique_ptr<ReGraphApplyEngine> apply;
    std::unique_ptr<ReGraphWritebackEngine> wrapper;
  };

public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPartitionedPmaLayout layout, GraphAlgorithmPolicy policy,
       std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
       GraSuReGraphConfig config,
       std::optional<AlgorithmInitialState> initial_state = std::nullopt)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), source_(policy.config().source),
        config_(config), policy_(std::move(policy)),
        out_degrees_(std::move(out_degrees)),
        initial_state_(std::move(initial_state)), fixed_rounds_(fixed_rounds),
        start_cycle_(scheduler_.clock(clock_id_).completed_cycles) {
    address_plan_ = make_grasu_partition_address_plan(
        layout_, config_.packed_partition_addresses, config_.row_offset_base, 0,
        config_.pma_base, config_.partition_address_stride,
        config_.partition_address_arena_base,
        config_.partition_address_alignment);
    if (config_.packed_partition_addresses) {
      const std::uint64_t alignment = config_.partition_address_alignment;
      const auto align_up = [alignment](std::uint64_t value) {
        const std::uint64_t remainder = value % alignment;
        if (remainder == 0) {
          return value;
        }
        if (alignment - remainder >
            std::numeric_limits<std::uint64_t>::max() - value) {
          throw std::overflow_error("ReGraph packed source-state overflow");
        }
        return value + alignment - remainder;
      };
      config_.source_state_base = align_up(address_plan_.arena_end);
      const std::uint64_t required_stride =
          align_up(layout_.partitions.size() * config_.partition_vertices *
                   state_bytes_per_vertex(policy_));
      config_.source_state_buffer_stride =
          std::max(config_.source_state_buffer_stride, required_stride);
    }
    validate_config();
    construct_partition_plans();
    construct_ports();
    if (policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) {
      iteration_context_ = std::make_unique<ReGraphIterationContext>(policy_);
    }
    initialize_sharded_graph_payloads();
    initialize_state();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error("GraSU-ReGraph system registered more than once");
    }
    if (source_prepare_ != nullptr) {
      source_prepare_state_read_port_->register_components(scheduler_);
      source_prepare_degree_read_port_->register_components(scheduler_);
      source_prepare_primary_write_port_->register_components(scheduler_);
      source_prepare_mirror_write_port_->register_components(scheduler_);
      scheduler_.add_component(*source_prepare_);
    }
    for (Pipeline &pipeline : pipelines_) {
      scheduler_.add_component(*pipeline.edge_axis);
      scheduler_.add_component(*pipeline.source_request_axis);
      scheduler_.add_component(*pipeline.source_response_axis);
      scheduler_.add_component(*pipeline.gather_axis);
      scheduler_.add_component(*pipeline.merger_axis);
      scheduler_.add_component(*pipeline.wrapper_axis);
      pipeline.row_port->register_components(scheduler_);
      pipeline.source_state_port->register_components(scheduler_);
      if (pipeline.degree_port != nullptr) {
        pipeline.degree_port->register_components(scheduler_);
      }
      for (auto &port : pipeline.pma_ports) {
        port->register_components(scheduler_);
      }
      pipeline.apply_state_read_port->register_components(scheduler_);
      pipeline.apply_state_write_port->register_components(scheduler_);
      if (pipeline.apply_auxiliary_read_port != nullptr) {
        pipeline.apply_auxiliary_read_port->register_components(scheduler_);
        pipeline.apply_auxiliary_write_port->register_components(scheduler_);
      }
      pipeline.source_state_primary_write_port->register_components(scheduler_);
      pipeline.source_state_mirror_write_port->register_components(scheduler_);
      scheduler_.add_component(*pipeline.source_hbm_reader);
      scheduler_.add_component(*pipeline.reader);
      scheduler_.add_component(*pipeline.gather);
      scheduler_.add_component(*pipeline.merger);
      scheduler_.add_component(*pipeline.apply);
      scheduler_.add_component(*pipeline.wrapper);
    }
    scheduler_.add_component(*controller_);
    registered_ = true;
  }

  [[nodiscard]] bool done() const noexcept {
    return registered_ && controller_->done() && all_ports_idle();
  }
  [[nodiscard]] bool failed() const noexcept { return controller_->failed(); }
  [[nodiscard]] const std::string &failure() const noexcept {
    return controller_->failure();
  }
  [[nodiscard]] std::vector<std::size_t> frontier_out_sizes() const {
    return controller_->frontier_out_sizes();
  }

  [[nodiscard]] GraSuReGraphCounters counters() const noexcept {
    GraSuReGraphCounters result;
    const auto account_axi_port = [&result](const FixedAxiPort &port) {
      result.axi_request_fifo_stalls += port.requests().stats().push_stalls;
      result.axi_backend_submit_stalls +=
          port.master().stats().backend_submit_stalls;
      result.axi_beats_issued += port.master().stats().beats_issued;
      result.axi_beats_completed += port.master().stats().beats_completed;
    };
    const auto sum = [this](auto value) {
      std::uint64_t total = 0;
      for (const Pipeline &pipeline : pipelines_) {
        total += value(pipeline);
      }
      return total;
    };
    const auto maximum = [this](auto value) {
      std::size_t result = 0;
      for (const Pipeline &pipeline : pipelines_) {
        result = std::max(result, value(pipeline));
      }
      return result;
    };
    result.state_bytes_per_vertex = state_bytes_per_vertex(policy_);
    result.destination_partitions = layout_.partitions.size();
    result.compute_pipelines = pipelines_.size();
    result.max_parallel_partitions = controller_->max_parallel_partitions();
    result.max_parallel_downstream_partitions =
        controller_->max_parallel_downstream_partitions();
    result.supersteps = controller_->supersteps();
    result.partition_passes = controller_->partition_passes();
    const auto &frontend_passes = controller_->worker_partition_passes();
    for (std::size_t frontend = 0;
         frontend < result.frontend_partition_passes.size() &&
         frontend < frontend_passes.size();
         ++frontend) {
      result.frontend_partition_passes[frontend] = frontend_passes[frontend];
    }
    result.pipeline_busy_cycles = controller_->pipeline_busy_cycles();
    result.downstream_busy_cycles = controller_->downstream_busy_cycles();
    if (source_prepare_ != nullptr) {
      result.source_prepare_cycles = source_prepare_->cycles();
      result.source_prepare_state_reads = source_prepare_->state_reads();
      result.source_prepare_state_read_bytes =
          result.source_prepare_state_reads * kStateWordsPerBurst *
          (config_.split_pagerank_state ? sizeof(std::uint32_t)
                                        : state_bytes_per_vertex(policy_));
      result.source_prepare_degree_reads = source_prepare_->degree_reads();
      result.source_prepare_writes = source_prepare_->writes();
    }
#define SUM_PIPELINE(field, expression)                                        \
  result.field = sum([](const Pipeline &p) { return (expression); })
#define MAX_PIPELINE(field, expression)                                        \
  result.field = maximum([](const Pipeline &p) { return (expression); })
    SUM_PIPELINE(row_reads, p.reader->row_reads());
    SUM_PIPELINE(source_state_reads, p.source_hbm_reader->requests());
    SUM_PIPELINE(source_cache_requests, p.reader->source_requests());
    SUM_PIPELINE(source_cache_request_markers,
                 p.reader->source_request_markers());
    SUM_PIPELINE(source_cache_lines, p.reader->source_lines());
    SUM_PIPELINE(source_cache_lane_writes, p.reader->source_lane_writes());
    SUM_PIPELINE(source_cache_response_markers,
                 p.reader->source_response_markers());
    SUM_PIPELINE(source_cache_wait_cycles, p.reader->source_wait_cycles());
    SUM_PIPELINE(source_cache_output_stall_cycles,
                 p.source_hbm_reader->output_stall_cycles());
    MAX_PIPELINE(source_cache_request_fifo_max_occupancy,
                 p.source_request_axis->stats().max_occupancy);
    MAX_PIPELINE(source_cache_response_fifo_max_occupancy,
                 p.source_response_axis->stats().max_occupancy);
    SUM_PIPELINE(source_state_writes, p.wrapper->source_writes());
    SUM_PIPELINE(degree_reads,
                 p.reader->degree_reads() + p.apply->degree_reads());
    SUM_PIPELINE(source_map_cycles, p.reader->source_map_cycles());
    SUM_PIPELINE(pma_segment_reads, p.reader->segment_reads());
    SUM_PIPELINE(edge_batches_scanned, p.gather->batches_scanned());
    SUM_PIPELINE(pma_slots_scanned, p.gather->slots_scanned());
    SUM_PIPELINE(live_edges_scanned, p.gather->live_edges());
    SUM_PIPELINE(active_edges_mapped, p.gather->active_edges());
    SUM_PIPELINE(gather_reset_cycles, p.gather->reset_cycles());
    SUM_PIPELINE(gather_merge_cycles, p.gather->merge_cycles());
    SUM_PIPELINE(gather_pipeline_drain_cycles,
                 p.gather->pipeline_drain_cycles());
    SUM_PIPELINE(gather_output_stall_cycles, p.gather->output_stall_cycles());
    SUM_PIPELINE(gather_bank_conflict_cycles, p.gather->conflict_cycles());
    SUM_PIPELINE(gather_bank_updates, p.gather->bank_updates());
    SUM_PIPELINE(gather_bypass_hits, p.gather->bypass_hits());
    SUM_PIPELINE(gather_bypass_misses, p.gather->bypass_misses());
    SUM_PIPELINE(gather_cross_bank_reductions,
                 p.gather->cross_bank_reductions());
    SUM_PIPELINE(gather_rows_emitted, p.gather->rows_emitted());
    SUM_PIPELINE(merger_rows_consumed, p.merger->rows_consumed());
    SUM_PIPELINE(merger_bursts_emitted, p.merger->bursts_emitted());
    SUM_PIPELINE(merger_output_stall_cycles, p.merger->output_stall_cycles());
    SUM_PIPELINE(apply_state_reads, p.apply->reads());
    SUM_PIPELINE(apply_state_writes, p.apply->writes());
    SUM_PIPELINE(apply_input_bursts, p.apply->input_bursts());
    SUM_PIPELINE(apply_output_stall_cycles, p.apply->output_stall_cycles());
    SUM_PIPELINE(apply_read_window_stalls, p.apply->read_window_stalls());
    SUM_PIPELINE(apply_pipeline_capacity_stalls,
                 p.apply->pipeline_capacity_stalls());
    SUM_PIPELINE(apply_write_window_stalls, p.apply->write_window_stalls());
    MAX_PIPELINE(apply_max_reads_inflight, p.apply->max_reads_inflight());
    MAX_PIPELINE(apply_max_pipeline_occupancy,
                 p.apply->max_pipeline_occupancy());
    MAX_PIPELINE(apply_max_writes_inflight, p.apply->max_writes_inflight());
    SUM_PIPELINE(hbm_wrapper_input_bursts, p.wrapper->input_bursts());
    SUM_PIPELINE(hbm_wrapper_pipeline_capacity_stalls,
                 p.wrapper->pipeline_capacity_stalls());
    SUM_PIPELINE(hbm_wrapper_write_window_stalls,
                 p.wrapper->write_window_stalls());
    MAX_PIPELINE(hbm_wrapper_max_pipeline_occupancy,
                 p.wrapper->max_pipeline_occupancy());
    MAX_PIPELINE(hbm_wrapper_max_writes_inflight,
                 p.wrapper->max_writes_inflight());
    MAX_PIPELINE(gather_merger_fifo_max_occupancy,
                 p.gather_axis->stats().max_occupancy);
    MAX_PIPELINE(merger_apply_fifo_max_occupancy,
                 p.merger_axis->stats().max_occupancy);
    MAX_PIPELINE(apply_wrapper_fifo_max_occupancy,
                 p.wrapper_axis->stats().max_occupancy);
    SUM_PIPELINE(activated_vertices, p.apply->total_activated());
#undef MAX_PIPELINE
#undef SUM_PIPELINE
    result.source_state_writes += result.source_prepare_writes;
    result.degree_reads += result.source_prepare_degree_reads;
    result.row_read_bytes = result.row_reads * 8;
    result.source_state_read_bytes =
        result.source_state_reads * config_.source_buffer_vertices * 4;
    result.source_state_write_bytes =
        result.source_state_writes * kStateWordsPerBurst * 4;
    result.degree_read_bytes =
        sum([](const Pipeline &p) {
          return p.reader->degree_reads() * 4 +
                 p.apply->degree_reads() * kStateWordsPerBurst * 4;
        }) +
        result.source_prepare_degree_reads * kStateWordsPerBurst * 4;
    result.pma_read_bytes = result.pma_segment_reads * kGraSuSegmentBytes;
    result.apply_read_bytes =
        result.apply_state_reads * kStateWordsPerBurst *
        (config_.split_pagerank_state ? sizeof(std::uint32_t)
                                      : state_bytes_per_vertex(policy_));
    result.apply_write_bytes =
        result.apply_state_writes * kStateWordsPerBurst *
        (config_.split_pagerank_state ? sizeof(std::uint32_t)
                                      : state_bytes_per_vertex(policy_));
    for (const Pipeline &pipeline : pipelines_) {
      account_axi_port(*pipeline.row_port);
      account_axi_port(*pipeline.source_state_port);
      account_axi_port(*pipeline.apply_state_read_port);
      account_axi_port(*pipeline.apply_state_write_port);
      if (pipeline.apply_auxiliary_read_port != nullptr) {
        account_axi_port(*pipeline.apply_auxiliary_read_port);
        account_axi_port(*pipeline.apply_auxiliary_write_port);
      }
      account_axi_port(*pipeline.source_state_primary_write_port);
      account_axi_port(*pipeline.source_state_mirror_write_port);
      if (pipeline.degree_port != nullptr) {
        account_axi_port(*pipeline.degree_port);
      }
      for (const auto &port : pipeline.pma_ports) {
        account_axi_port(*port);
      }
      result.axis_push_stalls +=
          pipeline.source_request_axis->stats().push_stalls +
          pipeline.source_response_axis->stats().push_stalls +
          pipeline.edge_axis->stats().push_stalls +
          pipeline.gather_axis->stats().push_stalls +
          pipeline.merger_axis->stats().push_stalls +
          pipeline.wrapper_axis->stats().push_stalls;
    }
    if (source_prepare_ != nullptr) {
      account_axi_port(*source_prepare_state_read_port_);
      account_axi_port(*source_prepare_degree_read_port_);
      account_axi_port(*source_prepare_primary_write_port_);
      account_axi_port(*source_prepare_mirror_write_port_);
    }
    result.start_cycle = start_cycle_;
    result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    result.last_iteration_error = controller_->iteration_error();
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> distances() const {
    if (policy_.config().kind != GraphAlgorithmKind::kWeightedSssp) {
      throw std::logic_error("distance view requires weighted SSSP policy");
    }
    return state_words();
  }

  [[nodiscard]] std::vector<std::uint32_t> state_words() const {
    const std::size_t bytes_per_vertex = config_.split_pagerank_state
                                             ? sizeof(std::uint32_t)
                                             : state_bytes_per_vertex(policy_);
    const auto bytes = backend_.inspect_payload(
        config_.vertex_state_channel, config_.vertex_state_base,
        layout_.vertices * bytes_per_vertex);
    std::vector<std::uint32_t> result(layout_.vertices);
    for (std::size_t vertex = 0; vertex < result.size(); ++vertex) {
      result[vertex] = decode_policy_value(
          policy_, decode_u32(bytes, vertex * bytes_per_vertex));
    }
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> auxiliary_state_words() const {
    if (!uses_auxiliary_state(policy_)) {
      throw std::logic_error(
          "auxiliary state view requires residual PageRank policy");
    }
    const std::size_t bytes_per_vertex = config_.split_pagerank_state
                                             ? sizeof(std::uint32_t)
                                             : state_bytes_per_vertex(policy_);
    const auto bytes = backend_.inspect_payload(
        config_.split_pagerank_state ? config_.residual_state_channel
                                     : config_.vertex_state_channel,
        config_.split_pagerank_state ? config_.residual_state_base
                                     : config_.vertex_state_base,
        layout_.vertices * bytes_per_vertex);
    std::vector<std::uint32_t> result(layout_.vertices);
    for (std::size_t vertex = 0; vertex < result.size(); ++vertex) {
      result[vertex] =
          decode_u32(bytes, vertex * bytes_per_vertex +
                                (config_.split_pagerank_state ? 0 : 4));
    }
    return result;
  }

private:
  void validate_config() const {
    const bool full_pagerank =
        policy_.config().kind == GraphAlgorithmKind::kFullPageRank;
    const bool residual_pagerank =
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
    const bool pagerank = full_pagerank || residual_pagerank;
    const bool connected_components =
        policy_.config().kind == GraphAlgorithmKind::kConnectedComponents;
    const auto require = [](bool condition, const char *message) {
      if (!condition) {
        throw std::invalid_argument(
            std::string("invalid GraSU-ReGraph configuration - ") + message);
      }
    };
    require(layout_.vertices != 0, "empty graph");
    require(source_ < layout_.vertices, "source outside graph");
    require(policy_.config().vertices == layout_.vertices,
            "policy vertex count mismatch");
    require(policy_.config().kind == GraphAlgorithmKind::kWeightedSssp ||
                pagerank || connected_components,
            "unsupported algorithm policy");
    require(!pagerank || out_degrees_.size() == layout_.vertices,
            "PageRank degree vector mismatch");
    require(!pagerank || fixed_rounds_ != 0, "PageRank has zero rounds");
    require(!connected_components || fixed_rounds_ != 0,
            "connected components has zero round limit");
    require(pagerank || out_degrees_.empty(),
            "non-PageRank algorithm unexpectedly has degrees");
    require(!config_.split_pagerank_state ||
                (residual_pagerank && config_.sharded_runtime_placement),
            "split PageRank state requires sharded residual PageRank");
    require(!connected_components || layout_.vertices <= kReGraphValueMask,
            "connected-components label exceeds ReGraph value field");
    if (initial_state_.has_value()) {
      const std::unordered_set<std::uint32_t> active(
          initial_state_->active_vertices.begin(),
          initial_state_->active_vertices.end());
      require(initial_state_->primary.size() == layout_.vertices,
              "warm-start primary-state size mismatch");
      require(uses_auxiliary_state(policy_)
                  ? initial_state_->auxiliary.size() == layout_.vertices
                  : initial_state_->auxiliary.empty(),
              "warm-start auxiliary-state size mismatch");
      require(active.size() == initial_state_->active_vertices.size(),
              "warm-start frontier contains duplicates");
      require(std::all_of(active.begin(), active.end(),
                          [this](std::uint32_t vertex) {
                            return vertex < layout_.vertices;
                          }),
              "warm-start frontier vertex outside graph");
    }
    require(config_.memory_channels >= 4, "fewer than four HBM channels");
    require(config_.compute_pipelines != 0, "zero compute pipelines");
    require(!layout_.partitions.empty(), "empty PMA partition list");
    require(config_.partition_vertices != 0, "zero partition vertices");
    require(layout_.partitions.size() ==
                (layout_.vertices + config_.partition_vertices - 1) /
                    config_.partition_vertices,
            "PMA partition count mismatch");
    require(layout_.partition_vertices == config_.partition_vertices,
            "PMA partition span mismatch");
    require(config_.partition_vertices % kStateWordsPerBurst == 0,
            "partition span is not burst aligned");
    require(config_.source_state_buffer_stride >=
                layout_.partitions.size() * config_.partition_vertices *
                    state_bytes_per_vertex(policy_),
            "source-state double-buffer stride is too small");
    require(config_.source_state_buffer_stride % 4096 == 0,
            "source-state stride is not 4 KiB aligned");
    require(config_.source_buffer_vertices != 0, "zero source-cache capacity");
    require(config_.source_buffer_vertices % kStateWordsPerBurst == 0,
            "source-cache capacity is not burst aligned");
    require(config_.source_cache_request_fifo_depth != 0,
            "zero source request FIFO depth");
    require(config_.source_cache_response_fifo_depth != 0,
            "zero source response FIFO depth");
    require(config_.edge_lanes != 0 && config_.edge_lanes <= 8,
            "invalid edge lane count");
    require(kGraSuSegmentSlots % config_.edge_lanes == 0,
            "edge lanes do not divide PMA segment slots");
    require(config_.gather_banks == config_.edge_lanes,
            "gather banks differ from edge lanes");
    require(config_.gather_bypass_distance != 0, "zero gather bypass distance");
    require(config_.gather_pipeline_latency > config_.gather_bypass_distance,
            "gather latency does not exceed bypass distance");
    require(config_.gather_vertices_per_reset_cycle != 0,
            "zero gather reset width");
    require(config_.gather_vertices_per_merge_cycle == 2,
            "unsupported gather merge width");
    require(config_.axis_fifo_depth != 0, "zero AXIS FIFO depth");
    require(config_.gather_merger_fifo_depth != 0,
            "zero gather-merger FIFO depth");
    require(config_.merger_apply_fifo_depth != 0,
            "zero merger-apply FIFO depth");
    require(config_.apply_wrapper_fifo_depth != 0,
            "zero apply-wrapper FIFO depth");
    require(config_.reader_buffer_batches >=
                kGraSuSegmentSlots / config_.edge_lanes,
            "reader buffer cannot hold one PMA segment");
    require(config_.max_pending_requests != 0, "zero pending-request capacity");
    require(config_.max_outstanding_bursts != 0,
            "zero outstanding-burst capacity");
    require(config_.response_beats_per_cycle != 0, "zero response bandwidth");
    require(config_.apply_request_window != 0, "zero apply request window");
    require(config_.apply_pipeline_latency != 0, "zero apply pipeline latency");
    require(config_.apply_pipeline_capacity != 0,
            "zero apply pipeline capacity");
    require(config_.hbm_wrapper_pipeline_latency != 0,
            "zero HBM-wrapper latency");
    require(config_.hbm_wrapper_pipeline_capacity != 0,
            "zero HBM-wrapper capacity");
    require(config_.max_supersteps != 0, "zero maximum supersteps");
    require(config_.partition_address_stride != 0,
            "zero partition address stride");
    require(config_.partition_address_alignment != 0,
            "zero partition address alignment");
    require(config_.row_channel < config_.memory_channels,
            "row channel outside HBM");
    require(config_.source_state_channel < config_.memory_channels,
            "source-state channel outside HBM");
    require(config_.source_state_mirror_channel < config_.memory_channels,
            "source-state mirror channel outside HBM");
    require(config_.vertex_state_channel < config_.memory_channels,
            "vertex-state channel outside HBM");
    require(!config_.split_pagerank_state ||
                config_.residual_state_channel < config_.memory_channels,
            "residual-state channel outside HBM");
    require(!pagerank || config_.degree_channel < config_.memory_channels,
            "degree channel outside HBM");
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      const std::size_t expected_base = partition * config_.partition_vertices;
      const std::size_t expected_vertices = std::min(
          config_.partition_vertices, layout_.vertices - expected_base);
      if (part.vertices != layout_.vertices ||
          part.destination_base != expected_base ||
          part.destination_vertices != expected_vertices) {
        throw std::invalid_argument(
            "GraSU-ReGraph PMA partitions are not contiguous");
      }
    }
  }

  void construct_partition_plans() {
    partition_plans_.reserve(layout_.partitions.size());
    if (config_.sharded_runtime_placement) {
      const std::vector<std::size_t> update_counts =
          config_.runtime_physical_updates_per_shard.empty()
              ? std::vector<std::size_t>(layout_.partitions.size(), 0)
              : config_.runtime_physical_updates_per_shard;
      runtime_plan_ = build_grasu_regraph_runtime_plan(
          layout_, update_counts, config_.cache_segments_per_half,
          kGraSuReGraphU55cGraphChannels,
          config_.runtime_channel_capacity_bytes);
      for (std::size_t partition = 0; partition < layout_.partitions.size();
           ++partition) {
        const GraSuPmaLayout &part = layout_.partitions[partition];
        const auto row =
            find_grasu_regraph_runtime_region(*runtime_plan_, partition, "row");
        ReGraphPartitionPlan plan{
            .destination_base = part.destination_base,
            .destination_vertices = part.destination_vertices,
            .row_base = row.channel_offset_bytes,
            .row_channel = row.channel,
        };
        for (std::size_t lane = 0; lane < 4; ++lane) {
          const auto pma = find_grasu_regraph_runtime_region(
              *runtime_plan_, partition, "pma" + std::to_string(lane));
          plan.pma_base[lane] = pma.channel_offset_bytes;
          plan.pma_channel[lane] = pma.channel;
        }
        partition_plans_.push_back(plan);
      }
      return;
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      partition_plans_.push_back(ReGraphPartitionPlan{
          .destination_base = part.destination_base,
          .destination_vertices = part.destination_vertices,
          .row_base = address_plan_.row_bases.at(partition),
          .row_channel = config_.row_channel,
          .pma_base = {address_plan_.pma_bases.at(partition),
                       address_plan_.pma_bases.at(partition),
                       address_plan_.pma_bases.at(partition),
                       address_plan_.pma_bases.at(partition)},
          .pma_channel = {0, 1, 2, 3},
      });
    }
  }

  void initialize_sharded_graph_payloads() {
    if (!runtime_plan_.has_value()) {
      return;
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      const ReGraphPartitionPlan &plan = partition_plans_[partition];
      std::vector<std::uint8_t> rows;
      rows.reserve(part.row_slot_bounds.size() * sizeof(std::uint64_t));
      for (const auto &[begin, end] : part.row_slot_bounds) {
        const std::uint64_t packed =
            (static_cast<std::uint64_t>(begin) << 32) | end;
        for (std::size_t byte = 0; byte < sizeof(packed); ++byte) {
          rows.push_back(static_cast<std::uint8_t>(packed >> (byte * 8)));
        }
      }
      const std::uint32_t total_slots = part.row_slot_bounds.empty()
                                            ? 0
                                            : part.row_slot_bounds.back().second;
      const std::uint64_t sentinel =
          (static_cast<std::uint64_t>(total_slots) << 32) | total_slots;
      for (std::size_t byte = 0; byte < sizeof(sentinel); ++byte) {
        rows.push_back(static_cast<std::uint8_t>(sentinel >> (byte * 8)));
      }
      backend_.initialize_payload(plan.row_channel, plan.row_base, rows);

      for (std::size_t segment = 0; segment < part.segments.size(); ++segment) {
        const std::size_t local = segment >> 1;
        const std::size_t parity = segment & 1U;
        const std::size_t lane = local < config_.cache_segments_per_half
                                     ? parity * 2
                                     : parity * 2 + 1;
        std::vector<std::uint8_t> bytes;
        bytes.reserve(kGraSuSegmentBytes);
        for (const std::uint32_t word : part.segments[segment]) {
          for (std::size_t byte = 0; byte < sizeof(word); ++byte) {
            bytes.push_back(static_cast<std::uint8_t>(word >> (byte * 8)));
          }
        }
        backend_.initialize_payload(
            plan.pma_channel[lane],
            plan.pma_base[lane] + local * kGraSuSegmentBytes, bytes);
      }
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  std::unique_ptr<FixedAxiPort>
  make_source_stream_port(const std::string &name) {
    FixedAxiPortConfig source = port_config(
        config_, config_.source_state_channel, next_initiator_++, 64);
    source.stream_read_beats = true;
    source.read_beat_fifo_depth = config_.source_cache_response_fifo_depth;
    source.read_reorder_capacity = config_.max_outstanding_bursts * 16;
    return std::make_unique<FixedAxiPort>(name, clock_id_, source, backend_);
  }

  void construct_ports() {
    const bool pagerank =
        policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
    if (pagerank) {
      source_prepare_state_read_port_ =
          make_port("grasu-regraph-source-prepare-state-read",
                    config_.vertex_state_channel, 64);
      source_prepare_degree_read_port_ =
          make_port("grasu-regraph-source-prepare-degree-read",
                    config_.degree_channel, 64);
      source_prepare_primary_write_port_ =
          make_port("grasu-regraph-source-prepare-primary-write",
                    config_.source_state_channel, 64);
      source_prepare_mirror_write_port_ =
          make_port("grasu-regraph-source-prepare-mirror-write",
                    config_.source_state_mirror_channel, 64);
    }
    pipelines_.resize(config_.compute_pipelines);
    for (std::size_t index = 0; index < pipelines_.size(); ++index) {
      Pipeline &pipeline = pipelines_[index];
      const std::string prefix =
          "grasu-regraph-p" + std::to_string(index) + "-";
      pipeline.edge_axis = std::make_unique<Fifo<PmaEdgeBatch>>(
          prefix + "pma-axis", clock_id_, config_.axis_fifo_depth);
      pipeline.source_request_axis =
          std::make_unique<Fifo<ReGraphSourceCacheRequest>>(
              prefix + "source-cache-request-axis", clock_id_,
              config_.source_cache_request_fifo_depth);
      pipeline.source_response_axis =
          std::make_unique<Fifo<ReGraphSourceCacheResponse>>(
              prefix + "source-cache-response-axis", clock_id_,
              config_.source_cache_response_fifo_depth);
      pipeline.gather_axis = std::make_unique<Fifo<ReGraphGatherRow>>(
          prefix + "gather-merger-axis", clock_id_,
          config_.gather_merger_fifo_depth);
      pipeline.merger_axis = std::make_unique<Fifo<ReGraphMergedBurst>>(
          prefix + "merger-apply-axis", clock_id_,
          config_.merger_apply_fifo_depth);
      pipeline.wrapper_axis = std::make_unique<Fifo<ReGraphAppliedBurst>>(
          prefix + "apply-wrapper-axis", clock_id_,
          config_.apply_wrapper_fifo_depth);
      pipeline.row_port = make_port(prefix + "row", config_.row_channel, 8);
      pipeline.source_state_port =
          make_source_stream_port(prefix + "source-state");
      if (pagerank) {
        pipeline.degree_port =
            make_port(prefix + "degree", config_.degree_channel, 4);
      }
      for (std::size_t channel = 0; channel < pipeline.pma_ports.size();
           ++channel) {
        pipeline.pma_ports[channel] =
            make_port(prefix + "pma" + std::to_string(channel), channel, 64);
      }
      pipeline.apply_state_read_port = make_port(
          prefix + "apply-state-read", config_.vertex_state_channel, 64);
      pipeline.apply_state_write_port = make_port(
          prefix + "apply-state-write", config_.vertex_state_channel, 64);
      if (config_.split_pagerank_state) {
        pipeline.apply_auxiliary_read_port = make_port(
            prefix + "apply-residual-read", config_.residual_state_channel, 64);
        pipeline.apply_auxiliary_write_port =
            make_port(prefix + "apply-residual-write",
                      config_.residual_state_channel, 64);
      }
      pipeline.source_state_primary_write_port =
          make_port(prefix + "source-state-primary-write",
                    config_.source_state_channel, 64);
      pipeline.source_state_mirror_write_port =
          make_port(prefix + "source-state-mirror-write",
                    config_.source_state_mirror_channel, 64);
    }
  }

  void initialize_state() {
    const std::size_t bytes_per_vertex = state_bytes_per_vertex(policy_);
    const std::size_t padded_vertices =
        layout_.partitions.size() * config_.partition_vertices;
    std::vector<std::uint8_t> bytes(padded_vertices * bytes_per_vertex);
    const std::unordered_set<std::uint32_t> initial_active =
        initial_state_.has_value()
            ? std::unordered_set<std::uint32_t>(
                  initial_state_->active_vertices.begin(),
                  initial_state_->active_vertices.end())
            : std::unordered_set<std::uint32_t>{};
    for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
      std::uint32_t encoded =
          policy_.config().kind == GraphAlgorithmKind::kWeightedSssp ||
                  policy_.config().kind ==
                      GraphAlgorithmKind::kConnectedComponents
              ? kReGraphInfinity
              : GraphAlgorithmPolicy::float_to_word(0.0F);
      if (vertex < layout_.vertices) {
        const AlgorithmVertexState state =
            initial_state_.has_value()
                ? AlgorithmVertexState{
                      .primary = initial_state_->primary[vertex],
                      .auxiliary = uses_auxiliary_state(policy_)
                                       ? initial_state_->auxiliary[vertex]
                                       : 0U,
                  }
                : policy_.initial_state(static_cast<std::uint32_t>(vertex));
        const bool active =
            initial_state_.has_value()
                ? initial_active.contains(static_cast<std::uint32_t>(vertex))
                : policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
                      policy_.config().kind ==
                          GraphAlgorithmKind::kConnectedComponents ||
                      vertex == source_;
        encoded = encode_policy_value(policy_, state.primary, active);
        if (uses_auxiliary_state(policy_)) {
          for (std::size_t byte = 0; byte < 4; ++byte) {
            bytes[vertex * bytes_per_vertex + 4 + byte] =
                static_cast<std::uint8_t>(state.auxiliary >> (byte * 8));
          }
        }
      }
      for (std::size_t byte = 0; byte < 4; ++byte) {
        bytes[vertex * bytes_per_vertex + byte] =
            static_cast<std::uint8_t>(encoded >> (byte * 8));
      }
    }
    if (config_.split_pagerank_state) {
      std::vector<std::uint8_t> primary_bytes(padded_vertices * 4);
      std::vector<std::uint8_t> auxiliary_bytes(padded_vertices * 4);
      for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
        std::copy_n(bytes.begin() + static_cast<std::ptrdiff_t>(vertex * 8), 4,
                    primary_bytes.begin() +
                        static_cast<std::ptrdiff_t>(vertex * 4));
        std::copy_n(
            bytes.begin() + static_cast<std::ptrdiff_t>(vertex * 8 + 4), 4,
            auxiliary_bytes.begin() + static_cast<std::ptrdiff_t>(vertex * 4));
      }
      backend_.initialize_payload(config_.vertex_state_channel,
                                  config_.vertex_state_base, primary_bytes);
      backend_.initialize_payload(config_.residual_state_channel,
                                  config_.residual_state_base, auxiliary_bytes);
    } else {
      backend_.initialize_payload(config_.vertex_state_channel,
                                  config_.vertex_state_base, bytes);
    }
    std::vector<std::uint8_t> source_bytes(padded_vertices * 4);
    if (iteration_context_ == nullptr) {
      for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
        std::copy_n(
            bytes.begin() +
                static_cast<std::ptrdiff_t>(vertex * bytes_per_vertex),
            4, source_bytes.begin() + static_cast<std::ptrdiff_t>(vertex * 4));
      }
    }
    backend_.initialize_payload(config_.source_state_channel,
                                config_.source_state_base, source_bytes);
    backend_.initialize_payload(config_.source_state_mirror_channel,
                                config_.source_state_base, source_bytes);
    if ((policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
         policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) &&
        config_.initialize_degree_payload) {
      std::vector<std::uint8_t> degree_bytes(layout_.vertices * 4);
      for (std::size_t vertex = 0; vertex < out_degrees_.size(); ++vertex) {
        for (std::size_t byte = 0; byte < 4; ++byte) {
          degree_bytes[vertex * 4 + byte] =
              static_cast<std::uint8_t>(out_degrees_[vertex] >> (byte * 8));
        }
      }
      backend_.initialize_payload(config_.degree_channel, config_.degree_base,
                                  degree_bytes);
    }
  }

  void construct_components() {
    if (iteration_context_ != nullptr) {
      source_prepare_ = std::make_unique<ReGraphPageRankSourcePrepare>(
          "grasu-regraph-pagerank-source-prepare", clock_id_, layout_.vertices,
          policy_, config_, *source_prepare_state_read_port_,
          *source_prepare_degree_read_port_,
          *source_prepare_primary_write_port_,
          *source_prepare_mirror_write_port_, *iteration_context_);
    }
    std::vector<GraSuReGraphWorker> workers;
    workers.reserve(pipelines_.size());
    for (std::size_t index = 0; index < pipelines_.size(); ++index) {
      Pipeline &pipeline = pipelines_[index];
      const std::string prefix =
          "grasu-regraph-p" + std::to_string(index) + "-";
      std::array<FixedAxiPort *, 4> pma{};
      for (std::size_t channel = 0; channel < pma.size(); ++channel) {
        pma[channel] = pipeline.pma_ports[channel].get();
      }
      pipeline.source_hbm_reader = std::make_unique<ReGraphSourceHbmReader>(
          prefix + "source-hbm-reader", clock_id_, config_, policy_,
          *pipeline.source_request_axis, *pipeline.source_response_axis,
          *pipeline.source_state_port);
      pipeline.reader = make_legacy_pma_reader(
          prefix + "reader", clock_id_, layout_.vertices, policy_, config_,
          ReGraphPartitionReader::Ports{
              .rows = pipeline.row_port.get(),
              .degree = pipeline.degree_port.get(),
              .pma = pma,
              .output = pipeline.edge_axis.get(),
              .source_requests = pipeline.source_request_axis.get(),
              .source_responses = pipeline.source_response_axis.get(),
          });
      pipeline.gather = make_regraph_gather(
          prefix + "gather", clock_id_, layout_.vertices, policy_, config_,
          *pipeline.edge_axis, *pipeline.gather_axis, *pipeline.reader);
      pipeline.merger = make_regraph_merger(
          prefix + "merger", clock_id_, config_, *pipeline.gather_axis,
          *pipeline.merger_axis);
      pipeline.apply = make_regraph_apply(
          prefix + "apply", clock_id_, layout_.vertices, policy_, config_,
          *pipeline.merger_axis, *pipeline.wrapper_axis,
          *pipeline.apply_state_read_port, *pipeline.apply_state_write_port,
          pipeline.degree_port.get(),
          iteration_context_ != nullptr
              ? static_cast<const ReGraphReaderContext &>(*iteration_context_)
              : static_cast<const ReGraphReaderContext &>(*pipeline.reader),
          pipeline.apply_auxiliary_read_port.get(),
          pipeline.apply_auxiliary_write_port.get());
      pipeline.wrapper = make_regraph_writeback(
          prefix + "hbm-wrapper", clock_id_, config_, policy_,
          *pipeline.wrapper_axis, *pipeline.source_state_primary_write_port,
          *pipeline.source_state_mirror_write_port);
      workers.push_back(GraSuReGraphWorker{
          .source_hbm = pipeline.source_hbm_reader.get(),
          .reader = pipeline.reader.get(),
          .gather = pipeline.gather.get(),
          .merger = pipeline.merger.get(),
          .apply = pipeline.apply.get(),
          .wrapper = pipeline.wrapper.get(),
          .partition = std::nullopt,
      });
    }
    controller_ = std::make_unique<GraSuReGraphController>(
        "grasu-regraph-controller", clock_id_, policy_.config().kind,
        policy_.config().kind == GraphAlgorithmKind::kWeightedSssp &&
                fixed_rounds_ == 0
            ? config_.max_supersteps
            : fixed_rounds_,
        policy_.config().kind == GraphAlgorithmKind::kWeightedSssp &&
            fixed_rounds_ != 0,
        partition_plans_, std::move(workers), iteration_context_.get(),
        source_prepare_.get(), config_.shared_downstream,
        config_.sharded_runtime_placement && config_.compute_pipelines == 4 &&
            config_.shared_downstream);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    if (source_prepare_ != nullptr &&
        (!source_prepare_state_read_port_->idle() ||
         !source_prepare_degree_read_port_->idle() ||
         !source_prepare_primary_write_port_->idle() ||
         !source_prepare_mirror_write_port_->idle())) {
      return false;
    }
    return std::all_of(
        pipelines_.begin(), pipelines_.end(), [](const Pipeline &pipeline) {
          if (!pipeline.source_request_axis->empty() ||
              !pipeline.source_response_axis->empty() ||
              !pipeline.edge_axis->empty() || !pipeline.gather_axis->empty() ||
              !pipeline.merger_axis->empty() ||
              !pipeline.wrapper_axis->empty() || !pipeline.row_port->idle() ||
              !pipeline.source_state_port->idle() ||
              !pipeline.apply_state_read_port->idle() ||
              !pipeline.apply_state_write_port->idle() ||
              (pipeline.apply_auxiliary_read_port != nullptr &&
               (!pipeline.apply_auxiliary_read_port->idle() ||
                !pipeline.apply_auxiliary_write_port->idle())) ||
              !pipeline.source_state_primary_write_port->idle() ||
              !pipeline.source_state_mirror_write_port->idle()) {
            return false;
          }
          if (pipeline.degree_port != nullptr &&
              !pipeline.degree_port->idle()) {
            return false;
          }
          return std::all_of(pipeline.pma_ports.begin(),
                             pipeline.pma_ports.end(),
                             [](const auto &port) { return port->idle(); });
        });
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPartitionedPmaLayout layout_;
  std::uint32_t source_{};
  GraSuReGraphConfig config_;
  GraphAlgorithmPolicy policy_;
  std::vector<std::uint32_t> out_degrees_;
  std::optional<AlgorithmInitialState> initial_state_;
  std::size_t fixed_rounds_{};
  GraSuPartitionAddressPlan address_plan_;
  std::vector<ReGraphPartitionPlan> partition_plans_;
  std::optional<GraSuReGraphRuntimePlan> runtime_plan_;
  std::unique_ptr<ReGraphIterationContext> iteration_context_;
  std::unique_ptr<FixedAxiPort> source_prepare_state_read_port_;
  std::unique_ptr<FixedAxiPort> source_prepare_degree_read_port_;
  std::unique_ptr<FixedAxiPort> source_prepare_primary_write_port_;
  std::unique_ptr<FixedAxiPort> source_prepare_mirror_write_port_;
  std::unique_ptr<ReGraphPageRankSourcePrepare> source_prepare_;
  std::vector<Pipeline> pipelines_;
  std::unique_ptr<GraSuReGraphController> controller_;
  std::uint32_t next_initiator_{3100};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

class GraSuNativeReGraphSsspSystem::Impl {
public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       std::size_t vertices, std::size_t compact_edge_slots,
       std::uint32_t source, std::size_t supersteps, GraSuReGraphConfig config)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        vertices_(vertices), compact_edge_slots_(compact_edge_slots),
        source_(source), supersteps_(supersteps), config_(config),
        policy_(AlgorithmPolicyConfig{
            .kind = GraphAlgorithmKind::kWeightedSssp,
            .vertices = vertices,
            .source = source,
        }),
        edge_burst_axis_("grasu-native-edge-array-axis", clock_id_,
                         config_.edge_array_fifo_depth),
        scatter_axis_("grasu-native-scatter-axis", clock_id_,
                      config_.axis_fifo_depth),
        source_request_axis_("grasu-native-source-cache-request-axis",
                             clock_id_,
                             config_.source_cache_request_fifo_depth),
        source_response_axis_("grasu-native-source-cache-response-axis",
                              clock_id_,
                              config_.source_cache_response_fifo_depth),
        gather_axis_("grasu-native-gather-merger-axis", clock_id_,
                     config_.gather_merger_fifo_depth),
        merger_axis_("grasu-native-merger-apply-axis", clock_id_,
                     config_.merger_apply_fifo_depth),
        wrapper_axis_("grasu-native-apply-wrapper-axis", clock_id_,
                      config_.apply_wrapper_fifo_depth),
        start_cycle_(scheduler_.clock(clock_id_).completed_cycles) {
    validate_config();
    construct_ports();
    initialize_state();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error(
          "native GraSU-ReGraph system registered more than once");
    }
    scheduler_.add_component(edge_burst_axis_);
    scheduler_.add_component(scatter_axis_);
    scheduler_.add_component(source_request_axis_);
    scheduler_.add_component(source_response_axis_);
    scheduler_.add_component(gather_axis_);
    scheduler_.add_component(merger_axis_);
    scheduler_.add_component(wrapper_axis_);
    edge_array_port_->register_components(scheduler_);
    source_state_port_->register_components(scheduler_);
    apply_state_read_port_->register_components(scheduler_);
    apply_state_write_port_->register_components(scheduler_);
    source_state_primary_write_port_->register_components(scheduler_);
    source_state_mirror_write_port_->register_components(scheduler_);
    scheduler_.add_component(*source_hbm_reader_);
    scheduler_.add_component(*edge_reader_);
    scheduler_.add_component(*scatter_);
    scheduler_.add_component(*gather_);
    scheduler_.add_component(*merger_);
    scheduler_.add_component(*apply_);
    scheduler_.add_component(*wrapper_);
    scheduler_.add_component(*controller_);
    registered_ = true;
  }

  [[nodiscard]] bool done() const noexcept {
    return registered_ && controller_->done() && all_ports_idle();
  }

  [[nodiscard]] bool failed() const noexcept { return false; }

  [[nodiscard]] const std::string &failure() const noexcept {
    static const std::string none;
    return none;
  }

  [[nodiscard]] GraSuNativeReGraphCounters counters() const noexcept {
    GraSuNativeReGraphCounters result;
    GraSuReGraphCounters &pipeline = result.pipeline;
    const auto account_axi_port = [&pipeline](const FixedAxiPort &port) {
      pipeline.axi_request_fifo_stalls += port.requests().stats().push_stalls;
      pipeline.axi_backend_submit_stalls +=
          port.master().stats().backend_submit_stalls;
    };
    pipeline.state_bytes_per_vertex = state_bytes_per_vertex(policy_);
    pipeline.destination_partitions = 1;
    pipeline.supersteps = controller_->rounds();
    pipeline.partition_passes = controller_->rounds();
    pipeline.source_state_reads = source_hbm_reader_->requests();
    pipeline.source_cache_requests = scatter_->source_requests();
    pipeline.source_cache_request_markers = scatter_->source_request_markers();
    pipeline.source_cache_lines = scatter_->source_lines();
    pipeline.source_cache_lane_writes = scatter_->source_lane_writes();
    pipeline.source_cache_response_markers =
        scatter_->source_response_markers();
    pipeline.source_cache_wait_cycles = scatter_->source_wait_cycles();
    pipeline.source_cache_output_stall_cycles =
        source_hbm_reader_->output_stall_cycles();
    pipeline.source_cache_request_fifo_max_occupancy =
        source_request_axis_.stats().max_occupancy;
    pipeline.source_cache_response_fifo_max_occupancy =
        source_response_axis_.stats().max_occupancy;
    pipeline.source_state_writes = wrapper_->source_writes();
    pipeline.edge_batches_scanned = gather_->batches_scanned();
    pipeline.live_edges_scanned = gather_->live_edges();
    pipeline.active_edges_mapped = gather_->active_edges();
    pipeline.gather_reset_cycles = gather_->reset_cycles();
    pipeline.gather_merge_cycles = gather_->merge_cycles();
    pipeline.gather_pipeline_drain_cycles = gather_->pipeline_drain_cycles();
    pipeline.gather_output_stall_cycles = gather_->output_stall_cycles();
    pipeline.gather_bank_conflict_cycles = gather_->conflict_cycles();
    pipeline.gather_bank_updates = gather_->bank_updates();
    pipeline.gather_bypass_hits = gather_->bypass_hits();
    pipeline.gather_bypass_misses = gather_->bypass_misses();
    pipeline.gather_cross_bank_reductions = gather_->cross_bank_reductions();
    pipeline.gather_rows_emitted = gather_->rows_emitted();
    pipeline.merger_rows_consumed = merger_->rows_consumed();
    pipeline.merger_bursts_emitted = merger_->bursts_emitted();
    pipeline.merger_output_stall_cycles = merger_->output_stall_cycles();
    pipeline.apply_state_reads = apply_->reads();
    pipeline.apply_state_writes = apply_->writes();
    pipeline.apply_input_bursts = apply_->input_bursts();
    pipeline.apply_output_stall_cycles = apply_->output_stall_cycles();
    pipeline.apply_read_window_stalls = apply_->read_window_stalls();
    pipeline.apply_pipeline_capacity_stalls =
        apply_->pipeline_capacity_stalls();
    pipeline.apply_write_window_stalls = apply_->write_window_stalls();
    pipeline.apply_max_reads_inflight = apply_->max_reads_inflight();
    pipeline.apply_max_pipeline_occupancy = apply_->max_pipeline_occupancy();
    pipeline.apply_max_writes_inflight = apply_->max_writes_inflight();
    pipeline.hbm_wrapper_input_bursts = wrapper_->input_bursts();
    pipeline.hbm_wrapper_pipeline_capacity_stalls =
        wrapper_->pipeline_capacity_stalls();
    pipeline.hbm_wrapper_write_window_stalls = wrapper_->write_window_stalls();
    pipeline.hbm_wrapper_max_pipeline_occupancy =
        wrapper_->max_pipeline_occupancy();
    pipeline.hbm_wrapper_max_writes_inflight = wrapper_->max_writes_inflight();
    pipeline.gather_merger_fifo_max_occupancy =
        gather_axis_.stats().max_occupancy;
    pipeline.merger_apply_fifo_max_occupancy =
        merger_axis_.stats().max_occupancy;
    pipeline.apply_wrapper_fifo_max_occupancy =
        wrapper_axis_.stats().max_occupancy;
    pipeline.activated_vertices = apply_->total_activated();
    pipeline.source_state_read_bytes = source_hbm_reader_->read_bytes();
    pipeline.source_state_write_bytes = pipeline.source_state_writes *
                                        kStateWordsPerBurst *
                                        state_bytes_per_vertex(policy_);
    pipeline.apply_read_bytes = pipeline.apply_state_reads *
                                kStateWordsPerBurst *
                                state_bytes_per_vertex(policy_);
    pipeline.apply_write_bytes = pipeline.apply_state_writes *
                                 kStateWordsPerBurst *
                                 state_bytes_per_vertex(policy_);
    account_axi_port(*edge_array_port_);
    account_axi_port(*source_state_port_);
    account_axi_port(*apply_state_read_port_);
    account_axi_port(*apply_state_write_port_);
    account_axi_port(*source_state_primary_write_port_);
    account_axi_port(*source_state_mirror_write_port_);
    pipeline.axis_push_stalls = edge_burst_axis_.stats().push_stalls +
                                scatter_axis_.stats().push_stalls +
                                source_request_axis_.stats().push_stalls +
                                source_response_axis_.stats().push_stalls +
                                gather_axis_.stats().push_stalls +
                                merger_axis_.stats().push_stalls +
                                wrapper_axis_.stats().push_stalls;
    pipeline.start_cycle = start_cycle_;
    pipeline.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    pipeline.last_iteration_error = apply_->iteration_error();
    result.edge_array_requests = edge_reader_->requests();
    result.edge_array_bursts = edge_reader_->bursts();
    result.edge_array_slots_scanned = gather_->slots_scanned();
    result.edge_array_read_bytes =
        result.edge_array_requests * compact_edge_slots_ * 8;
    result.edge_array_output_stall_cycles = edge_reader_->output_stall_cycles();
    result.cross_source_round_bursts = scatter_->cross_source_round_bursts();
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> distances() const {
    const auto bytes = backend_.inspect_payload(
        config_.vertex_state_channel, config_.vertex_state_base,
        vertices_ * state_bytes_per_vertex(policy_));
    std::vector<std::uint32_t> result(vertices_);
    for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
      result[vertex] = policy_distance(decode_u32(bytes, vertex * 4));
    }
    return result;
  }

private:
  void validate_config() const {
    const std::size_t highest_channel = std::max(
        {config_.edge_array_channel, config_.source_state_channel,
         config_.source_state_mirror_channel, config_.vertex_state_channel});
    if (vertices_ == 0 || vertices_ > config_.partition_vertices ||
        vertices_ > 65536 || source_ >= vertices_ || supersteps_ == 0 ||
        supersteps_ > config_.max_supersteps || compact_edge_slots_ < 8 ||
        compact_edge_slots_ % 8 != 0 ||
        compact_edge_slots_ > std::numeric_limits<std::uint32_t>::max() / 8U ||
        config_.memory_channels <= highest_channel ||
        config_.partition_vertices != 65536 ||
        config_.partition_vertices % kStateWordsPerBurst != 0 ||
        config_.source_buffer_vertices != 4096 ||
        config_.source_buffer_vertices % kStateWordsPerBurst != 0 ||
        config_.source_state_buffer_stride <
            config_.partition_vertices * state_bytes_per_vertex(policy_) ||
        config_.source_state_buffer_stride % 4096 != 0 ||
        config_.source_cache_request_fifo_depth == 0 ||
        config_.source_cache_response_fifo_depth == 0 ||
        config_.edge_array_fifo_depth == 0 || config_.axis_fifo_depth == 0 ||
        config_.gather_merger_fifo_depth == 0 ||
        config_.merger_apply_fifo_depth == 0 ||
        config_.apply_wrapper_fifo_depth == 0 || config_.edge_lanes != 8 ||
        config_.gather_banks != 8 || config_.gather_bypass_distance == 0 ||
        config_.gather_pipeline_latency <= config_.gather_bypass_distance ||
        config_.gather_vertices_per_reset_cycle == 0 ||
        config_.gather_vertices_per_merge_cycle != 2 ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.apply_request_window == 0 ||
        config_.apply_pipeline_latency == 0 ||
        config_.apply_pipeline_capacity == 0 ||
        config_.hbm_wrapper_pipeline_latency == 0 ||
        config_.hbm_wrapper_pipeline_capacity == 0) {
      throw std::invalid_argument("invalid native GraSU-ReGraph configuration");
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  std::unique_ptr<FixedAxiPort> make_stream_port(const std::string &name,
                                                 std::size_t channel,
                                                 std::size_t read_fifo_depth) {
    FixedAxiPortConfig port =
        port_config(config_, channel, next_initiator_++, 64);
    port.stream_read_beats = true;
    port.read_beat_fifo_depth = read_fifo_depth;
    port.read_reorder_capacity = config_.max_outstanding_bursts * 16;
    return std::make_unique<FixedAxiPort>(name, clock_id_, port, backend_);
  }

  void construct_ports() {
    edge_array_port_ =
        make_stream_port("grasu-native-edge-array", config_.edge_array_channel,
                         config_.edge_array_fifo_depth);
    source_state_port_ = make_stream_port(
        "grasu-native-source-state", config_.source_state_channel,
        config_.source_cache_response_fifo_depth);
    apply_state_read_port_ = make_port("grasu-native-apply-state-read",
                                       config_.vertex_state_channel, 64);
    apply_state_write_port_ = make_port("grasu-native-apply-state-write",
                                        config_.vertex_state_channel, 64);
    source_state_primary_write_port_ =
        make_port("grasu-native-source-state-primary-write",
                  config_.source_state_channel, 64);
    source_state_mirror_write_port_ =
        make_port("grasu-native-source-state-mirror-write",
                  config_.source_state_mirror_channel, 64);
  }

  void initialize_state() {
    std::vector<std::uint8_t> bytes(config_.partition_vertices * 4);
    for (std::size_t vertex = 0; vertex < config_.partition_vertices;
         ++vertex) {
      const std::uint32_t encoded =
          vertex == source_
              ? encode_distance(0, true)
              : encode_distance(GraphAlgorithmPolicy::kSsspInfinity, false);
      for (std::size_t byte = 0; byte < 4; ++byte) {
        bytes[vertex * 4 + byte] =
            static_cast<std::uint8_t>(encoded >> (byte * 8));
      }
    }
    backend_.initialize_payload(config_.vertex_state_channel,
                                config_.vertex_state_base, bytes);
    backend_.initialize_payload(config_.source_state_channel,
                                config_.source_state_base, bytes);
    backend_.initialize_payload(config_.source_state_mirror_channel,
                                config_.source_state_base, bytes);
  }

  void construct_components() {
    source_hbm_reader_ = std::make_unique<ReGraphSourceHbmReader>(
        "grasu-native-source-hbm-reader", clock_id_, config_, policy_,
        source_request_axis_, source_response_axis_, *source_state_port_);
    edge_reader_ = std::make_unique<NativeEdgeArrayHbmReader>(
        "grasu-native-edge-array-reader", clock_id_, compact_edge_slots_,
        config_, edge_burst_axis_, *edge_array_port_);
    scatter_ = std::make_unique<NativeEdgeArrayScatter>(
        "grasu-native-edge-array-scatter", clock_id_, vertices_, config_,
        edge_burst_axis_, scatter_axis_, source_request_axis_,
        source_response_axis_, *edge_reader_);
    gather_ = make_regraph_gather(
        "grasu-native-regraph-gather", clock_id_, vertices_, policy_, config_,
        scatter_axis_, gather_axis_, *scatter_);
    merger_ = make_regraph_merger("grasu-native-regraph-merger",
                                              clock_id_, config_, gather_axis_,
                                              merger_axis_);
    apply_ = make_regraph_apply(
        "grasu-native-regraph-apply", clock_id_, vertices_, policy_, config_,
        merger_axis_, wrapper_axis_, *apply_state_read_port_,
        *apply_state_write_port_, nullptr, *scatter_);
    wrapper_ = make_regraph_writeback(
        "grasu-native-regraph-hbm-wrapper", clock_id_, config_, policy_,
        wrapper_axis_, *source_state_primary_write_port_,
        *source_state_mirror_write_port_);
    controller_ = std::make_unique<GraSuNativeReGraphController>(
        "grasu-native-regraph-controller", clock_id_, supersteps_, vertices_,
        *source_hbm_reader_, *edge_reader_, *scatter_, *gather_, *merger_,
        *apply_, *wrapper_);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    return edge_burst_axis_.empty() && scatter_axis_.empty() &&
           source_request_axis_.empty() && source_response_axis_.empty() &&
           gather_axis_.empty() && merger_axis_.empty() &&
           wrapper_axis_.empty() && edge_array_port_->idle() &&
           source_state_port_->idle() && apply_state_read_port_->idle() &&
           apply_state_write_port_->idle() &&
           source_state_primary_write_port_->idle() &&
           source_state_mirror_write_port_->idle();
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  std::size_t vertices_{};
  std::size_t compact_edge_slots_{};
  std::uint32_t source_{};
  std::size_t supersteps_{};
  GraSuReGraphConfig config_;
  GraphAlgorithmPolicy policy_;
  Fifo<NativeEdgeArrayBurst> edge_burst_axis_;
  Fifo<PmaEdgeBatch> scatter_axis_;
  Fifo<ReGraphSourceCacheRequest> source_request_axis_;
  Fifo<ReGraphSourceCacheResponse> source_response_axis_;
  Fifo<ReGraphGatherRow> gather_axis_;
  Fifo<ReGraphMergedBurst> merger_axis_;
  Fifo<ReGraphAppliedBurst> wrapper_axis_;
  std::unique_ptr<FixedAxiPort> edge_array_port_;
  std::unique_ptr<FixedAxiPort> source_state_port_;
  std::unique_ptr<FixedAxiPort> apply_state_read_port_;
  std::unique_ptr<FixedAxiPort> apply_state_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_primary_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_mirror_write_port_;
  std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader_;
  std::unique_ptr<NativeEdgeArrayHbmReader> edge_reader_;
  std::unique_ptr<NativeEdgeArrayScatter> scatter_;
  std::unique_ptr<ReGraphGatherEngine> gather_;
  std::unique_ptr<ReGraphMergerEngine> merger_;
  std::unique_ptr<ReGraphApplyEngine> apply_;
  std::unique_ptr<ReGraphWritebackEngine> wrapper_;
  std::unique_ptr<GraSuNativeReGraphController> controller_;
  std::uint32_t next_initiator_{4100};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::uint32_t source, GraSuReGraphConfig config)
    : impl_(std::make_unique<Impl>(
          scheduler, clock_id, backend,
          one_partition_layout(layout, config.partition_vertices),
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kWeightedSssp,
              .vertices = layout.vertices,
              .source = source,
          }),
          std::vector<std::uint32_t>{}, 0, config)) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, GraphAlgorithmPolicy policy,
    std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : impl_(std::make_unique<Impl>(
          scheduler, clock_id, backend,
          one_partition_layout(std::move(layout), config.partition_vertices),
          std::move(policy), std::move(out_degrees), fixed_rounds, config,
          std::move(initial_state))) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(Scheduler &scheduler,
                                               ClockId clock_id,
                                               MemoryBackend &backend,
                                               GraSuPartitionedPmaLayout layout,
                                               std::uint32_t source,
                                               GraSuReGraphConfig config)
    : impl_(
          std::make_unique<Impl>(scheduler, clock_id, backend, layout,
                                 GraphAlgorithmPolicy(AlgorithmPolicyConfig{
                                     .kind = GraphAlgorithmKind::kWeightedSssp,
                                     .vertices = layout.vertices,
                                     .source = source,
                                 }),
                                 std::vector<std::uint32_t>{}, 0, config)) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, GraphAlgorithmPolicy policy,
    std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend,
                                   std::move(layout), std::move(policy),
                                   std::move(out_degrees), fixed_rounds, config,
                                   std::move(initial_state))) {}

GraSuReGraphSsspSystem::~GraSuReGraphSsspSystem() = default;

void GraSuReGraphSsspSystem::register_components() {
  impl_->register_components();
}

bool GraSuReGraphSsspSystem::done() const noexcept { return impl_->done(); }

bool GraSuReGraphSsspSystem::failed() const noexcept { return impl_->failed(); }

const std::string &GraSuReGraphSsspSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuReGraphCounters GraSuReGraphSsspSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<std::size_t> GraSuReGraphSsspSystem::frontier_out_sizes() const {
  return impl_->frontier_out_sizes();
}

std::vector<std::uint32_t> GraSuReGraphSsspSystem::distances() const {
  return impl_->distances();
}

std::vector<std::uint32_t> GraSuReGraphSsspSystem::state_words() const {
  return impl_->state_words();
}

std::vector<std::uint32_t>
GraSuReGraphSsspSystem::auxiliary_state_words() const {
  return impl_->auxiliary_state_words();
}

GraSuNativeReGraphSsspSystem::GraSuNativeReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    std::size_t vertices, std::size_t compact_edge_slots, std::uint32_t source,
    std::size_t supersteps, GraSuReGraphConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend, vertices,
                                   compact_edge_slots, source, supersteps,
                                   config)) {}

GraSuNativeReGraphSsspSystem::~GraSuNativeReGraphSsspSystem() = default;

void GraSuNativeReGraphSsspSystem::register_components() {
  impl_->register_components();
}

bool GraSuNativeReGraphSsspSystem::done() const noexcept {
  return impl_->done();
}

bool GraSuNativeReGraphSsspSystem::failed() const noexcept {
  return impl_->failed();
}

const std::string &GraSuNativeReGraphSsspSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuNativeReGraphCounters
GraSuNativeReGraphSsspSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<std::uint32_t> GraSuNativeReGraphSsspSystem::distances() const {
  return impl_->distances();
}

GraSuReGraphPageRankSystem::GraSuReGraphPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t iterations, float damping, GraSuReGraphConfig config)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(out_degrees), iterations, config)) {}

GraSuReGraphPageRankSystem::GraSuReGraphPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t iterations, float damping, GraSuReGraphConfig config)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(out_degrees), iterations, config)) {}

GraSuReGraphPageRankSystem::~GraSuReGraphPageRankSystem() = default;

void GraSuReGraphPageRankSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphPageRankSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphPageRankSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &GraSuReGraphPageRankSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters GraSuReGraphPageRankSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<float> GraSuReGraphPageRankSystem::ranks() const {
  const std::vector<std::uint32_t> words = engine_->state_words();
  std::vector<float> ranks(words.size());
  std::transform(words.begin(), words.end(), ranks.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return ranks;
}

GraSuReGraphResidualPageRankSystem::GraSuReGraphResidualPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t max_iterations, float damping, float epsilon,
    GraSuReGraphConfig config, ResidualPageRankContract residual_contract,
    std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kResidualPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
              .epsilon = epsilon,
              .residual_contract = residual_contract,
          }),
          std::move(out_degrees), max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphResidualPageRankSystem::GraSuReGraphResidualPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t max_iterations, float damping, float epsilon,
    GraSuReGraphConfig config, ResidualPageRankContract residual_contract,
    std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kResidualPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
              .epsilon = epsilon,
              .residual_contract = residual_contract,
          }),
          std::move(out_degrees), max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphResidualPageRankSystem::~GraSuReGraphResidualPageRankSystem() =
    default;

void GraSuReGraphResidualPageRankSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphResidualPageRankSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphResidualPageRankSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &
GraSuReGraphResidualPageRankSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters
GraSuReGraphResidualPageRankSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<float> GraSuReGraphResidualPageRankSystem::ranks() const {
  const std::vector<std::uint32_t> words = engine_->state_words();
  std::vector<float> values(words.size());
  std::transform(words.begin(), words.end(), values.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return values;
}

std::vector<float> GraSuReGraphResidualPageRankSystem::residuals() const {
  const std::vector<std::uint32_t> words = engine_->auxiliary_state_words();
  std::vector<float> values(words.size());
  std::transform(words.begin(), words.end(), values.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return values;
}

std::vector<std::size_t>
GraSuReGraphResidualPageRankSystem::frontier_out_sizes() const {
  return engine_->frontier_out_sizes();
}

GraSuReGraphConnectedComponentsSystem::GraSuReGraphConnectedComponentsSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::size_t max_iterations,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kConnectedComponents,
              .vertices = layout.vertices,
              .source = 0,
          }),
          std::vector<std::uint32_t>{}, max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphConnectedComponentsSystem::GraSuReGraphConnectedComponentsSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::size_t max_iterations,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kConnectedComponents,
              .vertices = layout.vertices,
              .source = 0,
          }),
          std::vector<std::uint32_t>{}, max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphConnectedComponentsSystem::
    ~GraSuReGraphConnectedComponentsSystem() = default;

void GraSuReGraphConnectedComponentsSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphConnectedComponentsSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphConnectedComponentsSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &
GraSuReGraphConnectedComponentsSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters
GraSuReGraphConnectedComponentsSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<std::uint32_t>
GraSuReGraphConnectedComponentsSystem::labels() const {
  return engine_->state_words();
}

std::vector<std::size_t>
GraSuReGraphConnectedComponentsSystem::frontier_out_sizes() const {
  return engine_->frontier_out_sizes();
}

} // namespace spine::sim
