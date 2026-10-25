#include "spine_sim/grasu_update/cached_processor.hpp"

#include <algorithm>
#include <deque>
#include <optional>
#include <utility>

#include "spine_sim/grasu_update/pma_word.hpp"

namespace spine::sim::grasu_update_detail {
namespace {

using Segment = std::array<std::uint32_t, kGraSuSegmentSlots>;

Segment edit(Segment value, const LocatedUpdate& item) {
  const auto key = encode_grasu_pma_edge(item.destination, item.weight);
  const auto position = std::lower_bound(value.begin(), value.end(), key);
  const bool found = position != value.end() && *position == key;
  if (item.delete_op) {
    if (!found) throw std::runtime_error("cached GraSU delete target is not live");
    std::move(position + 1, value.end(), position);
    value.back() = kGraSuPmaEmpty;
  } else {
    if (found || !is_grasu_pma_empty(value.back()))
      throw std::runtime_error("cached GraSU insert is duplicate or lacks reservation");
    std::move_backward(position, value.end() - 1, value.end());
    *position = key;
  }
  return value;
}

class CachedProcessor final : public Processor {
public:
  CachedProcessor(std::string name, ClockId clock, std::uint64_t base,
                  Ports ports, std::function<bool()> input_closed,
                  std::size_t valid_segments)
      : Processor(std::move(name), clock), base_(base), ports_(ports),
        input_closed_(std::move(input_closed)), cache_(kCachedHotSegments),
        valid_segments_(valid_segments) {
    if (base % kGraSuSegmentBytes || !ports.input || !ports.reads[0] ||
        ports.writes[0] != ports.reads[0] || ports.reads[1] || ports.writes[1] ||
        !ports.reads[0]->read_beat_stream_enabled() || !input_closed_ ||
        valid_segments > kCachedHotSegments)
      throw std::invalid_argument("invalid cached GraSU ports or completion boundary");
    transfer_segments_ = (valid_segments + kCachedHotBanks - 1) /
                         kCachedHotBanks * kCachedHotBanks;
    if (!transfer_segments_) phase_ = Phase::kProcess;
  }

  bool idle() const noexcept override { return phase_ == Phase::kDone; }
  bool failed() const noexcept override { return !failure_.empty(); }
  const std::string& failure() const noexcept override { return failure_; }
  std::uint64_t completed() const noexcept override { return completed_; }
  std::uint64_t lane_queue_stalls() const noexcept override { return stalls_; }
  std::uint64_t pma_reads() const noexcept override { return loaded_; }
  std::uint64_t pma_writes() const noexcept override { return written_; }

  void evaluate(const CycleContext& context) override {
    staged_route_.reset(); staged_beat_.reset();
    staged_starts_.clear(); staged_retires_.clear();
    stage_issue_ = stage_ack_ = stage_store_ = false;
    if (idle() || failed()) return;
    try {
      if (phase_ == Phase::kLoad || phase_ == Phase::kProcess) stage_route();
      if (phase_ == Phase::kProcess) {
        stage_updates(context.domain_cycle);
        stage_store_ = input_closed_() && ports_.input->empty() &&
                       work_items_ == 0 && !staged_route_;
      } else {
        stage_memory();
      }
    } catch (const std::exception& error) {
      failure_ = error.what();
    }
  }

  void commit(const CycleContext& context) override {
    if (idle() || failed()) return;
    if (staged_route_) {
      lanes_[staged_route_->first].queue.push_back(staged_route_->second);
      ++work_items_;
    }
    if (stage_issue_) {
      issued_ = true;
      if (phase_ == Phase::kStore) written_ = transfer_segments_;
    }
    if (stage_ack_) acknowledged_ = true;
    if (staged_beat_) cache_[loaded_++] = *staged_beat_;
    for (const auto bank : staged_retires_) {
      lanes_[bank].pending.pop_front();
      --work_items_; ++completed_;
    }
    for (const auto& start : staged_starts_) {
      auto& lane = lanes_[start.bank];
      lane.queue.pop_front();
      // Logical forwarding retains same-row input order. The packet remains
      // in the finite seven-cycle pipeline; HBM sees no edit before writeback.
      cache_[start.index] = start.value;
      lane.pending.push_back({context.domain_cycle + kCachedUpdateLatency, start.item});
      lane.next_accept = context.domain_cycle + kCachedUpdateInterval;
    }
    if (phase_ == Phase::kLoad && acknowledged_ && loaded_ == transfer_segments_)
      phase_ = Phase::kProcess;
    if (stage_store_) {
      write_data_.clear(); write_data_.reserve(transfer_bytes());
      for (std::size_t index = 0; index < transfer_segments_; ++index) {
        const auto bytes = encode_segment(cache_[index]);
        write_data_.insert(write_data_.end(), bytes.begin(), bytes.end());
      }
      phase_ = transfer_segments_ ? Phase::kStore : Phase::kDone;
      issued_ = acknowledged_ = false;
    }
    if (phase_ == Phase::kStore && acknowledged_) {
      phase_ = Phase::kDone;
      write_data_.clear();
    }
  }

private:
  std::uint64_t transfer_bytes() const { return transfer_segments_ * kGraSuSegmentBytes; }
  static constexpr std::size_t kPipelineEntries =
      (kCachedUpdateLatency + kCachedUpdateInterval - 1) / kCachedUpdateInterval;
  enum class Phase { kLoad, kProcess, kStore, kDone };
  struct Pending { std::uint64_t ready; LocatedUpdate item; };
  struct Lane {
    std::deque<LocatedUpdate> queue;
    std::deque<Pending> pending;
    std::uint64_t next_accept{};
  };
  struct Start { std::size_t bank, index; LocatedUpdate item; Segment value; };

