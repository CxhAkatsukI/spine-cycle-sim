#pragma once

#include "spine_sim/grasu_regraph.hpp"
#include "spine_sim/regraph_pma_adapter.hpp"
#include "spine_sim/routed_regraph_observation.hpp"
#include "spine_sim/routed_source_cache.hpp"

namespace spine::sim {

enum class RoutedSourceTopology {
  kFourDedicated,
  // Workers 0/2 share HBM23; workers 1/3 share HBM24.
  kTwoPairwise,
};

enum class RoutedInputPath {
  kPhysicalSlots,
  // Finite model candidate; no routed-hardware or timing-calibration claim.
  kPrefetchCompactedExperimental,
  // Two physical input masters/frontend and three slots at unchanged latency two.
  kDualPrefetchElasticExperimental,
  // Metadata, even PMA and odd PMA each own a finite physical master.
  kTriplePrefetchElasticExperimental,
};

enum class RoutedApplyTopology {
  kSharedMaster,
  // Separate read/write masters, still contending for the same HBM bank.
  kSplitMastersExperimental,
};

enum class RoutedGatherSchedule {
  kPartitionOrder,
  // Eight-row ownership, addressed publication and bounded arrival-order Apply.
  kReadyBurstsExperimental,
};

struct RoutedReGraphConfig {
  RoutedReGraphConfig();
  GraSuReGraphConfig compute;
  ReGraphPmaAdapterConfig adapter;
  std::size_t internal_fifo_depth{8};
  std::size_t external_fifo_depth{16};
  // v1/v2 retain 16; the routed v3 contract selects 32 on these three paths.
  std::size_t adapter_stream_depth{16};
  std::size_t gather_stream_depth{16};
  std::size_t mux_stream_depth{16};
  std::size_t shared_master_capacity{32};
  std::uint32_t first_initiator_id{600};
  std::uint64_t status_address{0x4800'0000ULL};
  std::size_t fixed_rounds{};
  bool independent_read_write{};
  // Preserve the earlier paired experiment's four-master XO by default.
  RoutedSourceTopology source_topology{RoutedSourceTopology::kFourDedicated};
  // Inspect, but never rewrite, the PMA/rows left by a drained G invocation.
  // State/seed initialization is still caller-prepared, outside device timing.
  bool reuse_resident_pma{};
  RoutedInputPath input_path{RoutedInputPath::kPhysicalSlots};
  // Default one; two finite tiles explicitly enable directory read lookahead.
  std::size_t experimental_directory_tiles{1};
  RoutedSourceLoading source_loading{RoutedSourceLoading::kEdgeCoupled};
  RoutedApplyTopology apply_topology{RoutedApplyTopology::kSharedMaster};
  RoutedGatherSchedule gather_schedule{RoutedGatherSchedule::kPartitionOrder};
};

struct RoutedReGraphInvocation {
  std::size_t round{}, partition{}, worker{};
  bool adapter{};
  std::uint64_t start{}, end{};
  bool operator==(const RoutedReGraphInvocation &) const = default;
};

struct RoutedReGraphRound {
  std::uint64_t start{}, apply_done{}, writeback_done{}, status_done{}, end{};
  std::size_t active_vertices{};
  bool operator==(const RoutedReGraphRound &) const = default;
};

struct RoutedReGraphCounters {
  std::uint64_t extent_reads{}, row_reads{}, segment_reads{}, packets{}, live_edges{}, dummy_edges{};
  std::uint64_t source_blocks{}, source_lines{}, source_terminators{}, gather_rows{}, mux_rows{};
  std::uint64_t apply_reads{}, apply_writes{}, source_writes{}, status_writes{};
  std::uint64_t axi_requests{}, axi_completions{}, axi_beats{}, axi_completed_beats{};
  std::uint64_t start_cycle{}, end_cycle{};
  bool operator==(const RoutedReGraphCounters &) const = default;
};

// Compute-only, with PMA and the old graph's state already resident. The caller
// advances the controller after every scheduler step. No host/DMA time is
// silently represented as device cycles. SSSP only until other routed XOs are
// separately admitted.
class RoutedReGraphSystem {
public:
  RoutedReGraphSystem(Scheduler &, ClockId, MemoryBackend &,
                     GraSuPartitionedPmaLayout, AlgorithmInitialState,
                     RoutedReGraphConfig = {});
  ~RoutedReGraphSystem();
  RoutedReGraphSystem(const RoutedReGraphSystem &) = delete;
  RoutedReGraphSystem &operator=(const RoutedReGraphSystem &) = delete;
  void register_components(bool reverse_order = false);
  void unregister_components();
  bool advance_if_complete();
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool failed() const noexcept;
  [[nodiscard]] const std::string &failure() const noexcept;
  [[nodiscard]] std::vector<std::uint32_t> distances() const;
  [[nodiscard]] std::vector<std::uint32_t> encoded_state() const;
  [[nodiscard]] std::vector<std::uint32_t> source_state(std::size_t copy, std::size_t buffer) const;
  [[nodiscard]] const GraSuReGraphRuntimePlan &runtime_plan() const noexcept;
  [[nodiscard]] const std::vector<RoutedReGraphInvocation> &invocations() const noexcept;
  [[nodiscard]] const std::vector<RoutedReGraphRound> &rounds() const noexcept;
  [[nodiscard]] RoutedReGraphCounters counters() const;
  [[nodiscard]] RoutedReGraphObservation observation() const;
  [[nodiscard]] std::string diagnostic() const;

private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace spine::sim
