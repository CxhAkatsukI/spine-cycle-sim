#include "spine_sim/grasu.hpp"

#include <algorithm>
#include <array>
#include <deque>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <tuple>
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

std::uint32_t decode_u32(const std::vector<std::uint8_t> &bytes,
                         std::size_t offset) {
  if (offset + 4 > bytes.size()) {
    throw std::invalid_argument("GraSU 32-bit payload has invalid size");
  }
  std::uint32_t value = 0;
  for (std::size_t index = 0; index < 4; ++index) {
    value |= static_cast<std::uint32_t>(bytes[offset + index]) << (index * 8);
  }
  return value;
}

void append_u32(std::vector<std::uint8_t> &bytes, std::uint32_t value) {
  for (std::size_t index = 0; index < 4; ++index) {
    bytes.push_back(static_cast<std::uint8_t>(value >> (index * 8)));
  }
}

std::vector<std::uint8_t> encode_partitioned_update(const GraSuEdge &edge) {
  std::vector<std::uint8_t> bytes;
  bytes.reserve(16);
  append_u32(bytes, edge.source);
  append_u32(bytes, edge.destination);
  append_u32(bytes, edge.weight);
  append_u32(bytes, edge.delete_op ? 1U : 0U);
  return bytes;
}

std::vector<std::uint8_t>
encode_segment(const std::array<std::uint32_t, kGraSuSegmentSlots> &segment) {
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
      segment[lane] |= static_cast<std::uint32_t>(bytes[lane * 4 + byte])
                       << (byte * 8);
    }
  }
  return segment;
}

std::uint64_t packed_edge(const GraSuEdge &edge) {
  return (static_cast<std::uint64_t>(edge.source) << 32) | edge.destination;
}

void validate_global_vertex(std::size_t vertices, const GraSuEdge &edge) {
  if (vertices == 0 || vertices > std::numeric_limits<std::uint32_t>::max() ||
      edge.source >= vertices || edge.destination >= vertices ||
      edge.weight > kGraSuPmaWeightMask) {
    throw std::invalid_argument("GraSU edge endpoint is outside PMA encoding");
  }
}

void validate_layout_edge(const GraSuPmaLayout &layout, const GraSuEdge &edge) {
  if (edge.source >= layout.vertices ||
      !layout.contains_destination(edge.destination) ||
      edge.weight > kGraSuPmaWeightMask) {
    throw std::invalid_argument("GraSU edge endpoint is outside PMA layout");
  }
}

std::uint32_t encode_pma_word(std::uint32_t destination, std::uint16_t weight,
                              GraSuPmaWordAbi abi) {
  if (abi == GraSuPmaWordAbi::kNativeRawDestination) {
    if (destination >= kGraSuPmaEmpty || weight != 1) {
      throw std::invalid_argument("native GraSU PMA requires unit-weight raw dst");
    }
    return destination;
  }
  return encode_grasu_pma_edge(destination, weight);
}

std::uint32_t decode_pma_destination(std::uint32_t encoded,
                                     GraSuPmaWordAbi abi) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return abi == GraSuPmaWordAbi::kNativeRawDestination
             ? encoded & ~kGraSuPmaEmpty
             : decode_grasu_pma_destination(encoded);
}

std::uint16_t decode_pma_weight(std::uint32_t encoded, GraSuPmaWordAbi abi) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return abi == GraSuPmaWordAbi::kNativeRawDestination
             ? std::uint16_t{1}
             : decode_grasu_pma_weight(encoded);
}

std::uint32_t pma_destination_sort_key(std::uint32_t encoded,
                                       GraSuPmaWordAbi abi) {
  return is_grasu_pma_empty(encoded) ? std::numeric_limits<std::uint32_t>::max()
                                     : decode_pma_destination(encoded, abi);
}

struct LocatedUpdate {
  std::uint64_t global_index{};
  std::uint32_t source{};
  std::size_t partition{};
  std::uint32_t segment_head_slot{};
  std::uint32_t destination{};
  std::uint16_t weight{1};
  bool delete_op{};
};

