#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include "spine_sim/component.hpp"

namespace spine::sim {

enum class MemoryOperation { kRead, kWrite };

struct BackendRequest {
  std::uint64_t request_id{};
  std::size_t channel{};
  MemoryOperation operation{MemoryOperation::kRead};
  std::uint64_t address{};
  std::uint32_t bytes{};
};

struct BackendResponse {
  std::uint64_t request_id{};
  bool success{true};
};

class MemoryBackend : public Component {
 public:
  using Component::Component;

  virtual bool try_submit(const BackendRequest& request) = 0;
  [[nodiscard]] virtual std::size_t response_count() const noexcept = 0;
  [[nodiscard]] virtual const BackendResponse& response_at(
      std::size_t index) const = 0;
  virtual bool stage_pop_responses(std::size_t count) = 0;
  [[nodiscard]] virtual std::size_t outstanding() const noexcept = 0;
};

struct MockMemoryConfig {
  std::size_t channels{};
  std::uint64_t latency_cycles{};
  std::size_t accepts_per_channel_per_cycle{};
  std::size_t max_outstanding_per_channel{};
  std::size_t response_queue_depth{};
};

struct MockMemoryStats {
  std::uint64_t accepted{};
  std::uint64_t submit_stalls{};
  std::uint64_t response_queue_stalls{};
  std::size_t max_outstanding{};
};

class MockMemoryBackend final : public MemoryBackend {
 public:
  MockMemoryBackend(std::string name, ClockId clock_id, MockMemoryConfig config);

  bool try_submit(const BackendRequest& request) override;
  [[nodiscard]] std::size_t response_count() const noexcept override;
  [[nodiscard]] const BackendResponse& response_at(
      std::size_t index) const override;
  bool stage_pop_responses(std::size_t count) override;
  [[nodiscard]] std::size_t outstanding() const noexcept override;
  [[nodiscard]] const MockMemoryStats& stats() const noexcept { return stats_; }

  void prepare(const CycleContext& context) override;
  void evaluate(const CycleContext&) override {}
  void commit(const CycleContext& context) override;

 private:
  struct Pending {
    BackendResponse response;
    std::size_t channel{};
    std::uint64_t due_cycle{};
  };

  [[nodiscard]] std::size_t channel_outstanding(std::size_t channel) const;

  MockMemoryConfig config_;
  std::deque<Pending> pending_;
  std::deque<BackendResponse> responses_;
  std::vector<BackendRequest> staged_submissions_;
  std::size_t staged_response_pops_{};
  MockMemoryStats stats_;
};

}  // namespace spine::sim
