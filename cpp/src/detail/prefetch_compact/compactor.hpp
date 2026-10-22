#pragma once

#include "reader.hpp"

namespace spine::sim::detail::prefetch_compact {
struct CompactorStats {
  std::uint64_t input_segments{}, live_edges{}, input_dummy{}, packets{}, output_dummy{}, output_stalls{};
  std::size_t max_lanes{}, max_pipeline{};
};

// Sixteen-lane stable selection into a 32-lane elastic queue, eight-lane output
// with a two-stage publisher. Never combine different 4096-source cache windows.
class Compactor final : public Component {
public:
  Compactor(ClockId clock, Fifo<Segment>& input, Fifo<ReGraphPmaPacket>& output,
            std::size_t destination_vertices, std::size_t pipeline_capacity = 2)
      : Component("window-compactor", clock), input_(input), output_(output),
        destinations_(destination_vertices), pipeline_capacity_(pipeline_capacity) {
    check(pipeline_capacity_ == 2 || pipeline_capacity_ == 3, "unsupported finite packet pipeline");
  }
  [[nodiscard]] bool done() const noexcept { return published_last_; }
  [[nodiscard]] const CompactorStats& stats() const noexcept { return stats_; }
  void evaluate(const CycleContext& context) override {
    input_value_.reset(); formed_.reset(); retired_ = switch_window_ = false;
    if (published_last_) return;
    if (!pipeline_.empty() && pipeline_.front().ready <= context.domain_cycle) {
      retired_ = output_.try_push(pipeline_.front().packet);
      if (!retired_) ++stats_.output_stalls;
    }
    const auto* next = input_.front();
    const bool boundary = window_ && next && next->source / 4096 != *window_;
    const bool flush = terminal_ || boundary;
    if (window_ && pipeline_.size() < pipeline_capacity_ && !closed_ &&
        (lanes_.size() > 8 || (flush && (!lanes_.empty() || !emitted_window_ || terminal_)))) {
      ReGraphPmaPacket packet;
      const auto count = std::min<std::size_t>(8, lanes_.size());
      for (unsigned lane = 0; lane < 8; ++lane) {
        packet.sources[lane] = lane < count ? lanes_[lane].first : (*window_ * 4096U | 0x8000'0000U);
        packet.destinations[lane] = lane < count ? lanes_[lane].second : 0x8000'0000U;
      }
      packet.last = terminal_ && lanes_.size() <= 8;
      formed_ = TimedPacket{packet, context.domain_cycle + 2, count};
    }
    if (boundary) {
      switch_window_ = lanes_.empty() && emitted_window_;
    } else if (!terminal_ && lanes_.size() <= 16 && next) {
      Segment value;
      if (input_.try_pop(value)) input_value_ = value;
    }
  }
  void commit(const CycleContext&) override {
    if (retired_) {
      published_last_ = pipeline_.front().packet.last;
      pipeline_.pop_front();
    }
    if (formed_) {
      for (std::size_t i = 0; i < formed_->count; ++i) lanes_.pop_front();
      stats_.output_dummy += 8 - formed_->count;
      ++stats_.packets;
      emitted_window_ = true;
      closed_ = formed_->packet.last;
      pipeline_.push_back(*formed_);
    }
    if (switch_window_) { window_.reset(); emitted_window_ = false; }
    if (input_value_) {
      check(!terminal_, "candidate input after terminal segment");
      const auto& value = *input_value_;
      if (!window_) window_ = value.source / 4096;
      check(*window_ == value.source / 4096, "candidate compactor mixed source windows");
      ++stats_.input_segments;
      for (auto data : value.words) {
        if ((data >> 31) || (data & 0x7ffffU) >= destinations_) { ++stats_.input_dummy; continue; }
        check(((data >> 19) & 0xfffU) != 0, "zero-weight live candidate edge");
        lanes_.emplace_back(value.source, data);
        ++stats_.live_edges;
      }
      terminal_ = value.last;
    }
    check(lanes_.size() <= 32 && pipeline_.size() <= pipeline_capacity_,
          "candidate compactor exceeded finite storage");
    stats_.max_lanes = std::max(stats_.max_lanes, lanes_.size());
    stats_.max_pipeline = std::max(stats_.max_pipeline, pipeline_.size());
  }
private:
  struct TimedPacket { ReGraphPmaPacket packet; std::uint64_t ready; std::size_t count; };
  Fifo<Segment>& input_;
  Fifo<ReGraphPmaPacket>& output_;
  const std::size_t destinations_;
  const std::size_t pipeline_capacity_;
  std::deque<std::pair<std::uint32_t, std::uint32_t>> lanes_;
  std::deque<TimedPacket> pipeline_;
  std::optional<std::uint32_t> window_;
  bool emitted_window_{}, terminal_{}, closed_{}, published_last_{}, retired_{}, switch_window_{};
  std::optional<Segment> input_value_;
  std::optional<TimedPacket> formed_;
  CompactorStats stats_;
};
}  // namespace spine::sim::detail::prefetch_compact
