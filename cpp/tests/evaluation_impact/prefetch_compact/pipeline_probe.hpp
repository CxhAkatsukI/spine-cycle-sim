#pragma once

#include "sink.hpp"
#include "spine_sim/scheduler.hpp"

namespace evaluation_impact::prefetch_compact {

struct PipelineProbe {
  std::uint64_t cycles{}, packets{}, one_cycle_gaps{}, two_cycle_gaps{};
  std::size_t peak{};
  bool operator==(const PipelineProbe&) const = default;
};

// Saturated same-window input isolates publisher storage from memory latency.
inline PipelineProbe pipeline_probe(std::size_t capacity, bool reverse, std::uint64_t period) {
  class Source final : public Component {
  public:
    Source(ClockId clock, Fifo<Segment>& output) : Component("source", clock), output_(output) {}
    void evaluate(const CycleContext&) override {
      accepted_ = false;
      if (sent_ == 1024) return;
      Segment segment{.source = 7, .last = sent_ == 1023};
      segment.words.fill((3U << 19) | 1U);
      accepted_ = output_.try_push(segment);
    }
    void commit(const CycleContext&) override { if (accepted_) ++sent_; }
  private:
    Fifo<Segment>& output_;
    std::size_t sent_{};
    bool accepted_{};
  };
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  Fifo<Segment> input("segments", clock, 16);
  Fifo<ReGraphPmaPacket> output("packets", clock, 2);
  Source source(clock, input);
  Compactor compactor(clock, input, output, 16, capacity);
  Sink sink(clock, output, {.vertices = 16, .destination_vertices = 16}, period);
  std::vector<Component*> components{&input, &output, &source, &compactor, &sink};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  PipelineProbe result;
  std::uint64_t previous{}, count{};
  for (; result.cycles < 30000; ++result.cycles) {
    scheduler.step();
    if (sink.packets != count) {
      check(sink.packets == count + 1, "publisher issued multiple packets per cycle");
      if (count) {
        result.one_cycle_gaps += result.cycles - previous == 1;
        result.two_cycle_gaps += result.cycles - previous == 2;
      }
      previous = result.cycles; count = sink.packets;
    }
    if (compactor.done() && input.empty() && output.empty() && sink.finished()) {
      ++result.cycles; break;
    }
  }
  check(result.cycles < 30000 && sink.packets == 2048 && sink.dummy == 0 && sink.edges.size() == 16384,
        "publisher probe lost input, padding or terminal marker");
  for (const auto& edge : sink.edges)
    check(edge == Edge{7, 1, 3}, "publisher probe changed payload");
  const auto& stats = compactor.stats();
  check(stats.max_pipeline <= capacity && stats.max_lanes <= 32 && stats.input_segments == 1024 &&
        stats.live_edges == 16384 && stats.packets == 2048, "publisher probe finite ledger failed");
  if (period > 1) check(stats.output_stalls > 0, "publisher probe did not exercise backpressure");
  result.packets = sink.packets; result.peak = stats.max_pipeline;
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
  return result;
}

inline void check_pipeline_probes() {
  for (auto period : {1U, 5U}) {
    const auto old = pipeline_probe(2, false, period);
    const auto next = pipeline_probe(3, false, period);
    check(old == pipeline_probe(2, true, period) && next == pipeline_probe(3, true, period),
          "publisher probe depends on registration order");
    for (const auto& [capacity, result] : {std::pair{2U, old}, std::pair{3U, next}})
      std::cout << "PIPELINE_PROBE {\"capacity\":" << capacity << ",\"latency\":2,\"period\":" << period
          << ",\"cycles\":" << result.cycles << ",\"packets\":" << result.packets
          << ",\"one_cycle_gaps\":" << result.one_cycle_gaps << ",\"two_cycle_gaps\":"
          << result.two_cycle_gaps << ",\"peak\":" << result.peak << "}\n";
    if (period == 1)
      // The third slot admits work before retirement; post-commit occupancy stays two.
      check(old.two_cycle_gaps > 1000 && next.one_cycle_gaps == 2047 &&
            next.cycles * 4 < old.cycles * 3 && next.peak == 2,
            "third storage slot did not eliminate registered publisher bubbles");
  }
}
}  // namespace evaluation_impact::prefetch_compact
