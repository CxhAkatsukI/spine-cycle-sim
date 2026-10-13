#include "spine_sim/grasu_update/processor.hpp"

#include <algorithm>
#include <deque>
#include <optional>
#include <unordered_map>
#include <utility>

#include "spine_sim/grasu_update/pma_word.hpp"

namespace spine::sim::grasu_update_detail {
namespace {
class DirectProcessor final : public Processor {
public:
  DirectProcessor(std::string name, ClockId clock_id, DirectProcessorTopology topology,
                    std::size_t lane_fifo_depth, std::uint64_t pma_base,
                    std::uint64_t partition_address_stride,
                    const std::vector<std::uint64_t> &partition_pma_bases,
                    bool explicit_runtime_regions,
                    GraSuPmaWordAbi pma_word_abi, Ports ports)
      : Processor(std::move(name), clock_id), cache_direct_(topology != DirectProcessorTopology::kCold),
        lane_fifo_depth_(lane_fifo_depth), pma_base_(pma_base),
        partition_address_stride_(partition_address_stride),
        partition_pma_bases_(partition_pma_bases), pma_word_abi_(pma_word_abi),
        explicit_runtime_regions_(explicit_runtime_regions),
        ports_(ports), lanes_(topology == DirectProcessorTopology::kSequentialHot ? 1 :
                              topology == DirectProcessorTopology::kParallelHot ? 16 : 32) {
    if (lane_fifo_depth_ == 0 || ports_.input == nullptr ||
        ports_.reads[0] == nullptr || ports_.writes[0] == nullptr ||
        (!cache_direct_ &&
         (ports_.reads[1] == nullptr || ports_.writes[1] == nullptr))) {
      throw std::invalid_argument("invalid GraSU PMA processor ports");
    }
  }

  [[nodiscard]] bool idle() const noexcept {
    return ports_.input->empty() && work_items_ == 0;
  }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t completed() const noexcept { return completed_; }
  [[nodiscard]] std::uint64_t lane_queue_stalls() const noexcept {
    return lane_queue_stalls_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    if (failed()) {
      return false;
    }
    if (!ports_.input->empty()) {
      return true;
    }
    if (work_items_ == 0) {
      return false;
    }
    const std::size_t port_count = cache_direct_ ? 1 : 2;
    for (std::size_t port = 0; port < port_count; ++port) {
      if (ports_.reads[port]->responses().front() != nullptr ||
          (ports_.writes[port] != ports_.reads[port] &&
           ports_.writes[port]->responses().front() != nullptr)) {
        return true;
      }
    }
    return std::any_of(lanes_.begin(), lanes_.end(), [](const Lane &lane) {
      return !lane.queue.empty() || lane.phase == LanePhase::kNeedRead ||
             lane.phase == LanePhase::kNeedWrite ||
             lane.phase == LanePhase::kNeedDegreeEmit;
    });
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return staged_route_.has_value() || !staged_starts_.empty() ||
           !staged_responses_.empty() || !staged_issues_.empty() ||
           staged_degree_lane_.has_value();
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
      ++work_items_;
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
      lane.phase = issue.write ? LanePhase::kWaitWrite : LanePhase::kWaitRead;
      auto &mapping = issue.write ? write_transactions_ : read_transactions_;
      mapping.emplace(issue.transaction_id, issue.lane);
    }
    if (staged_degree_lane_.has_value()) {
      Lane &lane = lanes_[*staged_degree_lane_];
      lane.phase = LanePhase::kIdle;
      if (work_items_ == 0) {
        throw std::logic_error("GraSU PMA processor work count underflow");
      }
      --work_items_;
      ++completed_;
    }
    staged_route_.reset();
    staged_starts_.clear();
    staged_responses_.clear();
    staged_issues_.clear();
    staged_degree_lane_.reset();
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
      return lanes_.size() == 1 ? 0 : (item.segment_head_slot >> 5) & 0xFU;
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
    const std::uint64_t partition_base =
        explicit_runtime_regions_
            ? pma_base_
            : partition_pma_bases_.empty()
            ? pma_base_ + item.partition * partition_address_stride_
            : partition_pma_bases_.at(item.partition);
    return partition_base + local_segment * kGraSuSegmentBytes;
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
        if (work_items_ == 0) {
          throw std::logic_error("GraSU PMA processor work count underflow");
        }
        --work_items_;
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
    const std::uint32_t key =
        pma_search_key(item.destination, item.weight, pma_word_abi_);
    const auto position = std::lower_bound(
        segment.begin(), segment.end(), key,
        [this](std::uint32_t encoded, std::uint32_t search_key) {
          return pma_word_sort_key(encoded, pma_word_abi_) < search_key;
        });
    const bool found = position != segment.end() &&
                       !is_grasu_pma_empty(*position) &&
                       pma_word_sort_key(*position, pma_word_abi_) == key;
    if (item.delete_op) {
      if (!found ||
          decode_pma_weight(*position, pma_word_abi_) != item.weight) {
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
      if (uses_full_word_key(pma_word_abi_) ||
          decode_pma_weight(*position, pma_word_abi_) == item.weight) {
        throw std::runtime_error(
            "GraSU weight update does not change PMA state");
      }
      *position = encoded;
      return {segment, 0};
    }
    if (!is_grasu_pma_empty(segment.back())) {
      throw std::runtime_error(
          "GraSU PMA segment has no reserved insertion slot (source=" +
          std::to_string(item.source) +
          ", destination=" + std::to_string(item.destination) +
          ", partition=" + std::to_string(item.partition) +
          ", segment_head_slot=" + std::to_string(item.segment_head_slot) +
          ", weight=" + std::to_string(item.weight) +
          ", last_binary_head=" + std::to_string(item.last_binary_head) + ")");
    }
    std::move_backward(position, segment.end() - 1, segment.end());
    *position = encoded;
    return {segment, 1};
  }

  bool cache_direct_{};
  std::size_t lane_fifo_depth_{};
  std::uint64_t pma_base_{};
  std::uint64_t partition_address_stride_{};
  const std::vector<std::uint64_t> &partition_pma_bases_;
  GraSuPmaWordAbi pma_word_abi_{GraSuPmaWordAbi::kNormalizedWeighted};
  bool explicit_runtime_regions_{};
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
  std::size_t work_items_{};
  std::uint64_t completed_{};
  std::uint64_t lane_queue_stalls_{};
  std::string failure_;
};


}  // namespace

std::unique_ptr<Processor> make_direct_processor(
    std::string name, ClockId clock, DirectProcessorTopology topology,
    std::size_t lane_fifo_depth, std::uint64_t pma_base,
    std::uint64_t partition_stride,
    const std::vector<std::uint64_t>& partition_bases,
    bool explicit_regions, GraSuPmaWordAbi abi, Processor::Ports ports) {
  return std::make_unique<DirectProcessor>(
      std::move(name), clock, topology, lane_fifo_depth, pma_base,
      partition_stride, partition_bases, explicit_regions, abi, ports);
}

}  // namespace spine::sim::grasu_update_detail
