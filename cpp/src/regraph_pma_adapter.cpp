#include "spine_sim/regraph_pma_adapter.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <utility>

#include "detail/grasu_regraph_payload.hpp"
#include "regraph_pma_cross_row/state.hpp"
#include "spine_sim/grasu_native.hpp"

namespace spine::sim {

ReGraphPmaAdapter::ReGraphPmaAdapter(std::string name, ClockId clock_id,
    ReGraphPmaAdapterConfig config, FixedAxiPort &memory, Fifo<ReGraphPmaPacket> &output)
    : Component(std::move(name), clock_id), config_(config), memory_(memory), output_(output) {
  if (!config_.pending_read_capacity || !config_.segment_buffer_capacity ||
      !config_.row_control_cycles || !config_.segment_issue_interval ||
      (config_.row_line_reads && !config_.prefetch_rows) ||
      (config_.cross_row.continuous_directory && !config_.cross_row_pipeline)) {
    throw std::invalid_argument("invalid routed PMA adapter capacity or schedule");
  }
  if (memory_.requests().clock_id() != clock_id || output_.clock_id() != clock_id) {
    throw std::invalid_argument("routed PMA adapter port clock mismatch");
  }
  if (config_.cross_row_pipeline)
    cross_row_ = std::make_unique<detail::CrossRowPmaAdapter>(clock_id, config_, memory_, output_, counters_, stream_complete_);
}

ReGraphPmaAdapter::~ReGraphPmaAdapter() = default;

void ReGraphPmaAdapter::start_partition(ReGraphPmaPartition partition) {
  if (!cross_row_ && ((phase_ != Phase::kIdle && phase_ != Phase::kDone) || !pending_.empty() ||
      !segments_.empty() || !memory_.idle())) {
    throw std::logic_error("routed PMA adapter restarted while busy");
  }
  // AXIS may still contain the previous partition's tail. The next invocation
  // appends packets in FIFO order; gather completion is not an adapter barrier.
  if (partition.vertices >= 0x8000'0000ULL || partition.slots >= 0x1'0000'0000ULL ||
      partition.slots % 16 || partition.destination_vertices > 65536 ||
      std::uint64_t(partition.destination_base) + partition.destination_vertices > 0x8000'0000ULL ||
      partition.row_base % 64 || std::any_of(partition.pma_base.begin(), partition.pma_base.end(),
                                          [](auto base) { return base % 64 != 0; })) {
    throw std::invalid_argument("invalid aligned destination-sharded PMA geometry");
  }
  if (cross_row_) {
    cross_row_->start(partition);
    return;
  }
  partition_ = partition;
  source_ = row_begin_ = row_count_ = rows_issued_ = rows_received_ = 0;
  total_slots_ = emitted_slots_ = 0;
  half_ = 0;
  stream_complete_ = false;
  phase_ = config_.row_line_reads && !partition_.vertices ? Phase::kEmptyPartition : Phase::kExtent;
}

void ReGraphPmaAdapter::bind_completion_notifier(void *owner, Notifier notifier) {
  if (!notifier || (notifier_ && (owner != notifier_owner_ || notifier != notifier_))) {
    throw std::invalid_argument("invalid routed adapter completion binding");
  }
  notifier_owner_ = owner;
  notifier_ = notifier;
}

void ReGraphPmaAdapter::unbind_completion_notifier(void *owner) noexcept {
  if (owner == notifier_owner_) {
    notifier_owner_ = nullptr;
    notifier_ = nullptr;
  }
}

void ReGraphPmaAdapter::notify() const noexcept {
  if (notifier_) notifier_(notifier_owner_);
}

bool ReGraphPmaAdapter::done() const noexcept { return cross_row_ ? cross_row_->done() : phase_ == Phase::kDone; }

bool ReGraphPmaAdapter::issue(Kind kind, std::size_t index, std::uint64_t address,
                            std::size_t channel, const CycleContext &context) {
  if (pending_.size() >= config_.pending_read_capacity) return false;
  if (!memory_.requests().try_push(AxiRequest{
          .transaction_id = next_id_, .operation = MemoryOperation::kRead,
          .address = address, .bytes = 64, .stream_read_beats = false,
          .target_channel = channel, .write_data = {}})) return false;
  staged_issue_ = Pending{kind, index, context.domain_cycle + config_.read_pipeline_cycles};
  return true;
}

void ReGraphPmaAdapter::evaluate(const CycleContext &context) {
  if (cross_row_) {
    cross_row_->evaluate(context);
    return;
  }
  staged_issue_.reset();
  staged_response_.reset();
  staged_packet_.reset();
  staged_control_ = staged_empty_exit_ = staged_output_stall_ = false;
  if (phase_ == Phase::kIdle || done()) return;
  if (const auto *front = memory_.responses().front()) {
    const auto found = pending_.find(front->transaction_id);
    if (found == pending_.end()) throw std::logic_error("unrecognized routed adapter response");
    if (context.domain_cycle >= found->second.ready_cycle) {
      AxiResponse response;
      if (memory_.responses().try_pop(response)) staged_response_ = std::move(response);
    }
  }
  if (phase_ == Phase::kExtent) {
    const auto last = partition_.vertices ? partition_.vertices - 1 : 0;
    issue(Kind::kExtent, last, (partition_.row_base + last * 8) & ~std::uint64_t{63},
          partition_.row_channel, context);
  } else if (phase_ == Phase::kRows && rows_issued_ < row_count_) {
    const auto row = row_begin_ + rows_issued_;
    issue(Kind::kRow, row, (partition_.row_base + row * 8) & ~std::uint64_t{63},
          partition_.row_channel, context);
  } else if (phase_ == Phase::kRowControl) {
    staged_control_ = true;
  } else if (phase_ == Phase::kEmptyExit) {
    staged_empty_exit_ = true;
  } else if (phase_ == Phase::kSegments) {
    if (segments_.contains(next_emit_segment_)) {
      auto value = packet();
      if (output_.try_push(value)) staged_packet_ = value;
      else staged_output_stall_ = true;
    }
    if (next_segment_ < end_segment_ && context.domain_cycle >= next_segment_issue_cycle_ &&
        pending_.size() + segments_.size() < config_.segment_buffer_capacity) {
      const auto local = next_segment_ >> 1;
      const auto bank = (next_segment_ & 1U) * 2 + (local < partition_.cache_segments_per_half ? 0 : 1);
      issue(Kind::kSegment, next_segment_, partition_.pma_base[bank] + local * 64,
            partition_.pma_channel[bank], context);
    }
  }
}

void ReGraphPmaAdapter::consume(const AxiResponse &response) {
  if (!response.success || response.read_data.size() != 64) {
    throw std::runtime_error("routed PMA adapter requires a successful full-line response");
  }
  const auto pending = pending_.at(response.transaction_id);
  pending_.erase(response.transaction_id);
  ++counters_.responses;
  if (pending.kind == Kind::kSegment) {
    if (!segments_.emplace(pending.index, response.read_data).second) {
      throw std::logic_error("duplicate routed PMA segment");
    }
    counters_.max_buffered_segments = std::max(counters_.max_buffered_segments, segments_.size());
    return;
  }
  const auto offset = ((partition_.row_base + pending.index * 8) & 63U);
  const std::uint64_t row = detail::decode_u32(response.read_data, offset) |
      (std::uint64_t(detail::decode_u32(response.read_data, offset + 4)) << 32);
  if (pending.kind == Kind::kExtent) {
    total_slots_ = partition_.vertices ? std::min<std::size_t>(std::uint32_t(row), partition_.slots) : 0;
    if (total_slots_ % 16) throw std::logic_error("routed PMA final extent is not segment aligned");
    stream_complete_ = total_slots_ == 0;
    if (stream_complete_) notify();
    select_source();
    return;
  }
  if (config_.row_line_reads) {
    if (pending.index != row_begin_ || row_begin_ % 8 || rows_received_)
      throw std::logic_error("whole-line directory response is not a fresh aligned block");
    for (std::size_t index = 0; index < row_count_; ++index)
      rows_.at(index) = detail::decode_u32(response.read_data, index * 8) |
          (std::uint64_t(detail::decode_u32(response.read_data, index * 8 + 4)) << 32);
    rows_received_ = row_count_;
  } else {
    rows_.at(pending.index - row_begin_) = row;
    ++rows_received_;
  }
  if (rows_received_ == row_count_) {
    phase_ = Phase::kRowControl;
    remaining_control_ = config_.row_control_cycles;
  }
}

void ReGraphPmaAdapter::select_source() {
  if (source_ == partition_.vertices || (config_.stop_after_last && emitted_slots_ >= total_slots_)) {
    if (emitted_slots_ != total_slots_ || !pending_.empty() || !segments_.empty()) {
      throw std::logic_error("routed PMA extent or read conservation failed");
    }
    phase_ = Phase::kDone;
    notify();
    return;
  }
  if (source_ >= row_begin_ && source_ < row_begin_ + row_count_) {
    phase_ = Phase::kRowControl;
    remaining_control_ = config_.row_control_cycles;
  } else {
    row_begin_ = source_;
    row_count_ = std::min<std::size_t>(config_.prefetch_rows ? 8 : 1, partition_.vertices - source_);
    rows_issued_ = rows_received_ = 0;
    phase_ = Phase::kRows;
  }
}

void ReGraphPmaAdapter::start_row() {
  const auto row = rows_.at(source_ - row_begin_);
  const std::size_t begin = row >> 32;
  const auto end = std::min<std::size_t>(std::uint32_t(row), partition_.slots);
  if (begin != emitted_slots_ || end < begin || end > total_slots_ || begin % 16 || end % 16) {
    throw std::logic_error("routed PMA rows must be contiguous, monotonic and segment aligned");
  }
  ++counters_.rows_visited;
  next_segment_ = next_emit_segment_ = begin / 16;
  end_segment_ = end / 16;
  half_ = 0;
  next_segment_issue_cycle_ = 0;
  if (begin == end) {
    ++counters_.empty_rows;
    // The routed helper must retire its exit pipeline even without a segment.
    // Zero preserves earlier profiles; skipped tail rows never reach this call.
    remaining_empty_exit_ = config_.empty_segment_exit_cycles;
    if (remaining_empty_exit_) phase_ = Phase::kEmptyExit;
    else {
      ++source_;
      select_source();
    }
  } else phase_ = Phase::kSegments;
}

ReGraphPmaPacket ReGraphPmaAdapter::packet() const {
  ReGraphPmaPacket result;
  const auto &bytes = segments_.at(next_emit_segment_);
  for (std::size_t lane = 0; lane < 8; ++lane) {
    const auto word = detail::decode_u32(bytes, (half_ * 8 + lane) * 4);
    const auto local = word & kGraSuPmaDestinationMask;
    const bool dummy = (word & 0x8000'0000U) != 0 || local >= partition_.destination_vertices;
    const auto flag = dummy ? 0x8000'0000U : 0U;
    result.sources[lane] = static_cast<std::uint32_t>(source_) | flag;
    auto destination = word & 0x7fff'ffffU;
    if (config_.format == ReGraphPmaFormat::kDestination) destination = partition_.destination_base + local;
    else if (config_.format == ReGraphPmaFormat::kUnitWeight) destination = local | (1U << kGraSuPmaWeightShift);
    result.destinations[lane] = destination | flag;
  }
  result.last = emitted_slots_ + 8 >= total_slots_;
  return result;
}

void ReGraphPmaAdapter::commit(const CycleContext &context) {
  if (cross_row_) {
    const bool stream_before = stream_complete_, done_before = done();
    cross_row_->commit(context);
    if (stream_before != stream_complete_ || done_before != done()) notify();
    return;
  }
  if (phase_ == Phase::kEmptyPartition) {
    phase_ = Phase::kDone;
    stream_complete_ = true;
    notify();
    return;
  }
  if (staged_response_) consume(*staged_response_);
  if (staged_issue_) {
    pending_.emplace(next_id_++, *staged_issue_);
    if (staged_issue_->kind == Kind::kExtent) {
      ++counters_.extent_reads;
      phase_ = Phase::kWaitExtent;
    } else if (staged_issue_->kind == Kind::kRow) {
      if (config_.row_line_reads) rows_issued_ = row_count_;
      else ++rows_issued_;
      ++counters_.row_reads;
    } else {
      ++next_segment_;
      ++counters_.segment_reads;
      next_segment_issue_cycle_ = context.domain_cycle + config_.segment_issue_interval;
    }
    counters_.max_pending_reads = std::max(counters_.max_pending_reads, pending_.size());
  }
  if (staged_control_ && --remaining_control_ == 0) start_row();
  if (staged_empty_exit_) {
    ++counters_.empty_exit_cycles;
    if (--remaining_empty_exit_ == 0) {
      ++source_;
      select_source();
    }
  }
  if (staged_output_stall_) ++counters_.output_stalls;
  if (staged_packet_) {
    ++counters_.packets;
    for (const auto source : staged_packet_->sources) {
      if (source & 0x8000'0000U) ++counters_.dummy_edges;
      else ++counters_.live_edges;
    }
    emitted_slots_ += 8;
    if (staged_packet_->last) {
      stream_complete_ = true;
      notify();
    }
    if (++half_ == 2) {
      half_ = 0;
      segments_.erase(next_emit_segment_++);
      if (next_emit_segment_ == end_segment_) {
        ++source_;
        select_source();
      }
    }
  }
}

} // namespace spine::sim
