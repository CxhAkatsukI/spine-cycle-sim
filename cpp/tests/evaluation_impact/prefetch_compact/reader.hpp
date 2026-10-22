#pragma once

#include <algorithm>
#include <array>
#include <deque>
#include <map>
#include "spine_sim/regraph_pma_adapter.hpp"

namespace evaluation_impact::prefetch_compact {
using namespace spine::sim;

inline void check(bool condition, const char* message) {
  if (!condition) throw std::logic_error(message);
}
inline std::uint32_t word(const std::vector<std::uint8_t>& data, std::size_t offset) {
  check(offset + 4 <= data.size(), "short candidate payload");
  std::uint32_t result = 0;
  for (unsigned i = 0; i < 4; ++i) result |= std::uint32_t{data[offset + i]} << (8 * i);
  return result;
}

struct Segment {
  std::uint32_t source{};
  std::array<std::uint32_t, 16> words{};
  bool last{};
};
struct ReaderStats {
  std::uint64_t bytes{}, requests{}, responses{}, beats{}, segments{}, rows{}, empty_rows{};
  std::uint64_t selector_wait{}, output_stalls{};
  std::size_t max_parents{}, max_bank_lines{}, max_pipeline{};
};

// Experimental architecture, not the routed profile: one 1024-row banked
// directory, two 256-line reserved rings, <=16 parents of <=16 beats, and a
// depth-two segment pipeline. Both parities may be in flight on the SAME AXI.
class Reader final : public Component {
public:
  Reader(ClockId clock, FixedAxiPort& memory, Fifo<Segment>& output,
         ReGraphPmaPartition partition, std::uint64_t read_delay = 71)
      : Component("prefetch-reader", clock), memory_(memory), output_(output),
        partition_(partition), delay_(read_delay) {
    check(partition.vertices && partition.slots && partition.slots % 16 == 0 &&
        partition.cache_segments_per_half && memory.read_beat_stream_enabled(),
        "invalid finite prefetch partition");
  }
  void evaluate(const CycleContext& context) override;
  void commit(const CycleContext& context) override;
  [[nodiscard]] bool done() const noexcept {
    return extent_ && consumed_ == total_ && pending_.empty() && pipeline_.empty();
  }
  [[nodiscard]] const ReaderStats& stats() const noexcept { return stats_; }

private:
  enum class Kind { kExtent, kDirectory, kPma };
  struct Request {
    Kind kind{};
    std::uint64_t id{}, address{}, ready{};
    std::size_t first{}, count{}, parity{}, received{};
    bool acknowledged{};
  };
  struct Line { std::array<std::uint32_t, 16> words{}; bool reserved{}, ready{}; };
  struct TimedSegment { Segment value; std::uint64_t ready{}; };
  void prepare_request(const CycleContext& context);
  void prepare_join(const CycleContext& context);
  void accept_beat(const AxiReadBeatResponse& beat, std::uint64_t cycle);
  std::size_t outstanding_directory() const;

  FixedAxiPort& memory_;
  Fifo<Segment>& output_;
  const ReGraphPmaPartition partition_;
  const std::uint64_t delay_;
  bool extent_{};
  std::size_t total_{}, consumed_{}, source_{}, segment_{}, tile_base_{}, dir_issued_{};
  std::array<std::uint64_t, 1024> directory_{};
  std::array<bool, 128> directory_valid_{};
  std::array<std::uint64_t, 128> directory_ready_{};
  std::array<std::array<Line, 256>, 2> banks_{};
  std::array<std::size_t, 2> issued_{}, released_{};
  std::map<std::uint64_t, Request> pending_;
  std::deque<TimedSegment> pipeline_;
  std::uint64_t next_id_{0x6d00'0000'0000'0000ULL};
  unsigned preference_{};
  std::optional<Request> issue_;
  std::optional<AxiResponse> response_;
  std::optional<AxiReadBeatResponse> beat_;
  std::optional<TimedSegment> join_;
  std::size_t next_source_{}, skipped_{};
  bool retired_{}, advance_tile_{};
  ReaderStats stats_;
};
}  // namespace evaluation_impact::prefetch_compact

#include "requests.hpp"
#include "join.hpp"
