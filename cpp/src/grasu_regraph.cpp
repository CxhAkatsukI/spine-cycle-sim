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
  std::array<std::uint16_t, 8> weights{};
  std::array<bool, 8> valid{};
};

struct ReGraphSourceCacheRequest {
  std::size_t source_round{};
  bool end{};
};

struct ReGraphSourceCacheResponse {
  std::size_t source_round{};
  std::size_t line{};
  std::array<std::uint32_t, kStateWordsPerBurst> words{};
  bool end{};
};

struct ReGraphGatherRow {
  std::size_t row{};
  std::array<std::optional<std::uint32_t>, 2> candidates{};
};

struct ReGraphMergedBurst {
  std::size_t offset{};
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst> candidates{};
};

struct ReGraphAppliedBurst {
  std::size_t offset{};
  std::vector<std::uint8_t> data;
};

class ReGraphSourceHbmReader final : public Component {
public:
  ReGraphSourceHbmReader(std::string name, ClockId clock_id,
                         const GraSuReGraphConfig &config,
                         Fifo<ReGraphSourceCacheRequest> &input,
                         Fifo<ReGraphSourceCacheResponse> &output,
                         FixedAxiPort &port)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        output_(output), port_(port) {}

  void start_round(std::uint64_t round) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("ReGraph source HBM reader started while busy");
    }
    algorithm_round_ = round;
    source_state_base_ =
        config_.source_state_base +
        ((round - 1) & 1U) * config_.source_state_buffer_stride;
    active_source_round_ = 0;
    lines_emitted_this_request_ = 0;
    phase_ = Phase::kIdle;
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
      };
      for (std::size_t word = 0; word < response.words.size(); ++word) {
        response.words[word] = decode_u32(beat->read_data, word * 4);
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
  }

private:
  enum class Phase { kIdle, kNeedIssue, kStream, kWaitParent, kEmitEnd, kDone };

  [[nodiscard]] std::size_t lines_per_round() const noexcept {
    return config_.source_buffer_vertices / kStateWordsPerBurst;
  }
  [[nodiscard]] std::uint64_t source_round_bytes() const noexcept {
    return config_.source_buffer_vertices * sizeof(std::uint32_t);
  }
  [[nodiscard]] std::uint64_t transaction_id(std::size_t source_round) const {
    return (algorithm_round_ << 48) | (1ULL << 47) | source_round;
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
  Phase phase_{Phase::kDone};
  std::uint64_t algorithm_round_{};
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

class PmaNativeReader final : public Component {
public:
  struct Ports {
    FixedAxiPort *rows{};
    std::array<FixedAxiPort *, 4> pma{};
    Fifo<PmaEdgeBatch> *output{};
    Fifo<ReGraphSourceCacheRequest> *source_requests{};
    Fifo<ReGraphSourceCacheResponse> *source_responses{};
  };

  PmaNativeReader(std::string name, ClockId clock_id, std::size_t vertices,
                  GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                  Ports ports)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), ports_(ports) {
    if (vertices_ == 0 || ports_.rows == nullptr || ports_.output == nullptr ||
        ports_.source_requests == nullptr ||
        ports_.source_responses == nullptr ||
        std::any_of(ports_.pma.begin(), ports_.pma.end(),
                    [](const auto *port) { return port == nullptr; })) {
      throw std::invalid_argument("invalid PMA-native reader ports");
    }
  }

  void start_round(std::uint64_t round) {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("PMA reader round started while busy");
    }
    if (round == 0) {
      throw std::invalid_argument("PMA reader round is one-based");
    }
    round_ = round;
    source_ = 0;
    begin_segment_ = 0;
    end_segment_ = 0;
    next_segment_ = 0;
    outstanding_segments_ = 0;
    pending_batches_.clear();
    pp_read_round_ = 0;
    pp_write_round_ = 0;
    pp_request_round_ = 0;
    source_end_sent_ = false;
    for (auto &slot : source_cache_) {
      slot.round = std::numeric_limits<std::size_t>::max();
      slot.lines_received = 0;
      slot.words.assign(config_.source_buffer_vertices, 0);
    }
    phase_ = Phase::kNeedRow;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t row_reads() const noexcept { return row_reads_; }
  [[nodiscard]] std::uint64_t source_requests() const noexcept {
    return source_requests_;
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
  [[nodiscard]] std::uint64_t segment_reads() const noexcept {
    return segment_reads_;
  }

  void evaluate(const CycleContext &) override {
    staged_request_ = RequestKind::kNone;
    staged_response_.reset();
    staged_pma_responses_.clear();
    staged_source_response_.reset();
    staged_source_request_.reset();
    staged_output_ = false;
    staged_advance_ = false;
    staged_cache_ready_ = false;
    staged_source_end_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return;
    }
    stage_source_response();
    stage_source_request();
    if (!pending_batches_.empty()) {
      staged_output_ = ports_.output->try_push(pending_batches_.front());
    }
    switch (phase_) {
    case Phase::kNeedSourceCache:
      if (source_cache_ready(pp_read_round_)) {
        staged_cache_ready_ = true;
      }
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
    case Phase::kSendEnd:
      staged_source_end_ = ports_.source_requests->try_push(
          ReGraphSourceCacheRequest{.end = true});
      break;
    case Phase::kWaitEnd:
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_source_response_.has_value()) {
      consume_source_response(*staged_source_response_);
    }
    if (staged_source_request_.has_value()) {
      pp_request_round_ = *staged_source_request_ + 1;
      ++source_requests_;
    }
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
    } else if (staged_request_ == RequestKind::kPma) {
      ++next_segment_;
      ++outstanding_segments_;
      ++segment_reads_;
    }
    if (staged_advance_) {
      advance_source();
    }
    if (staged_cache_ready_) {
      select_source_payload();
    } else if (phase_ == Phase::kNeedSourceCache) {
      ++source_wait_cycles_;
    }
    if (staged_source_end_) {
      source_end_sent_ = true;
      ++source_request_markers_;
      phase_ = Phase::kWaitEnd;
    }
  }

