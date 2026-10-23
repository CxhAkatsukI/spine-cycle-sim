#pragma once

#include <algorithm>
#include <array>
#include <deque>
#include <map>
#include <vector>
#include "spine_sim/regraph_pma_adapter.hpp"

namespace spine::sim::detail::prefetch_compact {
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
  std::uint64_t extent_beats{}, directory_beats{}, pma_beats{};
  std::uint64_t selector_wait{}, output_stalls{};
  std::uint64_t pma_requests{}, short_pma_requests{};
  std::size_t max_parents{}, max_bank_lines{}, max_pipeline{};
  std::array<std::size_t, 3> max_parents_per_port{};
};
enum class RefillPolicy { kAvailableSpace, kFullBurst };

}  // namespace spine::sim::detail::prefetch_compact
#include "directory.hpp"
namespace spine::sim::detail::prefetch_compact {

// Experimental architecture, not the routed profile: finite 1024-row banked
// directory, two finite reserved rings, <=16 parents of <=16 beats, and a
// latency-two segment pipeline. Optional physical masters separate odd PMA
// segments and directory reads; the default remains one tile/input master.
class Reader final : public Component {
public:
  Reader(ClockId clock, FixedAxiPort& memory, Fifo<Segment>& output,
         ReGraphPmaPartition partition, std::uint64_t read_delay = 71,
         FixedAxiPort* odd_memory = nullptr, RefillPolicy refill = RefillPolicy::kAvailableSpace,
         std::size_t pipeline_capacity = 2, FixedAxiPort* directory_memory = nullptr,
         std::size_t directory_tiles = 1, std::size_t bank_lines = 256)
      : Component("prefetch-reader", clock), memory_(memory), odd_memory_(odd_memory), output_(output),
        partition_(partition), delay_(read_delay), refill_(refill), pipeline_capacity_(pipeline_capacity),
        directory_memory_(directory_memory), directory_(partition.vertices, directory_tiles),
        banks_(make_banks(bank_lines)) {
    check(pipeline_capacity_ == 2 || pipeline_capacity_ == 3, "unsupported finite segment pipeline");
    check(partition.vertices && partition.slots && partition.slots % 16 == 0 &&
        partition.cache_segments_per_half && memory.read_beat_stream_enabled(),
        "invalid finite prefetch partition");
    check(!odd_memory_ || (odd_memory_ != &memory_ && odd_memory_->read_beat_stream_enabled()),
        "odd PMA port must be a distinct streaming physical master");
    check(!directory_memory_ || (odd_memory_ && directory_memory_ != &memory_ &&
        directory_memory_ != odd_memory_ && directory_memory_->read_beat_stream_enabled()),
        "directory port requires three distinct streaming physical masters");
    check(directory_tiles == 1 || directory_memory_, "directory lookahead requires its dedicated master");
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
    std::size_t port{};
    std::size_t directory_base{};
  };
  struct Line { std::array<std::uint32_t, 16> words{}; bool reserved{}, ready{}; };
  static std::array<std::vector<Line>, 2> make_banks(std::size_t lines) {
    check(lines == 256 || lines == 512, "unsupported finite PMA ring capacity");
    return {std::vector<Line>(lines), std::vector<Line>(lines)};
  }
  std::size_t bank_lines() const noexcept { return banks_[0].size(); }
  struct TimedSegment { Segment value; std::uint64_t ready{}; };
  void prepare_request(const CycleContext& context, std::size_t port);
  void prepare_join(const CycleContext& context);
  void accept_beat(const AxiReadBeatResponse& beat, std::uint64_t cycle);
  std::size_t outstanding_directory() const;
  std::size_t outstanding(std::size_t port) const;
  std::size_t port_count() const { return directory_memory_ ? 3 : odd_memory_ ? 2 : 1; }
  FixedAxiPort& memory(std::size_t port) {
    return port == 2 ? *directory_memory_ : port ? *odd_memory_ : memory_;
  }

  FixedAxiPort& memory_;
  FixedAxiPort* odd_memory_;
  Fifo<Segment>& output_;
  const ReGraphPmaPartition partition_;
  const std::uint64_t delay_;
  const RefillPolicy refill_;
  const std::size_t pipeline_capacity_;
  FixedAxiPort* directory_memory_;
  bool extent_{};
  std::size_t total_{}, consumed_{}, source_{}, segment_{};
  DirectoryTiles directory_;
  std::array<std::vector<Line>, 2> banks_;
  std::array<std::size_t, 2> issued_{}, released_{};
  std::map<std::uint64_t, Request> pending_;
  std::deque<TimedSegment> pipeline_;
  std::uint64_t next_id_{0x6d00'0000'0000'0000ULL};
  unsigned preference_{};
  std::array<std::optional<Request>, 3> issues_;
  std::array<std::optional<AxiResponse>, 3> responses_;
  std::array<std::optional<AxiReadBeatResponse>, 3> beats_;
  std::optional<TimedSegment> join_;
  std::size_t next_source_{}, skipped_{};
  bool retired_{}, advance_tile_{};
  ReaderStats stats_;
};
}  // namespace spine::sim::detail::prefetch_compact

#include "requests.hpp"
#include "join.hpp"
