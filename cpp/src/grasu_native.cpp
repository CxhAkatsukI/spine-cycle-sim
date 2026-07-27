#include "spine_sim/grasu_native.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <optional>
#include <stdexcept>
#include <utility>

#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace {

constexpr std::size_t kReGraphEdgesPerBurst = 8;
constexpr std::size_t kReGraphEdgeBytes = 8;
constexpr std::uint32_t kReGraphUnitWeight = 1U << kGraSuPmaWeightShift;

std::uint32_t decode_u32(const std::vector<std::uint8_t> &bytes,
                         std::size_t offset) {
  if (offset + 4 > bytes.size()) {
    throw std::invalid_argument("native compactor payload is truncated");
  }
  std::uint32_t value = 0;
  for (std::size_t byte = 0; byte < 4; ++byte) {
    value |= static_cast<std::uint32_t>(bytes[offset + byte]) << (byte * 8);
  }
  return value;
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != 8) {
    throw std::invalid_argument("native compactor row payload has wrong size");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < 8; ++byte) {
    value |= static_cast<std::uint64_t>(bytes[byte]) << (byte * 8);
  }
  return value;
}

void write_u32(std::array<std::uint8_t, kGraSuSegmentBytes> &bytes,
               std::size_t offset, std::uint32_t value) {
  for (std::size_t byte = 0; byte < 4; ++byte) {
    bytes.at(offset + byte) = static_cast<std::uint8_t>(value >> (byte * 8));
  }
}

