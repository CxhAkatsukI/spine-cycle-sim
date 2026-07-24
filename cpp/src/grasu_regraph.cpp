#include "spine_sim/grasu_regraph.hpp"

#include <algorithm>
#include <array>
#include <deque>
#include <limits>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace {

constexpr std::uint32_t kReGraphActive = 0x8000'0000U;
constexpr std::uint32_t kReGraphValueMask = 0x7fff'ffffU;
constexpr std::uint32_t kReGraphInfinity = 0x7fff'fffeU;
constexpr std::size_t kStateWordsPerBurst = 16;

std::uint32_t decode_u32(const std::vector<std::uint8_t> &bytes,
                         std::size_t offset = 0) {
  if (offset + 4 > bytes.size()) {
    throw std::invalid_argument("ReGraph 32-bit payload has invalid size");
  }
  std::uint32_t value = 0;
  for (std::size_t index = 0; index < 4; ++index) {
    value |= static_cast<std::uint32_t>(bytes[offset + index]) << (index * 8);
  }
  return value;
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != 8) {
    throw std::invalid_argument("ReGraph 64-bit payload has invalid size");
  }
  std::uint64_t value = 0;
  for (std::size_t index = 0; index < 8; ++index) {
    value |= static_cast<std::uint64_t>(bytes[index]) << (index * 8);
  }
  return value;
}

std::vector<std::uint8_t>
encode_words(const std::array<std::uint32_t, kStateWordsPerBurst> &words) {
  std::vector<std::uint8_t> bytes(kStateWordsPerBurst * 4);
  for (std::size_t word = 0; word < words.size(); ++word) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[word * 4 + byte] =
          static_cast<std::uint8_t>(words[word] >> (byte * 8));
    }
  }
  return bytes;
}

std::uint32_t policy_distance(std::uint32_t encoded) {
  const std::uint32_t value = encoded & kReGraphValueMask;
  return value == kReGraphInfinity ? GraphAlgorithmPolicy::kSsspInfinity
                                   : value;
}

std::uint32_t encode_distance(std::uint32_t distance, bool active) {
  const std::uint32_t value = distance == GraphAlgorithmPolicy::kSsspInfinity
                                  ? kReGraphInfinity
                                  : std::min(distance, kReGraphInfinity - 1);
  return value | (active ? kReGraphActive : 0U);
}

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

struct PmaEdgeBatch {
  std::uint32_t source{};
  std::uint32_t source_payload{};
  bool source_active{};
  std::size_t lanes{};
  std::array<std::uint32_t, 8> destinations{};
  std::array<bool, 8> valid{};
};

class PmaNativeReader final : public Component {
public:
  struct Ports {
    FixedAxiPort *rows{};
    FixedAxiPort *source_state{};
    std::array<FixedAxiPort *, 4> pma{};
    Fifo<PmaEdgeBatch> *output{};
  };

