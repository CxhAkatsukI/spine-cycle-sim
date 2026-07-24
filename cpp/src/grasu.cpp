#include "spine_sim/grasu.hpp"

#include <algorithm>
#include <array>
#include <deque>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace {

std::vector<std::uint8_t> encode_u64(std::uint64_t value) {
  std::vector<std::uint8_t> bytes(8);
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    bytes[index] = static_cast<std::uint8_t>(value >> (index * 8));
  }
  return bytes;
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != 8) {
    throw std::invalid_argument("GraSU 64-bit payload has invalid size");
  }
  std::uint64_t value = 0;
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    value |= static_cast<std::uint64_t>(bytes[index]) << (index * 8);
  }
  return value;
}

std::vector<std::uint8_t> encode_segment(
    const std::array<std::uint32_t, kGraSuSegmentSlots> &segment) {
  std::vector<std::uint8_t> bytes(kGraSuSegmentBytes);
  for (std::size_t lane = 0; lane < segment.size(); ++lane) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[lane * 4 + byte] =
          static_cast<std::uint8_t>(segment[lane] >> (byte * 8));
    }
  }
  return bytes;
}

std::array<std::uint32_t, kGraSuSegmentSlots>
decode_segment(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != kGraSuSegmentBytes) {
    throw std::invalid_argument("GraSU PMA segment payload has invalid size");
  }
  std::array<std::uint32_t, kGraSuSegmentSlots> segment{};
  for (std::size_t lane = 0; lane < segment.size(); ++lane) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      segment[lane] |=
          static_cast<std::uint32_t>(bytes[lane * 4 + byte]) << (byte * 8);
    }
  }
  return segment;
}

std::uint64_t packed_edge(const GraSuEdge &edge) {
  return (static_cast<std::uint64_t>(edge.source) << 32) |
         edge.destination;
}

void validate_vertex(std::size_t vertices, const GraSuEdge &edge) {
  if (edge.source >= vertices || edge.destination >= kGraSuPmaEmpty) {
    throw std::invalid_argument("GraSU edge endpoint is outside PMA encoding");
  }
}

struct LocatedUpdate {
  std::uint64_t global_index{};
  std::uint32_t segment_head_slot{};
  std::uint32_t destination{};
  bool delete_op{};
};

class GraSuDirectSearch final : public Component {
 public:
  struct Ports {
    FixedAxiPort *updates{};
    FixedAxiPort *rows{};
    FixedAxiPort *binary{};
    Fifo<LocatedUpdate> *output{};
  };

  GraSuDirectSearch(std::string name, ClockId clock_id, std::size_t cu,
                    std::size_t update_count, const GraSuNativeConfig &config,
                    Ports ports)
      : Component(std::move(name), clock_id), cu_(cu),
        update_count_(update_count), config_(config), ports_(ports) {
    if (cu_ >= 4 || ports_.updates == nullptr || ports_.rows == nullptr ||
        ports_.binary == nullptr || ports_.output == nullptr) {
      throw std::invalid_argument("invalid GraSU direct-search ports");
    }
  }

  [[nodiscard]] bool done() const noexcept {
    return local_index_ == update_count_ && phase_ == Phase::kNeedUpdate;
  }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t row_reads() const noexcept { return row_reads_; }
  [[nodiscard]] std::uint64_t binary_probes() const noexcept {
    return binary_probes_;
  }

  void evaluate(const CycleContext &) override {
    staged_response_.reset();
    staged_request_ = false;
    staged_emit_ = false;
    if (failed()) {
      return;
    }
    FixedAxiPort *response_port = nullptr;
    switch (phase_) {
    case Phase::kWaitUpdate:
      response_port = ports_.updates;
      break;
    case Phase::kWaitRow:
      response_port = ports_.rows;
      break;
    case Phase::kWaitBinary:
      response_port = ports_.binary;
      break;
    default:
      break;
    }
    if (response_port != nullptr && response_port->responses().front() != nullptr) {
      AxiResponse response;
      if (response_port->responses().try_pop(response)) {
        staged_response_ = std::move(response);
      }
      return;
    }

    switch (phase_) {
    case Phase::kNeedUpdate:
      if (local_index_ < update_count_) {
        staged_request_ = ports_.updates->requests().try_push(AxiRequest{
            .transaction_id = transaction_id(0),
            .operation = MemoryOperation::kRead,
            .address = config_.update_base + local_index_ * 8,
            .bytes = 8,
            .stream_read_beats = false,
            .write_data = {},
        });
      }
      break;
    case Phase::kNeedRow:
      staged_request_ = ports_.rows->requests().try_push(AxiRequest{
          .transaction_id = transaction_id(1),
          .operation = MemoryOperation::kRead,
          .address = config_.row_offset_base +
                     static_cast<std::uint64_t>(current_.source) * 8,
          .bytes = 8,
          .stream_read_beats = false,
          .write_data = {},
      });
      break;
    case Phase::kNeedBinary:
      staged_request_ = ports_.binary->requests().try_push(AxiRequest{
          .transaction_id = transaction_id(2),
          .operation = MemoryOperation::kRead,
          .address = config_.binary_base +
                     static_cast<std::uint64_t>(mid_segment_) * 8,
          .bytes = 8,
          .stream_read_beats = false,
          .write_data = {},
      });
      break;
    case Phase::kEmit:
      staged_emit_ = ports_.output->try_push(LocatedUpdate{
          .global_index = cu_ + local_index_ * 4,
          .segment_head_slot = static_cast<std::uint32_t>(
              begin_segment_ * kGraSuSegmentSlots),
          .destination = current_.destination,
          .delete_op = current_.delete_op,
      });
      break;
    default:
      break;
    }
  }