struct DegreeDelta {
  std::uint64_t global_index{};
  std::uint32_t source{};
  std::int32_t delta{};
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
                    std::size_t update_count, std::size_t partition_vertices,
                    bool partitioned_updates, const GraSuNativeConfig &config,
                    Ports ports)
      : Component(std::move(name), clock_id), cu_(cu),
        update_count_(update_count), partition_vertices_(partition_vertices),
        partitioned_updates_(partitioned_updates), config_(config),
        ports_(ports) {
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
    if (response_port != nullptr &&
        response_port->responses().front() != nullptr) {
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
            .address =
                config_.update_base + local_index_ * update_record_bytes(),
            .bytes = static_cast<std::uint32_t>(update_record_bytes()),
            .stream_read_beats = false,
            .write_data = {},
        });
      }
      break;
    case Phase::kNeedRow:
      staged_request_ = ports_.rows->requests().try_push(AxiRequest{
          .transaction_id = transaction_id(1),
          .operation = MemoryOperation::kRead,
          .address = partition_base(config_.row_offset_base) +
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
          .address = partition_base(config_.binary_base) +
                     static_cast<std::uint64_t>(mid_segment_) * 8,
          .bytes = 8,
          .stream_read_beats = false,
          .write_data = {},
      });
      break;
    case Phase::kEmit:
      staged_emit_ = ports_.output->try_push(LocatedUpdate{
          .global_index = cu_ + local_index_ * 4,
          .source = current_.source,
          .partition = current_partition_,
          .segment_head_slot =
              static_cast<std::uint32_t>(begin_segment_ * kGraSuSegmentSlots),
          .destination = current_.destination,
          .weight = current_.weight,
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
    return (static_cast<std::uint64_t>(cu_) << 56) | (local_index_ << 3) |
           stage;
  }

  [[nodiscard]] std::size_t update_record_bytes() const noexcept {
    return partitioned_updates_ ? 16 : 8;
  }

  [[nodiscard]] std::uint64_t partition_base(std::uint64_t base) const {
    return base + current_partition_ * config_.partition_address_stride;
  }

  void fail(std::string message) {
    if (failure_.empty()) {
      failure_ = std::move(message);
    }
  }

  void consume_response(const AxiResponse &response) {
    const std::size_t expected_bytes =
        phase_ == Phase::kWaitUpdate ? update_record_bytes() : 8;
    if (!response.success || response.read_data.size() != expected_bytes) {
      fail("GraSU direct-search received malformed AXI response");
      return;
    }
    switch (phase_) {
    case Phase::kWaitUpdate: {
      if (partitioned_updates_) {
        current_.source = decode_u32(response.read_data, 0);
        const std::uint32_t destination = decode_u32(response.read_data, 4);
        current_.weight =
            static_cast<std::uint16_t>(decode_u32(response.read_data, 8));
        current_.delete_op = decode_u32(response.read_data, 12) != 0;
        current_partition_ = destination / partition_vertices_;
        current_.destination = destination % partition_vertices_;
      } else {
        const std::uint64_t value = decode_u64(response.read_data);
        current_.delete_op = (value >> 63) != 0;
        const std::uint64_t edge = value & ~(std::uint64_t{1} << 63);
        current_.source = static_cast<std::uint32_t>(edge >> 32);
        const std::uint32_t encoded = static_cast<std::uint32_t>(edge);
        current_.destination =
            decode_pma_destination(encoded, config_.pma_word_abi);
        current_.weight = decode_pma_weight(encoded, config_.pma_word_abi);
        current_partition_ = 0;
      }
      phase_ = Phase::kNeedRow;
      break;
    }
    case Phase::kWaitRow: {
      const std::uint64_t value = decode_u64(response.read_data);
      const std::uint32_t begin_slots = static_cast<std::uint32_t>(value >> 32);
      const std::uint32_t end_slots = static_cast<std::uint32_t>(value);
      begin_segment_ = begin_slots >> 4;
      end_segment_ = end_slots >> 4;
      if (begin_segment_ >= end_segment_) {
        fail("GraSU update source has no reserved PMA segment");
        return;
      }
      mid_segment_ = (begin_segment_ + end_segment_) >> 1;
      phase_ =
          begin_segment_ == mid_segment_ ? Phase::kEmit : Phase::kNeedBinary;
      break;
    }
    case Phase::kWaitBinary: {
      const std::uint64_t value = decode_u64(response.read_data);
      const std::uint64_t edge = packed_edge(current_);
      if (value <= edge) {
        begin_segment_ = mid_segment_;
      } else {
        end_segment_ = mid_segment_;
      }
      mid_segment_ = (begin_segment_ + end_segment_) >> 1;
      phase_ =
          begin_segment_ == mid_segment_ ? Phase::kEmit : Phase::kNeedBinary;
      break;
    }
    default:
      fail("GraSU direct-search consumed response in invalid phase");
      break;
    }
  }

  std::size_t cu_{};
  std::size_t update_count_{};
  std::size_t partition_vertices_{};
  bool partitioned_updates_{};
  GraSuNativeConfig config_;
  Ports ports_;
  std::uint64_t local_index_{};
  Phase phase_{Phase::kNeedUpdate};
  GraSuEdge current_{};
  std::size_t current_partition_{};
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
    Fifo<DegreeDelta> *degree_output{};
  };

  GraSuPmaProcessor(std::string name, ClockId clock_id, bool cache_direct,
                    std::size_t lane_fifo_depth, std::uint64_t pma_base,
                    std::uint64_t partition_address_stride,
                    GraSuPmaWordAbi pma_word_abi, Ports ports)
      : Component(std::move(name), clock_id), cache_direct_(cache_direct),
        lane_fifo_depth_(lane_fifo_depth), pma_base_(pma_base),
        partition_address_stride_(partition_address_stride),
        pma_word_abi_(pma_word_abi), ports_(ports),
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
    staged_degree_lane_.reset();
    if (failed()) {
      return;
    }
    stage_input_route();
    stage_lane_starts();
    stage_responses();
    stage_degree_output();
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
    if (staged_degree_lane_.has_value()) {
      Lane &lane = lanes_[*staged_degree_lane_];
      lane.phase = LanePhase::kIdle;
      ++completed_;
    }
  }

 private:
  enum class LanePhase {
    kIdle,
    kNeedRead,
    kWaitRead,
    kNeedWrite,
    kWaitWrite,
    kNeedDegreeEmit
  };

  struct Lane {
    LanePhase phase{LanePhase::kIdle};
    std::deque<LocatedUpdate> queue;
    LocatedUpdate item{};
    std::array<std::uint32_t, kGraSuSegmentSlots> result{};
    std::int32_t degree_delta{};
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
    return pma_base_ + item.partition * partition_address_stride_ +
           local_segment * kGraSuSegmentBytes;
  }

  void stage_degree_output() {
    for (std::size_t lane_index = 0; lane_index < lanes_.size(); ++lane_index) {
      Lane &lane = lanes_[lane_index];
      if (lane.phase != LanePhase::kNeedDegreeEmit) {
        continue;
      }
      if (ports_.degree_output == nullptr) {
        throw std::logic_error("GraSU degree sideband is not connected");
      }
      if (ports_.degree_output->try_push(DegreeDelta{
              .global_index = lane.item.global_index,
              .source = lane.item.source,
              .delta = lane.degree_delta,
          })) {
        staged_degree_lane_ = lane_index;
      }
      break;
    }
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
          staged_responses_.push_back(StagedResponse{
              .write = write, .port = port, .response = std::move(response)});
        }
      }
      if (ports_.writes[port] != ports_.reads[port] &&
          ports_.writes[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (ports_.writes[port]->responses().try_pop(response)) {
          const bool write = response.operation == MemoryOperation::kWrite;
          staged_responses_.push_back(StagedResponse{
              .write = write, .port = port, .response = std::move(response)});
        }
      }
    }
  }

  void stage_requests() {
    const std::size_t port_count = cache_direct_ ? 1 : 2;
    for (std::size_t port = 0; port < port_count; ++port) {
      bool shared_port_used = false;
      for (std::size_t offset = 0; offset < lanes_.size(); ++offset) {
        const std::size_t lane_index =
            (write_rr_[port] + offset) % lanes_.size();
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
          staged_issues_.push_back(StagedIssue{.write = true,
                                               .lane = lane_index,
                                               .transaction_id = transaction});
          write_rr_[port] = (lane_index + 1) % lanes_.size();
          shared_port_used = ports_.writes[port] == ports_.reads[port];
        }
        break;
      }
      if (shared_port_used) {
        continue;
      }
      for (std::size_t offset = 0; offset < lanes_.size(); ++offset) {
        const std::size_t lane_index =
            (read_rr_[port] + offset) % lanes_.size();
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
          staged_issues_.push_back(StagedIssue{.write = false,
                                               .lane = lane_index,
                                               .transaction_id = transaction});
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
      if (ports_.degree_output == nullptr) {
        lane.phase = LanePhase::kIdle;
        ++completed_;
      } else {
        lane.phase = LanePhase::kNeedDegreeEmit;
      }
      return;
    }
    if (lane.phase != LanePhase::kWaitRead) {
      failure_ = "GraSU PMA read response violated lane state";
      return;
    }
    try {
      auto [result, degree_delta] =
          apply_update(decode_segment(staged.response.read_data), lane.item);
      lane.result = result;
      lane.degree_delta = degree_delta;
    } catch (const std::exception &error) {
      failure_ = error.what();
      return;
    }
    lane.phase = LanePhase::kNeedWrite;
  }

  std::pair<std::array<std::uint32_t, kGraSuSegmentSlots>, std::int32_t>
  apply_update(std::array<std::uint32_t, kGraSuSegmentSlots> segment,
               const LocatedUpdate &item) const {
    const auto position = std::lower_bound(
        segment.begin(), segment.end(), item.destination,
        [this](std::uint32_t encoded, std::uint32_t destination) {
          return pma_destination_sort_key(encoded, pma_word_abi_) < destination;
        });
    const bool found =
        position != segment.end() && !is_grasu_pma_empty(*position) &&
        decode_pma_destination(*position, pma_word_abi_) == item.destination;
    if (item.delete_op) {
      if (!found || decode_pma_weight(*position, pma_word_abi_) != item.weight) {
        throw std::runtime_error(
            "GraSU delete target is not live in PMA segment");
      }
      std::move(position + 1, segment.end(), position);
      segment.back() = kGraSuPmaEmpty;
      return {segment, -1};
    }
    const std::uint32_t encoded =
        encode_pma_word(item.destination, item.weight, pma_word_abi_);
    if (found) {
      if (decode_pma_weight(*position, pma_word_abi_) == item.weight) {
        throw std::runtime_error(
            "GraSU weight update does not change PMA state");
      }
      *position = encoded;
      return {segment, 0};
    }
    if (!is_grasu_pma_empty(segment.back())) {
      throw std::runtime_error(
          "GraSU PMA segment has no reserved insertion slot");
    }
    std::move_backward(position, segment.end() - 1, segment.end());
    *position = encoded;
    return {segment, 1};
  }

  bool cache_direct_{};
  std::size_t lane_fifo_depth_{};
  std::uint64_t pma_base_{};
  std::uint64_t partition_address_stride_{};
  GraSuPmaWordAbi pma_word_abi_{GraSuPmaWordAbi::kNormalizedWeighted};
  Ports ports_;
  std::vector<Lane> lanes_;
  std::optional<std::pair<std::size_t, LocatedUpdate>> staged_route_;
  std::vector<std::size_t> staged_starts_;
  std::vector<StagedResponse> staged_responses_;
  std::vector<StagedIssue> staged_issues_;
  std::optional<std::size_t> staged_degree_lane_;
  std::unordered_map<std::uint64_t, std::size_t> read_transactions_;
  std::unordered_map<std::uint64_t, std::size_t> write_transactions_;
  std::array<std::size_t, 2> read_rr_{};
  std::array<std::size_t, 2> write_rr_{};
  std::uint64_t next_transaction_{};
  std::uint64_t completed_{};
  std::uint64_t lane_queue_stalls_{};
  std::string failure_;
};

