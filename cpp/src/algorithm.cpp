#include "spine_sim/algorithm.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace spine::sim {

namespace {

std::uint64_t checked_add(std::uint64_t left, std::uint64_t right) {
  if (right > std::numeric_limits<std::uint64_t>::max() - left) {
    throw std::overflow_error("algorithm state layout exceeds uint64 range");
  }
  return left + right;
}

std::uint64_t align_up(std::uint64_t value, std::uint64_t alignment) {
  if (alignment == 0) {
    throw std::invalid_argument("algorithm state alignment must be positive");
  }
  const std::uint64_t remainder = value % alignment;
  return remainder == 0 ? value : checked_add(value, alignment - remainder);
}

}  // namespace

GraphAlgorithmPolicy::GraphAlgorithmPolicy(AlgorithmPolicyConfig config)
    : config_(config) {
  if (config_.vertices == 0 || config_.source >= config_.vertices ||
      !std::isfinite(config_.damping) || config_.damping <= 0.0F ||
      config_.damping >= 1.0F || !std::isfinite(config_.epsilon) ||
      config_.epsilon <= 0.0F) {
    throw std::invalid_argument("invalid graph algorithm policy configuration");
  }
}

std::string_view GraphAlgorithmPolicy::name() const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return "weighted_sssp";
    case GraphAlgorithmKind::kFullPageRank:
      return "full_pagerank";
    case GraphAlgorithmKind::kResidualPageRank:
      return "thresholded_residual_pagerank";
  }
  return "unknown";
}

AlgorithmStorageProfile GraphAlgorithmPolicy::storage_profile() const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return {.primary_state_arrays = 1};
    case GraphAlgorithmKind::kFullPageRank:
      return {
          .primary_state_arrays = 2,
          .auxiliary_state_arrays = 0,
          .degree_arrays = 1,
          .double_buffered_primary = true,
      };
    case GraphAlgorithmKind::kResidualPageRank:
      return {
          .primary_state_arrays = 1,
          .auxiliary_state_arrays = 1,
          .degree_arrays = 1,
      };
  }
  return {};
}

AlgorithmStateLayout GraphAlgorithmPolicy::state_layout(
    std::uint64_t alignment_bytes) const {
  constexpr std::uint64_t kStateWordBytes = sizeof(std::uint32_t);
  if (config_.vertices >
      std::numeric_limits<std::uint64_t>::max() / kStateWordBytes) {
    throw std::overflow_error("algorithm vertex-state array is too large");
  }
  const std::uint64_t array_bytes =
      static_cast<std::uint64_t>(config_.vertices) * kStateWordBytes;
  std::uint64_t cursor = 0;
  const auto reserve_region = [&] {
    cursor = align_up(cursor, alignment_bytes);
    const AlgorithmStateRegion region{.base = cursor, .bytes = array_bytes};
    cursor = checked_add(cursor, array_bytes);
    return region;
  };

  AlgorithmStateLayout layout{
      .primary_read = reserve_region(),
      .primary_write = {},
      .auxiliary = std::nullopt,
      .degree = std::nullopt,
      .alignment_bytes = alignment_bytes,
      .total_bytes = 0,
      .primary_ping_pong = false,
  };
  const AlgorithmStorageProfile storage = storage_profile();
  if (storage.double_buffered_primary) {
    layout.primary_write = reserve_region();
    layout.primary_ping_pong = true;
  } else {
    layout.primary_write = layout.primary_read;
  }
  if (storage.auxiliary_state_arrays != 0) {
    layout.auxiliary = reserve_region();
  }
  if (storage.degree_arrays != 0) {
    layout.degree = reserve_region();
  }
  layout.total_bytes = align_up(cursor, alignment_bytes);
  return layout;
}

AlgorithmOperationProfile
GraphAlgorithmPolicy::operation_profile() const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return {
          .integer_adds_per_edge = 1,
          .integer_compares_per_reduce = 1,
      };
    case GraphAlgorithmKind::kFullPageRank:
      return {
          .fp_adds_per_reduce = 1,
          .fp_adds_per_apply = 2,
          .fp_multiplies_per_source = 1,
          .fp_divides_per_source = 1,
      };
    case GraphAlgorithmKind::kResidualPageRank:
      return {
          .fp_adds_per_reduce = 1,
          .fp_adds_per_apply = 2,
          .fp_multiplies_per_source = 1,
          .fp_divides_per_source = 1,
          .fp_abs_compares_per_apply = 1,
      };
  }
  return {};
}

AlgorithmUpdateMode GraphAlgorithmPolicy::update_mode(
    bool has_insert_or_decrease, bool has_delete_or_increase) const noexcept {
  (void)has_insert_or_decrease;
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return has_delete_or_increase
                 ? AlgorithmUpdateMode::kFullRecomputeFallback
                 : AlgorithmUpdateMode::kIncremental;
    case GraphAlgorithmKind::kFullPageRank:
      return AlgorithmUpdateMode::kWarmStart;
    case GraphAlgorithmKind::kResidualPageRank:
      return AlgorithmUpdateMode::kSignedResidual;
  }
  return AlgorithmUpdateMode::kFullRecomputeFallback;
}

