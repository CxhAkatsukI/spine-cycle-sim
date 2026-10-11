#include "detail/grasu_regraph_streams.hpp"

#include <cmath>
#include <deque>
#include <limits>
#include <utility>

#include "spine_sim/grasu_native.hpp"

namespace spine::sim::detail {
namespace {

class PmaNativeReader final : public ReGraphPartitionReader {
public:
  PmaNativeReader(std::string name, ClockId clock_id, std::size_t vertices,
                  GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                  Ports ports)
      : ReGraphPartitionReader(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), ports_(ports) {
    if (vertices_ == 0 || ports_.rows == nullptr || ports_.output == nullptr ||
        ports_.source_requests == nullptr ||
        ports_.source_responses == nullptr ||
        std::any_of(ports_.pma.begin(), ports_.pma.end(),
                    [](const auto *port) { return port == nullptr; })) {
      throw std::invalid_argument("invalid PMA-native reader ports");
    }
    if (uses_degree() && ports_.degree == nullptr) {
      throw std::invalid_argument("PageRank PMA reader requires a degree port");
    }
  }

  void start_partition(std::uint64_t round, const ReGraphPartitionPlan &plan,
                       bool accumulate_dangling) override {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("PMA reader round started while busy");
    }
    if (round == 0) {
      throw std::invalid_argument("PMA reader round is one-based");
    }
    round_ = round;
    row_base_ = plan.row_base;
    row_channel_ = plan.row_channel;
    pma_base_ = plan.pma_base;
    pma_channel_ = plan.pma_channel;
    accumulate_dangling_ = accumulate_dangling;
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
    source_degree_ = 0;
    source_map_cycles_remaining_ = 0;
    if (config_.pagerank_prepared_source && uses_page_rank()) {
      dangling_mass_.reset();
    } else if (accumulate_dangling_) {
      dangling_mass_.reset();
    } else if (uses_degree() && !dangling_mass_.has_value()) {
      throw std::logic_error(
          "PMA reader partition started before dangling context was computed");
    }
    for (auto &slot : source_cache_) {
      slot.round = std::numeric_limits<std::size_t>::max();
      slot.lines_received = 0;
      slot.words.assign(config_.source_buffer_vertices, 0);
      slot.auxiliary_words.assign(config_.source_buffer_vertices, 0);
    }
    phase_ = Phase::kNeedRow;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept override {
    return phase_ == Phase::kDone;
  }
  [[nodiscard]] std::uint64_t row_reads() const noexcept override { return row_reads_; }
  [[nodiscard]] std::uint64_t source_requests() const noexcept override {
    return source_requests_;
  }
  [[nodiscard]] std::uint64_t source_request_markers() const noexcept override {
    return source_request_markers_;
  }
  [[nodiscard]] std::uint64_t source_lines() const noexcept override {
    return source_lines_;
  }
  [[nodiscard]] std::uint64_t source_lane_writes() const noexcept override {
    return source_lane_writes_;
  }
  [[nodiscard]] std::uint64_t source_response_markers() const noexcept override {
    return source_response_markers_;
  }
  [[nodiscard]] std::uint64_t source_wait_cycles() const noexcept override {
    return source_wait_cycles_;
  }
  [[nodiscard]] std::uint64_t segment_reads() const noexcept override {
    return segment_reads_;
  }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept override {
    return degree_reads_;
  }
  [[nodiscard]] std::uint64_t source_map_cycles() const noexcept override {
    return source_map_cycles_;
  }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    if (!uses_degree()) {
      return {};
    }
    const float dangling = GraphAlgorithmPolicy::word_to_float(
        dangling_mass_.value_or(GraphAlgorithmPolicy::float_to_word(0.0F)));
    return {
        .base = policy_.config().kind == GraphAlgorithmKind::kFullPageRank
                    ? policy_.initial_base_word()
                    : GraphAlgorithmPolicy::float_to_word(0.0F),
        .dangling_share = GraphAlgorithmPolicy::float_to_word(
            policy_.config().damping * dangling /
            static_cast<float>(policy_.config().vertices)),
    };
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
    return phase_ != Phase::kIdle && phase_ != Phase::kDone;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return false;
    }
    return staged_tick_ || staged_request_ != RequestKind::kNone ||
           staged_response_.has_value() ||
           staged_degree_response_.has_value() ||
           !staged_pma_responses_.empty() ||
           staged_source_response_.has_value() ||
           staged_source_request_.has_value() || staged_output_ ||
           staged_advance_ || staged_cache_ready_ || staged_source_end_ ||
           phase_ == Phase::kNeedSourceCache;
  }