class GraSuDegreeUpdater final : public Component {
 public:
  GraSuDegreeUpdater(std::string name, ClockId clock_id, std::size_t updates,
                     std::size_t reorder_entries, std::uint64_t degree_base,
                     std::array<Fifo<DegreeDelta> *, 4> inputs,
                     FixedAxiPort &port)
      : Component(std::move(name), clock_id), updates_(updates),
        degree_base_(degree_base), inputs_(inputs), port_(port),
        ready_(updates) {
    if (updates_ > reorder_entries) {
      throw std::invalid_argument(
          "GraSU degree reorder capacity is smaller than update batch");
    }
  }

  [[nodiscard]] bool done() const noexcept {
    return next_ == updates_ && phase_ == Phase::kIdle &&
           !current_.has_value() && ready_count_ == 0;
  }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t reads() const noexcept { return reads_; }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_; }
  [[nodiscard]] std::size_t reorder_max_occupancy() const noexcept {
    return reorder_max_occupancy_;
  }

  void evaluate(const CycleContext &) override {
    staged_inputs_.clear();
    staged_input_port_.reset();
    staged_ready_.reset();
    staged_response_.reset();
    staged_request_ = false;
    if (failed() || done()) {
      return;
    }
    for (std::size_t offset = 0; offset < inputs_.size(); ++offset) {
      const std::size_t input_index = (input_rr_ + offset) % inputs_.size();
      Fifo<DegreeDelta> *input = inputs_[input_index];
      const DegreeDelta *item = input->front();
      if (item == nullptr) {
        continue;
      }
      const bool staged_duplicate = std::any_of(
          staged_inputs_.begin(), staged_inputs_.end(),
          [&](const DegreeDelta &staged) {
            return staged.global_index == item->global_index;
          });
      if (item->global_index >= updates_ ||
          ready_[item->global_index].has_value() || staged_duplicate) {
        failure_ = "GraSU degree updater received duplicate or invalid tag";
        return;
      }
      DegreeDelta consumed;
      if (input->try_pop(consumed)) {
        staged_inputs_.push_back(consumed);
        staged_input_port_ = input_index;
      }
      break;
    }
    if ((phase_ == Phase::kWaitRead || phase_ == Phase::kWaitWrite) &&
        port_.responses().front() != nullptr) {
      AxiResponse response;
      if (port_.responses().try_pop(response)) {
        staged_response_ = std::move(response);
      }
      return;
    }
    if (phase_ == Phase::kIdle) {
      if (next_ < updates_ && ready_[next_].has_value()) {
        staged_ready_ = *ready_[next_];
      }
      return;
    }
    if (phase_ == Phase::kNeedRead) {
      staged_request_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(false),
          .operation = MemoryOperation::kRead,
          .address = degree_base_ + current_->source * 4,
          .bytes = 4,
          .stream_read_beats = false,
          .write_data = {},
      });
    } else if (phase_ == Phase::kNeedWrite) {
      std::vector<std::uint8_t> bytes;
      bytes.reserve(4);
      append_u32(bytes, updated_degree_);
      staged_request_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(true),
          .operation = MemoryOperation::kWrite,
          .address = degree_base_ + current_->source * 4,
          .bytes = 4,
          .stream_read_beats = false,
          .write_data = std::move(bytes),
      });
    }
  }

  void commit(const CycleContext &) override {
    if (failed()) {
      return;
    }
    for (const DegreeDelta &input : staged_inputs_) {
      ready_[input.global_index] = input;
      ++ready_count_;
    }
    if (staged_input_port_.has_value()) {
      input_rr_ = (*staged_input_port_ + 1) % inputs_.size();
    }
    if (staged_ready_.has_value()) {
      current_ = *staged_ready_;
      ready_[current_->global_index].reset();
      --ready_count_;
      if (current_->delta == 0) {
        current_.reset();
        ++next_;
      } else {
        phase_ = Phase::kNeedRead;
      }
    }
    reorder_max_occupancy_ = std::max(reorder_max_occupancy_, ready_count_);
    if (staged_response_.has_value()) {
      consume_response(*staged_response_);
      staged_response_.reset();
    }
    if (staged_request_) {
      if (phase_ == Phase::kNeedRead) {
        ++reads_;
        phase_ = Phase::kWaitRead;
      } else if (phase_ == Phase::kNeedWrite) {
        ++writes_;
        phase_ = Phase::kWaitWrite;
      }
    }
  }

 private:
  enum class Phase { kIdle, kNeedRead, kWaitRead, kNeedWrite, kWaitWrite };

  [[nodiscard]] std::uint64_t transaction_id(bool write) const noexcept {
    return 0xD000'0000'0000'0000ULL | (next_ << 1) | (write ? 1U : 0U);
  }
  void consume_response(const AxiResponse &response) {
    if (!response.success || !current_.has_value()) {
      failure_ = "GraSU degree updater received failed AXI response";
      return;
    }
    if (phase_ == Phase::kWaitRead) {
      if (response.operation != MemoryOperation::kRead ||
          response.transaction_id != transaction_id(false) ||
          response.read_data.size() != 4) {
        failure_ = "GraSU degree updater received malformed read response";
        return;
      }
      const std::uint32_t old_degree = decode_u32(response.read_data, 0);
      if (current_->delta < 0 && old_degree == 0) {
        failure_ = "GraSU degree update underflow";
        return;
      }
      updated_degree_ = static_cast<std::uint32_t>(
          static_cast<std::int64_t>(old_degree) + current_->delta);
      phase_ = Phase::kNeedWrite;
      return;
    }
    if (phase_ == Phase::kWaitWrite) {
      if (response.operation != MemoryOperation::kWrite ||
          response.transaction_id != transaction_id(true) ||
          !response.read_data.empty()) {
        failure_ = "GraSU degree updater received malformed write response";
        return;
      }
      current_.reset();
      ++next_;
      phase_ = Phase::kIdle;
      return;
    }
    failure_ = "GraSU degree updater response arrived out of phase";
  }

  std::size_t updates_{};
  std::uint64_t degree_base_{};
  std::array<Fifo<DegreeDelta> *, 4> inputs_{};
  FixedAxiPort &port_;
  std::vector<std::optional<DegreeDelta>> ready_;
  Phase phase_{Phase::kIdle};
  std::size_t next_{};
  std::size_t input_rr_{};
  std::size_t ready_count_{};
  std::size_t reorder_max_occupancy_{};
  std::uint32_t updated_degree_{};
  std::optional<DegreeDelta> current_;
  std::vector<DegreeDelta> staged_inputs_;
  std::optional<std::size_t> staged_input_port_;
  std::optional<DegreeDelta> staged_ready_;
  std::optional<AxiResponse> staged_response_;
  bool staged_request_{};
  std::uint64_t reads_{};
  std::uint64_t writes_{};
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

