#pragma once

#include <optional>
#include <vector>

#include "spine_sim/original_regraph/big_frontend_types.hpp"

namespace spine::sim::original_regraph {

class BigEdgeFork final : public Component {
 public:
  BigEdgeFork(std::string name, ClockId clock, Fifo<EdgeBurst>& input,
              Fifo<EdgeBurst>& scatter, Fifo<EdgeBurst>& source);
  void begin_partition(std::uint64_t bursts);
  bool finished() const noexcept { return remaining_ == 0; }
  std::uint64_t output_stalls() const noexcept { return output_stalls_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<EdgeBurst>& input_;
  Fifo<EdgeBurst>& scatter_;
  Fifo<EdgeBurst>& source_;
  std::uint64_t remaining_{};
  std::uint64_t output_stalls_{};
  bool accepted_{};
};

class BigRequestGenerator final : public Component {
 public:
  BigRequestGenerator(std::string name, ClockId clock, Fifo<EdgeBurst>& input,
                      Fifo<CachelineBatch>& output);
  void begin_partition(std::uint64_t bursts);
  bool finished() const noexcept { return end_sent_; }
  std::uint64_t bursts() const noexcept { return bursts_; }
  std::uint64_t output_stalls() const noexcept { return output_stalls_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<EdgeBurst>& input_;
  Fifo<CachelineBatch>& output_;
  std::uint64_t remaining_{};
  std::uint64_t bursts_{};
  std::uint64_t output_stalls_{};
  std::uint32_t previous_source_{};
  std::uint32_t previous_line_{};
  std::optional<EdgeBurst> accepted_;
  bool end_sent_{true};
  bool stage_end_{};
};

class BigCachelineSender final : public Component {
 public:
  BigCachelineSender(std::string name, ClockId clock, Fifo<CachelineBatch>& input,
                    Fifo<CachelineRequest>& output, std::size_t trace_limit = 0);
  void begin_partition();
  bool finished() const noexcept { return finished_; }
  const std::vector<CachelineRequest>& trace() const noexcept { return trace_; }
  std::uint64_t trace_dropped() const noexcept { return trace_dropped_; }
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;
 private:
  Fifo<CachelineBatch>& input_;
  Fifo<CachelineRequest>& output_;
  std::optional<CachelineBatch> batch_;
  std::optional<CachelineBatch> loaded_;
  std::optional<CachelineRequest> sent_;
  unsigned lane_{};
  bool initial_{};
  bool finished_{true};
  std::size_t trace_limit_{};
  std::vector<CachelineRequest> trace_;
  std::uint64_t trace_dropped_{};
};

}  // namespace spine::sim::original_regraph
