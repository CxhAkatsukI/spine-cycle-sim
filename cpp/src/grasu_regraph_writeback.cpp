#include "detail/grasu_regraph_compute.hpp"

#include <cmath>
#include <deque>
#include <limits>
#include <unordered_map>
#include <utility>

namespace spine::sim::detail {
namespace {

class ReGraphHbmWrapper final : public ReGraphWritebackEngine {
public:
  ReGraphHbmWrapper(std::string name, ClockId clock_id,
                    const GraSuReGraphConfig &config,
                    GraphAlgorithmPolicy policy,
                    Fifo<ReGraphAppliedBurst> &input,
                    AxiEndpoint primary_write_port,
                    AxiEndpoint mirror_write_port)
      : ReGraphWritebackEngine(std::move(name), clock_id), config_(config), input_(input),
        write_ports_{primary_write_port, mirror_write_port},
        policy_(std::move(policy)) {
    input_.bind_nonempty_notifier(this,
                                  &ReGraphHbmWrapper::notify_work_available);
    for (const AxiEndpoint &port : write_ports_) {
      port.responses().bind_nonempty_notifier(
          this, &ReGraphHbmWrapper::notify_work_available);
    }
    refresh_evaluate_ready();
  }

  ~ReGraphHbmWrapper() override {
    input_.unbind_nonempty_notifier(this);
    for (const AxiEndpoint &port : write_ports_) {
      port.responses().unbind_nonempty_notifier(this);
    }
  }