  void stage_route() {
    const auto* item = ports_.input->front();
    if (!item) return;
    const std::size_t index = item->segment_head_slot >> 5;
    if (item->partition != 0 || index >= valid_segments_)
      throw std::runtime_error("cached GraSU packet is outside its single hot window");
    const auto bank = index % kCachedHotBanks;
    if (lanes_[bank].queue.size() == kCachedBankQueueDepth) { ++stalls_; return; }
    LocatedUpdate consumed;
    if (ports_.input->try_pop(consumed)) staged_route_ = std::pair(bank, consumed);
  }

  void stage_updates(std::uint64_t cycle) {
    for (std::size_t bank = 0; bank < lanes_.size(); ++bank) {
      const auto& lane = lanes_[bank];
      if (!lane.pending.empty() && lane.pending.front().ready <= cycle) {
        const auto& item = lane.pending.front().item;
        if (!ports_.degree_output || ports_.degree_output->try_push(DegreeDelta{
                .global_index = item.global_index, .source = item.source,
                .delta = item.delete_op ? -1 : 1}))
          staged_retires_.push_back(bank);
      }
      if (lane.queue.empty() || cycle < lane.next_accept ||
          lane.pending.size() >= kPipelineEntries) continue;
      const auto& item = lane.queue.front();
      const std::size_t index = item.segment_head_slot >> 5;
      staged_starts_.push_back({bank, index, item, edit(cache_[index], item)});
    }
  }

  void stage_memory() {
    auto& port = *ports_.reads[0];
    const bool loading = phase_ == Phase::kLoad;
    const auto operation = loading ? MemoryOperation::kRead : MemoryOperation::kWrite;
    const std::uint64_t transaction = loading ? 0 : 1;
    if (!issued_)
      stage_issue_ = port.requests().try_push(AxiRequest{
          .transaction_id = transaction, .operation = operation, .address = base_,
          .bytes = transfer_bytes(), .stream_read_beats = loading, .write_data = write_data_});
    if (!port.responses().empty()) {
      AxiResponse response; port.responses().try_pop(response);
      if (acknowledged_ || !response.success || response.operation != operation ||
          response.transaction_id != transaction ||
          response.read_data.size() != (loading ? transfer_bytes() : 0))
        throw std::runtime_error("cached GraSU parent acknowledgement mismatch");
      stage_ack_ = true;
    }
    if (loading && !port.read_beats().empty()) {
      AxiReadBeatResponse beat; port.read_beats().try_pop(beat);
      if (!beat.success || beat.transaction_id != transaction || loaded_ >= transfer_segments_ ||
          beat.parent_offset != loaded_ * kGraSuSegmentBytes ||
          beat.address != base_ + beat.parent_offset ||
          beat.last != (loaded_ + 1 == transfer_segments_))
        throw std::runtime_error("cached GraSU preload beat identity/order mismatch");
      staged_beat_ = decode_segment(beat.read_data);
    }
  }

  std::uint64_t base_{};
  Ports ports_;
  std::function<bool()> input_closed_;
  std::vector<Segment> cache_;
  std::size_t valid_segments_{}, transfer_segments_{};
  std::array<Lane, kCachedHotBanks> lanes_;
  Phase phase_{Phase::kLoad};
  bool issued_{}, acknowledged_{}, stage_issue_{}, stage_ack_{}, stage_store_{};
  std::size_t work_items_{};
  std::uint64_t loaded_{}, written_{}, completed_{}, stalls_{};
  std::vector<std::uint8_t> write_data_;
  std::optional<std::pair<std::size_t, LocatedUpdate>> staged_route_;
  std::optional<Segment> staged_beat_;
  std::vector<Start> staged_starts_;
  std::vector<std::size_t> staged_retires_;
  std::string failure_;
};
}  // namespace

std::unique_ptr<Processor> make_cached_processor(
    std::string name, ClockId clock, std::uint64_t pma_base,
    Processor::Ports ports, std::function<bool()> input_closed,
    std::size_t valid_segments) {
  return std::make_unique<CachedProcessor>(std::move(name), clock, pma_base,
                                            ports, std::move(input_closed), valid_segments);
}

}  // namespace spine::sim::grasu_update_detail
