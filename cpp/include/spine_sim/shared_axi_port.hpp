#pragma once

#include <map>
#include <optional>
#include <vector>

#include "spine_sim/axi_endpoint.hpp"

namespace spine::sim {

struct SharedAxiPortCounters {
  std::uint64_t accepted{}, completed{}, parent_responses{}, read_beats{};
  std::uint64_t capacity_stalls{}, request_stalls{}, response_stalls{}, beat_stalls{};
  std::size_t max_pending{};
  bool operator==(const SharedAxiPortCounters &) const = default;
};

// Registered round-robin client arbitration onto exactly one physical master.
// A route remains occupied until both the parent response and all streamed
// beats are forwarded. Per-client FIFOs provide finite, visible backpressure.
class SharedAxiPort final : public Component {
public:
  SharedAxiPort(std::string name, ClockId clock, FixedAxiPort &physical,
                std::vector<AxiEndpoint> clients, std::size_t capacity);
  [[nodiscard]] std::size_t pending() const noexcept { return routes_.size(); }
  [[nodiscard]] bool idle() const noexcept;
  [[nodiscard]] const SharedAxiPortCounters &counters() const noexcept { return counters_; }
  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

private:
  struct Route {
    std::size_t client{};
    std::uint64_t original_id{}, address{}, bytes{}, beat_bytes{};
    MemoryOperation operation{};
    bool stream{}, parent_done{}, beats_done{};
  };
  void stage_request();
  void stage_response();
  void stage_beat();
  void retire(std::uint64_t id);
  FixedAxiPort &physical_;
  std::vector<AxiEndpoint> clients_;
  std::size_t capacity_{}, next_client_{};
  std::uint64_t next_id_{1};
  std::map<std::uint64_t, Route> routes_;
  std::optional<Route> staged_request_;
  std::optional<std::uint64_t> staged_response_;
  std::optional<std::pair<std::uint64_t, std::size_t>> staged_beat_;
  SharedAxiPortCounters counters_;
};

} // namespace spine::sim