private:
  enum class Phase {
    kIdle,
    kNeedRow,
    kWaitRow,
    kNeedSourceCache,
    kScan,
    kSendEnd,
    kWaitEnd,
    kDone,
  };
  enum class RequestKind { kNone, kRow, kPma };

  struct SourceCacheSlot {
    std::size_t round{std::numeric_limits<std::size_t>::max()};
    std::size_t lines_received{};
    std::vector<std::uint32_t> words;
  };

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

  void stage_source_request() {
    if (phase_ == Phase::kSendEnd || phase_ == Phase::kWaitEnd ||
        source_end_sent_) {
      return;
    }
    const std::size_t request_round =
        std::max(pp_request_round_, pp_read_round_);
    if (request_round - pp_read_round_ > 1) {
      return;
    }
    if (ports_.source_requests->try_push(
            ReGraphSourceCacheRequest{.source_round = request_round})) {
      staged_source_request_ = request_round;
    }
  }

  void stage_source_response() {
    if (ports_.source_responses->front() == nullptr) {
      return;
    }
    ReGraphSourceCacheResponse response;
    if (ports_.source_responses->try_pop(response)) {
      staged_source_response_ = std::move(response);
    }
  }

  [[nodiscard]] std::size_t source_lines_per_round() const noexcept {
    return config_.source_buffer_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] bool source_cache_ready(std::size_t source_round) const {
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    return pp_write_round_ > source_round && slot.round == source_round &&
           slot.lines_received == source_lines_per_round();
  }

  void consume_source_response(const ReGraphSourceCacheResponse &response) {
    if (response.end) {
      if (phase_ != Phase::kWaitEnd) {
        throw std::runtime_error(
            "ReGraph source-cache end response arrived out of phase");
      }
      ++source_response_markers_;
      phase_ = Phase::kDone;
      return;
    }
    if (response.line >= source_lines_per_round()) {
      throw std::runtime_error("ReGraph source-cache line is out of range");
    }
    SourceCacheSlot &slot = source_cache_[response.source_round & 1U];
    if (response.line == 0) {
      slot.round = response.source_round;
      slot.lines_received = 0;
    }
    if (slot.round != response.source_round ||
        slot.lines_received != response.line) {
      throw std::runtime_error(
          "ReGraph source-cache response order does not match HLS stream");
    }
    std::copy(response.words.begin(), response.words.end(),
              slot.words.begin() + static_cast<std::ptrdiff_t>(
                                       response.line * kStateWordsPerBurst));
    ++slot.lines_received;
    pp_write_round_ = response.source_round;
    ++source_lines_;
    source_lane_writes_ += config_.edge_lanes;
  }

  void select_source_payload() {
    const SourceCacheSlot &slot = source_cache_[pp_read_round_ & 1U];
    const std::size_t offset = source_ % config_.source_buffer_vertices;
    const std::uint32_t encoded = slot.words.at(offset);
    source_active_ = (encoded & kReGraphActive) != 0;
    source_payload_ =
        policy_
            .prepare_source(
                AlgorithmVertexState{.primary = policy_distance(encoded)}, 0)
            .edge_payload;
    phase_ = Phase::kScan;
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
    if (phase_ == Phase::kWaitRow) {
      const std::uint64_t bounds = decode_u64(response.read_data);
      begin_segment_ =
          static_cast<std::uint32_t>(bounds >> 32) / kGraSuSegmentSlots;
      end_segment_ = static_cast<std::uint32_t>(bounds) / kGraSuSegmentSlots;
      next_segment_ = begin_segment_;
      if (begin_segment_ == end_segment_) {
        advance_source();
      } else {
        pp_read_round_ = source_ / config_.source_buffer_vertices;
        phase_ = Phase::kNeedSourceCache;
      }
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
        const std::uint32_t encoded =
            decode_u32(response.read_data, (offset + lane) * 4);
        batch.valid[lane] = !is_grasu_pma_empty(encoded);
        if (batch.valid[lane]) {
          batch.destinations[lane] = decode_grasu_pma_destination(encoded);
          batch.weights[lane] = decode_grasu_pma_weight(encoded);
        }
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
      phase_ = Phase::kSendEnd;
      return;
    }
    phase_ = Phase::kNeedRow;
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
  std::array<SourceCacheSlot, 2> source_cache_;
  std::size_t pp_read_round_{};
  std::size_t pp_write_round_{};
  std::size_t pp_request_round_{};
  bool source_active_{};
  std::uint32_t source_payload_{};
  std::deque<PmaEdgeBatch> pending_batches_;
  RequestKind staged_request_{RequestKind::kNone};
  std::optional<AxiResponse> staged_response_;
  std::vector<AxiResponse> staged_pma_responses_;
  std::optional<ReGraphSourceCacheResponse> staged_source_response_;
  std::optional<std::size_t> staged_source_request_;
  bool staged_output_{};
  bool staged_advance_{};
  bool staged_cache_ready_{};
  bool staged_source_end_{};
  bool source_end_sent_{};
  std::uint64_t row_reads_{};
  std::uint64_t source_requests_{};
  std::uint64_t source_request_markers_{};
  std::uint64_t source_lines_{};
  std::uint64_t source_lane_writes_{};
  std::uint64_t source_response_markers_{};
  std::uint64_t source_wait_cycles_{};
  std::uint64_t segment_reads_{};
};

