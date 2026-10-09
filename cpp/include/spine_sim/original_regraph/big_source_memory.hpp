#pragma once

#include <deque>
#include <map>
#include <memory>
#include <optional>

#include "spine_sim/original_regraph/big_frontend_types.hpp"

namespace spine::sim::original_regraph {

struct BigSourceCounters {
  std::uint64_t requests{};
  std::uint64_t responses{};
  std::uint64_t cache_hits{};
  std::uint64_t reads{};
  std::uint64_t acknowledgements{};
  std::uint64_t read_bytes{};
  std::uint64_t partition_ends{};
  std::uint64_t capacity_stalls{};
  std::uint64_t output_stalls{};
  std::size_t max_live{};
};

class BigSourceMemory final : public Component {
 public:
  BigSourceMemory(std::string name, ClockId clock, ReadPort memory,
      Fifo<CachelineRequest>& input, Fifo<CachelineResponse>& output,
      std::uint64_t property_address, std::uint64_t property_bytes, std::size_t live_capacity = 32);
  void begin_partitions(unsigned count);
  bool finished() const noexcept;
  const BigSourceCounters& counters() const noexcept { return counters_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  struct Read { std::uint64_t transaction{}; std::uint32_t line{}; PropertyLine data{}; bool ready{}; };
  struct Entry { CachelineRequest request{}; std::shared_ptr<Read> read; };
  ReadPort memory_;
  Fifo<CachelineRequest>& input_;
  Fifo<CachelineResponse>& output_;
  std::uint64_t address_;
  std::uint64_t bytes_;
  std::size_t capacity_;
  std::uint64_t next_transaction_{1};
  std::deque<Entry> entries_;
  std::map<std::uint64_t, std::shared_ptr<Read>> reads_;
  std::shared_ptr<Read> cache_;
  std::optional<Entry> accepted_;
  std::optional<AxiResponse> acknowledged_;
  bool stage_output_{};
  unsigned partitions_{};
  unsigned accepted_ends_{};
  unsigned completed_ends_{};
  BigSourceCounters counters_;
};

}  // namespace spine::sim::original_regraph
