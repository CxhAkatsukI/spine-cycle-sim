#pragma once

namespace spine::sim::detail::prefetch_compact {
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
    if (pipeline_.size() < pipeline_capacity_ && line.ready) {
      join_ = TimedSegment{Segment{static_cast<std::uint32_t>(next_source_), line.words,
                                  consumed_ + 16 == total_}, context.domain_cycle + 2};
      if (consumed_ + 16 == end) ++next_source_;
    }
    break;
  }
  if (!join_ && !skipped_) ++stats_.selector_wait;
}

inline void Reader::evaluate(const CycleContext& context) {
  for (std::size_t port = 0; port < port_count(); ++port) {
    issues_[port].reset(); responses_[port].reset(); beats_[port].reset();
  }
  join_.reset();
  retired_ = advance_tile_ = false;
  skipped_ = 0;
  next_source_ = source_;
  if (done()) return;
  for (std::size_t port = 0; port < port_count(); ++port) {
    auto& physical = memory(port);
    if (const auto* front = physical.responses().front()) {
      check(pending_.contains(front->transaction_id) && pending_.at(front->transaction_id).port == port,
          "candidate unknown or misrouted acknowledgement");
      if (context.domain_cycle >= pending_.at(front->transaction_id).ready) {
        AxiResponse response;
        if (physical.responses().try_pop(response)) responses_[port] = std::move(response);
      }
    }
    if (const auto* front = physical.read_beats().front()) {
      check(pending_.contains(front->transaction_id) && pending_.at(front->transaction_id).port == port,
          "candidate unknown or misrouted beat");
      if (context.domain_cycle >= pending_.at(front->transaction_id).ready) {
        AxiReadBeatResponse beat;
        if (physical.read_beats().try_pop(beat)) beats_[port] = std::move(beat);
      }
    }
    prepare_request(context, port);
  }
  if (!pipeline_.empty() && pipeline_.front().ready <= context.domain_cycle) {
    retired_ = output_.try_push(pipeline_.front().value);
    if (!retired_) ++stats_.output_stalls;
  }
  prepare_join(context);
}

inline void Reader::commit(const CycleContext& context) {
  for (std::size_t port = 0; port < port_count(); ++port) {
    if (const auto& response = responses_[port]) {
      auto& request = pending_.at(response->transaction_id);
      check(response->success && response->operation == MemoryOperation::kRead &&
          response->read_data.size() == request.count * 64 && !request.acknowledged,
          "candidate acknowledgement mismatch");
      request.acknowledged = true;
      ++stats_.responses;
    }
    if (beats_[port]) accept_beat(*beats_[port], context.domain_cycle);
  }
  for (auto it = pending_.begin(); it != pending_.end();) {
    if (it->second.acknowledged && it->second.received == it->second.count) it = pending_.erase(it);
    else ++it;
  }
  for (const auto& issue : issues_) if (issue) {
    pending_.emplace(issue->id, *issue);
    next_id_ = std::max(next_id_, issue->id + 1); ++stats_.requests;
    stats_.bytes += issue->count * 64;
    if (issue->kind == Kind::kDirectory) dir_issued_ += issue->count;
    if (issue->kind == Kind::kPma) {
      ++stats_.pma_requests;
      if (issue->count < 16) ++stats_.short_pma_requests;
      for (std::size_t i = 0; i < issue->count; ++i) {
        auto& line = banks_[issue->parity][(issue->first + i) % 256];
        check(!line.reserved && !line.ready, "candidate overwrote reserved bank data");
        line.reserved = true;
      }
      issued_[issue->parity] += issue->count;
    }
    preference_ = issue->kind == Kind::kDirectory ? 1 :
        (issue->kind == Kind::kPma ? (issue->parity + 2) % 3 : 0);
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
  for (std::size_t port = 0; port < port_count(); ++port) {
    const auto parents = outstanding(port);
    check(parents <= 16, "candidate per-port parent bound exceeded");
    stats_.max_parents_per_port[port] = std::max(stats_.max_parents_per_port[port], parents);
  }
  stats_.max_pipeline = std::max(stats_.max_pipeline, pipeline_.size());
  check(pipeline_.size() <= pipeline_capacity_, "candidate segment pipeline exceeded finite storage");
  for (unsigned parity = 0; parity < 2; ++parity) {
    const auto occupied = issued_[parity] - released_[parity];
    check(occupied <= 256, "candidate bank ring reservation exceeded");
    stats_.max_bank_lines = std::max(stats_.max_bank_lines, occupied);
  }
}
}  // namespace spine::sim::detail::prefetch_compact