std::uint32_t encode_grasu_pma_edge(std::uint32_t destination,
                                    std::uint16_t weight) {
  if (destination > kGraSuPmaDestinationMask ||
      weight > kGraSuPmaWeightMask) {
    throw std::invalid_argument("GraSU weighted PMA edge exceeds ReGraph ABI");
  }
  return (static_cast<std::uint32_t>(weight) << kGraSuPmaWeightShift) |
         destination;
}

std::uint32_t decode_grasu_pma_destination(std::uint32_t encoded) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return encoded & kGraSuPmaDestinationMask;
}

std::uint16_t decode_grasu_pma_weight(std::uint32_t encoded) {
  if (is_grasu_pma_empty(encoded)) {
    throw std::invalid_argument("cannot decode an empty GraSU PMA slot");
  }
  return static_cast<std::uint16_t>((encoded >> kGraSuPmaWeightShift) &
                                    kGraSuPmaWeightMask);
}

bool is_grasu_pma_empty(std::uint32_t encoded) noexcept {
  return (encoded & kGraSuPmaEmpty) != 0;
}

GraSuPmaLayout GraSuPmaLayout::build(
    std::size_t vertices, const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &reserved_updates) {
  if (vertices == 0 || vertices > kGraSuPmaLocalVertexCapacity) {
    throw std::invalid_argument(
        "weighted GraSU/ReGraph PMA currently supports one 19-bit partition");
  }
  return build_partition(vertices, 0, vertices, initial_edges,
                         reserved_updates);
}

