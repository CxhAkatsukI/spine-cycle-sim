#pragma once

#include <deque>

#include "spine_sim/original_grasu/types.hpp"

namespace spine::sim::original_grasu {

using SearchQueues = std::array<Fifo<Update>*, kSearchLanes>;

class EdgeReader final : public Component {
 public:
  EdgeReader(std::string name, ClockId clock, StreamPort memory, SearchQueues output);
  void begin(std::uint64_t address, std::uint32_t updates);
  bool finished() const noexcept;
  const Counters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  StreamPort memory_;
  SearchQueues output_;
  std::uint64_t address_{}, transaction_{}, next_transaction_{1};
  std::uint32_t count_{}, received_{}, ends_{};
  bool started_{}, issued_{}, acknowledged_{};
  bool stage_issue_{}, stage_ack_{}, stage_beat_{}, stage_end_{};
  Counters counters_;
};

struct SearchRequest {
  unsigned lane{}, kind{};
  std::uint32_t address{};
  std::uint64_t value{};
  bool operator==(const SearchRequest&) const = default;
};

class Search final : public Component {
 public:
  Search(std::string name, ClockId clock, SearchQueues input, SearchQueues results,
         Fifo<Update>& output, std::array<Port, 8> memory, Timing timing = {});
  void begin(std::uint32_t updates, std::uint64_t binary_address, std::uint64_t row_address,
             std::uint32_t segments, std::uint32_t vertices);
  bool finished() const noexcept;
  const Counters& counters() const noexcept { return counters_; }
  const std::vector<SearchRequest>& requests() const noexcept { return trace_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  enum class Phase { kEdge, kRow, kRowWait, kBinary, kBinaryWait, kEmit, kEnd };
  struct Lane {
    Phase phase{Phase::kEdge};
    std::uint64_t edge{}, ready{};
    std::uint32_t begin{}, end{}, middle{};
  };
  struct Pending {
    unsigned lane;
    std::uint32_t address;
    std::uint64_t transaction;
    std::optional<std::uint64_t> value;
  };
  struct Response { unsigned port; Pending pending; std::uint64_t value; };
  SearchQueues input_, results_;
  Fifo<Update>& output_;
  std::array<Port, 8> memory_;
  Timing timing_;
  std::array<Lane, 64> lanes_, next_lanes_;
  std::array<std::deque<Pending>, 8> pending_;
  std::array<unsigned, 8> cursors_{};
  std::array<bool, 8> advance_{};
  std::array<std::uint16_t, 8> ended_{};
  std::vector<std::pair<unsigned, Pending>> issues_;
  std::vector<Response> responses_, retire_;
  std::vector<SearchRequest> trace_;
  std::uint64_t binary_address_{}, row_address_{}, next_transaction_{1};
  std::uint32_t count_{}, merged_{}, segments_{}, vertices_{};
  bool started_{}, stage_merge_{};
  Counters counters_;
};

}  // namespace spine::sim::original_grasu