  PmaNativeReader(std::string name, ClockId clock_id, std::size_t vertices,
                  GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                  Ports ports)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), ports_(ports) {
    if (vertices_ == 0 || ports_.rows == nullptr ||
        ports_.source_state == nullptr || ports_.output == nullptr ||
        std::any_of(ports_.pma.begin(), ports_.pma.end(),
                    [](const auto *port) { return port == nullptr; })) {
      throw std::invalid_argument("invalid PMA-native reader ports");
    }
  }

  void start_round(std::uint64_t round) {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("PMA reader round started while busy");
    }
    round_ = round;
    source_ = 0;
    begin_segment_ = 0;
    end_segment_ = 0;
    next_segment_ = 0;
    outstanding_segments_ = 0;
    pending_batches_.clear();
    phase_ = Phase::kNeedSourceChunk;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t row_reads() const noexcept { return row_reads_; }
  [[nodiscard]] std::uint64_t state_reads() const noexcept {
    return state_reads_;
  }
  [[nodiscard]] std::uint64_t state_read_bytes() const noexcept {
    return state_read_bytes_;
  }
  [[nodiscard]] std::uint64_t segment_reads() const noexcept {
    return segment_reads_;
  }

  void evaluate(const CycleContext &) override {
    staged_request_ = RequestKind::kNone;
    staged_response_.reset();
    staged_pma_responses_.clear();
    staged_output_ = false;
    staged_advance_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return;
    }
    if (!pending_batches_.empty()) {
      staged_output_ = ports_.output->try_push(pending_batches_.front());
    }
    switch (phase_) {
    case Phase::kNeedSourceChunk: {
      const std::size_t remaining = vertices_ - source_;
      const std::size_t words =
          std::min(remaining, config_.source_buffer_vertices);
      chunk_words_ = ((words + kStateWordsPerBurst - 1) / kStateWordsPerBurst) *
                     kStateWordsPerBurst;
      if (ports_.source_state->requests().try_push(AxiRequest{
              .transaction_id = transaction_id(1),
              .operation = MemoryOperation::kRead,
              .address = config_.vertex_state_base + source_ * 4,
              .bytes = chunk_words_ * 4,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        staged_request_ = RequestKind::kState;
      }
      break;
    }
    case Phase::kWaitSourceChunk:
      stage_scalar_response(*ports_.source_state);
      break;
    case Phase::kNeedRow:
      if (ports_.rows->requests().try_push(AxiRequest{
              .transaction_id = transaction_id(0),
              .operation = MemoryOperation::kRead,
              .address = config_.row_offset_base + source_ * 8,
              .bytes = 8,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        staged_request_ = RequestKind::kRow;
      }
      break;
    case Phase::kWaitRow:
      stage_scalar_response(*ports_.rows);
      break;
    case Phase::kScan:
      stage_pma_responses();
      stage_pma_request();
      if (next_segment_ == end_segment_ && outstanding_segments_ == 0 &&
          pending_batches_.empty()) {
        staged_advance_ = true;
      }
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_output_) {
      pending_batches_.pop_front();
    }
    if (staged_response_.has_value()) {
      consume_scalar_response(*staged_response_);
      staged_response_.reset();
    }
    for (const AxiResponse &response : staged_pma_responses_) {
      consume_pma_response(response);
    }
    if (staged_request_ == RequestKind::kRow) {
      ++row_reads_;
      phase_ = Phase::kWaitRow;
    } else if (staged_request_ == RequestKind::kState) {
      ++state_reads_;
      state_read_bytes_ += chunk_words_ * 4;
      phase_ = Phase::kWaitSourceChunk;
    } else if (staged_request_ == RequestKind::kPma) {
      ++next_segment_;
      ++outstanding_segments_;
      ++segment_reads_;
    }
    if (staged_advance_) {
      advance_source();
    }
  }

private:
  enum class Phase {
    kIdle,
    kNeedSourceChunk,
    kWaitSourceChunk,
    kNeedRow,
    kWaitRow,
    kScan,
    kDone,
  };
  enum class RequestKind { kNone, kRow, kState, kPma };

  [[nodiscard]] std::uint64_t transaction_id(std::uint64_t stage) const {
    return (round_ << 48) | (static_cast<std::uint64_t>(source_) << 16) | stage;
  }

  [[nodiscard]] std::size_t pma_channel(std::size_t segment) const {
    const std::size_t local = segment >> 1;
    const std::size_t parity = segment & 1U;
    return local < config_.cache_segments_per_half ? parity * 2
                                                   : parity * 2 + 1;
  }

  [[nodiscard]] std::uint64_t pma_address(std::size_t segment) const {
    return config_.pma_base + (segment >> 1) * kGraSuSegmentBytes;
  }

  void stage_scalar_response(FixedAxiPort &port) {
    if (port.responses().front() == nullptr) {
      return;
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      staged_response_ = std::move(response);
    }
  }

  void stage_pma_request() {
    if (next_segment_ >= end_segment_ ||
        pending_batches_.size() +
                staged_pma_responses_.size() * batches_per_segment() +
                batches_per_segment() >
            config_.reader_buffer_batches) {
      return;
    }
    FixedAxiPort &port = *ports_.pma[pma_channel(next_segment_)];
    if (port.requests().try_push(AxiRequest{
            .transaction_id = transaction_id(2) + next_segment_,
            .operation = MemoryOperation::kRead,
            .address = pma_address(next_segment_),
            .bytes = kGraSuSegmentBytes,
            .stream_read_beats = false,
            .write_data = {},
        })) {
      staged_request_ = RequestKind::kPma;
    }
  }

  void stage_pma_responses() {
    for (FixedAxiPort *port : ports_.pma) {
      if (pending_batches_.size() +
              staged_pma_responses_.size() * batches_per_segment() +
              batches_per_segment() >
          config_.reader_buffer_batches) {
        break;
      }
      if (port->responses().front() == nullptr) {
        continue;
      }
      AxiResponse response;
      if (port->responses().try_pop(response)) {
        staged_pma_responses_.push_back(std::move(response));
      }
    }
  }

  void consume_scalar_response(const AxiResponse &response) {
    if (!response.success) {
      throw std::runtime_error("PMA reader received failed AXI response");
    }
    if (phase_ == Phase::kWaitSourceChunk) {
      if (response.read_data.size() != chunk_words_ * 4) {
        throw std::runtime_error(
            "PMA reader received malformed source-cache response");
      }
      source_cache_base_ = source_;
      source_cache_.resize(chunk_words_);
      for (std::size_t index = 0; index < chunk_words_; ++index) {
        source_cache_[index] = decode_u32(response.read_data, index * 4);
      }
      phase_ = Phase::kNeedRow;
      return;
    }
    if (phase_ == Phase::kWaitRow) {
      const std::uint64_t bounds = decode_u64(response.read_data);
      begin_segment_ =
          static_cast<std::uint32_t>(bounds >> 32) / kGraSuSegmentSlots;
      end_segment_ = static_cast<std::uint32_t>(bounds) / kGraSuSegmentSlots;
      next_segment_ = begin_segment_;
      const std::uint32_t encoded =
          source_cache_.at(source_ - source_cache_base_);
      source_active_ = (encoded & kReGraphActive) != 0;
      source_payload_ =
          policy_
              .prepare_source(
                  AlgorithmVertexState{.primary = policy_distance(encoded)}, 0)
              .edge_payload;
      phase_ = Phase::kScan;
      return;
    }
    throw std::runtime_error(
        "PMA reader received scalar response out of phase");
  }

  void consume_pma_response(const AxiResponse &response) {
    if (!response.success || response.read_data.size() != kGraSuSegmentBytes ||
        outstanding_segments_ == 0) {
      throw std::runtime_error(
          "PMA reader received malformed segment response");
    }
    --outstanding_segments_;
    for (std::size_t offset = 0; offset < kGraSuSegmentSlots;
         offset += config_.edge_lanes) {
      PmaEdgeBatch batch{
          .source = static_cast<std::uint32_t>(source_),
          .source_payload = source_payload_,
          .source_active = source_active_,
          .lanes = config_.edge_lanes,
      };
      for (std::size_t lane = 0; lane < config_.edge_lanes; ++lane) {
        const std::uint32_t destination =
            decode_u32(response.read_data, (offset + lane) * 4);
        batch.destinations[lane] = destination;
        batch.valid[lane] = (destination & kGraSuPmaEmpty) == 0;
      }
      pending_batches_.push_back(batch);
    }
  }

  [[nodiscard]] std::size_t batches_per_segment() const noexcept {
    return kGraSuSegmentSlots / config_.edge_lanes;
  }

  void advance_source() {
    ++source_;
    if (source_ == vertices_) {
      phase_ = Phase::kDone;
      return;
    }
    phase_ = source_ == source_cache_base_ + chunk_words_
                 ? Phase::kNeedSourceChunk
                 : Phase::kNeedRow;
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Ports ports_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::size_t source_{};
  std::size_t begin_segment_{};
  std::size_t end_segment_{};
  std::size_t next_segment_{};
  std::size_t outstanding_segments_{};
  std::size_t source_cache_base_{};
  std::size_t chunk_words_{};
  std::vector<std::uint32_t> source_cache_;
  bool source_active_{};
  std::uint32_t source_payload_{};
  std::deque<PmaEdgeBatch> pending_batches_;
  RequestKind staged_request_{RequestKind::kNone};
  std::optional<AxiResponse> staged_response_;
  std::vector<AxiResponse> staged_pma_responses_;
  bool staged_output_{};
  bool staged_advance_{};
  std::uint64_t row_reads_{};
  std::uint64_t state_reads_{};
  std::uint64_t state_read_bytes_{};
  std::uint64_t segment_reads_{};
};

class ReGraphGather final : public Component {
public:
  ReGraphGather(std::string name, ClockId clock_id, std::size_t vertices,
                GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                Fifo<PmaEdgeBatch> &input, const PmaNativeReader &reader)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        reader_(reader), reduced_(vertices) {}

  void start_round() {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("ReGraph gather round started while busy");
    }
    std::fill(reduced_.begin(), reduced_.end(), std::nullopt);
    remaining_ = divide_ceil(config_.partition_vertices,
                             config_.gather_vertices_per_reset_cycle);
    phase_ = Phase::kReset;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] const std::vector<std::optional<std::uint32_t>> &
  reduced() const noexcept {
    return reduced_;
  }
  [[nodiscard]] std::uint64_t slots_scanned() const noexcept {
    return slots_scanned_;
  }
  [[nodiscard]] std::uint64_t batches_scanned() const noexcept {
    return batches_scanned_;
  }
  [[nodiscard]] std::uint64_t live_edges() const noexcept {
    return live_edges_;
  }
  [[nodiscard]] std::uint64_t active_edges() const noexcept {
    return active_edges_;
  }
  [[nodiscard]] std::uint64_t reset_cycles() const noexcept {
    return reset_cycles_;
  }
  [[nodiscard]] std::uint64_t merge_cycles() const noexcept {
    return merge_cycles_;
  }
  [[nodiscard]] std::uint64_t conflict_cycles() const noexcept {
    return conflict_cycles_;
  }

  void evaluate(const CycleContext &) override {
    staged_tick_ = false;
    staged_start_merge_ = false;
    staged_batch_.reset();
    switch (phase_) {
    case Phase::kReset:
    case Phase::kMerge:
      staged_tick_ = remaining_ != 0;
      break;
    case Phase::kScan:
      if (busy_cycles_ != 0) {
        staged_tick_ = true;
      } else if (input_.front() != nullptr) {
        PmaEdgeBatch batch;
        if (input_.try_pop(batch)) {
          staged_batch_ = batch;
        }
      } else if (reader_.done()) {
        staged_start_merge_ = true;
      }
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
  }

  void commit(const CycleContext &) override {
    if (phase_ == Phase::kReset && staged_tick_) {
      --remaining_;
      ++reset_cycles_;
      if (remaining_ == 0) {
        phase_ = Phase::kScan;
      }
      return;
    }
    if (phase_ == Phase::kMerge && staged_tick_) {
      --remaining_;
      ++merge_cycles_;
      if (remaining_ == 0) {
        phase_ = Phase::kDone;
      }
      return;
    }
    if (phase_ != Phase::kScan) {
      return;
    }
    if (busy_cycles_ != 0 && staged_tick_) {
      --busy_cycles_;
    }
    if (staged_batch_.has_value()) {
      consume_batch(*staged_batch_);
      staged_batch_.reset();
    }
    if (staged_start_merge_) {
      remaining_ = divide_ceil(config_.partition_vertices,
                               config_.gather_vertices_per_merge_cycle);
      phase_ = Phase::kMerge;
    }
  }

private:
  enum class Phase { kIdle, kReset, kScan, kMerge, kDone };

  static std::size_t divide_ceil(std::size_t value, std::size_t divisor) {
    return (value + divisor - 1) / divisor;
  }

  void consume_batch(const PmaEdgeBatch &batch) {
    ++batches_scanned_;
    slots_scanned_ += batch.lanes;
    std::vector<std::size_t> bank_counts(config_.gather_banks);
    for (std::size_t lane = 0; lane < batch.lanes; ++lane) {
      if (!batch.valid[lane]) {
        continue;
      }
      ++live_edges_;
      const std::uint32_t destination = batch.destinations[lane];
      if (destination >= vertices_) {
        throw std::runtime_error("PMA edge exceeds ReGraph vertex range");
      }
      if (!batch.source_active) {
        continue;
      }
      ++active_edges_;
      ++bank_counts[destination % config_.gather_banks];
      const std::uint32_t candidate = policy_.map_edge(batch.source_payload, 1);
      reduced_[destination] = policy_.reduce(reduced_[destination], candidate);
    }
    const std::size_t cycles =
        *std::max_element(bank_counts.begin(), bank_counts.end());
    if (cycles > 1) {
      busy_cycles_ = cycles - 1;
      conflict_cycles_ += cycles - 1;
    }
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<PmaEdgeBatch> &input_;
  const PmaNativeReader &reader_;
  std::vector<std::optional<std::uint32_t>> reduced_;
  Phase phase_{Phase::kIdle};
  std::size_t remaining_{};
  std::size_t busy_cycles_{};
  bool staged_tick_{};
  bool staged_start_merge_{};
  std::optional<PmaEdgeBatch> staged_batch_;
  std::uint64_t batches_scanned_{};
  std::uint64_t slots_scanned_{};
  std::uint64_t live_edges_{};
  std::uint64_t active_edges_{};
  std::uint64_t reset_cycles_{};
  std::uint64_t merge_cycles_{};
  std::uint64_t conflict_cycles_{};
};

class ReGraphApply final : public Component {
public:
  ReGraphApply(std::string name, ClockId clock_id, std::size_t vertices,
               GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
               FixedAxiPort &read_port, FixedAxiPort &write_port)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), read_port_(read_port),
        write_port_(write_port) {}

  void start_round(const std::vector<std::optional<std::uint32_t>> &reduced) {
    if (running_ || !read_inflight_.empty() || !write_inflight_.empty() ||
        !ready_writes_.empty()) {
      throw std::logic_error("ReGraph apply round started while busy");
    }
    reduced_ = &reduced;
    next_read_offset_ = 0;
    completed_writes_ = 0;
    active_vertices_ = 0;
    done_ = false;
    running_ = true;
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::size_t active_vertices() const noexcept {
    return active_vertices_;
  }
  [[nodiscard]] std::uint64_t reads() const noexcept { return reads_; }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_; }
  [[nodiscard]] std::uint64_t total_activated() const noexcept {
    return total_activated_;
  }
  [[nodiscard]] std::uint64_t read_window_stalls() const noexcept {
    return read_window_stalls_;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept {
    return write_window_stalls_;
  }
  [[nodiscard]] std::size_t max_reads_inflight() const noexcept {
    return max_reads_inflight_;
  }
  [[nodiscard]] std::size_t max_pipeline_occupancy() const noexcept {
    return max_pipeline_occupancy_;
  }
  [[nodiscard]] std::size_t max_writes_inflight() const noexcept {
    return max_writes_inflight_;
  }

  void evaluate(const CycleContext &context) override {
    staged_read_issue_ = false;
    staged_write_issue_.reset();
    staged_read_response_.reset();
    staged_write_response_.reset();
    if (!running_) {
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

    const auto ready =
        std::find_if(ready_writes_.begin(), ready_writes_.end(),
                     [&](const ReadyWrite &item) {
                       return item.due_cycle <= context.domain_cycle;
                     });
    if (ready != ready_writes_.end()) {
      if (write_inflight_.size() >= config_.apply_request_window) {
        ++write_window_stalls_;
      } else {
        const std::size_t index =
            static_cast<std::size_t>(ready - ready_writes_.begin());
        const ReadyWrite &item = ready_writes_[index];
        if (write_port_.requests().try_push(AxiRequest{
                .transaction_id = transaction_id(item.offset),
                .operation = MemoryOperation::kWrite,
                .address = config_.vertex_state_base + item.offset * 4,
                .bytes = kStateWordsPerBurst * 4,
                .stream_read_beats = false,
                .write_data = item.data,
            })) {
          staged_write_issue_ = index;
        }
      }
    }

    if (next_read_offset_ >= config_.partition_vertices) {
      return;
    }
    if (read_inflight_.size() >= config_.apply_request_window) {
      ++read_window_stalls_;
      return;
    }
    if (pipeline_occupancy() >= config_.apply_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      return;
    }
    staged_read_issue_ = read_port_.requests().try_push(AxiRequest{
        .transaction_id = transaction_id(next_read_offset_),
        .operation = MemoryOperation::kRead,
        .address = config_.vertex_state_base + next_read_offset_ * 4,
        .bytes = kStateWordsPerBurst * 4,
        .stream_read_beats = false,
        .write_data = {},
    });
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      return;
    }
    if (staged_read_response_.has_value()) {
      consume_read_response(*staged_read_response_, context.domain_cycle);
      staged_read_response_.reset();
    }
    if (staged_write_response_.has_value()) {
      consume_write_response(*staged_write_response_);
      staged_write_response_.reset();
    }
    if (staged_read_issue_) {
      const std::uint64_t id = transaction_id(next_read_offset_);
      if (!read_inflight_.emplace(id, next_read_offset_).second) {
        throw std::logic_error("duplicate ReGraph apply read transaction");
      }
      next_read_offset_ += kStateWordsPerBurst;
      ++reads_;
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite item = std::move(ready_writes_[*staged_write_issue_]);
      ready_writes_.erase(ready_writes_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(item.offset);
      if (!write_inflight_.emplace(id, item.offset).second) {
        throw std::logic_error("duplicate ReGraph apply write transaction");
      }
      ++writes_;
    }
    max_reads_inflight_ = std::max(max_reads_inflight_, read_inflight_.size());
    max_writes_inflight_ =
        std::max(max_writes_inflight_, write_inflight_.size());
    max_pipeline_occupancy_ =
        std::max(max_pipeline_occupancy_, pipeline_occupancy());
    if (completed_writes_ == total_bursts()) {
      running_ = false;
      done_ = true;
    }
  }

private:
  struct ReadyWrite {
    std::size_t offset{};
    std::uint64_t due_cycle{};
    std::vector<std::uint8_t> data;
  };

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return offset / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t pipeline_occupancy() const noexcept {
    return read_inflight_.size() + ready_writes_.size();
  }

  void consume_read_response(const AxiResponse &response, std::uint64_t cycle) {
    const auto found = read_inflight_.find(response.transaction_id);
    if (!response.success || found == read_inflight_.end() ||
        response.read_data.size() != kStateWordsPerBurst * 4) {
      throw std::runtime_error(
          "ReGraph apply received malformed read response");
    }
    const std::size_t offset = found->second;
    read_inflight_.erase(found);
    std::array<std::uint32_t, kStateWordsPerBurst> result{};
    for (std::size_t lane = 0; lane < result.size(); ++lane) {
      const std::size_t vertex = offset + lane;
      const std::uint32_t encoded = decode_u32(response.read_data, lane * 4);
      if (vertex >= vertices_) {
        result[lane] = kReGraphInfinity;
        continue;
      }
      const AlgorithmApplyResult applied = policy_.apply(
          AlgorithmVertexState{.primary = policy_distance(encoded)},
          reduced_->at(vertex));
      result[lane] =
          encode_distance(applied.state_after.primary, applied.active);
      if (applied.active) {
        ++active_vertices_;
        ++total_activated_;
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .offset = offset,
        .due_cycle = cycle + config_.apply_pipeline_latency,
        .data = encode_words(result),
    });
  }

  void consume_write_response(const AxiResponse &response) {
    const auto found = write_inflight_.find(response.transaction_id);
    if (!response.success || found == write_inflight_.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "ReGraph apply received malformed write response");
    }
    write_inflight_.erase(found);
    ++completed_writes_;
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  FixedAxiPort &read_port_;
  FixedAxiPort &write_port_;
  const std::vector<std::optional<std::uint32_t>> *reduced_{};
  std::unordered_map<std::uint64_t, std::size_t> read_inflight_;
  std::unordered_map<std::uint64_t, std::size_t> write_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<AxiResponse> staged_read_response_;
  std::optional<AxiResponse> staged_write_response_;
  std::optional<std::size_t> staged_write_issue_;
  std::size_t next_read_offset_{};
  std::size_t completed_writes_{};
  std::size_t active_vertices_{};
  bool staged_read_issue_{};
  bool running_{};
  bool done_{};
  std::uint64_t reads_{};
  std::uint64_t writes_{};
  std::uint64_t total_activated_{};
  std::uint64_t read_window_stalls_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_reads_inflight_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
};

class GraSuReGraphController final : public Component {
public:
  GraSuReGraphController(std::string name, ClockId clock_id,
                         std::size_t max_supersteps, PmaNativeReader &reader,
                         ReGraphGather &gather, ReGraphApply &apply)
      : Component(std::move(name), clock_id), max_supersteps_(max_supersteps),
        reader_(reader), gather_(gather), apply_(apply) {}

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t supersteps() const noexcept { return round_; }

  void evaluate(const CycleContext &) override {
    staged_ = Action::kNone;
    if (failed() || done()) {
      return;
    }
    if (phase_ == Phase::kStart) {
      staged_ = Action::kStartGather;
    } else if (phase_ == Phase::kGather && gather_.done()) {
      staged_ = Action::kStartApply;
    } else if (phase_ == Phase::kApply && apply_.done()) {
      staged_ =
          apply_.active_vertices() == 0 ? Action::kFinish : Action::kNextRound;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_ == Action::kStartGather || staged_ == Action::kNextRound) {
      if (round_ == max_supersteps_) {
        failure_ = "ReGraph SSSP exceeded maximum supersteps";
        return;
      }
      ++round_;
      reader_.start_round(round_);
      gather_.start_round();
      phase_ = Phase::kGather;
    } else if (staged_ == Action::kStartApply) {
      apply_.start_round(gather_.reduced());
      phase_ = Phase::kApply;
    } else if (staged_ == Action::kFinish) {
      phase_ = Phase::kDone;
    }
  }

private:
  enum class Phase { kStart, kGather, kApply, kDone };
  enum class Action { kNone, kStartGather, kStartApply, kNextRound, kFinish };

  std::size_t max_supersteps_{};
  PmaNativeReader &reader_;
  ReGraphGather &gather_;
  ReGraphApply &apply_;
  Phase phase_{Phase::kStart};
  Action staged_{Action::kNone};
  std::uint64_t round_{};
  std::string failure_;
};

} // namespace

class GraSuReGraphSsspSystem::Impl {
public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPmaLayout layout, std::uint32_t source, GraSuReGraphConfig config)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), source_(source), config_(config),
        policy_(AlgorithmPolicyConfig{
            .kind = GraphAlgorithmKind::kWeightedSssp,
            .vertices = layout_.vertices,
            .source = source_,
        }),
        edge_axis_("grasu-regraph-pma-axis", clock_id_,
                   config_.axis_fifo_depth),
        start_cycle_(scheduler_.clock(clock_id_).completed_cycles) {
    validate_config();
    construct_ports();
    initialize_state();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error("GraSU-ReGraph system registered more than once");
    }
    scheduler_.add_component(edge_axis_);
    row_port_->register_components(scheduler_);
    source_state_port_->register_components(scheduler_);
    for (auto &port : pma_ports_) {
      port->register_components(scheduler_);
    }
    apply_state_read_port_->register_components(scheduler_);
    apply_state_write_port_->register_components(scheduler_);
    scheduler_.add_component(*reader_);
    scheduler_.add_component(*gather_);
    scheduler_.add_component(*apply_);
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

  [[nodiscard]] GraSuReGraphCounters counters() const noexcept {
    GraSuReGraphCounters result;
    result.supersteps = controller_->supersteps();
    result.row_reads = reader_->row_reads();
    result.source_state_reads = reader_->state_reads();
    result.pma_segment_reads = reader_->segment_reads();
    result.edge_batches_scanned = gather_->batches_scanned();
    result.pma_slots_scanned = gather_->slots_scanned();
    result.live_edges_scanned = gather_->live_edges();
    result.active_edges_mapped = gather_->active_edges();
    result.gather_reset_cycles = gather_->reset_cycles();
    result.gather_merge_cycles = gather_->merge_cycles();
    result.gather_bank_conflict_cycles = gather_->conflict_cycles();
    result.apply_state_reads = apply_->reads();
    result.apply_state_writes = apply_->writes();
    result.apply_read_window_stalls = apply_->read_window_stalls();
    result.apply_pipeline_capacity_stalls = apply_->pipeline_capacity_stalls();
    result.apply_write_window_stalls = apply_->write_window_stalls();
    result.apply_max_reads_inflight = apply_->max_reads_inflight();
    result.apply_max_pipeline_occupancy = apply_->max_pipeline_occupancy();
    result.apply_max_writes_inflight = apply_->max_writes_inflight();
    result.activated_vertices = apply_->total_activated();
    result.row_read_bytes = result.row_reads * 8;
    result.source_state_read_bytes = reader_->state_read_bytes();
    result.pma_read_bytes = result.pma_segment_reads * kGraSuSegmentBytes;
    result.apply_read_bytes = result.apply_state_reads * 64;
    result.apply_write_bytes = result.apply_state_writes * 64;
    result.axi_backend_submit_stalls =
        row_port_->master().stats().backend_submit_stalls +
        source_state_port_->master().stats().backend_submit_stalls +
        apply_state_read_port_->master().stats().backend_submit_stalls +
        apply_state_write_port_->master().stats().backend_submit_stalls;
    for (const auto &port : pma_ports_) {
      result.axi_backend_submit_stalls +=
          port->master().stats().backend_submit_stalls;
    }
    result.axis_push_stalls = edge_axis_.stats().push_stalls;
    result.start_cycle = start_cycle_;
    result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> distances() const {
    const auto bytes = backend_.inspect_payload(config_.vertex_state_channel,
                                                config_.vertex_state_base,
                                                layout_.vertices * 4);
    std::vector<std::uint32_t> result(layout_.vertices);
    for (std::size_t vertex = 0; vertex < result.size(); ++vertex) {
      result[vertex] = policy_distance(decode_u32(bytes, vertex * 4));
    }
    return result;
  }

private:
  void validate_config() const {
    if (layout_.vertices == 0 || source_ >= layout_.vertices ||
        config_.memory_channels < 4 ||
        config_.partition_vertices < layout_.vertices ||
        config_.partition_vertices % kStateWordsPerBurst != 0 ||
        config_.source_buffer_vertices == 0 ||
        config_.source_buffer_vertices % kStateWordsPerBurst != 0 ||
        config_.edge_lanes == 0 || config_.edge_lanes > 8 ||
        kGraSuSegmentSlots % config_.edge_lanes != 0 ||
        config_.gather_banks == 0 ||
        config_.gather_vertices_per_reset_cycle == 0 ||
        config_.gather_vertices_per_merge_cycle == 0 ||
        config_.axis_fifo_depth == 0 ||
        config_.reader_buffer_batches <
            kGraSuSegmentSlots / config_.edge_lanes ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.apply_request_window == 0 ||
        config_.apply_pipeline_latency == 0 ||
        config_.apply_pipeline_capacity == 0 || config_.max_supersteps == 0 ||
        config_.row_channel >= config_.memory_channels ||
        config_.vertex_state_channel >= config_.memory_channels) {
      throw std::invalid_argument("invalid GraSU-ReGraph configuration");
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  void construct_ports() {
    row_port_ = make_port("grasu-regraph-row", config_.row_channel, 8);
    source_state_port_ = make_port("grasu-regraph-source-state",
                                   config_.vertex_state_channel, 64);
    for (std::size_t channel = 0; channel < pma_ports_.size(); ++channel) {
      pma_ports_[channel] =
          make_port("grasu-regraph-pma" + std::to_string(channel), channel, 64);
    }
    apply_state_read_port_ = make_port("grasu-regraph-apply-state-read",
                                       config_.vertex_state_channel, 64);
    apply_state_write_port_ = make_port("grasu-regraph-apply-state-write",
                                        config_.vertex_state_channel, 64);
  }

  void initialize_state() {
    std::vector<std::uint8_t> bytes(config_.partition_vertices * 4);
    for (std::size_t vertex = 0; vertex < config_.partition_vertices;
         ++vertex) {
      const std::uint32_t encoded =
          vertex == source_ ? kReGraphActive : kReGraphInfinity;
      for (std::size_t byte = 0; byte < 4; ++byte) {
        bytes[vertex * 4 + byte] =
            static_cast<std::uint8_t>(encoded >> (byte * 8));
      }
    }
    backend_.initialize_payload(config_.vertex_state_channel,
                                config_.vertex_state_base, bytes);
  }

  void construct_components() {
    std::array<FixedAxiPort *, 4> pma{};
    for (std::size_t index = 0; index < pma.size(); ++index) {
      pma[index] = pma_ports_[index].get();
    }
    reader_ = std::make_unique<PmaNativeReader>(
        "grasu-regraph-reader", clock_id_, layout_.vertices, policy_, config_,
        PmaNativeReader::Ports{
            .rows = row_port_.get(),
            .source_state = source_state_port_.get(),
            .pma = pma,
            .output = &edge_axis_,
        });
    gather_ = std::make_unique<ReGraphGather>("grasu-regraph-gather", clock_id_,
                                              layout_.vertices, policy_,
                                              config_, edge_axis_, *reader_);
    apply_ = std::make_unique<ReGraphApply>(
        "grasu-regraph-apply", clock_id_, layout_.vertices, policy_, config_,
        *apply_state_read_port_, *apply_state_write_port_);
    controller_ = std::make_unique<GraSuReGraphController>(
        "grasu-regraph-controller", clock_id_, config_.max_supersteps, *reader_,
        *gather_, *apply_);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    if (!edge_axis_.empty() || !row_port_->idle() ||
        !source_state_port_->idle() || !apply_state_read_port_->idle() ||
        !apply_state_write_port_->idle()) {
      return false;
    }
    return std::all_of(pma_ports_.begin(), pma_ports_.end(),
                       [](const auto &port) { return port->idle(); });
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPmaLayout layout_;
  std::uint32_t source_{};
  GraSuReGraphConfig config_;
  GraphAlgorithmPolicy policy_;
  Fifo<PmaEdgeBatch> edge_axis_;
  std::unique_ptr<FixedAxiPort> row_port_;
  std::unique_ptr<FixedAxiPort> source_state_port_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports_;
  std::unique_ptr<FixedAxiPort> apply_state_read_port_;
  std::unique_ptr<FixedAxiPort> apply_state_write_port_;
  std::unique_ptr<PmaNativeReader> reader_;
  std::unique_ptr<ReGraphGather> gather_;
  std::unique_ptr<ReGraphApply> apply_;
  std::unique_ptr<GraSuReGraphController> controller_;
  std::uint32_t next_initiator_{3100};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::uint32_t source, GraSuReGraphConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend,
                                   std::move(layout), source, config)) {}

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

std::vector<std::uint32_t> GraSuReGraphSsspSystem::distances() const {
  return impl_->distances();
}

} // namespace spine::sim