GraSuPmaLayout GraSuPmaLayout::build_partition(
    std::size_t source_vertices, std::uint32_t destination_base,
    std::size_t destination_vertices,
    const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &reserved_updates) {
  if (source_vertices == 0 ||
      source_vertices > std::numeric_limits<std::uint32_t>::max() ||
      destination_vertices == 0 ||
      destination_vertices > kGraSuPmaLocalVertexCapacity ||
      static_cast<std::uint64_t>(destination_base) + destination_vertices >
          source_vertices) {
    throw std::invalid_argument("invalid GraSU destination partition");
  }
  std::vector<std::map<std::uint32_t, std::uint16_t>> initial(source_vertices);
  std::vector<std::set<std::uint32_t>> reserved(source_vertices);
  for (const GraSuEdge &edge : initial_edges) {
    validate_global_vertex(source_vertices, edge);
    if (edge.destination < destination_base ||
        edge.destination >=
            static_cast<std::uint64_t>(destination_base) +
                destination_vertices) {
      throw std::invalid_argument(
          "initial GraSU edge is outside destination partition");
    }
    if (edge.delete_op) {
      throw std::invalid_argument("initial GraSU edge cannot be a deletion");
    }
    const std::uint32_t local = edge.destination - destination_base;
    initial[edge.source][local] = edge.weight;
    reserved[edge.source].insert(local);
  }
  for (const GraSuEdge &edge : reserved_updates) {
    validate_global_vertex(source_vertices, edge);
    if (edge.destination < destination_base ||
        edge.destination >=
            static_cast<std::uint64_t>(destination_base) +
                destination_vertices) {
      throw std::invalid_argument(
          "reserved GraSU edge is outside destination partition");
    }
    if (!edge.delete_op) {
      reserved[edge.source].insert(edge.destination - destination_base);
    }
  }

  GraSuPmaLayout layout;
  layout.vertices = source_vertices;
  layout.destination_base = destination_base;
  layout.destination_vertices = destination_vertices;
  layout.row_slot_bounds.resize(source_vertices);
  std::uint32_t next_slot = 0;
  for (std::size_t source = 0; source < source_vertices; ++source) {
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
        const auto found = initial[source].find(destination);
        if (found != initial[source].end()) {
          live_segment[live_count++] =
              encode_grasu_pma_edge(destination, found->second);
        }
      }
      layout.binary_heads.push_back(
          (static_cast<std::uint64_t>(source) << 32) |
          reserved_segment.front());
      layout.reserved_segments.push_back(reserved_segment);
      layout.segments.push_back(live_segment);
      if (next_slot > std::numeric_limits<std::uint32_t>::max() -
                          kGraSuSegmentSlots) {
        throw std::overflow_error("GraSU PMA row offsets exceed 32 bits");
      }
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
      for (std::uint32_t encoded : segments.at(segment)) {
        if (!is_grasu_pma_empty(encoded)) {
          edges.push_back(GraSuEdge{
              .source = static_cast<std::uint32_t>(source),
              .destination = destination_base +
                             decode_grasu_pma_destination(encoded),
              .weight = decode_grasu_pma_weight(encoded),
          });
        }
      }
    }
  }
  return edges;
}

std::size_t GraSuPmaLayout::segment_for(const GraSuEdge &edge) const {
  validate_layout_edge(*this, edge);
  const std::uint32_t local = local_destination(edge.destination);
  const auto [begin_slot, end_slot] = row_slot_bounds.at(edge.source);
  std::size_t begin = begin_slot / kGraSuSegmentSlots;
  std::size_t end = end_slot / kGraSuSegmentSlots;
  if (begin == end) {
    throw std::invalid_argument("GraSU edge source has no reserved PMA segment");
  }
  std::size_t mid = (begin + end) >> 1;
  const std::uint64_t edge_word =
      (static_cast<std::uint64_t>(edge.source) << 32) | local;
  while (begin != mid) {
    if (binary_heads.at(mid) <= edge_word) {
      begin = mid;
    } else {
      end = mid;
    }
    mid = (begin + end) >> 1;
  }
  const auto &reserved = reserved_segments.at(begin);
  if (std::find(reserved.begin(), reserved.end(), local) ==
      reserved.end()) {
    throw std::invalid_argument("GraSU insertion was not reserved by host PMA layout");
  }
  return begin;
}

bool GraSuPmaLayout::contains_destination(
    std::uint32_t destination) const noexcept {
  return destination >= destination_base &&
         static_cast<std::uint64_t>(destination) <
             static_cast<std::uint64_t>(destination_base) +
                 destination_vertices;
}

std::uint32_t
GraSuPmaLayout::local_destination(std::uint32_t destination) const {
  if (!contains_destination(destination)) {
    throw std::invalid_argument("GraSU destination is outside PMA partition");
  }
  return destination - destination_base;
}

GraSuPartitionedPmaLayout GraSuPartitionedPmaLayout::build(
    std::size_t vertices, std::size_t partition_vertices,
    const std::vector<GraSuEdge> &initial_edges,
    const std::vector<GraSuEdge> &reserved_updates) {
  if (vertices == 0 || vertices > std::numeric_limits<std::uint32_t>::max() ||
      partition_vertices == 0 ||
      partition_vertices > kGraSuPmaLocalVertexCapacity) {
    throw std::invalid_argument("invalid GraSU partitioned PMA dimensions");
  }
  const std::size_t partition_count =
      (vertices + partition_vertices - 1) / partition_vertices;
  std::vector<std::vector<GraSuEdge>> initial_by_partition(partition_count);
  std::vector<std::vector<GraSuEdge>> reserved_by_partition(partition_count);
  for (const GraSuEdge &edge : initial_edges) {
    validate_global_vertex(vertices, edge);
    initial_by_partition[edge.destination / partition_vertices].push_back(edge);
  }
  for (const GraSuEdge &edge : reserved_updates) {
    validate_global_vertex(vertices, edge);
    reserved_by_partition[edge.destination / partition_vertices].push_back(edge);
  }

  GraSuPartitionedPmaLayout result;
  result.vertices = vertices;
  result.partition_vertices = partition_vertices;
  result.partitions.reserve(partition_count);
  for (std::size_t partition = 0; partition < partition_count; ++partition) {
    const std::size_t base = partition * partition_vertices;
    const std::size_t count = std::min(partition_vertices, vertices - base);
    result.partitions.push_back(GraSuPmaLayout::build_partition(
        vertices, static_cast<std::uint32_t>(base), count,
        initial_by_partition[partition], reserved_by_partition[partition]));
  }
  return result;
}

std::size_t GraSuPartitionedPmaLayout::partition_for_destination(
    std::uint32_t destination) const {
  if (destination >= vertices || partition_vertices == 0) {
    throw std::out_of_range("GraSU destination is outside partitioned PMA");
  }
  return destination / partition_vertices;
}