  void start_partition(std::uint64_t round, std::size_t destination_base) override {
    const bool writes_pending =
        std::any_of(write_inflight_.begin(), write_inflight_.end(),
                    [](const auto &entries) { return !entries.empty(); });
    if (round == 0 || running_ || writes_pending || !pipeline_.empty()) {
      throw std::logic_error("ReGraph HBM wrapper round started while busy");
    }
    target_source_base_ = config_.source_state_base +
                          (round & 1U) * config_.source_state_buffer_stride +
                          destination_base * 4;
    destination_base_ = destination_base;
    input_bursts_this_round_ = 0;
    completed_writes_ = 0;
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept override { return done_; }
  [[nodiscard]] std::uint64_t input_bursts() const noexcept override {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t source_writes() const noexcept override {
    return source_writes_;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept override {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept override {
    return write_window_stalls_;
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
           (staged_input_.has_value() || staged_write_issue_.has_value() ||
            std::any_of(
                staged_write_responses_.begin(), staged_write_responses_.end(),
                [](const auto &response) { return response.has_value(); }));
  }

  void evaluate(const CycleContext &context) override {
    staged_input_.reset();
    staged_write_issue_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    for (std::size_t port = 0; port < write_ports_.size(); ++port) {
      if (write_ports_[port].responses().front() != nullptr) {
        AxiResponse response;
        if (write_ports_[port].responses().try_pop(response)) {
          staged_write_responses_[port] = std::move(response);
        }
      }
    }

    const auto ready = std::find_if(
        pipeline_.begin(), pipeline_.end(), [&](const ReadyWrite &item) {
          return item.due_cycle <= context.domain_cycle;
        });
    if (ready != pipeline_.end()) {
      if (!write_window_available()) {
        ++write_window_stalls_;
      } else if (write_request_fifos_available()) {
        const std::size_t index =
            static_cast<std::size_t>(ready - pipeline_.begin());
        const ReadyWrite &item = pipeline_[index];
        for (const AxiEndpoint &port : write_ports_) {
          if (!port.requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.burst.offset),
                  .operation = MemoryOperation::kWrite,
                  .address = target_source_base_ + item.burst.offset * 4,
                  .bytes =
                      static_cast<std::uint32_t>(item.burst.source_data.size()),
                  .stream_read_beats = false,
                  .write_data = item.burst.source_data,
              })) {
            throw std::logic_error(
                "ReGraph HBM wrapper atomic write staging failed");
          }
        }
        staged_write_issue_ = index;
      } else {
        ++write_window_stalls_;
      }
    }

    if (input_bursts_this_round_ == total_bursts() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (pipeline_.size() >= config_.hbm_wrapper_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    ReGraphAppliedBurst burst;
    if (input_.try_pop(burst)) {
      staged_input_ = std::move(burst);
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
    for (std::size_t port = 0; port < staged_write_responses_.size(); ++port) {
      if (staged_write_responses_[port].has_value()) {
        consume_write_response(*staged_write_responses_[port], port);
      }
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite item = std::move(pipeline_[*staged_write_issue_]);
      pipeline_.erase(pipeline_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(item.burst.offset);
      for (auto &entries : write_inflight_) {
        if (!entries.emplace(id, item.burst.offset).second) {
          throw std::logic_error(
              "duplicate ReGraph HBM wrapper write transaction");
        }
      }
      source_writes_ += write_ports_.size();
    }
    if (staged_input_.has_value()) {
      const std::size_t expected_offset =
          input_bursts_this_round_ * kStateWordsPerBurst;
      if (staged_input_->offset != expected_offset) {
        throw std::runtime_error(
            "ReGraph HBM wrapper received a burst out of order");
      }
      pipeline_.push_back(ReadyWrite{
          .burst = std::move(*staged_input_),
          .due_cycle =
              context.domain_cycle + config_.hbm_wrapper_pipeline_latency,
      });
      ++input_bursts_this_round_;
      ++input_bursts_;
    }
    max_pipeline_occupancy_ =
        std::max(max_pipeline_occupancy_, pipeline_.size());
    for (const auto &entries : write_inflight_) {
      max_writes_inflight_ = std::max(max_writes_inflight_, entries.size());
    }
    if (input_bursts_this_round_ == total_bursts() && pipeline_.empty() &&
        completed_writes_ == total_bursts() * write_ports_.size()) {
      running_ = false;
      done_ = true;
      done_signal_.notify();
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  struct ReadyWrite {
    ReGraphAppliedBurst burst;
    std::uint64_t due_cycle{};
  };

  static void notify_work_available(void *owner) noexcept {
    auto *wrapper = static_cast<ReGraphHbmWrapper *>(owner);
    wrapper->evaluate_ready_ = wrapper->running_;
    wrapper->set_latched_evaluate_ready(wrapper->evaluate_ready_);
  }

  [[nodiscard]] bool response_available() const noexcept {
    return std::any_of(write_ports_.begin(), write_ports_.end(),
                       [](const AxiEndpoint &port) {
                         return port.responses().front() != nullptr;
                       });
  }

  void refresh_evaluate_ready() noexcept {
    evaluate_ready_ = running_ && (response_available() || !pipeline_.empty() ||
                                   (input_bursts_this_round_ < total_bursts() &&
                                    input_.front() != nullptr));
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_input_.reset();
    staged_write_issue_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    set_latched_commit_ready(false);
  }

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return (destination_base_ + offset) / kStateWordsPerBurst;
  }

  [[nodiscard]] bool write_window_available() const noexcept {
    return std::all_of(write_inflight_.begin(), write_inflight_.end(),
                       [&](const auto &entries) {
                         return entries.size() < config_.apply_request_window;
                       });
  }

  [[nodiscard]] bool write_request_fifos_available() const noexcept {
    return std::all_of(
        write_ports_.begin(), write_ports_.end(),
        [](const auto &port) { return !port.requests().full(); });
  }

  void consume_write_response(const AxiResponse &response, std::size_t port) {
    auto &entries = write_inflight_.at(port);
    const auto found = entries.find(response.transaction_id);
    if (!response.success || found == entries.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "ReGraph HBM wrapper received malformed write response");
    }
    entries.erase(found);
    ++completed_writes_;
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphAppliedBurst> &input_;
  std::array<AxiEndpoint, 2> write_ports_;
  GraphAlgorithmPolicy policy_;
  std::array<std::unordered_map<std::uint64_t, std::size_t>, 2> write_inflight_;
  std::deque<ReadyWrite> pipeline_;
  std::optional<ReGraphAppliedBurst> staged_input_;
  std::optional<std::size_t> staged_write_issue_;
  std::array<std::optional<AxiResponse>, 2> staged_write_responses_;
  std::size_t input_bursts_this_round_{};
  std::size_t completed_writes_{};
  std::uint64_t target_source_base_{};
  std::size_t destination_base_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  std::uint64_t input_bursts_{};
  std::uint64_t source_writes_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
  ReGraphDoneSignal done_signal_;
};

} // namespace

std::unique_ptr<ReGraphWritebackEngine> make_regraph_writeback(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    GraphAlgorithmPolicy policy, Fifo<ReGraphAppliedBurst> &input,
    AxiEndpoint primary, AxiEndpoint mirror) {
  return std::make_unique<ReGraphHbmWrapper>(
      std::move(name), clock, config, std::move(policy), input, primary, mirror);
}

std::unique_ptr<ReGraphWritebackEngine> make_regraph_writeback(
    std::string name, ClockId clock, const GraSuReGraphConfig &config,
    GraphAlgorithmPolicy policy, Fifo<ReGraphAppliedBurst> &input,
    FixedAxiPort &primary, FixedAxiPort &mirror) {
  return make_regraph_writeback(
      std::move(name), clock, config, std::move(policy), input,
      AxiEndpoint(primary), AxiEndpoint(mirror));
}

} // namespace spine::sim::detail