class ReGraphGather final : public Component {
public:
  ReGraphGather(std::string name, ClockId clock_id, std::size_t vertices,
                GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                Fifo<PmaEdgeBatch> &input, Fifo<ReGraphGatherRow> &output,
                const PmaNativeReader &reader)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), reader_(reader), bank_rows_(config.gather_banks),
        bypass_(config.gather_banks,
                std::vector<BypassEntry>(config.gather_bypass_distance + 1)) {}

  void start_round(bool reset_tmp_prop) {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("ReGraph gather round started while busy");
    }
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
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
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
  [[nodiscard]] std::uint64_t pipeline_drain_cycles() const noexcept {
    return pipeline_drain_cycles_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t rows_emitted() const noexcept {
    return rows_emitted_;
  }
  [[nodiscard]] std::uint64_t conflict_cycles() const noexcept { return 0; }
  [[nodiscard]] std::uint64_t bank_updates() const noexcept {
    return bank_updates_;
  }
  [[nodiscard]] std::uint64_t bypass_hits() const noexcept {
    return bypass_hits_;
  }
  [[nodiscard]] std::uint64_t bypass_misses() const noexcept {
    return bypass_misses_;
  }
  [[nodiscard]] std::uint64_t cross_bank_reductions() const noexcept {
    return cross_bank_reductions_;
  }

  void evaluate(const CycleContext &) override {
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
        if (vertex >= vertices_) {
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
  }

  void commit(const CycleContext &context) override {
    commit_physical_writes(context.domain_cycle);
    if (phase_ == Phase::kReset && staged_tick_) {
      --remaining_;
      ++reset_cycles_;
      if (remaining_ == 0) {
        phase_ = Phase::kScan;
      }
      return;
    }
    if (phase_ == Phase::kMerge) {
      if (staged_output_stall_) {
        ++output_stall_cycles_;
      }
      if (!staged_row_output_) {
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
      return;
    }
    if (phase_ != Phase::kScan) {
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
      if (destination >= vertices_) {
        throw std::runtime_error("PMA edge exceeds ReGraph vertex range");
      }
      if (!batch.source_active) {
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
      const std::uint32_t candidate =
          policy_.map_edge(batch.source_payload, batch.weights[lane]);
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
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<PmaEdgeBatch> &input_;
  Fifo<ReGraphGatherRow> &output_;
  const PmaNativeReader &reader_;
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
};

class ReGraphMerger final : public Component {
public:
  ReGraphMerger(std::string name, ClockId clock_id,
                const GraSuReGraphConfig &config, Fifo<ReGraphGatherRow> &input,
                Fifo<ReGraphMergedBurst> &output)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        output_(output) {}

  void start_round() {
    if (running_ || pending_output_.has_value() || packed_rows_ != 0) {
      throw std::logic_error("ReGraph merger round started while busy");
    }
    consumed_rows_this_round_ = 0;
    done_ = false;
    running_ = true;
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t rows_consumed() const noexcept {
    return rows_consumed_;
  }
  [[nodiscard]] std::uint64_t bursts_emitted() const noexcept {
    return bursts_emitted_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }

  void evaluate(const CycleContext &) override {
    staged_input_.reset();
    staged_output_ = false;
    staged_output_stall_ = false;
    if (!running_) {
      return;
    }
    if (pending_output_.has_value()) {
      staged_output_ = output_.try_push(*pending_output_);
      if (!staged_output_) {
        staged_output_stall_ = true;
        return;
      }
    }
    if (consumed_rows_this_round_ == rows_per_round() ||
        input_.front() == nullptr) {
      return;
    }
    ReGraphGatherRow row;
    if (input_.try_pop(row)) {
      staged_input_ = std::move(row);
    }
  }

  void commit(const CycleContext &) override {
    if (!running_) {
      return;
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
    }
    if (staged_output_) {
      pending_output_.reset();
      ++bursts_emitted_;
    }
    if (staged_input_.has_value()) {
      if (staged_input_->row != consumed_rows_this_round_) {
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
            .offset = (consumed_rows_this_round_ - kRowsPerBurst) * 2,
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
  }

private:
  static constexpr std::size_t kRowsPerBurst = kStateWordsPerBurst / 2;

  [[nodiscard]] std::size_t rows_per_round() const noexcept {
    return config_.partition_vertices / 2;
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphGatherRow> &input_;
  Fifo<ReGraphMergedBurst> &output_;
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst>
      packed_candidates_{};
  std::optional<ReGraphGatherRow> staged_input_;
  std::optional<ReGraphMergedBurst> pending_output_;
  std::size_t consumed_rows_this_round_{};
  std::size_t packed_rows_{};
  bool staged_output_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  std::uint64_t rows_consumed_{};
  std::uint64_t bursts_emitted_{};
  std::uint64_t output_stall_cycles_{};
};

class ReGraphApply final : public Component {
public:
  ReGraphApply(std::string name, ClockId clock_id, std::size_t vertices,
               GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
               Fifo<ReGraphMergedBurst> &input,
               Fifo<ReGraphAppliedBurst> &output, FixedAxiPort &read_port,
               FixedAxiPort &write_port)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), read_port_(read_port), write_port_(write_port) {}

  void start_round(std::uint64_t round) {
    if (round == 0 || running_ || !read_inflight_.empty() ||
        !write_inflight_.empty() || !ready_writes_.empty()) {
      throw std::logic_error("ReGraph apply round started while busy");
    }
    completed_writes_ = 0;
    input_bursts_this_round_ = 0;
    next_write_offset_ = 0;
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
  [[nodiscard]] std::uint64_t input_bursts() const noexcept {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
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
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_read_response_.reset();
    staged_write_response_.reset();
    staged_output_stall_ = false;
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
        if (!write_port_.requests().full() && !output_.full()) {
          if (!write_port_.requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.offset),
                  .operation = MemoryOperation::kWrite,
                  .address = config_.vertex_state_base + item.offset * 4,
                  .bytes = kStateWordsPerBurst * 4,
                  .stream_read_beats = false,
                  .write_data = item.data,
              }) ||
              !output_.try_push(ReGraphAppliedBurst{
                  .offset = item.offset,
                  .data = item.data,
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
    const ReGraphMergedBurst &next = *input_.front();
    if (read_port_.requests().try_push(AxiRequest{
            .transaction_id = transaction_id(next.offset),
            .operation = MemoryOperation::kRead,
            .address = config_.vertex_state_base + next.offset * 4,
            .bytes = kStateWordsPerBurst * 4,
            .stream_read_beats = false,
            .write_data = {},
        })) {
      ReGraphMergedBurst consumed;
      if (!input_.try_pop(consumed)) {
        throw std::logic_error("ReGraph apply input staging failed");
      }
      staged_read_issue_ = std::move(consumed);
    }
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
    if (staged_output_stall_) {
      ++output_stall_cycles_;
    }
    if (staged_read_issue_.has_value()) {
      const std::uint64_t id = transaction_id(staged_read_issue_->offset);
      if (!read_inflight_.emplace(id, std::move(*staged_read_issue_)).second) {
        throw std::logic_error("duplicate ReGraph apply read transaction");
      }
      ++input_bursts_this_round_;
      ++input_bursts_;
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
      next_write_offset_ += kStateWordsPerBurst;
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
    ReGraphMergedBurst burst = std::move(found->second);
    read_inflight_.erase(found);
    std::array<std::uint32_t, kStateWordsPerBurst> result{};
    for (std::size_t lane = 0; lane < result.size(); ++lane) {
      const std::size_t vertex = burst.offset + lane;
      const std::uint32_t encoded = decode_u32(response.read_data, lane * 4);
      if (vertex >= vertices_) {
        result[lane] = kReGraphInfinity;
        continue;
      }
      const AlgorithmApplyResult applied = policy_.apply(
          AlgorithmVertexState{.primary = policy_distance(encoded)},
          burst.candidates[lane]);
      result[lane] =
          encode_distance(applied.state_after.primary, applied.active);
      if (applied.active) {
        ++active_vertices_;
        ++total_activated_;
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .offset = burst.offset,
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
  Fifo<ReGraphMergedBurst> &input_;
  Fifo<ReGraphAppliedBurst> &output_;
  FixedAxiPort &read_port_;
  FixedAxiPort &write_port_;
  std::unordered_map<std::uint64_t, ReGraphMergedBurst> read_inflight_;
  std::unordered_map<std::uint64_t, std::size_t> write_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<AxiResponse> staged_read_response_;
  std::optional<AxiResponse> staged_write_response_;
  std::optional<ReGraphMergedBurst> staged_read_issue_;
  std::optional<std::size_t> staged_write_issue_;
  std::size_t completed_writes_{};
  std::size_t input_bursts_this_round_{};
  std::size_t next_write_offset_{};
  std::size_t active_vertices_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  std::uint64_t reads_{};
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
};

class ReGraphHbmWrapper final : public Component {
public:
  ReGraphHbmWrapper(std::string name, ClockId clock_id,
                    const GraSuReGraphConfig &config,
                    Fifo<ReGraphAppliedBurst> &input,
                    FixedAxiPort &primary_write_port,
                    FixedAxiPort &mirror_write_port)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        write_ports_{&primary_write_port, &mirror_write_port} {}

  void start_round(std::uint64_t round) {
    const bool writes_pending =
        std::any_of(write_inflight_.begin(), write_inflight_.end(),
                    [](const auto &entries) { return !entries.empty(); });
    if (round == 0 || running_ || writes_pending || !pipeline_.empty()) {
      throw std::logic_error("ReGraph HBM wrapper round started while busy");
    }
    target_source_base_ = config_.source_state_base +
                          (round & 1U) * config_.source_state_buffer_stride;
    input_bursts_this_round_ = 0;
    completed_writes_ = 0;
    done_ = false;
    running_ = true;
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t input_bursts() const noexcept {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t source_writes() const noexcept {
    return source_writes_;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept {
    return write_window_stalls_;
  }
  [[nodiscard]] std::size_t max_pipeline_occupancy() const noexcept {
    return max_pipeline_occupancy_;
  }
  [[nodiscard]] std::size_t max_writes_inflight() const noexcept {
    return max_writes_inflight_;
  }

  void evaluate(const CycleContext &context) override {
    staged_input_.reset();
    staged_write_issue_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    if (!running_) {
      return;
    }
    for (std::size_t port = 0; port < write_ports_.size(); ++port) {
      if (write_ports_[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (write_ports_[port]->responses().try_pop(response)) {
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
        for (FixedAxiPort *port : write_ports_) {
          if (!port->requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.burst.offset),
                  .operation = MemoryOperation::kWrite,
                  .address = target_source_base_ + item.burst.offset * 4,
                  .bytes = kStateWordsPerBurst * 4,
                  .stream_read_beats = false,
                  .write_data = item.burst.data,
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
      return;
    }
    if (pipeline_.size() >= config_.hbm_wrapper_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      return;
    }
    ReGraphAppliedBurst burst;
    if (input_.try_pop(burst)) {
      staged_input_ = std::move(burst);
    }
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
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
    }
  }

private:
  struct ReadyWrite {
    ReGraphAppliedBurst burst;
    std::uint64_t due_cycle{};
  };

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return offset / kStateWordsPerBurst;
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
        [](const auto *port) { return !port->requests().full(); });
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
  std::array<FixedAxiPort *, 2> write_ports_;
  std::array<std::unordered_map<std::uint64_t, std::size_t>, 2> write_inflight_;
  std::deque<ReadyWrite> pipeline_;
  std::optional<ReGraphAppliedBurst> staged_input_;
  std::optional<std::size_t> staged_write_issue_;
  std::array<std::optional<AxiResponse>, 2> staged_write_responses_;
  std::size_t input_bursts_this_round_{};
  std::size_t completed_writes_{};
  std::uint64_t target_source_base_{};
  bool running_{};
  bool done_{};
  std::uint64_t input_bursts_{};
  std::uint64_t source_writes_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
};

class GraSuReGraphController final : public Component {
public:
  GraSuReGraphController(std::string name, ClockId clock_id,
                         std::size_t max_supersteps,
                         ReGraphSourceHbmReader &source_hbm,
                         PmaNativeReader &reader, ReGraphGather &gather,
                         ReGraphMerger &merger, ReGraphApply &apply,
                         ReGraphHbmWrapper &wrapper)
      : Component(std::move(name), clock_id), max_supersteps_(max_supersteps),
        source_hbm_(source_hbm), reader_(reader), gather_(gather),
        merger_(merger), apply_(apply), wrapper_(wrapper) {}

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
      staged_ = Action::kStartRound;
    } else if (phase_ == Phase::kRound && source_hbm_.done() &&
               reader_.done() && gather_.done() && merger_.done() &&
               apply_.done() && wrapper_.done()) {
      staged_ =
          apply_.active_vertices() == 0 ? Action::kFinish : Action::kNextRound;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_ == Action::kStartRound || staged_ == Action::kNextRound) {
      if (round_ == max_supersteps_) {
        failure_ = "ReGraph SSSP exceeded maximum supersteps";
        return;
      }
      ++round_;
      source_hbm_.start_round(round_);
      reader_.start_round(round_);
      gather_.start_round(round_ == 1);
      merger_.start_round();
      apply_.start_round(round_);
      wrapper_.start_round(round_);
      phase_ = Phase::kRound;
    } else if (staged_ == Action::kFinish) {
      phase_ = Phase::kDone;
    }
  }

private:
  enum class Phase { kStart, kRound, kDone };
  enum class Action { kNone, kStartRound, kNextRound, kFinish };

  std::size_t max_supersteps_{};
  ReGraphSourceHbmReader &source_hbm_;
  PmaNativeReader &reader_;
  ReGraphGather &gather_;
  ReGraphMerger &merger_;
  ReGraphApply &apply_;
  ReGraphHbmWrapper &wrapper_;
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
        source_request_axis_("regraph-source-cache-request-axis", clock_id_,
                             config_.source_cache_request_fifo_depth),
        source_response_axis_("regraph-source-cache-response-axis", clock_id_,
                              config_.source_cache_response_fifo_depth),
        gather_axis_("regraph-gather-merger-axis", clock_id_,
                     config_.gather_merger_fifo_depth),
        merger_axis_("regraph-merger-apply-axis", clock_id_,
                     config_.merger_apply_fifo_depth),
        wrapper_axis_("regraph-apply-wrapper-axis", clock_id_,
                      config_.apply_wrapper_fifo_depth),
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
    scheduler_.add_component(source_request_axis_);
    scheduler_.add_component(source_response_axis_);
    scheduler_.add_component(gather_axis_);
    scheduler_.add_component(merger_axis_);
    scheduler_.add_component(wrapper_axis_);
    row_port_->register_components(scheduler_);
    source_state_port_->register_components(scheduler_);
    for (auto &port : pma_ports_) {
      port->register_components(scheduler_);
    }
    apply_state_read_port_->register_components(scheduler_);
    apply_state_write_port_->register_components(scheduler_);
    source_state_primary_write_port_->register_components(scheduler_);
    source_state_mirror_write_port_->register_components(scheduler_);
    scheduler_.add_component(*source_hbm_reader_);
    scheduler_.add_component(*reader_);
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
  [[nodiscard]] bool failed() const noexcept { return controller_->failed(); }
  [[nodiscard]] const std::string &failure() const noexcept {
    return controller_->failure();
  }

  [[nodiscard]] GraSuReGraphCounters counters() const noexcept {
    GraSuReGraphCounters result;
    result.supersteps = controller_->supersteps();
    result.row_reads = reader_->row_reads();
    result.source_state_reads = source_hbm_reader_->requests();
    result.source_cache_requests = reader_->source_requests();
    result.source_cache_request_markers = reader_->source_request_markers();
    result.source_cache_lines = reader_->source_lines();
    result.source_cache_lane_writes = reader_->source_lane_writes();
    result.source_cache_response_markers = reader_->source_response_markers();
    result.source_cache_wait_cycles = reader_->source_wait_cycles();
    result.source_cache_output_stall_cycles =
        source_hbm_reader_->output_stall_cycles();
    result.source_cache_request_fifo_max_occupancy =
        source_request_axis_.stats().max_occupancy;
    result.source_cache_response_fifo_max_occupancy =
        source_response_axis_.stats().max_occupancy;
    result.source_state_writes = wrapper_->source_writes();
    result.pma_segment_reads = reader_->segment_reads();
    result.edge_batches_scanned = gather_->batches_scanned();
    result.pma_slots_scanned = gather_->slots_scanned();
    result.live_edges_scanned = gather_->live_edges();
    result.active_edges_mapped = gather_->active_edges();
    result.gather_reset_cycles = gather_->reset_cycles();
    result.gather_merge_cycles = gather_->merge_cycles();
    result.gather_pipeline_drain_cycles = gather_->pipeline_drain_cycles();
    result.gather_output_stall_cycles = gather_->output_stall_cycles();
    result.gather_bank_conflict_cycles = gather_->conflict_cycles();
    result.gather_bank_updates = gather_->bank_updates();
    result.gather_bypass_hits = gather_->bypass_hits();
    result.gather_bypass_misses = gather_->bypass_misses();
    result.gather_cross_bank_reductions = gather_->cross_bank_reductions();
    result.gather_rows_emitted = gather_->rows_emitted();
    result.merger_rows_consumed = merger_->rows_consumed();
    result.merger_bursts_emitted = merger_->bursts_emitted();
    result.merger_output_stall_cycles = merger_->output_stall_cycles();
    result.apply_state_reads = apply_->reads();
    result.apply_state_writes = apply_->writes();
    result.apply_input_bursts = apply_->input_bursts();
    result.apply_output_stall_cycles = apply_->output_stall_cycles();
    result.apply_read_window_stalls = apply_->read_window_stalls();
    result.apply_pipeline_capacity_stalls = apply_->pipeline_capacity_stalls();
    result.apply_write_window_stalls = apply_->write_window_stalls();
    result.apply_max_reads_inflight = apply_->max_reads_inflight();
    result.apply_max_pipeline_occupancy = apply_->max_pipeline_occupancy();
    result.apply_max_writes_inflight = apply_->max_writes_inflight();
    result.hbm_wrapper_input_bursts = wrapper_->input_bursts();
    result.hbm_wrapper_pipeline_capacity_stalls =
        wrapper_->pipeline_capacity_stalls();
    result.hbm_wrapper_write_window_stalls = wrapper_->write_window_stalls();
    result.hbm_wrapper_max_pipeline_occupancy =
        wrapper_->max_pipeline_occupancy();
    result.hbm_wrapper_max_writes_inflight = wrapper_->max_writes_inflight();
    result.gather_merger_fifo_max_occupancy =
        gather_axis_.stats().max_occupancy;
    result.merger_apply_fifo_max_occupancy = merger_axis_.stats().max_occupancy;
    result.apply_wrapper_fifo_max_occupancy =
        wrapper_axis_.stats().max_occupancy;
    result.activated_vertices = apply_->total_activated();
    result.row_read_bytes = result.row_reads * 8;
    result.source_state_read_bytes = source_hbm_reader_->read_bytes();
    result.source_state_write_bytes = result.source_state_writes * 64;
    result.pma_read_bytes = result.pma_segment_reads * kGraSuSegmentBytes;
    result.apply_read_bytes = result.apply_state_reads * 64;
    result.apply_write_bytes = result.apply_state_writes * 64;
    result.axi_backend_submit_stalls =
        row_port_->master().stats().backend_submit_stalls +
        source_state_port_->master().stats().backend_submit_stalls +
        apply_state_read_port_->master().stats().backend_submit_stalls +
        apply_state_write_port_->master().stats().backend_submit_stalls +
        source_state_primary_write_port_->master()
            .stats()
            .backend_submit_stalls +
        source_state_mirror_write_port_->master().stats().backend_submit_stalls;
    for (const auto &port : pma_ports_) {
      result.axi_backend_submit_stalls +=
          port->master().stats().backend_submit_stalls;
    }
    result.axis_push_stalls =
        source_request_axis_.stats().push_stalls +
        source_response_axis_.stats().push_stalls +
        edge_axis_.stats().push_stalls + gather_axis_.stats().push_stalls +
        merger_axis_.stats().push_stalls + wrapper_axis_.stats().push_stalls;
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
        config_.source_state_buffer_stride <
            config_.partition_vertices * sizeof(std::uint32_t) ||
        config_.source_state_buffer_stride % 4096 != 0 ||
        config_.source_buffer_vertices == 0 ||
        config_.source_buffer_vertices % kStateWordsPerBurst != 0 ||
        config_.source_cache_request_fifo_depth == 0 ||
        config_.source_cache_response_fifo_depth == 0 ||
        config_.edge_lanes == 0 || config_.edge_lanes > 8 ||
        kGraSuSegmentSlots % config_.edge_lanes != 0 ||
        config_.gather_banks != config_.edge_lanes ||
        config_.gather_bypass_distance == 0 ||
        config_.gather_pipeline_latency <= config_.gather_bypass_distance ||
        config_.gather_vertices_per_reset_cycle == 0 ||
        config_.gather_vertices_per_merge_cycle != 2 ||
        config_.axis_fifo_depth == 0 || config_.gather_merger_fifo_depth == 0 ||
        config_.merger_apply_fifo_depth == 0 ||
        config_.apply_wrapper_fifo_depth == 0 ||
        config_.reader_buffer_batches <
            kGraSuSegmentSlots / config_.edge_lanes ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.apply_request_window == 0 ||
        config_.apply_pipeline_latency == 0 ||
        config_.apply_pipeline_capacity == 0 ||
        config_.hbm_wrapper_pipeline_latency == 0 ||
        config_.hbm_wrapper_pipeline_capacity == 0 ||
        config_.max_supersteps == 0 ||
        config_.row_channel >= config_.memory_channels ||
        config_.source_state_channel >= config_.memory_channels ||
        config_.source_state_mirror_channel >= config_.memory_channels ||
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

  std::unique_ptr<FixedAxiPort> make_source_stream_port() {
    FixedAxiPortConfig source = port_config(
        config_, config_.source_state_channel, next_initiator_++, 64);
    source.stream_read_beats = true;
    source.read_beat_fifo_depth = config_.source_cache_response_fifo_depth;
    source.read_reorder_capacity = config_.max_outstanding_bursts * 16;
    return std::make_unique<FixedAxiPort>("grasu-regraph-source-state",
                                          clock_id_, source, backend_);
  }

  void construct_ports() {
    row_port_ = make_port("grasu-regraph-row", config_.row_channel, 8);
    source_state_port_ = make_source_stream_port();
    for (std::size_t channel = 0; channel < pma_ports_.size(); ++channel) {
      pma_ports_[channel] =
          make_port("grasu-regraph-pma" + std::to_string(channel), channel, 64);
    }
    apply_state_read_port_ = make_port("grasu-regraph-apply-state-read",
                                       config_.vertex_state_channel, 64);
    apply_state_write_port_ = make_port("grasu-regraph-apply-state-write",
                                        config_.vertex_state_channel, 64);
    source_state_primary_write_port_ =
        make_port("grasu-regraph-source-state-primary-write",
                  config_.source_state_channel, 64);
    source_state_mirror_write_port_ =
        make_port("grasu-regraph-source-state-mirror-write",
                  config_.source_state_mirror_channel, 64);
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
    backend_.initialize_payload(config_.source_state_channel,
                                config_.source_state_base, bytes);
    backend_.initialize_payload(config_.source_state_mirror_channel,
                                config_.source_state_base, bytes);
  }

  void construct_components() {
    std::array<FixedAxiPort *, 4> pma{};
    for (std::size_t index = 0; index < pma.size(); ++index) {
      pma[index] = pma_ports_[index].get();
    }
    source_hbm_reader_ = std::make_unique<ReGraphSourceHbmReader>(
        "grasu-regraph-source-hbm-reader", clock_id_, config_,
        source_request_axis_, source_response_axis_, *source_state_port_);
    reader_ = std::make_unique<PmaNativeReader>(
        "grasu-regraph-reader", clock_id_, layout_.vertices, policy_, config_,
        PmaNativeReader::Ports{
            .rows = row_port_.get(),
            .pma = pma,
            .output = &edge_axis_,
            .source_requests = &source_request_axis_,
            .source_responses = &source_response_axis_,
        });
    gather_ = std::make_unique<ReGraphGather>(
        "grasu-regraph-gather", clock_id_, layout_.vertices, policy_, config_,
        edge_axis_, gather_axis_, *reader_);
    merger_ = std::make_unique<ReGraphMerger>(
        "grasu-regraph-merger", clock_id_, config_, gather_axis_, merger_axis_);
    apply_ = std::make_unique<ReGraphApply>(
        "grasu-regraph-apply", clock_id_, layout_.vertices, policy_, config_,
        merger_axis_, wrapper_axis_, *apply_state_read_port_,
        *apply_state_write_port_);
    wrapper_ = std::make_unique<ReGraphHbmWrapper>(
        "grasu-regraph-hbm-wrapper", clock_id_, config_, wrapper_axis_,
        *source_state_primary_write_port_, *source_state_mirror_write_port_);
    controller_ = std::make_unique<GraSuReGraphController>(
        "grasu-regraph-controller", clock_id_, config_.max_supersteps,
        *source_hbm_reader_, *reader_, *gather_, *merger_, *apply_, *wrapper_);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    if (!source_request_axis_.empty() || !source_response_axis_.empty() ||
        !edge_axis_.empty() || !gather_axis_.empty() || !merger_axis_.empty() ||
        !wrapper_axis_.empty() || !row_port_->idle() ||
        !source_state_port_->idle() || !apply_state_read_port_->idle() ||
        !apply_state_write_port_->idle() ||
        !source_state_primary_write_port_->idle() ||
        !source_state_mirror_write_port_->idle()) {
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
  Fifo<ReGraphSourceCacheRequest> source_request_axis_;
  Fifo<ReGraphSourceCacheResponse> source_response_axis_;
  Fifo<ReGraphGatherRow> gather_axis_;
  Fifo<ReGraphMergedBurst> merger_axis_;
  Fifo<ReGraphAppliedBurst> wrapper_axis_;
  std::unique_ptr<FixedAxiPort> row_port_;
  std::unique_ptr<FixedAxiPort> source_state_port_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports_;
  std::unique_ptr<FixedAxiPort> apply_state_read_port_;
  std::unique_ptr<FixedAxiPort> apply_state_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_primary_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_mirror_write_port_;
  std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader_;
  std::unique_ptr<PmaNativeReader> reader_;
  std::unique_ptr<ReGraphGather> gather_;
  std::unique_ptr<ReGraphMerger> merger_;
  std::unique_ptr<ReGraphApply> apply_;
  std::unique_ptr<ReGraphHbmWrapper> wrapper_;
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