const GraSuPmaLayout &
GraSuPartitionedPmaLayout::partition_for(const GraSuEdge &edge) const {
  if (edge.source >= vertices) {
    throw std::out_of_range("GraSU source is outside partitioned PMA");
  }
  return partitions.at(partition_for_destination(edge.destination));
}

std::vector<GraSuEdge> GraSuPartitionedPmaLayout::live_edges() const {
  std::vector<GraSuEdge> result;
  for (const GraSuPmaLayout &partition : partitions) {
    auto edges = partition.live_edges();
    result.insert(result.end(), edges.begin(), edges.end());
  }
  std::sort(result.begin(), result.end(), [](const auto &left, const auto &right) {
    return std::tuple(left.source, left.destination, left.weight) <
           std::tuple(right.source, right.destination, right.weight);
  });
  return result;
}

void initialize_grasu_pma_layout_payloads(
    MemoryBackend &backend, const GraSuPmaLayout &layout,
    const GraSuNativeConfig &config) {
  for (std::size_t channel = 0; channel < 4; ++channel) {
    std::vector<std::uint8_t> row_bytes;
    for (const auto &[begin, end] : layout.row_slot_bounds) {
      const auto encoded =
          encode_u64((static_cast<std::uint64_t>(begin) << 32) | end);
      row_bytes.insert(row_bytes.end(), encoded.begin(), encoded.end());
    }
    backend.initialize_payload(channel, config.row_offset_base, row_bytes);

    std::vector<std::uint8_t> binary_bytes;
    for (std::uint64_t head : layout.binary_heads) {
      const auto encoded = encode_u64(head);
      binary_bytes.insert(binary_bytes.end(), encoded.begin(), encoded.end());
    }
    backend.initialize_payload(channel, config.binary_base, binary_bytes);
  }

  for (std::size_t segment = 0; segment < layout.segments.size(); ++segment) {
    const std::size_t parity = segment & 1U;
    const std::size_t local = segment >> 1;
    auto words = layout.segments[segment];
    if (config.pma_word_abi == GraSuPmaWordAbi::kNativeRawDestination) {
      for (std::uint32_t &word : words) {
        if (!is_grasu_pma_empty(word)) {
          word = encode_pma_word(decode_grasu_pma_destination(word), 1,
                                 config.pma_word_abi);
        }
      }
    }
    const auto bytes = encode_segment(words);
    backend.initialize_payload(parity * 2,
                               config.pma_base + local * kGraSuSegmentBytes,
                               bytes);
    backend.initialize_payload(parity * 2 + 1,
                               config.pma_base + local * kGraSuSegmentBytes,
                               bytes);
  }
}

namespace {

GraSuPartitionedPmaLayout
one_partition_update_layout(GraSuPmaLayout layout) {
  GraSuPartitionedPmaLayout result;
  result.vertices = layout.vertices;
  result.partition_vertices = layout.destination_vertices;
  result.partitions.push_back(std::move(layout));
  return result;
}

}  // namespace

class GraSuPmaUpdateSystem::Impl {
 public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPartitionedPmaLayout layout, std::vector<GraSuEdge> updates,
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
    for (auto &fifo : degree_outputs_) {
      if (fifo != nullptr) {
        scheduler_.add_component(*fifo);
      }
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
    if (degree_port_ != nullptr) {
      degree_port_->register_components(scheduler_);
    }
    for (auto &search : searches_) {
      scheduler_.add_component(*search);
    }
    scheduler_.add_component(*dispatch_);
    for (auto &processor : processors_) {
      scheduler_.add_component(*processor);
    }
    if (degree_updater_ != nullptr) {
      scheduler_.add_component(*degree_updater_);
    }
    registered_ = true;
  }