  void evaluate(const CycleContext &) override {
    staged_tick_ = false;
    staged_request_ = RequestKind::kNone;
    staged_response_.reset();
    staged_degree_response_.reset();
    staged_pma_responses_.clear();
    staged_source_response_.reset();
    staged_source_request_.reset();
    staged_output_ = false;
    staged_advance_ = false;
    staged_cache_ready_ = false;
    staged_source_end_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      set_latched_commit_ready(false);
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
    case Phase::kNeedDegree:
      if (ports_.degree->requests().try_push(AxiRequest{
              .transaction_id = next_transaction_id_,
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + source_ * 4,
              .bytes = 4,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        staged_request_ = RequestKind::kDegree;
      }
      break;
    case Phase::kWaitDegree:
      if (ports_.degree->responses().front() != nullptr) {
        AxiResponse response;
        if (ports_.degree->responses().try_pop(response)) {
          staged_degree_response_ = std::move(response);
        }
      }
      break;
    case Phase::kSourceMapDelay:
      staged_tick_ = true;
      break;
    case Phase::kNeedRow:
      if (ports_.rows->requests().try_push(AxiRequest{
              .transaction_id = next_transaction_id_,
              .operation = MemoryOperation::kRead,
              .address = row_base_ + source_ * 8,
              .bytes = 8,
              .stream_read_beats = false,
              .target_channel = row_channel_,
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
    set_latched_commit_ready(commit_ready());
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
    if (staged_degree_response_.has_value()) {
      consume_degree_response(*staged_degree_response_);
      staged_degree_response_.reset();
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
    } else if (staged_request_ == RequestKind::kDegree) {
      ++degree_reads_;
      phase_ = Phase::kWaitDegree;
    }
    if (staged_request_ != RequestKind::kNone) {
      ++next_transaction_id_;
    }
    if (staged_advance_) {
      advance_source();
    }
    if (staged_cache_ready_) {
      select_source_state();
    } else if (phase_ == Phase::kNeedSourceCache) {
      ++source_wait_cycles_;
    }
    if (staged_source_end_) {
      source_end_sent_ = true;
      ++source_request_markers_;
      phase_ = Phase::kWaitEnd;
    }
    if (phase_ == Phase::kSourceMapDelay && staged_tick_) {
      if (source_map_cycles_remaining_ == 0) {
        throw std::logic_error("ReGraph source-map delay underflow");
      }
      --source_map_cycles_remaining_;
      ++source_map_cycles_;
      if (source_map_cycles_remaining_ == 0) {
        phase_ = Phase::kScan;
      }
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(evaluate_ready());
  }

private:
  enum class Phase {
    kIdle,
    kNeedRow,
    kWaitRow,
    kNeedSourceCache,
    kNeedDegree,
    kWaitDegree,
    kSourceMapDelay,
    kScan,
    kSendEnd,
    kWaitEnd,
    kDone,
  };
  enum class RequestKind { kNone, kRow, kPma, kDegree };

  struct SourceCacheSlot {
    std::size_t round{std::numeric_limits<std::size_t>::max()};
    std::size_t lines_received{};
    std::vector<std::uint32_t> words;
    std::vector<std::uint32_t> auxiliary_words;
  };

  [[nodiscard]] std::size_t pma_port(std::size_t segment) const {
    const std::size_t local = segment >> 1;
    const std::size_t parity = segment & 1U;
    return local < config_.cache_segments_per_half ? parity * 2
                                                   : parity * 2 + 1;
  }

  [[nodiscard]] std::uint64_t pma_address(std::size_t segment) const {
    const std::size_t port = pma_port(segment);
    return pma_base_[port] + (segment >> 1) * kGraSuSegmentBytes;
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
    const std::size_t vertices_per_beat =
        config_.pagerank_prepared_source && uses_page_rank()
            ? kStateWordsPerBurst
            : state_vertices_per_beat(policy_);
    return config_.source_buffer_vertices / vertices_per_beat;
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
      notify_done();
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
    const std::size_t expected_vertices =
        config_.pagerank_prepared_source && uses_page_rank()
            ? kStateWordsPerBurst
            : state_vertices_per_beat(policy_);
    if (response.vertices != expected_vertices) {
      throw std::runtime_error(
          "ReGraph source-cache response has the wrong vertex count");
    }
    const std::size_t offset = response.line * response.vertices;
    std::copy_n(response.words.begin(), response.vertices,
                slot.words.begin() + static_cast<std::ptrdiff_t>(offset));
    if (uses_auxiliary_state(policy_) && !config_.pagerank_prepared_source) {
      std::copy_n(response.auxiliary_words.begin(), response.vertices,
                  slot.auxiliary_words.begin() +
                      static_cast<std::ptrdiff_t>(offset));
    }
    ++slot.lines_received;
    pp_write_round_ = response.source_round;
    ++source_lines_;
    source_lane_writes_ += config_.edge_lanes;
  }

  [[nodiscard]] bool uses_degree() const noexcept {
    return uses_page_rank() && !config_.pagerank_prepared_source;
  }

  [[nodiscard]] bool uses_page_rank() const noexcept {
    return policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
           policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
  }

  void select_source_state() {
    const SourceCacheSlot &slot = source_cache_[pp_read_round_ & 1U];
    const std::size_t offset = source_ % config_.source_buffer_vertices;
    const std::uint32_t encoded = slot.words.at(offset);
    if (config_.pagerank_prepared_source && uses_page_rank()) {
      source_state_ = encoded;
      source_auxiliary_ = 0;
      source_payload_ = encoded;
      source_active_ = encoded != GraphAlgorithmPolicy::float_to_word(0.0F);
      phase_ = Phase::kScan;
      return;
    }
    source_state_ = decode_policy_value(policy_, encoded);
    source_auxiliary_ =
        uses_auxiliary_state(policy_) ? slot.auxiliary_words.at(offset) : 0;
    source_active_ =
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank
            ? std::fabs(
                  GraphAlgorithmPolicy::word_to_float(source_auxiliary_)) >
                  GraphAlgorithmPolicy::word_to_float(
                      policy_.activation_threshold_word())
            : (encoded & kReGraphActive) != 0;
    if (uses_degree()) {
      phase_ = Phase::kNeedDegree;
    } else {
      prepare_source_payload(0);
    }
  }

  void prepare_source_payload(std::uint32_t out_degree) {
    const AlgorithmSourceResult prepared = policy_.prepare_source(
        AlgorithmVertexState{.primary = source_state_,
                             .auxiliary = source_auxiliary_},
        out_degree);
    source_payload_ = source_active_ ? prepared.edge_payload : 0;
    if (uses_degree()) {
      if (accumulate_dangling_) {
        dangling_mass_ = policy_.reduce(
            dangling_mass_, source_active_
                                ? prepared.dangling_payload
                                : GraphAlgorithmPolicy::float_to_word(0.0F));
      }
      source_map_cycles_remaining_ = config_.pagerank_source_map_latency;
      phase_ = source_map_cycles_remaining_ == 0 ? Phase::kScan
                                                 : Phase::kSourceMapDelay;
    } else {
      phase_ = Phase::kScan;
    }
  }

  void consume_degree_response(const AxiResponse &response) {
    if (phase_ != Phase::kWaitDegree || !response.success ||
        response.read_data.size() != 4) {
      throw std::runtime_error("PMA reader received malformed degree response");
    }
    source_degree_ = decode_u32(response.read_data);
    prepare_source_payload(source_degree_);
  }

  void stage_pma_request() {
    if (next_segment_ >= end_segment_ ||
        pending_batches_.size() +
                staged_pma_responses_.size() * batches_per_segment() +
                batches_per_segment() >
            config_.reader_buffer_batches) {
      return;
    }
    const std::size_t logical_port = pma_port(next_segment_);
    FixedAxiPort &port = *ports_.pma[logical_port];
    if (port.requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = MemoryOperation::kRead,
            .address = pma_address(next_segment_),
            .bytes = kGraSuSegmentBytes,
            .stream_read_beats = false,
            .target_channel = pma_channel_[logical_port],
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
      if (begin_segment_ == end_segment_ &&
          (!uses_degree() || !accumulate_dangling_)) {
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
  std::uint64_t row_base_{};
  std::size_t row_channel_{};
  std::array<std::uint64_t, 4> pma_base_{};
  std::array<std::size_t, 4> pma_channel_{};
  bool accumulate_dangling_{};
  std::uint64_t next_transaction_id_{0x7100'0000'0000'0000ULL};
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
  std::uint32_t source_state_{};
  std::uint32_t source_auxiliary_{};
  std::uint32_t source_payload_{};
  std::uint32_t source_degree_{};
  std::size_t source_map_cycles_remaining_{};
  std::optional<std::uint32_t> dangling_mass_;
  std::deque<PmaEdgeBatch> pending_batches_;
  RequestKind staged_request_{RequestKind::kNone};
  std::optional<AxiResponse> staged_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::vector<AxiResponse> staged_pma_responses_;
  std::optional<ReGraphSourceCacheResponse> staged_source_response_;
  std::optional<std::size_t> staged_source_request_;
  bool staged_output_{};
  bool staged_tick_{};
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
  std::uint64_t degree_reads_{};
  std::uint64_t source_map_cycles_{};
};

} // namespace

std::unique_ptr<ReGraphPartitionReader> make_legacy_pma_reader(
    std::string name, ClockId clock_id, std::size_t vertices,
    GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
    ReGraphPartitionReader::Ports ports) {
  return std::make_unique<PmaNativeReader>(std::move(name), clock_id, vertices,
                                         std::move(policy), config, ports);
}

} // namespace spine::sim::detail