  void commit(const CycleContext &) override {
    if (failed()) {
      return;
    }
    if (staged_response_.has_value()) {
      consume_response(*staged_response_);
      staged_response_.reset();
      return;
    }
    if (staged_emit_) {
      ++local_index_;
      phase_ = Phase::kNeedUpdate;
      return;
    }
    if (!staged_request_) {
      return;
    }
    switch (phase_) {
    case Phase::kNeedUpdate:
      phase_ = Phase::kWaitUpdate;
      break;
    case Phase::kNeedRow:
      ++row_reads_;
      phase_ = Phase::kWaitRow;
      break;
    case Phase::kNeedBinary:
      ++binary_probes_;
      phase_ = Phase::kWaitBinary;
      break;
    default:
      fail("GraSU direct-search issued from invalid phase");
      break;
    }
  }

 private:
  enum class Phase {
    kNeedUpdate,
    kWaitUpdate,
    kNeedRow,
    kWaitRow,
    kNeedBinary,
    kWaitBinary,
    kEmit,
  };

  [[nodiscard]] std::uint64_t transaction_id(std::uint64_t stage) const {
    return (static_cast<std::uint64_t>(cu_) << 56) |
           (local_index_ << 3) | stage;
  }

  void fail(std::string message) {
    if (failure_.empty()) {
      failure_ = std::move(message);
    }
  }

  void consume_response(const AxiResponse &response) {
    if (!response.success || response.read_data.size() != 8) {
      fail("GraSU direct-search received malformed AXI response");
      return;
    }
    const std::uint64_t value = decode_u64(response.read_data);
    switch (phase_) {
    case Phase::kWaitUpdate: {
      current_.delete_op = (value >> 63) != 0;
      const std::uint64_t edge = value & ~(std::uint64_t{1} << 63);
      current_.source = static_cast<std::uint32_t>(edge >> 32);
      current_.destination = static_cast<std::uint32_t>(edge);
      phase_ = Phase::kNeedRow;
      break;
    }
    case Phase::kWaitRow: {
      const std::uint32_t begin_slots = static_cast<std::uint32_t>(value >> 32);
      const std::uint32_t end_slots = static_cast<std::uint32_t>(value);
      begin_segment_ = begin_slots >> 4;
      end_segment_ = end_slots >> 4;
      if (begin_segment_ >= end_segment_) {
        fail("GraSU update source has no reserved PMA segment");
        return;
      }
      mid_segment_ = (begin_segment_ + end_segment_) >> 1;
      phase_ = begin_segment_ == mid_segment_ ? Phase::kEmit
                                              : Phase::kNeedBinary;
      break;
    }
    case Phase::kWaitBinary: {
      const std::uint64_t edge = packed_edge(current_);
      if (value <= edge) {
        begin_segment_ = mid_segment_;
      } else {
        end_segment_ = mid_segment_;
      }
      mid_segment_ = (begin_segment_ + end_segment_) >> 1;
      phase_ = begin_segment_ == mid_segment_ ? Phase::kEmit
                                              : Phase::kNeedBinary;
      break;
    }
    default:
      fail("GraSU direct-search consumed response in invalid phase");
      break;
    }
  }

  std::size_t cu_{};
  std::size_t update_count_{};
  GraSuNativeConfig config_;
  Ports ports_;
  std::uint64_t local_index_{};
  Phase phase_{Phase::kNeedUpdate};
  GraSuEdge current_{};
  std::uint32_t begin_segment_{};
  std::uint32_t end_segment_{};
  std::uint32_t mid_segment_{};
  std::optional<AxiResponse> staged_response_;
  bool staged_request_{};
  bool staged_emit_{};
  std::string failure_;
  std::uint64_t row_reads_{};
  std::uint64_t binary_probes_{};
};

class GraSuDispatch final : public Component {
 public:
  GraSuDispatch(std::string name, ClockId clock_id, std::size_t updates,
                std::size_t cache_segments_per_half,
                std::array<Fifo<LocatedUpdate> *, 4> inputs,
                std::array<Fifo<LocatedUpdate> *, 4> outputs)
      : Component(std::move(name), clock_id), updates_(updates),
        cache_segments_per_half_(cache_segments_per_half), inputs_(inputs),
        outputs_(outputs) {}