  [[nodiscard]] bool failed() const noexcept {
    if (dispatch_ != nullptr && dispatch_->failed()) {
      return true;
    }
    if (degree_updater_ != nullptr && degree_updater_->failed()) {
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
    if (degree_updater_ != nullptr && degree_updater_->failed()) {
      return degree_updater_->failure();
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
    if (!registered_ || failed() || dispatch_ == nullptr ||
        !dispatch_->done()) {
      return false;
    }
    if (!std::all_of(searches_.begin(), searches_.end(),
                     [](const auto &item) { return item->done(); }) ||
        !std::all_of(processors_.begin(), processors_.end(),
                     [](const auto &item) { return item->idle(); })) {
      return false;
    }
    if (degree_updater_ != nullptr && !degree_updater_->done()) {
      return false;
    }
    return all_ports_idle();
  }

  [[nodiscard]] GraSuUpdateCounters counters() const {
    GraSuUpdateCounters result;
    result.updates = updates_.size();
    result.update_record_bytes = partitioned_updates() ? 16 : 8;
    std::set<std::size_t> touched_partitions;
    for (const GraSuEdge &edge : updates_) {
      touched_partitions.insert(
          layout_.partition_for_destination(edge.destination));
    }
    result.destination_partitions_touched = touched_partitions.size();
    result.partition_routes = partitioned_updates() ? updates_.size() : 0;
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint16_t> live;
    for (const GraSuEdge &edge : layout_.live_edges()) {
      live[{edge.source, edge.destination}] = edge.weight;
    }
    for (const GraSuEdge &edge : updates_) {
      const auto key = std::pair(edge.source, edge.destination);
      const auto found = live.find(key);
      if (edge.delete_op) {
        ++result.deletes;
        live.erase(found);
      } else if (found == live.end()) {
        ++result.inserts;
        live.emplace(key, edge.weight);
      } else {
        if (edge.weight < found->second) {
          ++result.weight_decreases;
        } else {
          ++result.weight_increases;
        }
        found->second = edge.weight;
      }
    }
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
    result.update_read_bytes = result.updates * result.update_record_bytes;
    result.row_read_bytes = result.row_reads * 8;
    result.binary_read_bytes = result.binary_probes * 8;
    result.pma_read_bytes = result.pma_reads * kGraSuSegmentBytes;
    result.pma_write_bytes = result.pma_writes * kGraSuSegmentBytes;
    if (degree_updater_ != nullptr) {
      result.degree_reads = degree_updater_->reads();
      result.degree_writes = degree_updater_->writes();
      result.degree_read_bytes = result.degree_reads * 4;
      result.degree_write_bytes = result.degree_writes * 4;
      result.degree_reorder_max_occupancy =
          degree_updater_->reorder_max_occupancy();
      result.axi_backend_submit_stalls +=
          degree_port_->master().stats().backend_submit_stalls;
      for (const auto &fifo : degree_outputs_) {
        result.degree_fifo_stalls += fifo->stats().push_stalls;
        result.degree_fifo_max_occupancy = std::max(
            result.degree_fifo_max_occupancy, fifo->stats().max_occupancy);
      }
    }
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
    return inspect_segment(0, global_segment);
  }

  [[nodiscard]] std::array<std::uint32_t, kGraSuSegmentSlots>
  inspect_segment(std::size_t partition, std::size_t local_segment) const {
    const GraSuPmaLayout &layout = layout_.partitions.at(partition);
    if (local_segment >= layout.segments.size()) {
      throw std::out_of_range("GraSU PMA segment index out of range");
    }
    const std::size_t local = local_segment >> 1;
    const bool cache = local < config_.cache_segments_per_half;
    const std::size_t parity = local_segment & 1U;
    const std::size_t channel = cache ? parity * 2 : parity * 2 + 1;
    return decode_segment(backend_.inspect_payload(
        channel,
        config_.pma_base + partition * config_.partition_address_stride +
            local * kGraSuSegmentBytes,
        kGraSuSegmentBytes));
  }

  [[nodiscard]] std::vector<GraSuEdge> live_edges() const {
    std::vector<GraSuEdge> edges;
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &layout = layout_.partitions[partition];
      for (std::size_t source = 0; source < layout.vertices; ++source) {
        const auto [begin, end] = layout.row_slot_bounds.at(source);
        for (std::size_t segment = begin / kGraSuSegmentSlots;
             segment < end / kGraSuSegmentSlots; ++segment) {
          for (std::uint32_t encoded : inspect_segment(partition, segment)) {
            if (!is_grasu_pma_empty(encoded)) {
              edges.push_back(GraSuEdge{
                  .source = static_cast<std::uint32_t>(source),
                  .destination =
                      layout.destination_base +
                      decode_pma_destination(encoded, config_.pma_word_abi),
                  .weight = decode_pma_weight(encoded, config_.pma_word_abi),
              });
            }
          }
        }
      }
    }
    std::sort(
        edges.begin(), edges.end(), [](const auto &left, const auto &right) {
          return std::tuple(left.source, left.destination, left.weight) <
                 std::tuple(right.source, right.destination, right.weight);
        });
    return edges;
  }

  [[nodiscard]] const GraSuPmaLayout &initial_layout() const noexcept {
    return layout_.partitions.front();
  }

  [[nodiscard]] const GraSuPartitionedPmaLayout &
  initial_partitioned_layout() const noexcept {
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
        config_.response_beats_per_cycle == 0 ||
        config_.partition_address_stride == 0 ||
        (config_.maintain_out_degree &&
         (config_.degree_channel >= config_.memory_channels ||
          config_.degree_fifo_depth == 0 ||
          config_.degree_reorder_entries == 0)) ||
        (config_.maintain_out_degree &&
         updates_.size() > config_.degree_reorder_entries) ||
        layout_.vertices == 0 || layout_.partition_vertices == 0 ||
        layout_.partitions.empty() ||
        layout_.partitions.size() !=
            (layout_.vertices + layout_.partition_vertices - 1) /
                layout_.partition_vertices ||
        (config_.pma_word_abi == GraSuPmaWordAbi::kNativeRawDestination &&
         layout_.partitions.size() != 1)) {
      throw std::invalid_argument("invalid GraSU native configuration");
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      const std::size_t expected_base = partition * layout_.partition_vertices;
      const std::size_t expected_vertices = std::min(
          layout_.partition_vertices, layout_.vertices - expected_base);
      if (part.vertices != layout_.vertices ||
          part.destination_base != expected_base ||
          part.destination_vertices != expected_vertices) {
        throw std::invalid_argument("GraSU PMA partitions are not contiguous");
      }
    }
  }

  [[nodiscard]] bool partitioned_updates() const noexcept {
    return layout_.partitions.size() > 1;
  }

  void validate_updates() const {
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint16_t> live;
    for (const GraSuEdge &edge : layout_.live_edges()) {
      if (config_.pma_word_abi == GraSuPmaWordAbi::kNativeRawDestination &&
          edge.weight != 1) {
        throw std::invalid_argument(
            "native GraSU PMA supports unit-weight edges only");
      }
      live.emplace(std::pair(edge.source, edge.destination), edge.weight);
    }
    for (const GraSuEdge &edge : updates_) {
      if (config_.pma_word_abi == GraSuPmaWordAbi::kNativeRawDestination &&
          edge.weight != 1) {
        throw std::invalid_argument(
            "native GraSU PMA supports unit-weight updates only");
      }
      const GraSuPmaLayout &partition = layout_.partition_for(edge);
      validate_layout_edge(partition, edge);
      (void)partition.segment_for(edge);
      const auto key = std::pair(edge.source, edge.destination);
      if (edge.delete_op) {
        const auto found = live.find(key);
        if (found == live.end() || found->second != edge.weight) {
          throw std::invalid_argument("GraSU delete target is not live");
        }
        live.erase(found);
      } else {
        const auto found = live.find(key);
        if (found != live.end() && found->second == edge.weight) {
          throw std::invalid_argument(
              "GraSU update does not change edge state");
        }
        live[key] = edge.weight;
      }
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        grasu_port_config(config_, channel, next_initiator_++, width),
        backend_);
  }

