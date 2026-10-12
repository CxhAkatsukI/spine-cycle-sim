#include "bank_stream.hpp"

#include <algorithm>
#include <stdexcept>
#include "directory_tile.hpp"

namespace spine::sim::detail {

void BankStreamReader::select_row() {
  const auto row = cache_.at(source_ - join_base_);
  begin_ = row >> 32;
  end_ = std::min<std::size_t>(std::uint32_t(row), partition_.slots);
  if (begin_ != consumed_slots_ || end_ < begin_ || end_ > total_ || begin_ % 16 || end_ % 16)
    throw std::logic_error("bank stream requires contiguous aligned rows beginning at zero");
  segment_ = begin_ / 16;
  ++counters_.rows_visited;
  if (begin_ == end_) ++counters_.empty_rows;
  row_selected_ = true;
}

void BankStreamReader::evaluate(const CycleContext &context) {
  staged_issue_.reset(); staged_response_.reset(); staged_join_.reset(); staged_beat_.reset();
  staged_line_ = staged_advance_ = staged_retire_ = staged_terminal_ = false;
  if (closed_) return;
  if (pending_ && context.domain_cycle >= pending_->ready && memory_.responses().front()) {
    AxiResponse response;
    if (memory_.responses().try_pop(response)) staged_response_ = std::move(response);
  }
  if (config_.cross_row.bank_read_beats && pending_ && context.domain_cycle >= pending_->ready &&
      beat_space() && memory_.read_beats().front()) {
    AxiReadBeatResponse beat;
    if (memory_.read_beats().try_pop(beat)) staged_beat_ = std::move(beat);
  }
  if (!pending_) {
    if (phase_ == Phase::kExtent) {
      const auto last = partition_.vertices - 1;
      issue(phase_, (partition_.row_base + last * 8) & ~std::uint64_t{63}, partition_.row_channel, 64, context);
    } else if (phase_ == Phase::kDirectory && directory_.empty()) {
      loader_count_ = std::min<std::size_t>(1024, partition_.vertices - loader_base_);
      issue(phase_, partition_.row_base + loader_base_ * 8, partition_.row_channel,
            (loader_count_ + 7) / 8 * 64, context);
    } else if (phase_ == Phase::kBanks && context.domain_cycle >= loader_ready_) {
      if (interval_first_ == interval_end_) next_interval();
      if (phase_ == Phase::kBanks && interval_first_ < interval_end_) {
        const auto limit = partition_.cache_segments_per_half;
        const auto stop = interval_first_ < limit ? std::min(interval_end_, limit) : interval_end_;
        const auto count = stop - interval_first_;
        if (config_.cross_row.bank_read_beats ||
            banks_[parity_].size() + count <= config_.cross_row.bank_fifo_lines) {
          const auto bank = parity_ * 2 + (interval_first_ < limit ? 0 : 1);
          issue(phase_, partition_.pma_base[bank] + interval_first_ * 64,
                partition_.pma_channel[bank], count * 64, context, parity_);
        }
      }
    }
  }
  if (!pipeline_.empty() && context.domain_cycle >= pipeline_.front().ready)
    staged_retire_ = loaded_.try_push(pipeline_.front().record);
  if (!extent_ready_) return;
  if (consumed_slots_ == total_) {
    if (phase_ == Phase::kFinished && !pending_ && pipeline_.empty())
      staged_terminal_ = loaded_.try_push(PmaLoadedSegment{PmaSegmentTask{.terminal = true}, {}});
    return;
  }
  if (join_loaded_ < join_count_) {
    // One 512-bit directory line per cycle, with eight-way cache banking.
    staged_line_ = directory_.size() >= std::min<std::size_t>(8, join_count_ - join_loaded_);
  } else if (row_selected_ && context.domain_cycle >= join_ready_) {
    if (segment_ == end_ / 16) staged_advance_ = true;
    else if ((pipeline_.size() < 2 || staged_retire_) && !banks_[segment_ % 2].empty())
      staged_join_ = Joined{PmaLoadedSegment{PmaSegmentTask{source_, begin_, end_, segment_, false},
                                            banks_[segment_ % 2].front()}, context.domain_cycle + 2};
  }
}

void BankStreamReader::commit(const CycleContext &context) {
  if (staged_response_) {
    if (config_.cross_row.bank_read_beats) {
      const auto &response = *staged_response_;
      if (response.transaction_id != pending_->id || !response.success ||
          response.operation != MemoryOperation::kRead || response.read_data.size() != pending_->bytes ||
          pending_->acknowledged)
        throw std::logic_error("bank stream read acknowledgement mismatch");
      pending_->acknowledged = true;
      ++counters_.responses;
    } else {
      if (pending_->phase == Phase::kDirectory) loader_ready_ = context.domain_cycle + 3;
      receive(*staged_response_);
    }
  }
  if (staged_beat_) receive_beat(*staged_beat_);
  if (config_.cross_row.bank_read_beats && pending_ && pending_->acknowledged &&
      pending_->received == pending_->count) {
    if (pending_->phase == Phase::kDirectory) loader_ready_ = context.domain_cycle + 3;
    finish_stream_read();
  }
  if (staged_issue_) {
    pending_ = staged_issue_;
    ++next_id_;
    if (pending_->phase == Phase::kExtent) ++counters_.extent_reads;
    else if (pending_->phase == Phase::kDirectory) {
      counters_.row_reads += pending_->count;
      ++counters_.directory_requests;
    } else {
      counters_.segment_reads += pending_->count;
      ++counters_.pma_requests;
    }
    counters_.max_pending_reads = std::max<std::size_t>(counters_.max_pending_reads, 1);
  }
  if (staged_retire_) pipeline_.pop_front();
  if (staged_join_) {
    banks_[segment_ % 2].pop_front();
    ++segment_; consumed_slots_ += 16;
    pipeline_.push_back(std::move(*staged_join_));
  }
  if (staged_line_) {
    for (unsigned lane = 0; lane < 8 && join_loaded_ < join_count_; ++lane) {
      cache_[join_loaded_++] = directory_.front(); directory_.pop_front();
    }
    if (join_loaded_ == join_count_) {
      source_ = join_base_;
      select_row();
      join_ready_ = context.domain_cycle + 2;
    }
  }
  if (staged_advance_) {
    if (++source_ == join_base_ + join_count_) {
      join_base_ += join_count_;
      join_count_ = std::min<std::size_t>(1024, partition_.vertices - join_base_);
      join_loaded_ = 0;
      row_selected_ = false;
    } else select_row();
  }
  // Trailing prefetched metadata is read physically but is never a source visit.
  if (extent_ready_ && consumed_slots_ == total_ && phase_ == Phase::kFinished && !pending_)
    directory_.clear();
  if (staged_terminal_) {
    if (!banks_[0].empty() || !banks_[1].empty() || !directory_.empty())
      throw std::logic_error("bank terminal leaked physical work");
    closed_ = true;
  }
  counters_.max_buffered_segments = std::max(counters_.max_buffered_segments, loaded_.size());
}

} // namespace spine::sim::detail
