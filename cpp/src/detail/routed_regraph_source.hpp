#pragma once

#include <map>

#include "grasu_regraph_streams.hpp"
#include "spine_sim/axi_endpoint.hpp"

namespace spine::sim::detail {

inline constexpr std::size_t kRoutedSourceVertices = 4096;
inline constexpr std::size_t kRoutedSourceLines = kRoutedSourceVertices / 16;
inline constexpr std::size_t kRoutedSourceBytes = kRoutedSourceVertices * 4;

struct RoutedSourceRegion {
  std::uint64_t base{};
  std::size_t channel{};
  std::size_t allocated_vertices{};
};

struct RoutedSourceWorker {
  Fifo<ReGraphSourceCacheRequest> *requests{};
  Fifo<ReGraphSourceCacheResponse> *responses{};
};

struct RoutedSourceCounters {
  std::array<std::uint64_t, 2> blocks{}, lines{}, terminators{};
  std::uint64_t memory_parents{}, memory_completions{}, output_stalls{}, issue_stalls{};
  std::size_t max_pending{};
  bool operator==(const RoutedSourceCounters &) const = default;
};

// One worker for the measured SSSP XO, two for the later pairwise HLS source.
// System composition, not this service, owns physical-master/channel sharing.
class RoutedSourceService final : public Component {
public:
  RoutedSourceService(std::string name, ClockId clock,
                   std::vector<RoutedSourceWorker> workers, AxiEndpoint memory,
                   std::size_t parent_capacity);
  void start_round(std::vector<RoutedSourceRegion> regions,
                   std::vector<std::size_t> invocations);
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] const RoutedSourceCounters &counters() const noexcept { return counters_; }
  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

private:
  struct Block {
    std::size_t worker{}, round{}, line{};
    std::uint64_t address{}, id{};
    bool end{}, issued{};
  };
  struct Parent { std::uint64_t address{}; bool response{}, data{}; };
  void select_request();
  void issue_block();
  void forward_line();

  std::vector<RoutedSourceWorker> workers_;
  AxiEndpoint memory_;
  std::size_t parent_capacity_;
  std::vector<RoutedSourceRegion> regions_;
  std::vector<std::size_t> expected_, completed_;
  std::map<std::uint64_t, Parent> pending_;
  std::optional<Block> block_, selected_;
  std::optional<AxiResponse> response_;
  bool prefer_second_{}, issued_{}, forwarded_{}, started_{};
  std::uint64_t next_id_{1};
  RoutedSourceCounters counters_;
};

} // namespace spine::sim::detail