  void construct_links_and_ports() {
    for (std::size_t index = 0; index < 4; ++index) {
      search_outputs_[index] = std::make_unique<Fifo<LocatedUpdate>>(
          "grasu-search-axis" + std::to_string(index), clock_id_,
          config_.axis_fifo_depth);
      process_inputs_[index] = std::make_unique<Fifo<LocatedUpdate>>(
          "grasu-process-axis" + std::to_string(index), clock_id_,
          config_.axis_fifo_depth);
      if (config_.maintain_out_degree) {
        degree_outputs_[index] = std::make_unique<Fifo<DegreeDelta>>(
            "grasu-degree-axis" + std::to_string(index), clock_id_,
            config_.degree_fifo_depth);
      }
      search_ports_[index].updates =
          make_port("grasu-update" + std::to_string(index), index,
                    partitioned_updates() ? 16 : 8);
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
        processor_ports_[processor_index].reads[half] =
            make_port("grasu-ddr" + std::to_string(index) + "-read" +
                          std::to_string(half),
                      channel, 64);
        processor_ports_[processor_index].writes[half] =
            make_port("grasu-ddr" + std::to_string(index) + "-write" +
                          std::to_string(half),
                      channel, 64);
        processor_ports_[processor_index].owned_registration_order.push_back(
            processor_ports_[processor_index].reads[half].get());
        processor_ports_[processor_index].owned_registration_order.push_back(
            processor_ports_[processor_index].writes[half].get());
      }
    }
    if (config_.maintain_out_degree) {
      degree_port_ = make_port("grasu-degree-rmw", config_.degree_channel, 4);
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
        if (partitioned_updates()) {
          const auto encoded = encode_partitioned_update(edge);
          update_bytes.insert(update_bytes.end(), encoded.begin(),
                              encoded.end());
        } else {
          const GraSuPmaLayout &layout = layout_.partitions.front();
          std::uint64_t value =
              (static_cast<std::uint64_t>(edge.source) << 32) |
              encode_pma_word(layout.local_destination(edge.destination),
                              edge.weight, config_.pma_word_abi);
          if (edge.delete_op) {
            value |= std::uint64_t{1} << 63;
          }
          const auto encoded = encode_u64(value);
          update_bytes.insert(update_bytes.end(), encoded.begin(),
                              encoded.end());
        }
      }
      backend_.initialize_payload(channel, config_.update_base, update_bytes);
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      GraSuNativeConfig partition_config = config_;
      const std::uint64_t offset = partition * config_.partition_address_stride;
      partition_config.row_offset_base += offset;
      partition_config.binary_base += offset;
      partition_config.pma_base += offset;
      initialize_grasu_pma_layout_payloads(
          backend_, layout_.partitions[partition], partition_config);
    }
    if (config_.maintain_out_degree) {
      std::vector<std::uint32_t> degrees(layout_.vertices);
      for (const GraSuEdge &edge : layout_.live_edges()) {
        ++degrees[edge.source];
      }
      std::vector<std::uint8_t> bytes;
      bytes.reserve(degrees.size() * 4);
      for (std::uint32_t degree : degrees) {
        append_u32(bytes, degree);
      }
      backend_.initialize_payload(config_.degree_channel, config_.degree_base,
                                  bytes);
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
          counts[index], layout_.partition_vertices, partitioned_updates(),
          config_,
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
          config_.partition_address_stride, config_.pma_word_abi,
          GraSuPmaProcessor::Ports{
              .input = process_inputs_[index].get(),
              .reads = {ports.reads[0].get(), ports.reads[1].get()},
              .writes = {cache ? ports.reads[0].get() : ports.writes[0].get(),
                         cache ? nullptr : ports.writes[1].get()},
              .degree_output = degree_outputs_[index].get(),
          });
    }
    if (config_.maintain_out_degree) {
      std::array<Fifo<DegreeDelta> *, 4> degree_inputs{};
      for (std::size_t index = 0; index < degree_inputs.size(); ++index) {
        degree_inputs[index] = degree_outputs_[index].get();
      }
      degree_updater_ = std::make_unique<GraSuDegreeUpdater>(
          "grasu-degree-updater", clock_id_, updates_.size(),
          config_.degree_reorder_entries, config_.degree_base, degree_inputs,
          *degree_port_);
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
    if (degree_port_ != nullptr && !degree_port_->idle()) {
      return false;
    }
    return true;
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPartitionedPmaLayout layout_;
  std::vector<GraSuEdge> updates_;
  GraSuNativeConfig config_;
  std::array<std::unique_ptr<Fifo<LocatedUpdate>>, 4> search_outputs_;
  std::array<std::unique_ptr<Fifo<LocatedUpdate>>, 4> process_inputs_;
  std::array<std::unique_ptr<Fifo<DegreeDelta>>, 4> degree_outputs_;
  std::array<SearchPortSet, 4> search_ports_;
  std::array<ProcessorPortSet, 4> processor_ports_;
  std::array<std::unique_ptr<GraSuDirectSearch>, 4> searches_;
  std::unique_ptr<GraSuDispatch> dispatch_;
  std::array<std::unique_ptr<GraSuPmaProcessor>, 4> processors_;
  std::unique_ptr<FixedAxiPort> degree_port_;
  std::unique_ptr<GraSuDegreeUpdater> degree_updater_;
  std::uint32_t next_initiator_{3000};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

GraSuPmaUpdateSystem::GraSuPmaUpdateSystem(Scheduler &scheduler,
                                           ClockId clock_id,
                                           MemoryBackend &backend,
                                           GraSuPmaLayout layout,
                                           std::vector<GraSuEdge> updates,
                                           GraSuNativeConfig config)
    : impl_(
          std::make_unique<Impl>(scheduler, clock_id, backend,
                                 one_partition_update_layout(std::move(layout)),
                                 std::move(updates), config)) {}

GraSuPmaUpdateSystem::GraSuPmaUpdateSystem(Scheduler &scheduler,
                                           ClockId clock_id,
                                           MemoryBackend &backend,
                                           GraSuPartitionedPmaLayout layout,
                                           std::vector<GraSuEdge> updates,
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

GraSuUpdateCounters GraSuPmaUpdateSystem::counters() const {
  return impl_->counters();
}

std::vector<GraSuEdge> GraSuPmaUpdateSystem::live_edges() const {
  return impl_->live_edges();
}

std::array<std::uint32_t, kGraSuSegmentSlots>
GraSuPmaUpdateSystem::inspect_segment(std::size_t global_segment) const {
  return impl_->inspect_segment(global_segment);
}

std::array<std::uint32_t, kGraSuSegmentSlots>
GraSuPmaUpdateSystem::inspect_segment(std::size_t partition,
                                      std::size_t local_segment) const {
  return impl_->inspect_segment(partition, local_segment);
}

const GraSuPmaLayout &GraSuPmaUpdateSystem::initial_layout() const noexcept {
  return impl_->initial_layout();
}

const GraSuPartitionedPmaLayout &
GraSuPmaUpdateSystem::initial_partitioned_layout() const noexcept {
  return impl_->initial_partitioned_layout();
}

}  // namespace spine::sim