AlgorithmVertexState GraphAlgorithmPolicy::initial_state(
    std::uint32_t vertex) const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return {.primary = vertex == config_.source ? 0U : kSsspInfinity};
    case GraphAlgorithmKind::kFullPageRank:
      return {.primary = float_to_word(1.0F / config_.vertices)};
    case GraphAlgorithmKind::kResidualPageRank:
      return {
          .primary = float_to_word(0.0F),
          .auxiliary = initial_base_word(),
      };
  }
  return {};
}

AlgorithmSourceResult GraphAlgorithmPolicy::prepare_source(
    AlgorithmVertexState state, std::uint32_t out_degree) const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp:
      return {
          .edge_payload = state.primary,
          .state_after = state,
      };
    case GraphAlgorithmKind::kFullPageRank: {
      const float rank = word_to_float(state.primary);
      return {
          .edge_payload = float_to_word(
              out_degree == 0
                  ? 0.0F
                  : config_.damping * rank / static_cast<float>(out_degree)),
          .dangling_payload = float_to_word(out_degree == 0 ? rank : 0.0F),
          .state_after = state,
      };
    }
    case GraphAlgorithmKind::kResidualPageRank: {
      const float delta = word_to_float(state.auxiliary);
      AlgorithmVertexState after{
          .primary = float_to_word(word_to_float(state.primary) + delta),
          .auxiliary = float_to_word(0.0F),
      };
      return {
          .edge_payload = float_to_word(
              out_degree == 0
                  ? 0.0F
                  : config_.damping * delta / static_cast<float>(out_degree)),
          .dangling_payload = float_to_word(out_degree == 0 ? delta : 0.0F),
          .state_after = after,
          .primary_changed = delta != 0.0F,
          .auxiliary_changed = delta != 0.0F,
      };
    }
  }
  return {};
}

std::uint32_t GraphAlgorithmPolicy::map_edge(
    std::uint32_t source_payload, std::uint16_t weight) const noexcept {
  return config_.kind == GraphAlgorithmKind::kWeightedSssp
             ? saturating_weight_add(source_payload, weight)
             : source_payload;
}

std::uint32_t GraphAlgorithmPolicy::reduce(
    std::optional<std::uint32_t> current,
    std::uint32_t candidate) const noexcept {
  if (!current.has_value()) {
    return candidate;
  }
  if (config_.kind == GraphAlgorithmKind::kWeightedSssp) {
    return std::min(*current, candidate);
  }
  return float_to_word(word_to_float(*current) + word_to_float(candidate));
}

AlgorithmApplyResult GraphAlgorithmPolicy::apply(
    AlgorithmVertexState old_state, std::optional<std::uint32_t> reduced,
    AlgorithmIterationContext context) const noexcept {
  switch (config_.kind) {
    case GraphAlgorithmKind::kWeightedSssp: {
      const std::uint32_t candidate = reduced.value_or(kSsspInfinity);
      const bool active = candidate < old_state.primary;
      return {
          .state_after = {
              .primary = active ? candidate : old_state.primary,
              .auxiliary = old_state.auxiliary,
          },
          .active = active,
          .error = active ? 1.0F : 0.0F,
      };
    }
    case GraphAlgorithmKind::kFullPageRank: {
      const float base = word_to_float(context.base);
      const float dangling = word_to_float(context.dangling_share);
      const float incoming = word_to_float(reduced.value_or(float_to_word(0.0F)));
      const float value = (base + dangling) + incoming;
      return {
          .state_after = {
              .primary = float_to_word(value),
              .auxiliary = old_state.auxiliary,
          },
          .active = true,
          .error = std::fabs(value - word_to_float(old_state.primary)),
      };
    }
    case GraphAlgorithmKind::kResidualPageRank: {
      const float incoming =
          word_to_float(reduced.value_or(float_to_word(0.0F))) +
          word_to_float(context.dangling_share);
      const float residual = word_to_float(old_state.auxiliary) + incoming;
      return {
          .state_after = {
              .primary = old_state.primary,
              .auxiliary = float_to_word(residual),
          },
          .active = std::fabs(residual) >
                    word_to_float(activation_threshold_word()),
          .error = std::fabs(residual),
      };
    }
  }
  return {};
}

std::uint32_t GraphAlgorithmPolicy::initial_base_word() const noexcept {
  return float_to_word((1.0F - config_.damping) / config_.vertices);
}

std::uint32_t
GraphAlgorithmPolicy::activation_threshold_word() const noexcept {
  return float_to_word(config_.epsilon / config_.vertices);
}

std::uint32_t GraphAlgorithmPolicy::float_to_word(float value) noexcept {
  return std::bit_cast<std::uint32_t>(value);
}

float GraphAlgorithmPolicy::word_to_float(std::uint32_t word) noexcept {
  return std::bit_cast<float>(word);
}

std::uint32_t GraphAlgorithmPolicy::saturating_weight_add(
    std::uint32_t value, std::uint16_t weight) const noexcept {
  if (value == kSsspInfinity || value > kSsspInfinity - weight) {
    return kSsspInfinity;
  }
  return value + weight;
}

}  // namespace spine::sim
