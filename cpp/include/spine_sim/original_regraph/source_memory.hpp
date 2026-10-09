#pragma once

#include <optional>

#include "spine_sim/original_regraph/frontend_types.hpp"

namespace spine::sim::original_regraph {

struct SourceMemoryCounters {
  std::uint64_t rounds{};
  std::uint64_t response_lines{};
  std::uint64_t read_bytes{};
  std::uint64_t partition_terminators{};
  std::uint64_t acknowledgements{};
  std::uint64_t response_stalls{};
};

class LittleSourceMemory final : public Component {
 public:
  LittleSourceMemory(std::string name, ClockId clock, ReadPort memory,
                     Fifo<SourceRequest>& input, Fifo<SourceResponse>& output,
                     std::uint64_t property_address, std::uint64_t property_bytes);
  void begin_partitions(unsigned count, std::optional<std::uint64_t> property_address = std::nullopt);
  bool finished() const noexcept { return phase_ == Phase::kFinished; }
  const SourceMemoryCounters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

 private:
  enum class Phase { kFinished, kIdle, kRequest, kStream, kEnd };
  ReadPort memory_;
  Fifo<SourceRequest>& input_;
  Fifo<SourceResponse>& output_;
  std::uint64_t property_address_{};
  std::uint64_t property_bytes_{};
  std::uint64_t next_transaction_{1};
  std::uint64_t transaction_{};
  std::uint32_t round_{};
  std::size_t returned_{};
  unsigned partitions_{};
  unsigned completed_{};
  bool acknowledged_{};
  Phase phase_{Phase::kFinished};
  std::optional<SourceRequest> accepted_;
  bool stage_issue_{};
  bool stage_ack_{};
  bool stage_beat_{};
  bool stage_end_{};
  SourceMemoryCounters counters_;
};

}  // namespace spine::sim::original_regraph
