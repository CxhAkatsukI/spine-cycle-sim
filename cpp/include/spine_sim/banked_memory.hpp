#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>
#include <unordered_map>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"

namespace spine::sim {

enum class OnChipOperation { kRead, kWrite };
enum class ReadAfterWritePolicy { kStall, kBypassLatest };

struct OnChipRequest {
  std::uint64_t transaction_id{};
  OnChipOperation operation{OnChipOperation::kRead};
  std::uint64_t word_address{};
  std::uint64_t write_data{};
};

struct OnChipResponse {
  std::uint64_t transaction_id{};
  OnChipOperation operation{OnChipOperation::kRead};
  std::uint64_t read_data{};
};

struct BankedMemoryConfig {
  std::size_t banks{};
  std::uint64_t capacity_words{};
  std::size_t read_ports_per_bank{};
  std::size_t write_ports_per_bank{};
  std::uint64_t latency_cycles{};
  std::size_t max_outstanding_per_port{};
  ReadAfterWritePolicy raw_policy{ReadAfterWritePolicy::kStall};
};

struct BankedMemoryStats {
  std::uint64_t accepted_reads{};
  std::uint64_t accepted_writes{};
  std::uint64_t read_bank_conflict_stalls{};
  std::uint64_t write_bank_conflict_stalls{};
  std::uint64_t raw_hazard_stalls{};
  std::uint64_t outstanding_limit_stalls{};
  std::uint64_t response_backpressure_stalls{};
  std::size_t max_outstanding{};
};

class BankedMemory final : public Component {
 public:
  BankedMemory(std::string name, ClockId clock_id, BankedMemoryConfig config);

  std::size_t attach_port(Fifo<OnChipRequest>& requests,
                          Fifo<OnChipResponse>& responses);
  void initialize_word(std::uint64_t word_address, std::uint64_t value);
  [[nodiscard]] std::uint64_t inspect_word(std::uint64_t word_address) const;
  [[nodiscard]] const BankedMemoryStats& stats() const noexcept { return stats_; }
  [[nodiscard]] const BankedMemoryConfig& config() const noexcept {
    return config_;
  }
  [[nodiscard]] std::size_t outstanding() const noexcept;

  void evaluate(const CycleContext& context) override;
  void commit(const CycleContext&) override {}

 private:
  struct Port {
    Fifo<OnChipRequest>* requests{};
    Fifo<OnChipResponse>* responses{};
  };

  struct Completion {
    std::uint64_t due_cycle{};
    OnChipResponse response;
    std::uint64_t word_address{};
    std::uint64_t write_data{};
    bool write_applied{};
  };

  struct Candidate {
    std::size_t port{};
    std::size_t bank{};
    OnChipRequest request;
    bool raw_blocked{};
  };

  [[nodiscard]] std::size_t bank_for(std::uint64_t word_address) const;
  void validate_address(std::uint64_t word_address) const;
  [[nodiscard]] bool has_pending_write(std::uint64_t word_address) const;
  [[nodiscard]] std::uint64_t visible_word(std::uint64_t word_address) const;
  void retire_completions(const CycleContext& context);
  void accept_requests(const CycleContext& context);
  void grant(const Candidate& candidate, const CycleContext& context);

  BankedMemoryConfig config_;
  std::vector<Port> ports_;
  std::vector<std::deque<Completion>> completions_;
  std::vector<std::size_t> round_robin_start_;
  std::unordered_map<std::uint64_t, std::uint64_t> words_;
  BankedMemoryStats stats_;
};

}  // namespace spine::sim