FixedAxiPortConfig port_config(const GraSuNativeCompactorConfig &config,
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

class NativePmaCompactor final : public Component {
public:
  struct Ports {
    FixedAxiPort *rows{};
    std::array<FixedAxiPort *, 4> pma{};
    FixedAxiPort *edge_array{};
  };

  NativePmaCompactor(std::string name, ClockId clock_id,
                     const GraSuPmaLayout &layout,
                     std::size_t compact_edge_slots,
                     GraSuNativeCompactorConfig config, Ports ports)
      : Component(std::move(name), clock_id), layout_(layout),
        compact_edge_slots_(compact_edge_slots), config_(config), ports_(ports),
        pma_slot_count_(layout.segments.size() * kGraSuSegmentSlots) {
    if (ports_.rows == nullptr || ports_.edge_array == nullptr ||
        std::any_of(ports_.pma.begin(), ports_.pma.end(),
                    [](const auto *port) { return port == nullptr; })) {
      throw std::invalid_argument("native compactor ports are incomplete");
    }
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const GraSuNativeCompactorCounters &counters() const noexcept {
    return counters_;
  }

  void evaluate(const CycleContext &) override {
    staged_action_ = Action::kNone;
    staged_read_.reset();
    staged_write_response_.reset();
    staged_slot_.reset();
    if (failed() || done()) {
      return;
    }

    stage_write_response();
    switch (phase_) {
    case Phase::kBarrier:
      staged_action_ = Action::kBarrierToken;
      break;
    case Phase::kNeedTotalRow:
    case Phase::kNeedRow:
      stage_row_request();
      break;
    case Phase::kWaitTotalRow:
    case Phase::kWaitRow:
      stage_read_response(*ports_.rows);
      break;
    case Phase::kNeedSegment:
      if (next_segment_ == end_segment_) {
        staged_action_ = Action::kAdvanceSource;
      } else {
        stage_pma_request();
      }
      break;
    case Phase::kWaitSegment:
      stage_read_response(*ports_.pma[pma_channel(next_segment_)]);
      break;
    case Phase::kLanePipeline:
      staged_action_ = Action::kPipelineTick;
      break;
    case Phase::kScan:
      stage_scan_slot();
      break;
    case Phase::kPad:
      if (emitted_slots_ == compact_edge_slots_) {
        staged_action_ = Action::kBeginDrain;
      } else {
        stage_output_slot(0, 0, true, false);
      }
      break;
    case Phase::kDrain:
      if (pending_writes_ == 0 && ports_.edge_array->idle()) {
        staged_action_ = Action::kFinish;
      }
      break;
    case Phase::kDone:
      break;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_write_response_.has_value()) {
      consume_write_response(*staged_write_response_);
    }
    if (failed()) {
      return;
    }
    if (staged_read_.has_value()) {
      consume_read_response(*staged_read_);
      if (failed()) {
        return;
      }
    }
    if (staged_slot_.has_value()) {
      commit_slot(*staged_slot_);
    }
    switch (staged_action_) {
    case Action::kBarrierToken:
      ++counters_.completion_token_reads;
      ++counters_.barrier_cycles;
      if (counters_.completion_token_reads == config_.completion_tokens) {
        phase_ = Phase::kNeedTotalRow;
      }
      break;
    case Action::kIssueTotalRow:
      ++counters_.row_reads;
      phase_ = Phase::kWaitTotalRow;
      break;
    case Action::kIssueRow:
      ++counters_.row_reads;
      phase_ = Phase::kWaitRow;
      break;
    case Action::kIssueSegment:
      ++counters_.pma_segment_reads;
      phase_ = Phase::kWaitSegment;
      break;
    case Action::kPipelineTick:
      ++counters_.lane_pipeline_cycles;
      if (--pipeline_cycles_remaining_ == 0) {
        lane_ = 0;
        phase_ = Phase::kScan;
      }
      break;
    case Action::kAdvanceSource:
      advance_source();
      break;
    case Action::kBeginDrain:
      phase_ = Phase::kDrain;
      break;
    case Action::kFinish:
      phase_ = Phase::kDone;
      break;
    case Action::kNone:
      break;
    }
  }

private:
  enum class Phase {
    kBarrier,
    kNeedTotalRow,
    kWaitTotalRow,
    kNeedRow,
    kWaitRow,
    kNeedSegment,
    kWaitSegment,
    kLanePipeline,
    kScan,
    kPad,
    kDrain,
    kDone,
  };
  enum class Action {
    kNone,
    kBarrierToken,
    kIssueTotalRow,
    kIssueRow,
    kIssueSegment,
    kPipelineTick,
    kAdvanceSource,
    kBeginDrain,
    kFinish,
  };
  struct StagedSlot {
    std::uint32_t source{};
    std::uint32_t raw_destination{};
    bool dummy{};
    bool valid_seen{};
    bool append{};
    bool write_issued{};
    std::array<std::uint8_t, kGraSuSegmentBytes> next_burst{};
  };

  void fail(std::string message) {
    if (failure_.empty()) {
      failure_ = std::move(message);
    }
  }

  [[nodiscard]] std::uint64_t next_transaction() noexcept {
    return next_transaction_++;
  }

  void stage_write_response() {
    if (ports_.edge_array->responses().front() == nullptr) {
      return;
    }
    AxiResponse response;
    if (ports_.edge_array->responses().try_pop(response)) {
      staged_write_response_ = std::move(response);
    }
  }

  void stage_read_response(FixedAxiPort &port) {
    if (port.responses().front() == nullptr) {
      return;
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      staged_read_ = std::move(response);
    }
  }

  void stage_row_request() {
    const std::size_t row =
        phase_ == Phase::kNeedTotalRow ? layout_.vertices - 1 : source_;
    if (ports_.rows->requests().try_push(AxiRequest{
            .transaction_id = next_transaction(),
            .operation = MemoryOperation::kRead,
            .address = config_.row_offset_base + row * 8,
            .bytes = 8,
            .stream_read_beats = false,
            .write_data = {},
        })) {
      staged_action_ = phase_ == Phase::kNeedTotalRow ? Action::kIssueTotalRow
                                                      : Action::kIssueRow;
    }
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

  void stage_pma_request() {
    if (ports_.pma[pma_channel(next_segment_)]->requests().try_push(AxiRequest{
            .transaction_id = next_transaction(),
            .operation = MemoryOperation::kRead,
            .address = pma_address(next_segment_),
            .bytes = kGraSuSegmentBytes,
            .stream_read_beats = false,
            .write_data = {},
        })) {
      staged_action_ = Action::kIssueSegment;
    }
  }

  void stage_scan_slot() {
    const std::uint64_t slot = next_segment_ * kGraSuSegmentSlots + lane_;
    const std::uint32_t raw = decode_u32(current_segment_, lane_ * 4);
    const bool valid = (raw & kGraSuPmaEmpty) == 0 && slot >= row_begin_ &&
                       slot < row_end_ && slot < total_slots_;
    if (valid && raw >= layout_.vertices) {
      fail("native GraSU PMA word is not a raw in-range destination");
      return;
    }
    if (valid) {
      stage_output_slot(static_cast<std::uint32_t>(source_), raw, false, true);
    } else {
      staged_slot_ = StagedSlot{.valid_seen = false, .append = false};
    }
  }

  void stage_output_slot(std::uint32_t source, std::uint32_t raw_destination,
                         bool dummy, bool valid_seen) {
    if (!dummy && emitted_slots_ >= compact_edge_slots_) {
      staged_slot_ = StagedSlot{.valid_seen = valid_seen, .append = false};
      return;
    }
    auto next = burst_;
    const std::size_t offset = burst_lane_ * kReGraphEdgeBytes;
    write_u32(next, offset, dummy ? source | kGraSuPmaEmpty : source);
    write_u32(next, offset + 4,
              (raw_destination & kGraSuPmaDestinationMask) |
                  kReGraphUnitWeight | (dummy ? kGraSuPmaEmpty : 0U));
    const bool full = burst_lane_ + 1 == kReGraphEdgesPerBurst;
    if (full) {
      std::vector<std::uint8_t> bytes(next.begin(), next.end());
      if (!ports_.edge_array->requests().try_push(AxiRequest{
              .transaction_id = next_transaction(),
              .operation = MemoryOperation::kWrite,
              .address = config_.edge_array_base +
                         edge_array_bursts_ * kGraSuSegmentBytes,
              .bytes = kGraSuSegmentBytes,
              .stream_read_beats = false,
              .write_data = std::move(bytes),
          })) {
        ++counters_.output_issue_stall_cycles;
        return;
      }
    }
    staged_slot_ = StagedSlot{
        .source = source,
        .raw_destination = raw_destination,
        .dummy = dummy,
        .valid_seen = valid_seen,
        .append = true,
        .write_issued = full,
        .next_burst = next,
    };
  }

  void consume_read_response(const AxiResponse &response) {
    if (!response.success || response.operation != MemoryOperation::kRead) {
      fail("native compactor AXI read failed");
      return;
    }
    if (phase_ == Phase::kWaitTotalRow) {
      const std::uint64_t packed = decode_u64(response.read_data);
      total_slots_ = std::min<std::uint64_t>(static_cast<std::uint32_t>(packed),
                                             pma_slot_count_);
      source_ = 0;
      phase_ = Phase::kNeedRow;
      return;
    }
    if (phase_ == Phase::kWaitRow) {
      const std::uint64_t packed = decode_u64(response.read_data);
      row_begin_ = static_cast<std::uint32_t>(packed >> 32);
      row_end_ = std::min<std::uint64_t>(static_cast<std::uint32_t>(packed),
                                         pma_slot_count_);
      next_segment_ = row_begin_ >> 4;
      end_segment_ = (row_end_ + kGraSuSegmentSlots - 1) >> 4;
      phase_ = Phase::kNeedSegment;
      return;
    }
    if (phase_ == Phase::kWaitSegment) {
      if (response.read_data.size() != kGraSuSegmentBytes) {
        fail("native compactor PMA response has wrong size");
        return;
      }
      current_segment_ = response.read_data;
      pipeline_cycles_remaining_ = config_.lane_pipeline_latency;
      phase_ = Phase::kLanePipeline;
      return;
    }
    fail("native compactor received an out-of-phase AXI response");
  }

  void consume_write_response(const AxiResponse &response) {
    if (!response.success || response.operation != MemoryOperation::kWrite ||
        !response.read_data.empty() || pending_writes_ == 0) {
      fail("native compactor edge-array write response is malformed");
      return;
    }
    --pending_writes_;
  }

  void commit_slot(const StagedSlot &slot) {
    if (slot.valid_seen) {
      ++counters_.valid_edges_seen;
    }
    if (phase_ == Phase::kScan) {
      ++counters_.pma_slots_scanned;
    }
    if (slot.append) {
      burst_ = slot.next_burst;
      ++emitted_slots_;
      ++counters_.emitted_edge_slots;
      if (slot.dummy) {
        ++counters_.dummy_edge_slots;
      }
      if (slot.write_issued) {
        burst_.fill(0);
        burst_lane_ = 0;
        ++edge_array_bursts_;
        ++pending_writes_;
        ++counters_.edge_array_writes;
      } else {
        ++burst_lane_;
      }
    }
    if (phase_ == Phase::kScan) {
      ++lane_;
      if (lane_ == kGraSuSegmentSlots) {
        ++next_segment_;
        phase_ = Phase::kNeedSegment;
      }
    }
  }

  void advance_source() {
    ++source_;
    if (source_ == layout_.vertices) {
      phase_ = Phase::kPad;
    } else {
      phase_ = Phase::kNeedRow;
    }
  }

  const GraSuPmaLayout &layout_;
  std::size_t compact_edge_slots_{};
  GraSuNativeCompactorConfig config_;
  Ports ports_;
  std::uint64_t pma_slot_count_{};
  Phase phase_{Phase::kBarrier};
  Action staged_action_{Action::kNone};
  std::optional<AxiResponse> staged_read_;
  std::optional<AxiResponse> staged_write_response_;
  std::optional<StagedSlot> staged_slot_;
  std::uint64_t next_transaction_{};
  std::size_t source_{};
  std::uint64_t total_slots_{};
  std::uint64_t row_begin_{};
  std::uint64_t row_end_{};
  std::size_t next_segment_{};
  std::size_t end_segment_{};
  std::size_t lane_{};
  std::size_t pipeline_cycles_remaining_{};
  std::vector<std::uint8_t> current_segment_;
  std::array<std::uint8_t, kGraSuSegmentBytes> burst_{};
  std::size_t burst_lane_{};
  std::uint64_t emitted_slots_{};
  std::uint64_t edge_array_bursts_{};
  std::size_t pending_writes_{};
  GraSuNativeCompactorCounters counters_;
  std::string failure_;
};

} // namespace

class GraSuNativeCompactorSystem::Impl {
public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPmaLayout layout, std::size_t compact_edge_slots,
       GraSuNativeCompactorConfig config)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), compact_edge_slots_(compact_edge_slots),
        config_(config),
        start_cycle_(scheduler.clock(clock_id).completed_cycles) {
    validate();
    construct_ports();
    std::array<FixedAxiPort *, 4> pma{};
    for (std::size_t index = 0; index < pma.size(); ++index) {
      pma[index] = pma_ports_[index].get();
    }
    compactor_ = std::make_unique<NativePmaCompactor>(
        "grasu-native-pma-compactor", clock_id_, layout_, compact_edge_slots_,
        config_,
        NativePmaCompactor::Ports{.rows = row_port_.get(),
                                  .pma = pma,
                                  .edge_array = edge_array_port_.get()});
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error("native compactor registered more than once");
    }
    row_port_->register_components(scheduler_);
    for (auto &port : pma_ports_) {
      port->register_components(scheduler_);
    }
    edge_array_port_->register_components(scheduler_);
    scheduler_.add_component(*compactor_);
    registered_ = true;
    active_ = true;
  }

  void unregister_components() {
    if (!registered_ || !active_ || !done()) {
      throw std::logic_error(
          "native compactor can only unregister after completion");
    }
    scheduler_.remove_component(*compactor_);
    edge_array_port_->unregister_components(scheduler_);
    for (auto iterator = pma_ports_.rbegin(); iterator != pma_ports_.rend();
         ++iterator) {
      (*iterator)->unregister_components(scheduler_);
    }
    row_port_->unregister_components(scheduler_);
    end_cycle_ = scheduler_.clock(clock_id_).completed_cycles;
    active_ = false;
  }

  [[nodiscard]] bool done() const noexcept {
    return registered_ && compactor_->done() && all_ports_idle();
  }
  [[nodiscard]] bool failed() const noexcept { return compactor_->failed(); }
  [[nodiscard]] const std::string &failure() const noexcept {
    return compactor_->failure();
  }

  [[nodiscard]] GraSuNativeCompactorCounters counters() const noexcept {
    GraSuNativeCompactorCounters result = compactor_->counters();
    const auto account_axi_port = [&result](const FixedAxiPort &port) {
      result.axi_request_fifo_stalls +=
          port.requests().stats().push_stalls;
      result.axi_backend_submit_stalls +=
          port.master().stats().backend_submit_stalls;
    };
    result.row_read_bytes = result.row_reads * 8;
    result.pma_read_bytes = result.pma_segment_reads * kGraSuSegmentBytes;
    result.edge_array_write_bytes =
        result.edge_array_writes * kGraSuSegmentBytes;
    account_axi_port(*row_port_);
    account_axi_port(*edge_array_port_);
    for (const auto &port : pma_ports_) {
      account_axi_port(*port);
    }
    result.start_cycle = start_cycle_;
    result.end_cycle = active_ ? scheduler_.clock(clock_id_).completed_cycles
                               : end_cycle_;
    return result;
  }

  [[nodiscard]] std::vector<std::uint8_t> edge_array_payload() const {
    return backend_.inspect_payload(config_.edge_array_channel,
                                    config_.edge_array_base,
                                    compact_edge_slots_ * kReGraphEdgeBytes);
  }

  [[nodiscard]] std::vector<GraSuEdge> compacted_live_edges() const {
    const std::vector<std::uint8_t> bytes = edge_array_payload();
    std::vector<GraSuEdge> result;
    for (std::size_t slot = 0; slot < compact_edge_slots_; ++slot) {
      const std::uint32_t source = decode_u32(bytes, slot * 8);
      const std::uint32_t destination = decode_u32(bytes, slot * 8 + 4);
      if ((source & kGraSuPmaEmpty) != 0 ||
          (destination & kGraSuPmaEmpty) != 0) {
        continue;
      }
      result.push_back(GraSuEdge{
          .source = source,
          .destination = destination & kGraSuPmaDestinationMask,
          .weight = static_cast<std::uint16_t>(
              (destination >> kGraSuPmaWeightShift) & kGraSuPmaWeightMask),
      });
    }
    return result;
  }

