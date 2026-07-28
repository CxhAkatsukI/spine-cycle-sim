#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string_view>
#include <vector>

namespace spine::sim {

enum class GraphAlgorithmKind {
  kWeightedSssp,
  kFullPageRank,
  kResidualPageRank,
  kConnectedComponents,
};

enum class AlgorithmUpdateMode {
  kIncremental,
  kFullRecomputeFallback,
  kWarmStart,
  kSignedResidual,
};

enum class ResidualPageRankContract {
  kGenericDanglingL1Cold,
  kDeltaHlsSinkFreeLinfWarm,
};

struct AlgorithmPolicyConfig {
  GraphAlgorithmKind kind{GraphAlgorithmKind::kWeightedSssp};
  std::size_t vertices{};
  std::uint32_t source{};
  float damping{0.85F};
  float epsilon{1.0e-6F};
  ResidualPageRankContract residual_contract{
      ResidualPageRankContract::kGenericDanglingL1Cold};
};

struct AlgorithmStorageProfile {
  std::size_t primary_state_arrays{};
  std::size_t auxiliary_state_arrays{};
  std::size_t degree_arrays{};
  bool double_buffered_primary{};
};

struct AlgorithmStateRegion {
  std::uint64_t base{};
  std::uint64_t bytes{};
};

struct AlgorithmStateLayout {
  AlgorithmStateRegion primary_read;
  AlgorithmStateRegion primary_write;
  std::optional<AlgorithmStateRegion> auxiliary;
  std::optional<AlgorithmStateRegion> degree;
  std::uint64_t alignment_bytes{};
  std::uint64_t total_bytes{};
  bool primary_ping_pong{};
};

struct AlgorithmOperationProfile {
  std::size_t integer_adds_per_edge{};
  std::size_t integer_compares_per_reduce{};
  std::size_t fp_adds_per_reduce{};
  std::size_t fp_adds_per_apply{};
  std::size_t fp_multiplies_per_source{};
  std::size_t fp_divides_per_source{};
  std::size_t fp_abs_compares_per_apply{};
  std::size_t source_map_ii{1};
  std::size_t edge_map_ii{1};
  std::size_t reduce_ii{1};
  std::size_t apply_ii{1};
  bool timing_characterized{};
};

struct AlgorithmVertexState {
  std::uint32_t primary{};
  std::uint32_t auxiliary{};
};

struct AlgorithmInitialState {
  std::vector<std::uint32_t> primary;
  std::vector<std::uint32_t> auxiliary;
  std::vector<std::uint32_t> active_vertices;
};

struct AlgorithmSourceResult {
  std::uint32_t edge_payload{};
  std::uint32_t dangling_payload{};
  AlgorithmVertexState state_after;
  bool primary_changed{};
  bool auxiliary_changed{};
};

struct AlgorithmIterationContext {
  std::uint32_t base{};
  std::uint32_t dangling_share{};
};

struct AlgorithmApplyResult {
  AlgorithmVertexState state_after;
  bool active{};
  float error{};
};

class GraphAlgorithmPolicy {
 public:
  static constexpr std::uint32_t kSsspInfinity = 0xffffffffU;

  explicit GraphAlgorithmPolicy(AlgorithmPolicyConfig config);

  [[nodiscard]] const AlgorithmPolicyConfig &config() const noexcept {
    return config_;
  }
  [[nodiscard]] std::string_view name() const noexcept;
  [[nodiscard]] AlgorithmStorageProfile storage_profile() const noexcept;
  [[nodiscard]] AlgorithmStateLayout state_layout(
      std::uint64_t alignment_bytes = 4096) const;
  [[nodiscard]] AlgorithmOperationProfile operation_profile() const noexcept;
  [[nodiscard]] AlgorithmUpdateMode update_mode(
      bool has_insert_or_decrease,
      bool has_delete_or_increase) const noexcept;

  [[nodiscard]] AlgorithmVertexState initial_state(
      std::uint32_t vertex) const noexcept;
  [[nodiscard]] AlgorithmSourceResult prepare_source(
      AlgorithmVertexState state, std::uint32_t out_degree) const noexcept;
  [[nodiscard]] std::uint32_t map_edge(std::uint32_t source_payload,
                                       std::uint16_t weight) const noexcept;
  [[nodiscard]] std::uint32_t reduce(
      std::optional<std::uint32_t> current,
      std::uint32_t candidate) const noexcept;
  [[nodiscard]] AlgorithmApplyResult apply(
      AlgorithmVertexState old_state,
      std::optional<std::uint32_t> reduced,
      AlgorithmIterationContext context = {}) const noexcept;

  [[nodiscard]] std::uint32_t initial_base_word() const noexcept;
  [[nodiscard]] std::uint32_t activation_threshold_word() const noexcept;
  [[nodiscard]] std::uint32_t reduction_identity_word() const noexcept;

  [[nodiscard]] static std::uint32_t float_to_word(float value) noexcept;
  [[nodiscard]] static float word_to_float(std::uint32_t word) noexcept;

 private:
  [[nodiscard]] std::uint32_t saturating_weight_add(
      std::uint32_t value, std::uint16_t weight) const noexcept;

  AlgorithmPolicyConfig config_;
};

}  // namespace spine::sim
