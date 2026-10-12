#pragma once

#include <deque>

#include "spine_sim/regraph_pma_adapter.hpp"
#include "directory_tile.hpp"
#include "bank_stream.hpp"
#include "records.hpp"

namespace spine::sim::detail {

// Owns the default-off two-process adapter; legacy state is never consulted.
class CrossRowPmaAdapter {
public:
  CrossRowPmaAdapter(ClockId clock, const ReGraphPmaAdapterConfig &config,
                    FixedAxiPort &memory, Fifo<ReGraphPmaPacket> &output,
                    ReGraphPmaAdapterCounters &counters, bool &stream_complete);
  void start(ReGraphPmaPartition partition);
  [[nodiscard]] bool done() const noexcept;
  void evaluate(const CycleContext &context);
  void commit(const CycleContext &context);

private:
  enum class Phase { kIdle, kExtent, kWaitExtent, kDirectory, kWaitDirectory,
                     kScan, kDrain, kTerminal, kReaderDone, kDone };
  enum class Kind { kExtent, kDirectory, kSegment };
  using Task = PmaSegmentTask;
  using Loaded = PmaLoadedSegment;
  struct Pending {
    Kind kind;
    Task task;
    std::uint64_t ready_cycle;
  };
  struct Inflight {
    std::uint64_t id;
    Task task;
  };
  bool issue(Kind kind, Task task, std::uint64_t address, std::size_t channel,
             const CycleContext &context, std::size_t bytes = 64);
  void receive(const AxiResponse &response);
  void begin_row();
  void finish_block(const CycleContext &context);
  ReGraphPmaPacket packet() const;
  void evaluate_packet_pipeline(const CycleContext &context);
  void commit_packet_pipeline(const CycleContext &context);

  const ReGraphPmaAdapterConfig config_;
  FixedAxiPort &memory_;
  Fifo<ReGraphPmaPacket> &output_;
  ReGraphPmaAdapterCounters &counters_;
  bool &stream_complete_;
  Fifo<Loaded> loaded_;
  std::unique_ptr<BankStreamReader> bank_reader_;
  ReGraphPmaPartition partition_;
  Phase phase_{Phase::kIdle};
  std::array<std::uint64_t, 8> rows_{};
  std::unique_ptr<PmaDirectoryTile> tile_;
  std::size_t block_{}, block_count_{}, source_{}, begin_{}, end_{}, segment_{};
  std::size_t total_slots_{}, issued_slots_{}, emitted_slots_{};
  std::map<std::uint64_t, Pending> pending_;
  std::deque<Inflight> inflight_;
  std::map<std::uint64_t, std::vector<std::uint8_t>> returned_;
  std::optional<Loaded> publishing_;
  unsigned half_{};
  std::uint64_t publish_ready_{}, drain_until_{};
  std::uint64_t directory_ready_{};
  struct PendingPacket { ReGraphPmaPacket value; std::uint64_t ready; };
  std::deque<PendingPacket> packet_pipeline_;
  std::optional<PendingPacket> staged_formed_;
  std::size_t formed_slots_{};
  bool publisher_closed_{};
  std::uint64_t next_id_{0x7b00'0000'0000'0000ULL};

  std::optional<Pending> staged_issue_;
  std::optional<AxiResponse> staged_response_;
  std::optional<Loaded> staged_loaded_;
  std::optional<ReGraphPmaPacket> staged_packet_;
  bool staged_transfer_{}, staged_terminal_{}, staged_advance_{}, staged_stall_{};
};

} // namespace spine::sim::detail