  [[nodiscard]] bool done() const noexcept { return next_ == updates_; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t cache_updates() const noexcept {
    return cache_updates_;
  }
  [[nodiscard]] std::uint64_t ddr_updates() const noexcept {
    return ddr_updates_;
  }

  void evaluate(const CycleContext &) override {
    staged_ = false;
    if (done() || failed()) {
      return;
    }
    Fifo<LocatedUpdate> &input = *inputs_[next_ & 3U];
    const LocatedUpdate *item = input.front();
    if (item == nullptr) {
      return;
    }
    if (item->global_index != next_) {
      failure_ = "GraSU dispatch input order mismatch";
      return;
    }
    const std::size_t local_index = item->segment_head_slot >> 5;
    staged_cache_ = local_index < cache_segments_per_half_;
    const std::size_t parity = (item->segment_head_slot >> 4) & 1U;
    staged_target_ = (staged_cache_ ? 0U : 2U) + parity;
    if (outputs_[staged_target_]->try_push(*item)) {
      LocatedUpdate consumed;
      if (!input.try_pop(consumed)) {
        throw std::logic_error("GraSU dispatch lost visible input");
      }
      staged_ = true;
    }
  }

  void commit(const CycleContext &) override {
    if (!staged_) {
      return;
    }
    ++next_;
    if (staged_cache_) {
      ++cache_updates_;
    } else {
      ++ddr_updates_;
    }
  }

 private:
  std::size_t updates_{};
  std::size_t cache_segments_per_half_{};
  std::array<Fifo<LocatedUpdate> *, 4> inputs_{};
  std::array<Fifo<LocatedUpdate> *, 4> outputs_{};
  std::size_t next_{};
  std::size_t staged_target_{};
  bool staged_cache_{};
  bool staged_{};
  std::string failure_;
  std::uint64_t cache_updates_{};
  std::uint64_t ddr_updates_{};
};

class GraSuPmaProcessor final : public Component {
 public:
  struct Ports {
    Fifo<LocatedUpdate> *input{};
    std::array<FixedAxiPort *, 2> reads{};
    std::array<FixedAxiPort *, 2> writes{};
  };

  GraSuPmaProcessor(std::string name, ClockId clock_id, bool cache_direct,
                    std::size_t lane_fifo_depth, std::uint64_t pma_base,
                    Ports ports)
      : Component(std::move(name), clock_id), cache_direct_(cache_direct),
        lane_fifo_depth_(lane_fifo_depth), pma_base_(pma_base), ports_(ports),
        lanes_(cache_direct ? 1 : 32) {
    if (lane_fifo_depth_ == 0 || ports_.input == nullptr ||
        ports_.reads[0] == nullptr || ports_.writes[0] == nullptr ||
        (!cache_direct_ &&
         (ports_.reads[1] == nullptr || ports_.writes[1] == nullptr))) {
      throw std::invalid_argument("invalid GraSU PMA processor ports");
    }
  }

  [[nodiscard]] bool idle() const noexcept {
    return ports_.input->empty() &&
           std::all_of(lanes_.begin(), lanes_.end(), [](const Lane &lane) {
             return lane.phase == LanePhase::kIdle && lane.queue.empty();
           });
  }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t completed() const noexcept { return completed_; }
  [[nodiscard]] std::uint64_t lane_queue_stalls() const noexcept {
    return lane_queue_stalls_;
  }

  void evaluate(const CycleContext &) override {
    staged_route_.reset();
    staged_starts_.clear();
    staged_responses_.clear();
    staged_issues_.clear();
    if (failed()) {
      return;
    }
    stage_input_route();
    stage_lane_starts();
    stage_responses();
    stage_requests();
  }

  void commit(const CycleContext &) override {
    if (failed()) {
      return;
    }
    if (staged_route_.has_value()) {
      lanes_[staged_route_->first].queue.push_back(staged_route_->second);
      staged_route_.reset();
    }
    for (std::size_t lane_index : staged_starts_) {
      Lane &lane = lanes_[lane_index];
      lane.item = lane.queue.front();
      lane.queue.pop_front();
      lane.phase = LanePhase::kNeedRead;
    }
    for (const StagedResponse &staged : staged_responses_) {
      consume_response(staged);
      if (failed()) {
        return;
      }
    }
    for (const StagedIssue &issue : staged_issues_) {
      Lane &lane = lanes_[issue.lane];
      lane.phase = issue.write ? LanePhase::kWaitWrite
                               : LanePhase::kWaitRead;
      auto &mapping = issue.write ? write_transactions_ : read_transactions_;
      mapping.emplace(issue.transaction_id, issue.lane);
    }
  }

 private:
  enum class LanePhase { kIdle, kNeedRead, kWaitRead, kNeedWrite, kWaitWrite };

  struct Lane {
    LanePhase phase{LanePhase::kIdle};
    std::deque<LocatedUpdate> queue;
    LocatedUpdate item{};
    std::array<std::uint32_t, kGraSuSegmentSlots> result{};
  };

  struct StagedResponse {
    bool write{};
    std::size_t port{};
    AxiResponse response;
  };

  struct StagedIssue {
    bool write{};
    std::size_t lane{};
    std::uint64_t transaction_id{};
  };

  [[nodiscard]] std::size_t lane_for(const LocatedUpdate &item) const {
    if (cache_direct_) {
      return 0;
    }
    const std::size_t half = (item.segment_head_slot >> 5) & 1U;
    const std::size_t lane = (item.segment_head_slot >> 6) & 0xFU;
    return half * 16 + lane;
  }

  [[nodiscard]] std::size_t port_for_lane(std::size_t lane) const {
    return cache_direct_ ? 0 : lane / 16;
  }

  [[nodiscard]] std::uint64_t address_for(const LocatedUpdate &item) const {
    const std::uint64_t local_segment =
        static_cast<std::uint64_t>(item.segment_head_slot) >> 5;
    return pma_base_ + local_segment * kGraSuSegmentBytes;
  }

  void stage_input_route() {
    const LocatedUpdate *item = ports_.input->front();
    if (item == nullptr) {
      return;
    }
    const std::size_t lane = lane_for(*item);
    if (lanes_[lane].queue.size() >= lane_fifo_depth_) {
      ++lane_queue_stalls_;
      return;
    }
    LocatedUpdate consumed;
    if (ports_.input->try_pop(consumed)) {
      staged_route_ = std::pair(lane, consumed);
    }
  }

