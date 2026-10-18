#pragma once

#include "preparation.hpp"
#include <bit>
#include <cfenv>
#include <cmath>

#ifdef __FAST_MATH__
#error "The matched binary32 model cannot use fast-math"
#endif

namespace original_r_k4 {
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559 &&
              std::numeric_limits<float>::digits == 24);
using Binding = rb::Binding;
inline constexpr float damping = 108.0F / 128.0F;
inline constexpr float base = 0.0F, dangling_share = 0.0F;

inline float rounded(float value) { volatile float stored = value; return stored; }
inline std::uint32_t bits(float value) { return std::bit_cast<std::uint32_t>(value); }
inline float number(std::uint32_t value) { return std::bit_cast<float>(value); }
inline float exact_float(std::uint32_t value) {
  const auto result = rounded(static_cast<float>(value));
  require(static_cast<double>(result) == static_cast<double>(value), "inexact binary32 input conversion");
  return result;
}

inline float payload(std::uint32_t gathered, std::uint32_t divisor) {
  require(gathered <= (1u << 24), "inexact/order-dependent binary32 gather domain");
  (void)rb::apply(gathered, divisor);
  const auto rank = exact_float(gathered);
  return divisor ? rounded(rounded(damping * rank) / exact_float(divisor)) : 0.0F;
}

struct Model {
  rb::Model original;
  Preparation preparation;
  std::vector<Buffer> state;
  Words gathered_external, payload_external, fixed_external;
  std::array<unsigned, 4> worker_partitions{};

  const Buffer& buffer(const std::string& name) const {
    const auto found = std::find_if(state.begin(), state.end(), [&](const Buffer& value) { return value.name == name; });
    require(found != state.end(), "missing model state buffer");
    return *found;
  }

  // Decode the actual production-packed ports, not the CSR or builder edge list.
  Words gather_packed() const {
    Words result(original.aligned, bits(0.0F));
    const auto& source = buffer("source_a0").initial;
    for (std::size_t partition = 0; partition < preparation.graph.shards.size(); ++partition) {
      const auto& shard = preparation.graph.shards[partition];
      const auto& rows = preparation.buffer(partition, "row").initial;
      for (std::size_t src = 0; src < original.vertices; ++src) {
        const std::size_t begin = rows[2 * src + 1], end = rows[2 * src];
        require(begin <= end && end <= shard.initial_pma_words.size(), "packed row bounds corrupted");
        for (auto slot = begin; slot < end; ++slot) {
          const auto segment = slot / 16, local_segment = segment / 2;
          const auto port = 2 * (segment % 2) + (local_segment >= cache_segments ? 1 : 0);
          const auto word = preparation.buffer(partition, "pma" + std::to_string(port)).initial.at(
              local_segment * 16 + slot % 16);
          if (word == prod::kWeightedPmaEmpty) continue;
          require(!(word & prod::kWeightedPmaEmpty) && prod::decode_weighted_pma_weight(word) == 1 &&
                  prod::decode_weighted_pma_destination(word) < shard.destination_vertices, "bad packed PMA edge");
          const auto dst = shard.destination_base + prod::decode_weighted_pma_destination(word);
          result[dst] = bits(rounded(number(result[dst]) + number(source[src])));
        }
      }
    }
    return result;
  }

  static Model load(const std::filesystem::path& directory, Binding selected) {
    require(std::fegetround() == FE_TONEAREST, "binary32 round-to-nearest environment required");
    require(selected == Binding::author_initial || selected == Binding::csr_degree, "explicit divisor binding required");
    Model result;
    result.original = rb::Model::load(directory, "a4", selected);
    const auto& original = result.original;
    const auto csr = Csr::load(directory, original);
    const auto edges = csr.edges(original);
    const auto gathered = csr.gather(original);
    const auto& divisors = selected == Binding::author_initial ? original.initial : original.degrees;
    result.gathered_external.resize(original.vertices);
    result.payload_external.resize(original.vertices);
    result.fixed_external.resize(original.vertices);
    for (std::size_t vertex = 0; vertex < original.vertices; ++vertex) {
      (void)exact_float(original.initial[vertex]);
      result.payload_external[vertex] = bits(payload(gathered[vertex], divisors[vertex]));
      result.gathered_external[vertex] = bits(exact_float(gathered[vertex]));
      result.fixed_external[vertex] = rb::apply(gathered[vertex], divisors[vertex]);
    }
    result.preparation = Preparation::build(original.vertices, edges, original.aligned);
    Words source(original.aligned), divisor(original.aligned), rank_target(original.aligned), next_source(original.aligned);
    for (std::size_t external = 0; external < original.vertices; ++external) {
      const auto internal = result.preparation.graph.external_to_internal[external];
      source[internal] = bits(exact_float(original.initial[external]));
      divisor[internal] = divisors[external];
      rank_target[internal] = result.gathered_external[external];
      next_source[internal] = result.payload_external[external];
    }
    const auto add = [&](std::string name, std::size_t bank, Words initial, Words target = {}) {
      const auto bytes = initial.size() * 4;
      auto value = make_buffer(std::move(name), no_shard, bank, std::move(initial), bytes);
      if (!target.empty()) {
        require(target.size() == value.logical_words, "state target extent mismatch");
        target.resize(value.allocated_words + rb::guard_words, rb::guard);
        value.expected = std::move(target);
      }
      result.state.push_back(std::move(value));
    };
    add("source_a0", 23, source);
    add("source_a1", 24, std::move(source));
    add("source_b0", 23, Words(original.aligned, rb::guard), next_source);
    add("source_b1", 24, Words(original.aligned, rb::guard), std::move(next_source));
    add("rank", 25, Words(original.aligned, bits(0.0F)), rank_target);
    add("divisor", 27, std::move(divisor));
    // Match the unchanged apply's 16-lane, eight-bank statistics reduction order.
    std::array<std::array<float, 8>, 16> error{}, dangling{};
    for (std::size_t internal = 0; internal < original.vertices; ++internal) {
      const auto lane = internal % 16, bank = (internal / 16) % 8;
      const auto rank = number(rank_target[internal]);
      error[lane][bank] = rounded(error[lane][bank] + std::fabs(rank));
      if (result.buffer("divisor").initial[internal] == 0)
        dangling[lane][bank] = rounded(dangling[lane][bank] + rank);
    }
    float error_sum = 0, dangling_sum = 0;
    for (std::size_t lane = 0; lane < 16; ++lane) for (std::size_t bank = 0; bank < 8; ++bank) {
      error_sum = rounded(error_sum + error[lane][bank]);
      dangling_sum = rounded(dangling_sum + dangling[lane][bank]);
    }
    Words stats(16, rb::guard);
    stats[0] = 0; stats[1] = original.vertices; stats[2] = bits(error_sum);
    stats[3] = bits(dangling_sum); stats[4] = original.vertices;
    add("stats", 27, Words(16, rb::guard), std::move(stats));
    for (std::size_t partition = 0; partition < result.preparation.graph.shards.size(); ++partition)
      ++result.worker_partitions[partition % 4];
    require(result.gather_packed() == rank_target, "packed PMA/CSR binary32 gather mismatch");
    return result;
  }
};
}  // namespace original_r_k4
