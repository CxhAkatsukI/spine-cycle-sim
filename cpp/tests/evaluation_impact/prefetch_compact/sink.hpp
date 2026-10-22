#pragma once

#include "compactor.hpp"

namespace evaluation_impact::prefetch_compact {
using Edge = std::array<std::uint32_t, 3>;

class Sink final : public Component {
public:
  Sink(ClockId clock, Fifo<ReGraphPmaPacket>& input, ReGraphPmaPartition partition,
       std::uint64_t period)
      : Component("compact-diagnostic-sink", clock), input_(input), partition_(partition), period_(period) {
    check(period > 0, "zero sink period");
  }
  void evaluate(const CycleContext& context) override {
    staged_.reset();
    if (context.domain_cycle % period_ == 0) {
      ReGraphPmaPacket packet;
      if (input_.try_pop(packet)) staged_ = packet;
    }
  }
  void commit(const CycleContext& context) override {
    if (!staged_) return;
    check(!finished(), "candidate packet after TLAST");
    const auto window = (staged_->sources[0] & 0x7fff'ffffU) / 4096;
    check(!last_window_ || *last_window_ <= window, "candidate source windows reordered");
    last_window_ = window;
    ++packets;
    for (unsigned lane = 0; lane < 8; ++lane) {
      const auto source = staged_->sources[lane], data = staged_->destinations[lane];
      check((source >> 31) == (data >> 31) && (source & 0x7fff'ffffU) / 4096 == window,
            "candidate packet mixes cache windows/dummy flags");
      if (source >> 31) { ++dummy; continue; }
      const auto local = data & 0x7ffffU, weight = (data >> 19) & 0xfffU;
      check(source < partition_.vertices && local < partition_.destination_vertices && weight > 0,
            "candidate emitted invalid weighted edge");
      edges.push_back({source, local + partition_.destination_base, weight});
    }
    if (staged_->last) end = context.domain_cycle + 1;
  }
  [[nodiscard]] bool finished() const noexcept { return end != 0; }
  std::vector<Edge> edges;
  std::uint64_t packets{}, dummy{}, end{};
private:
  Fifo<ReGraphPmaPacket>& input_;
  const ReGraphPmaPartition partition_;
  const std::uint64_t period_;
  std::optional<std::uint32_t> last_window_;
  std::optional<ReGraphPmaPacket> staged_;
};
}  // namespace evaluation_impact::prefetch_compact