  void stage_lane_starts() {
    for (std::size_t lane = 0; lane < lanes_.size(); ++lane) {
      if (lanes_[lane].phase == LanePhase::kIdle &&
          !lanes_[lane].queue.empty()) {
        staged_starts_.push_back(lane);
      }
    }
  }

  void stage_responses() {
    const std::size_t ports = cache_direct_ ? 1 : 2;
    for (std::size_t port = 0; port < ports; ++port) {
      if (ports_.reads[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (ports_.reads[port]->responses().try_pop(response)) {
          const bool write = response.operation == MemoryOperation::kWrite;
          staged_responses_.push_back(
              StagedResponse{.write = write,
                             .port = port,
                             .response = std::move(response)});
        }
      }
      if (ports_.writes[port] != ports_.reads[port] &&
          ports_.writes[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (ports_.writes[port]->responses().try_pop(response)) {
          const bool write = response.operation == MemoryOperation::kWrite;
          staged_responses_.push_back(
              StagedResponse{.write = write,
                             .port = port,
                             .response = std::move(response)});
        }
      }
    }
  }

  void stage_requests() {
    const std::size_t port_count = cache_direct_ ? 1 : 2;
    for (std::size_t port = 0; port < port_count; ++port) {
      bool shared_port_used = false;
      for (std::size_t offset = 0; offset < lanes_.size(); ++offset) {
        const std::size_t lane_index = (write_rr_[port] + offset) % lanes_.size();
        Lane &lane = lanes_[lane_index];
        if (port_for_lane(lane_index) != port ||
            lane.phase != LanePhase::kNeedWrite) {
          continue;
        }
        const std::uint64_t transaction = next_transaction_++;
        if (ports_.writes[port]->requests().try_push(AxiRequest{
                .transaction_id = transaction,
                .operation = MemoryOperation::kWrite,
                .address = address_for(lane.item),
                .bytes = kGraSuSegmentBytes,
                .stream_read_beats = false,
                .write_data = encode_segment(lane.result),
            })) {
          staged_issues_.push_back(StagedIssue{
              .write = true, .lane = lane_index, .transaction_id = transaction});
          write_rr_[port] = (lane_index + 1) % lanes_.size();
          shared_port_used = ports_.writes[port] == ports_.reads[port];
        }
        break;
      }
      if (shared_port_used) {
        continue;
      }
      for (std::size_t offset = 0; offset < lanes_.size(); ++offset) {
        const std::size_t lane_index = (read_rr_[port] + offset) % lanes_.size();
        Lane &lane = lanes_[lane_index];
        if (port_for_lane(lane_index) != port ||
            lane.phase != LanePhase::kNeedRead) {
          continue;
        }
        const std::uint64_t transaction = next_transaction_++;
        if (ports_.reads[port]->requests().try_push(AxiRequest{
                .transaction_id = transaction,
                .operation = MemoryOperation::kRead,
                .address = address_for(lane.item),
                .bytes = kGraSuSegmentBytes,
                .stream_read_beats = false,
                .write_data = {},
            })) {
          staged_issues_.push_back(StagedIssue{
              .write = false, .lane = lane_index, .transaction_id = transaction});
          read_rr_[port] = (lane_index + 1) % lanes_.size();
        }
        break;
      }
    }
  }

  void consume_response(const StagedResponse &staged) {
    auto &mapping = staged.write ? write_transactions_ : read_transactions_;
    const auto found = mapping.find(staged.response.transaction_id);
    if (found == mapping.end()) {
      failure_ = "GraSU PMA response has unknown transaction ID";
      return;
    }
    Lane &lane = lanes_[found->second];
    mapping.erase(found);
    if (!staged.response.success) {
      failure_ = "GraSU PMA AXI transaction failed";
      return;
    }
    if (staged.write) {
      if (lane.phase != LanePhase::kWaitWrite) {
        failure_ = "GraSU PMA write response violated lane state";
        return;
      }
      lane.phase = LanePhase::kIdle;
      ++completed_;
      return;
    }
    if (lane.phase != LanePhase::kWaitRead) {
      failure_ = "GraSU PMA read response violated lane state";
      return;
    }
    try {
      lane.result = apply_update(decode_segment(staged.response.read_data),
                                 lane.item);
    } catch (const std::exception &error) {
      failure_ = error.what();
      return;
    }
    lane.phase = LanePhase::kNeedWrite;
  }

  static std::array<std::uint32_t, kGraSuSegmentSlots>
  apply_update(std::array<std::uint32_t, kGraSuSegmentSlots> segment,
               const LocatedUpdate &item) {
    const auto position = std::lower_bound(segment.begin(), segment.end(),
                                           item.destination);
    if (item.delete_op) {
      if (position == segment.end() || *position != item.destination) {
        throw std::runtime_error("GraSU delete target is not live in PMA segment");
      }
      std::move(position + 1, segment.end(), position);
      segment.back() = kGraSuPmaEmpty;
      return segment;
    }
    if (position != segment.end() && *position == item.destination) {
      throw std::runtime_error("GraSU insertion target is already live");
    }
    if (segment.back() != kGraSuPmaEmpty) {
      throw std::runtime_error("GraSU PMA segment has no reserved insertion slot");
    }
    std::move_backward(position, segment.end() - 1, segment.end());
    *position = item.destination;
    return segment;
  }

  bool cache_direct_{};
  std::size_t lane_fifo_depth_{};
  std::uint64_t pma_base_{};
  Ports ports_;
  std::vector<Lane> lanes_;
  std::optional<std::pair<std::size_t, LocatedUpdate>> staged_route_;
  std::vector<std::size_t> staged_starts_;
  std::vector<StagedResponse> staged_responses_;
  std::vector<StagedIssue> staged_issues_;
  std::unordered_map<std::uint64_t, std::size_t> read_transactions_;
  std::unordered_map<std::uint64_t, std::size_t> write_transactions_;
  std::array<std::size_t, 2> read_rr_{};
  std::array<std::size_t, 2> write_rr_{};
  std::uint64_t next_transaction_{};
  std::uint64_t completed_{};
  std::uint64_t lane_queue_stalls_{};
  std::string failure_;
};

FixedAxiPortConfig grasu_port_config(const GraSuNativeConfig &config,
                                     std::size_t channel,
                                     std::uint32_t initiator,
                                     std::uint32_t width) {
  return FixedAxiPortConfig{
      .memory_channels = config.memory_channels,
      .channel = channel,
      .initiator_id = initiator,
      .data_width_bytes = width,
      .max_burst_beats = 16,
      .request_fifo_depth = config.max_pending_requests,
      .response_fifo_depth = config.max_pending_requests,
      .read_beat_fifo_depth = 1,
      .read_reorder_capacity = config.max_pending_requests,
      .stream_read_beats = false,
      .max_pending_requests = config.max_pending_requests,
      .max_outstanding_bursts = config.max_outstanding_bursts,
      .address_accepts_per_cycle = 1,
      .beat_issues_per_cycle = 1,
      .response_beats_per_cycle = config.response_beats_per_cycle,
  };
}

}  // namespace

GraSuPmaLayout GraSuPmaLayout::build(
    std::size_t vertices, const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &reserved_updates) {
  if (vertices == 0 || vertices >= kGraSuPmaEmpty) {
    throw std::invalid_argument("GraSU vertex count is outside PMA encoding");
  }
  std::vector<std::set<std::uint32_t>> initial(vertices);
  std::vector<std::set<std::uint32_t>> reserved(vertices);
  for (const GraSuEdge &edge : initial_edges) {
    validate_vertex(vertices, edge);
    if (edge.delete_op) {
      throw std::invalid_argument("initial GraSU edge cannot be a deletion");
    }
    initial[edge.source].insert(edge.destination);
    reserved[edge.source].insert(edge.destination);
  }
  for (const GraSuEdge &edge : reserved_updates) {
    validate_vertex(vertices, edge);
    if (!edge.delete_op) {
      reserved[edge.source].insert(edge.destination);
    }
  }

  GraSuPmaLayout layout;
  layout.vertices = vertices;
  layout.row_slot_bounds.resize(vertices);
  std::uint32_t next_slot = 0;
  for (std::size_t source = 0; source < vertices; ++source) {
    const std::uint32_t begin = next_slot;
    const std::vector<std::uint32_t> destinations(reserved[source].begin(),
                                                  reserved[source].end());
    for (std::size_t offset = 0; offset < destinations.size();
         offset += kGraSuSegmentSlots) {
      std::array<std::uint32_t, kGraSuSegmentSlots> reserved_segment;
      std::array<std::uint32_t, kGraSuSegmentSlots> live_segment;
      reserved_segment.fill(kGraSuPmaEmpty);
      live_segment.fill(kGraSuPmaEmpty);
      const std::size_t count = std::min(kGraSuSegmentSlots,
                                         destinations.size() - offset);
      std::size_t live_count = 0;
      for (std::size_t lane = 0; lane < count; ++lane) {
        const std::uint32_t destination = destinations[offset + lane];
        reserved_segment[lane] = destination;
        if (initial[source].contains(destination)) {
          live_segment[live_count++] = destination;
        }
      }
      layout.binary_heads.push_back(
          (static_cast<std::uint64_t>(source) << 32) |
          reserved_segment.front());
      layout.reserved_segments.push_back(reserved_segment);
      layout.segments.push_back(live_segment);
      next_slot += kGraSuSegmentSlots;
    }
    layout.row_slot_bounds[source] = {begin, next_slot};
  }
  return layout;
}

std::vector<GraSuEdge> GraSuPmaLayout::live_edges() const {
  std::vector<GraSuEdge> edges;
  for (std::size_t source = 0; source < vertices; ++source) {
    const auto [begin, end] = row_slot_bounds.at(source);
    for (std::size_t segment = begin / kGraSuSegmentSlots;
         segment < end / kGraSuSegmentSlots; ++segment) {
      for (std::uint32_t destination : segments.at(segment)) {
        if ((destination & kGraSuPmaEmpty) == 0) {
          edges.push_back(GraSuEdge{
              .source = static_cast<std::uint32_t>(source),
              .destination = destination,
          });
        }
      }
    }
  }
  return edges;
}

std::size_t GraSuPmaLayout::segment_for(const GraSuEdge &edge) const {
  validate_vertex(vertices, edge);
  const auto [begin_slot, end_slot] = row_slot_bounds.at(edge.source);
  std::size_t begin = begin_slot / kGraSuSegmentSlots;
  std::size_t end = end_slot / kGraSuSegmentSlots;
  if (begin == end) {
    throw std::invalid_argument("GraSU edge source has no reserved PMA segment");
  }
  std::size_t mid = (begin + end) >> 1;
  const std::uint64_t edge_word = packed_edge(edge);
  while (begin != mid) {
    if (binary_heads.at(mid) <= edge_word) {
      begin = mid;
    } else {
      end = mid;
    }
    mid = (begin + end) >> 1;
  }
  const auto &reserved = reserved_segments.at(begin);
  if (std::find(reserved.begin(), reserved.end(), edge.destination) ==
      reserved.end()) {
    throw std::invalid_argument("GraSU insertion was not reserved by host PMA layout");
  }
  return begin;
}

class GraSuPmaUpdateSystem::Impl {
 public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPmaLayout layout, std::vector<GraSuEdge> updates,
       GraSuNativeConfig config)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), updates_(std::move(updates)),
        config_(config),
        start_cycle_(scheduler.clock(clock_id).completed_cycles) {
    validate_config();
    validate_updates();
    construct_links_and_ports();
    initialize_payloads();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error("GraSU update system registered more than once");
    }
    for (auto &fifo : search_outputs_) {
      scheduler_.add_component(*fifo);
    }
    for (auto &fifo : process_inputs_) {
      scheduler_.add_component(*fifo);
    }
    for (auto &ports : search_ports_) {
      ports.updates->register_components(scheduler_);
      ports.rows->register_components(scheduler_);
      ports.binary->register_components(scheduler_);
    }
    for (auto &processor : processor_ports_) {
      for (FixedAxiPort *port : processor.owned_registration_order) {
        port->register_components(scheduler_);
      }
    }
    for (auto &search : searches_) {
      scheduler_.add_component(*search);
    }
    scheduler_.add_component(*dispatch_);
    for (auto &processor : processors_) {
      scheduler_.add_component(*processor);
    }
    registered_ = true;
  }

  [[nodiscard]] bool failed() const noexcept {
    if (dispatch_ != nullptr && dispatch_->failed()) {
      return true;
    }
    return std::any_of(searches_.begin(), searches_.end(),
                       [](const auto &item) { return item->failed(); }) ||
           std::any_of(processors_.begin(), processors_.end(),
                       [](const auto &item) { return item->failed(); });
  }

  [[nodiscard]] const std::string &failure() const noexcept {
    if (dispatch_ != nullptr && dispatch_->failed()) {
      return dispatch_->failure();
    }
    for (const auto &search : searches_) {
      if (search->failed()) {
        return search->failure();
      }
    }
    for (const auto &processor : processors_) {
      if (processor->failed()) {
        return processor->failure();
      }
    }
    static const std::string empty;
    return empty;
  }

  [[nodiscard]] bool done() const noexcept {
    if (!registered_ || failed() || dispatch_ == nullptr || !dispatch_->done()) {
      return false;
    }
    if (!std::all_of(searches_.begin(), searches_.end(),
                     [](const auto &item) { return item->done(); }) ||
        !std::all_of(processors_.begin(), processors_.end(),
                     [](const auto &item) { return item->idle(); })) {
      return false;
    }
    return all_ports_idle();
  }

  [[nodiscard]] GraSuUpdateCounters counters() const noexcept {
    GraSuUpdateCounters result;
    result.updates = updates_.size();
    result.inserts = static_cast<std::uint64_t>(std::count_if(
        updates_.begin(), updates_.end(),
        [](const GraSuEdge &edge) { return !edge.delete_op; }));
    result.deletes = result.updates - result.inserts;
    for (const auto &search : searches_) {
      result.row_reads += search->row_reads();
      result.binary_probes += search->binary_probes();
    }
    if (dispatch_ != nullptr) {
      result.cache_updates = dispatch_->cache_updates();
      result.ddr_updates = dispatch_->ddr_updates();
    }
    for (const auto &processor : processors_) {
      result.pma_reads += processor->completed();
      result.pma_writes += processor->completed();
      result.lane_queue_stalls += processor->lane_queue_stalls();
    }
    result.update_read_bytes = result.updates * 8;
    result.row_read_bytes = result.row_reads * 8;
    result.binary_read_bytes = result.binary_probes * 8;
    result.pma_read_bytes = result.pma_reads * kGraSuSegmentBytes;
    result.pma_write_bytes = result.pma_writes * kGraSuSegmentBytes;
    for (const auto &ports : search_ports_) {
      result.axi_backend_submit_stalls +=
          ports.updates->master().stats().backend_submit_stalls +
          ports.rows->master().stats().backend_submit_stalls +
          ports.binary->master().stats().backend_submit_stalls;
    }
    for (const auto &ports : processor_ports_) {
      for (const FixedAxiPort *port : ports.owned_registration_order) {
        result.axi_backend_submit_stalls +=
            port->master().stats().backend_submit_stalls;
      }
    }
    for (const auto &fifo : search_outputs_) {
      result.axis_push_stalls += fifo->stats().push_stalls;
    }
    for (const auto &fifo : process_inputs_) {
      result.axis_push_stalls += fifo->stats().push_stalls;
    }
    result.start_cycle = start_cycle_;
    result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    return result;
  }

  [[nodiscard]] std::array<std::uint32_t, kGraSuSegmentSlots>
  inspect_segment(std::size_t global_segment) const {
    if (global_segment >= layout_.segments.size()) {
      throw std::out_of_range("GraSU PMA segment index out of range");
    }
    const std::size_t local = global_segment >> 1;
    const bool cache = local < config_.cache_segments_per_half;
    const std::size_t parity = global_segment & 1U;
    const std::size_t channel = cache ? parity * 2 : parity * 2 + 1;
    return decode_segment(backend_.inspect_payload(
        channel, config_.pma_base + local * kGraSuSegmentBytes,
        kGraSuSegmentBytes));
  }

  [[nodiscard]] std::vector<GraSuEdge> live_edges() const {
    std::vector<GraSuEdge> edges;
    for (std::size_t source = 0; source < layout_.vertices; ++source) {
      const auto [begin, end] = layout_.row_slot_bounds.at(source);
      for (std::size_t segment = begin / kGraSuSegmentSlots;
           segment < end / kGraSuSegmentSlots; ++segment) {
        for (std::uint32_t destination : inspect_segment(segment)) {
          if ((destination & kGraSuPmaEmpty) == 0) {
            edges.push_back(GraSuEdge{
                .source = static_cast<std::uint32_t>(source),
                .destination = destination,
            });
          }
        }
      }
    }
    std::sort(edges.begin(), edges.end(), [](const auto &left, const auto &right) {
      return std::pair(left.source, left.destination) <
             std::pair(right.source, right.destination);
    });
    return edges;
  }

  [[nodiscard]] const GraSuPmaLayout &initial_layout() const noexcept {
    return layout_;
  }

 private:
  struct SearchPortSet {
    std::unique_ptr<FixedAxiPort> updates;
    std::unique_ptr<FixedAxiPort> rows;
    std::unique_ptr<FixedAxiPort> binary;
  };

  struct ProcessorPortSet {
    std::array<std::unique_ptr<FixedAxiPort>, 2> reads;
    std::array<std::unique_ptr<FixedAxiPort>, 2> writes;
    std::vector<FixedAxiPort *> owned_registration_order;
  };

  void validate_config() const {
    if (config_.memory_channels < 4 || config_.cache_segments_per_half == 0 ||
        config_.axis_fifo_depth == 0 || config_.lane_fifo_depth == 0 ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0) {
      throw std::invalid_argument("invalid GraSU native configuration");
    }
  }

  void validate_updates() const {
    std::set<std::pair<std::uint32_t, std::uint32_t>> live;
    for (const GraSuEdge &edge : layout_.live_edges()) {
      live.emplace(edge.source, edge.destination);
    }
    for (const GraSuEdge &edge : updates_) {
      validate_vertex(layout_.vertices, edge);
      (void)layout_.segment_for(edge);
      const auto key = std::pair(edge.source, edge.destination);
      if (edge.delete_op) {
        if (live.erase(key) != 1) {
          throw std::invalid_argument("GraSU delete target is not live");
        }
      } else if (!live.insert(key).second) {
        throw std::invalid_argument("GraSU insertion target is already live");
      }
    }
  }

  std::unique_ptr<FixedAxiPort> make_port(const std::string &name,
                                         std::size_t channel,
                                         std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        grasu_port_config(config_, channel, next_initiator_++, width), backend_);
  }

  void construct_links_and_ports() {
    for (std::size_t index = 0; index < 4; ++index) {
      search_outputs_[index] = std::make_unique<Fifo<LocatedUpdate>>(
          "grasu-search-axis" + std::to_string(index), clock_id_,
          config_.axis_fifo_depth);
      process_inputs_[index] = std::make_unique<Fifo<LocatedUpdate>>(
          "grasu-process-axis" + std::to_string(index), clock_id_,
          config_.axis_fifo_depth);
      search_ports_[index].updates =
          make_port("grasu-update" + std::to_string(index), index, 8);
      search_ports_[index].rows =
          make_port("grasu-row" + std::to_string(index), index, 8);
      search_ports_[index].binary =
          make_port("grasu-binary" + std::to_string(index), index, 8);
    }

    for (std::size_t index = 0; index < 2; ++index) {
      const std::size_t channel = index * 2;
      processor_ports_[index].reads[0] =
          make_port("grasu-cache" + std::to_string(index), channel, 64);
      processor_ports_[index].writes[0].reset();
      processor_ports_[index].owned_registration_order = {
          processor_ports_[index].reads[0].get()};
    }
    for (std::size_t index = 0; index < 2; ++index) {
      const std::size_t processor_index = index + 2;
      const std::size_t channel = index * 2 + 1;
      for (std::size_t half = 0; half < 2; ++half) {
        processor_ports_[processor_index].reads[half] = make_port(
            "grasu-ddr" + std::to_string(index) + "-read" +
                std::to_string(half),
            channel, 64);
        processor_ports_[processor_index].writes[half] = make_port(
            "grasu-ddr" + std::to_string(index) + "-write" +
                std::to_string(half),
            channel, 64);
        processor_ports_[processor_index].owned_registration_order.push_back(
            processor_ports_[processor_index].reads[half].get());
        processor_ports_[processor_index].owned_registration_order.push_back(
            processor_ports_[processor_index].writes[half].get());
      }
    }
  }

  void initialize_payloads() {
    std::array<std::vector<GraSuEdge>, 4> striped;
    for (std::size_t index = 0; index < updates_.size(); ++index) {
      striped[index & 3U].push_back(updates_[index]);
    }
    for (std::size_t channel = 0; channel < 4; ++channel) {
      std::vector<std::uint8_t> update_bytes;
      for (const GraSuEdge &edge : striped[channel]) {
        std::uint64_t value = packed_edge(edge);
        if (edge.delete_op) {
          value |= std::uint64_t{1} << 63;
        }
        const auto encoded = encode_u64(value);
        update_bytes.insert(update_bytes.end(), encoded.begin(), encoded.end());
      }
      backend_.initialize_payload(channel, config_.update_base, update_bytes);

      std::vector<std::uint8_t> row_bytes;
      for (const auto &[begin, end] : layout_.row_slot_bounds) {
        const auto encoded = encode_u64(
            (static_cast<std::uint64_t>(begin) << 32) | end);
        row_bytes.insert(row_bytes.end(), encoded.begin(), encoded.end());
      }
      backend_.initialize_payload(channel, config_.row_offset_base, row_bytes);

      std::vector<std::uint8_t> binary_bytes;
      for (std::uint64_t head : layout_.binary_heads) {
        const auto encoded = encode_u64(head);
        binary_bytes.insert(binary_bytes.end(), encoded.begin(), encoded.end());
      }
      backend_.initialize_payload(channel, config_.binary_base, binary_bytes);
    }

    for (std::size_t segment = 0; segment < layout_.segments.size(); ++segment) {
      const std::size_t parity = segment & 1U;
      const std::size_t local = segment >> 1;
      const auto bytes = encode_segment(layout_.segments[segment]);
      backend_.initialize_payload(parity * 2, config_.pma_base + local * 64,
                                  bytes);
      backend_.initialize_payload(parity * 2 + 1,
                                  config_.pma_base + local * 64, bytes);
    }
  }

  void construct_components() {
    std::array<std::size_t, 4> counts{};
    for (std::size_t index = 0; index < updates_.size(); ++index) {
      ++counts[index & 3U];
    }
    std::array<Fifo<LocatedUpdate> *, 4> search_outputs{};
    std::array<Fifo<LocatedUpdate> *, 4> process_inputs{};
    for (std::size_t index = 0; index < 4; ++index) {
      search_outputs[index] = search_outputs_[index].get();
      process_inputs[index] = process_inputs_[index].get();
      searches_[index] = std::make_unique<GraSuDirectSearch>(
          "grasu-bin-search" + std::to_string(index), clock_id_, index,
          counts[index], config_,
          GraSuDirectSearch::Ports{
              .updates = search_ports_[index].updates.get(),
              .rows = search_ports_[index].rows.get(),
              .binary = search_ports_[index].binary.get(),
              .output = search_outputs_[index].get(),
          });
    }
    dispatch_ = std::make_unique<GraSuDispatch>(
        "grasu-dispatch", clock_id_, updates_.size(),
        config_.cache_segments_per_half, search_outputs, process_inputs);

    for (std::size_t index = 0; index < 4; ++index) {
      const bool cache = index < 2;
      auto &ports = processor_ports_[index];
      processors_[index] = std::make_unique<GraSuPmaProcessor>(
          "grasu-processor" + std::to_string(index), clock_id_, cache,
          config_.lane_fifo_depth, config_.pma_base,
          GraSuPmaProcessor::Ports{
              .input = process_inputs_[index].get(),
              .reads = {ports.reads[0].get(), ports.reads[1].get()},
              .writes = {cache ? ports.reads[0].get() : ports.writes[0].get(),
                         cache ? nullptr : ports.writes[1].get()},
          });
    }
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    for (const auto &ports : search_ports_) {
      if (!ports.updates->idle() || !ports.rows->idle() ||
          !ports.binary->idle()) {
        return false;
      }
    }
    for (const auto &ports : processor_ports_) {
      for (FixedAxiPort *port : ports.owned_registration_order) {
        if (!port->idle()) {
          return false;
        }
      }
    }
    return true;
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPmaLayout layout_;
  std::vector<GraSuEdge> updates_;
  GraSuNativeConfig config_;
  std::array<std::unique_ptr<Fifo<LocatedUpdate>>, 4> search_outputs_;
  std::array<std::unique_ptr<Fifo<LocatedUpdate>>, 4> process_inputs_;
  std::array<SearchPortSet, 4> search_ports_;
  std::array<ProcessorPortSet, 4> processor_ports_;
  std::array<std::unique_ptr<GraSuDirectSearch>, 4> searches_;
  std::unique_ptr<GraSuDispatch> dispatch_;
  std::array<std::unique_ptr<GraSuPmaProcessor>, 4> processors_;
  std::uint32_t next_initiator_{3000};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

GraSuPmaUpdateSystem::GraSuPmaUpdateSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::vector<GraSuEdge> updates,
    GraSuNativeConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend,
                                  std::move(layout), std::move(updates),
                                  config)) {}

GraSuPmaUpdateSystem::~GraSuPmaUpdateSystem() = default;

void GraSuPmaUpdateSystem::register_components() {
  impl_->register_components();
}

bool GraSuPmaUpdateSystem::done() const noexcept { return impl_->done(); }

bool GraSuPmaUpdateSystem::failed() const noexcept { return impl_->failed(); }

const std::string &GraSuPmaUpdateSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuUpdateCounters GraSuPmaUpdateSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<GraSuEdge> GraSuPmaUpdateSystem::live_edges() const {
  return impl_->live_edges();
}

std::array<std::uint32_t, kGraSuSegmentSlots>
GraSuPmaUpdateSystem::inspect_segment(std::size_t global_segment) const {
  return impl_->inspect_segment(global_segment);
}

const GraSuPmaLayout &GraSuPmaUpdateSystem::initial_layout() const noexcept {
  return impl_->initial_layout();
}

}  // namespace spine::sim
