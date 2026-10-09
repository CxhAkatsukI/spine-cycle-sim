#pragma once

#include <deque>
#include <optional>
#include <vector>

#include "spine_sim/original_regraph/state_types.hpp"

namespace spine::sim::original_regraph {

struct WriterCounters {
  std::uint64_t lines{};
  std::uint64_t write_requests{};
  std::uint64_t acknowledgements{};
  std::uint64_t write_bytes{};
  std::uint64_t input_terminators{};
  std::uint64_t credit_stalls{};
  std::uint64_t request_stalls{};
  std::size_t max_live_lines{};
};

class PropertyBroadcastWriter final : public Component {
 public:
  PropertyBroadcastWriter(std::string name, ClockId clock, Fifo<PropertyWrite>& input,
                           std::vector<WriteTarget> targets,
                           std::size_t line_credits = kWriterLineCredits);
  void begin(std::uint32_t lines, std::optional<std::uint64_t> property_address = std::nullopt);
  bool finished() const noexcept { return !active_; }
  const WriterCounters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  struct Pending {
    std::uint64_t transaction{};
    PropertyWrite packet;
    std::vector<std::uint8_t> payload;
    std::uint32_t issued{};
    std::uint32_t acknowledged{};
  };
  Fifo<PropertyWrite>& input_;
  std::vector<WriteTarget> targets_;
  std::size_t line_credits_{};
  std::uint32_t all_targets_{};
  std::deque<Pending> pending_;
  std::uint64_t next_transaction_{1};
  std::uint32_t expected_{};
  std::uint32_t accepted_{};
  bool active_{};
  bool input_ended_{};
  std::optional<PropertyWrite> staged_input_;
  std::optional<std::pair<std::uint64_t, std::uint32_t>> staged_issue_;
  std::vector<std::pair<std::uint64_t, std::uint32_t>> staged_acks_;
  bool stage_end_{};
  WriterCounters counters_;
};

}  // namespace spine::sim::original_regraph