private:
  void validate() const {
    if (layout_.vertices == 0 || layout_.vertices > 65536 ||
        layout_.destination_base != 0 ||
        layout_.destination_vertices != layout_.vertices ||
        config_.memory_channels < 4 || config_.cache_segments_per_half == 0 ||
        config_.completion_tokens == 0 || config_.lane_pipeline_latency == 0 ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.row_channel >= config_.memory_channels ||
        config_.edge_array_channel >= config_.memory_channels ||
        compact_edge_slots_ < 32 ||
        compact_edge_slots_ % kReGraphEdgesPerBurst != 0) {
      throw std::invalid_argument(
          "invalid native GraSU compactor configuration");
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  void construct_ports() {
    row_port_ = make_port("grasu-native-compactor-row", config_.row_channel, 8);
    for (std::size_t channel = 0; channel < pma_ports_.size(); ++channel) {
      pma_ports_[channel] = make_port(
          "grasu-native-compactor-pma" + std::to_string(channel), channel, 64);
    }
    edge_array_port_ = make_port("grasu-native-compactor-edge-array",
                                 config_.edge_array_channel, 64);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    return row_port_->idle() && edge_array_port_->idle() &&
           std::all_of(pma_ports_.begin(), pma_ports_.end(),
                       [](const auto &port) { return port->idle(); });
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPmaLayout layout_;
  std::size_t compact_edge_slots_{};
  GraSuNativeCompactorConfig config_;
  std::unique_ptr<FixedAxiPort> row_port_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports_;
  std::unique_ptr<FixedAxiPort> edge_array_port_;
  std::unique_ptr<NativePmaCompactor> compactor_;
  std::uint32_t next_initiator_{3200};
  std::uint64_t start_cycle_{};
  std::uint64_t end_cycle_{};
  bool registered_{};
  bool active_{};
};

GraSuNativeCompactorSystem::GraSuNativeCompactorSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::size_t compact_edge_slots,
    GraSuNativeCompactorConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend,
                                   std::move(layout), compact_edge_slots,
                                   config)) {}

GraSuNativeCompactorSystem::~GraSuNativeCompactorSystem() = default;

void GraSuNativeCompactorSystem::register_components() {
  impl_->register_components();
}

void GraSuNativeCompactorSystem::unregister_components() {
  impl_->unregister_components();
}

bool GraSuNativeCompactorSystem::done() const noexcept { return impl_->done(); }

bool GraSuNativeCompactorSystem::failed() const noexcept {
  return impl_->failed();
}

const std::string &GraSuNativeCompactorSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuNativeCompactorCounters
GraSuNativeCompactorSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<GraSuEdge>
GraSuNativeCompactorSystem::compacted_live_edges() const {
  return impl_->compacted_live_edges();
}

std::vector<std::uint8_t>
GraSuNativeCompactorSystem::edge_array_payload() const {
  return impl_->edge_array_payload();
}

} // namespace spine::sim
