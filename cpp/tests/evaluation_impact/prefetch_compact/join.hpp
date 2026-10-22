#pragma once

namespace evaluation_impact::prefetch_compact {
inline void Reader::prepare_join(const CycleContext& context) {
  next_source_ = source_;
  skipped_ = 0;
  if (!extent_ || consumed_ == total_) return;
  const auto tile_end = std::min(tile_base_ + 1024, partition_.vertices);
  if (source_ == tile_end) {
    const auto lines = (tile_end - tile_base_ + 7) / 8;
    advance_tile_ = dir_issued_ == lines && outstanding_directory() == 0;
    return;
  }
  // An eight-bank priority selector can skip at most eight empty rows per cycle.
  for (unsigned lane = 0; lane < 8 && next_source_ < tile_end; ++lane) {
    const auto offset = next_source_ - tile_base_, line_index = offset / 8;
    if (!directory_valid_[line_index] || context.domain_cycle < directory_ready_[line_index]) break;
    const auto value = directory_[offset];
    const auto begin = std::size_t(value >> 32), end = std::size_t(std::uint32_t(value));
    check(begin % 16 == 0 && end % 16 == 0 && begin <= consumed_ && end >= consumed_ &&
        end <= total_, "candidate noncontiguous directory");
    if (begin == end) { ++next_source_; ++skipped_; continue; }
    check(segment_ * 16 == consumed_ && consumed_ < end, "candidate source/segment mismatch");
    const auto& line = banks_[segment_ % 2][(segment_ / 2) % 256];
    if (pipeline_.size() < 2 && line.ready) {
      join_ = TimedSegment{Segment{static_cast<std::uint32_t>(next_source_), line.words,
                                  consumed_ + 16 == total_}, context.domain_cycle + 2};
      if (consumed_ + 16 == end) ++next_source_;
    }
    break;
  }
  if (!join_ && !skipped_) ++stats_.selector_wait;
}

inline void Reader::evaluate(const CycleContext& context) {
  issue_.reset(); response_.reset(); beat_.reset(); join_.reset();
  retired_ = advance_tile_ = false;
  skipped_ = 0;
  next_source_ = source_;
  if (done()) return;
  if (const auto* front = memory_.responses().front()) {
    check(pending_.contains(front->transaction_id), "candidate unknown acknowledgement");
    if (context.domain_cycle >= pending_.at(front->transaction_id).ready) {
      AxiResponse response;
      if (memory_.responses().try_pop(response)) response_ = std::move(response);
    }
  }
  if (const auto* front = memory_.read_beats().front()) {
    check(pending_.contains(front->transaction_id), "candidate unknown beat");
    if (context.domain_cycle >= pending_.at(front->transaction_id).ready) {
      AxiReadBeatResponse beat;
      if (memory_.read_beats().try_pop(beat)) beat_ = std::move(beat);
    }
  }
  prepare_request(context);
  if (!pipeline_.empty() && pipeline_.front().ready <= context.domain_cycle) {
    retired_ = output_.try_push(pipeline_.front().value);
    if (!retired_) ++stats_.output_stalls;
  }
  prepare_join(context);
}

inline void Reader::commit(const CycleContext& context) {
  if (response_) {
    auto& request = pending_.at(response_->transaction_id);
    check(response_->success && response_->operation == MemoryOperation::kRead &&
        response_->read_data.size() == request.count * 64 && !request.acknowledged,
        "candidate acknowledgement mismatch");
    request.acknowledged = true;
    ++stats_.responses;
  }
  if (beat_) accept_beat(*beat_, context.domain_cycle);
  for (auto it = pending_.begin(); it != pending_.end();) {
    if (it->second.acknowledged && it->second.received == it->second.count) it = pending_.erase(it);
    else ++it;
  }
  if (issue_) {
    pending_.emplace(issue_->id, *issue_);
    ++next_id_; ++stats_.requests;
    stats_.bytes += issue_->count * 64;
    if (issue_->kind == Kind::kDirectory) dir_issued_ += issue_->count;
    if (issue_->kind == Kind::kPma) {
      for (std::size_t i = 0; i < issue_->count; ++i) {
        auto& line = banks_[issue_->parity][(issue_->first + i) % 256];
        check(!line.reserved && !line.ready, "candidate overwrote reserved bank data");
        line.reserved = true;
      }
      issued_[issue_->parity] += issue_->count;
    }
    preference_ = issue_->kind == Kind::kDirectory ? 1 :
        (issue_->kind == Kind::kPma ? (issue_->parity + 2) % 3 : 0);
  }
  if (retired_) pipeline_.pop_front();
  if (join_) {
    auto& line = banks_[segment_ % 2][(segment_ / 2) % 256];
    line.reserved = line.ready = false;
    ++released_[segment_ % 2]; ++segment_; consumed_ += 16; ++stats_.segments;
    pipeline_.push_back(*join_);
  }
  stats_.rows += next_source_ - source_;
  stats_.empty_rows += skipped_;
  source_ = next_source_;
  if (advance_tile_) {
    tile_base_ += 1024;
    dir_issued_ = 0;
    directory_valid_.fill(false);
  }
  stats_.max_parents = std::max(stats_.max_parents, pending_.size());
  stats_.max_pipeline = std::max(stats_.max_pipeline, pipeline_.size());
  for (unsigned parity = 0; parity < 2; ++parity) {
    const auto occupied = issued_[parity] - released_[parity];
    check(occupied <= 256, "candidate bank ring reservation exceeded");
    stats_.max_bank_lines = std::max(stats_.max_bank_lines, occupied);
  }
}
}  // namespace evaluation_impact::prefetch_compact
