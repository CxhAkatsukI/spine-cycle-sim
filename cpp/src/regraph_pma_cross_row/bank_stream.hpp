#pragma once

#include <deque>
#include "records.hpp"
#include "spine_sim/regraph_pma_adapter.hpp"

namespace spine::sim::detail {

// Single shared AXI reader, finite directory/bank queues, independent ordered
// metadata join. The legacy mode waits for aggregate responses; beat mode
// consumes the same physical reads progressively with finite backpressure.
class BankStreamReader {
public:
  BankStreamReader(const ReGraphPmaAdapterConfig &config, FixedAxiPort &memory,
                   Fifo<PmaLoadedSegment> &loaded, ReGraphPmaAdapterCounters &counters);
  void start(ReGraphPmaPartition partition);
  void evaluate(const CycleContext &context);
  void commit(const CycleContext &context);
  [[nodiscard]] std::size_t total_slots() const noexcept { return total_; }
  [[nodiscard]] bool closed() const noexcept { return closed_; }
  [[nodiscard]] bool empty_stream_ready() const noexcept { return extent_ready_ && !total_; }

private:
  enum class Phase { kExtent, kDirectory, kBanks, kFinished };
  struct Request {
    Phase phase;
    std::uint64_t id{}, ready{};
    std::size_t bytes{}, parity{}, count{};
    std::uint64_t address{};
    std::size_t received{};
    bool acknowledged{};
  };
  struct Joined { PmaLoadedSegment record; std::uint64_t ready; };
  void issue(Phase phase, std::uint64_t address, std::size_t channel,
             std::size_t bytes, const CycleContext &context, std::size_t parity = 0);
  void receive(const AxiResponse &response);
  void receive_beat(const AxiReadBeatResponse &beat);
  void finish_stream_read();
  [[nodiscard]] bool beat_space() const;
  void select_row();
  void next_interval();
  const ReGraphPmaAdapterConfig config_;
  FixedAxiPort &memory_;
  Fifo<PmaLoadedSegment> &loaded_;
  ReGraphPmaAdapterCounters &counters_;
  ReGraphPmaPartition partition_;
  Phase phase_{Phase::kFinished};
  bool extent_ready_{}, closed_{}, row_selected_{};
  std::size_t total_{}, loader_base_{}, loader_count_{}, loader_segment_{}, loader_last_{};
  std::size_t chunk_end_{}, parity_{}, interval_first_{}, interval_end_{};
  std::uint64_t last_directory_row_{};
  std::array<std::deque<std::vector<std::uint8_t>>, 2> banks_;
  std::deque<std::uint64_t> directory_;
  std::array<std::uint64_t, 1024> cache_{};
  std::size_t join_base_{}, join_count_{}, join_loaded_{}, source_{}, begin_{}, end_{}, segment_{};
  std::size_t consumed_slots_{};
  std::uint64_t loader_ready_{}, join_ready_{};
  std::deque<Joined> pipeline_;
  std::optional<Request> pending_, staged_issue_;
  std::optional<AxiResponse> staged_response_;
  std::optional<AxiReadBeatResponse> staged_beat_;
  std::optional<Joined> staged_join_;
  bool staged_line_{}, staged_advance_{}, staged_retire_{}, staged_terminal_{};
  std::uint64_t next_id_{0x7c00'0000'0000'0000ULL};
};
} // namespace spine::sim::detail
