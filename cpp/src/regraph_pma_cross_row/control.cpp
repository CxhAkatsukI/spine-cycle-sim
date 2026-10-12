#include "state.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::detail {

CrossRowPmaAdapter::CrossRowPmaAdapter(ClockId clock, const ReGraphPmaAdapterConfig &config,
    FixedAxiPort &memory, Fifo<ReGraphPmaPacket> &output,
    ReGraphPmaAdapterCounters &counters, bool &stream_complete)
    : config_(config), memory_(memory), output_(output), counters_(counters),
      stream_complete_(stream_complete), loaded_("cross_row_loaded", clock, config.cross_row.loaded_fifo_capacity) {
  if (!config.row_line_reads || !config.prefetch_rows || !config.stop_after_last ||
      config.empty_segment_exit_cycles || config.pending_read_capacity > 16 ||
      !config.cross_row.reader_pipeline_capacity || config.cross_row.reader_pipeline_capacity > 74 ||
      config.cross_row.loaded_fifo_capacity > 16 || !config.cross_row.block_drain_cycles ||
      !config.cross_row.publisher_pipeline_cycles)
    throw std::invalid_argument("invalid explicit cross-row structural schedule");
}

bool CrossRowPmaAdapter::done() const noexcept { return phase_ == Phase::kDone; }

void CrossRowPmaAdapter::start(ReGraphPmaPartition partition) {
  if ((phase_ != Phase::kIdle && !done()) || !pending_.empty() || !inflight_.empty() ||
      !returned_.empty() || !loaded_.empty() || publishing_ || !memory_.idle())
    throw std::logic_error("cross-row adapter restarted while busy");
  partition_ = partition;
  block_ = block_count_ = source_ = total_slots_ = issued_slots_ = emitted_slots_ = 0;
  stream_complete_ = false;
  half_ = 0;
  phase_ = partition.vertices ? Phase::kExtent : Phase::kTerminal;
}

void CrossRowPmaAdapter::evaluate(const CycleContext &context) {
  staged_issue_.reset();
  staged_response_.reset();
  staged_loaded_.reset();
  staged_packet_.reset();
  staged_transfer_ = staged_terminal_ = staged_advance_ = staged_stall_ = false;
  if (phase_ == Phase::kIdle || done()) return;
  if (const auto *front = memory_.responses().front()) {
    const auto found = pending_.find(front->transaction_id);
    if (found == pending_.end()) throw std::logic_error("unknown cross-row response");
    if (context.domain_cycle >= found->second.ready_cycle) {
      AxiResponse response;
      if (memory_.responses().try_pop(response)) staged_response_ = std::move(response);
    }
  }
  if (!inflight_.empty() && returned_.contains(inflight_.front().id)) {
    const auto &front = inflight_.front();
    staged_transfer_ = loaded_.try_push(Loaded{front.task, returned_.at(front.id)});
  }
  if (phase_ == Phase::kExtent) {
    const auto last = partition_.vertices - 1;
    issue(Kind::kExtent, Task{.source = last}, (partition_.row_base + last * 8) & ~std::uint64_t{63},
          partition_.row_channel, context);
  } else if (phase_ == Phase::kDirectory) {
    issue(Kind::kDirectory, {}, partition_.row_base + block_ * 8, partition_.row_channel, context);
  } else if (phase_ == Phase::kScan) {
    if (segment_ < end_ / 16) {
      if (inflight_.size() < config_.cross_row.reader_pipeline_capacity) {
        const auto local = segment_ / 2;
        const auto bank = (segment_ % 2) * 2 + (local < partition_.cache_segments_per_half ? 0 : 1);
        issue(Kind::kSegment, Task{source_, begin_, end_, segment_, false},
              partition_.pma_base[bank] + local * 64, partition_.pma_channel[bank], context);
      }
    } else staged_advance_ = true;
  } else if (phase_ == Phase::kTerminal && inflight_.empty()) {
    staged_terminal_ = loaded_.try_push(Loaded{Task{.terminal = true}, {}});
  }
  if (publishing_) {
    if (context.domain_cycle >= publish_ready_) {
      const auto value = packet();
      if (output_.try_push(value)) staged_packet_ = value;
      else staged_stall_ = true;
    }
  } else {
    Loaded loaded;
    if (loaded_.try_pop(loaded)) staged_loaded_ = std::move(loaded);
  }
}

void CrossRowPmaAdapter::commit(const CycleContext &context) {
  if (staged_response_) receive(*staged_response_);
  if (staged_transfer_) {
    returned_.erase(inflight_.front().id);
    inflight_.pop_front();
  }
  if (staged_issue_) {
    pending_.emplace(next_id_, *staged_issue_);
    switch (staged_issue_->kind) {
    case Kind::kExtent: ++counters_.extent_reads; phase_ = Phase::kWaitExtent; break;
    case Kind::kDirectory: ++counters_.row_reads; phase_ = Phase::kWaitDirectory; break;
    case Kind::kSegment:
      inflight_.push_back(Inflight{next_id_, staged_issue_->task});
      ++segment_;
      issued_slots_ += 16;
      ++counters_.segment_reads;
      if (issued_slots_ == total_slots_) finish_block(context);
      break;
    }
    ++next_id_;
    counters_.max_pending_reads = std::max(counters_.max_pending_reads, pending_.size());
  }
  if (staged_advance_) {
    ++source_;
    if (source_ < block_ + block_count_) begin_row();
    else finish_block(context);
  }
  if (phase_ == Phase::kDrain && context.domain_cycle >= drain_until_ && inflight_.empty()) {
    block_ += block_count_;
    phase_ = issued_slots_ == total_slots_ ? Phase::kTerminal : Phase::kDirectory;
  }
  if (staged_terminal_) phase_ = Phase::kReaderDone;
  if (staged_loaded_) {
    if (staged_loaded_->task.terminal) {
      if (!pending_.empty() || !inflight_.empty() || !returned_.empty() || emitted_slots_ != total_slots_)
        throw std::logic_error("cross-row terminal violates read/output conservation");
      phase_ = Phase::kDone;
      stream_complete_ = true;
    } else {
      publishing_ = std::move(*staged_loaded_);
      half_ = 0;
      publish_ready_ = context.domain_cycle + config_.cross_row.publisher_pipeline_cycles;
    }
  }
  if (staged_packet_) {
    ++counters_.packets;
    for (auto source : staged_packet_->sources) {
      if (source & 0x8000'0000U) ++counters_.dummy_edges;
      else ++counters_.live_edges;
    }
    emitted_slots_ += 8;
    if (staged_packet_->last) stream_complete_ = true;
    if (++half_ == 2) publishing_.reset();
    else publish_ready_ = context.domain_cycle + 1;
  }
  if (staged_stall_) ++counters_.output_stalls;
  loaded_.commit(context);
  counters_.max_buffered_segments = std::max(counters_.max_buffered_segments, loaded_.size());
}

} // namespace spine::sim::detail
