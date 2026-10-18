#pragma once

#include "buffers.hpp"
#include <weighted_pma_runtime_plan.hpp>

namespace original_r_k4 {
namespace prod = grasu::integration;
inline constexpr std::size_t partition_vertices = 65536;
inline constexpr std::size_t cache_segments = 131072;
using Edge = prod::WeightedEdgeRecord;

inline void validate_permutation(const prod::WeightedPartitionedPmaGraph& graph) {
  require(graph.external_to_internal.size() == graph.vertices &&
          graph.internal_to_external.size() == graph.vertices, "permutation extent mismatch");
  std::vector<bool> seen(graph.vertices);
  for (std::size_t external = 0; external < graph.vertices; ++external) {
    const auto internal = graph.external_to_internal[external];
    require(internal < graph.vertices && !seen[internal], "non-bijective production permutation");
    seen[internal] = true;
    require(graph.internal_to_external[internal] == external, "permutation inverse mismatch");
  }
}

inline std::vector<std::uint64_t> edge_keys(const std::vector<Edge>& edges, std::size_t vertices) {
  std::vector<std::uint64_t> result;
  result.reserve(edges.size());
  for (const auto& edge : edges) {
    require(edge.source < vertices && edge.destination < vertices && edge.weight == 1 && !edge.delete_op,
            "only static unit-weight edges admitted");
    result.push_back((std::uint64_t{edge.source} << 32) | edge.destination);
  }
  std::sort(result.begin(), result.end());
  require(std::adjacent_find(result.begin(), result.end()) == result.end(),
          "duplicate edge rejected, never deduplicated");
  return result;
}

struct Csr {
  Words offsets, destinations;

  static Csr load(const std::filesystem::path& directory, const rb::Model& original) {
    return {rb::wt::read_words(directory / "csr_offsets.u32le", std::uint64_t{original.vertices} + 1),
            rb::wt::read_words(directory / "csr_destinations.u32le", original.logical_edges)};
  }

  std::vector<Edge> edges(const rb::Model& original) const {
    require(offsets.size() == std::size_t{original.vertices} + 1 &&
            destinations.size() == original.logical_edges && offsets.front() == 0 &&
            offsets.back() == destinations.size(), "CSR extent mismatch");
    std::vector<Edge> result;
    result.reserve(destinations.size());
    for (std::uint32_t source = 0; source < original.vertices; ++source) {
      require(offsets[source] <= offsets[source + 1] && offsets[source + 1] <= destinations.size() &&
              original.degrees[source] == offsets[source + 1] - offsets[source], "bad CSR offsets or degrees");
      for (auto offset = offsets[source]; offset < offsets[source + 1]; ++offset) {
        require(destinations[offset] < original.vertices && destinations[offset] < original.published,
                "CSR destination outside admitted publication");
        result.push_back({source, destinations[offset], 1, false});
      }
    }
    const auto keys = edge_keys(result, original.vertices);
    std::vector<Edge> task_edges;
    task_edges.reserve(result.size());
    for (const auto& task : original.tasks)
      for (std::size_t index = 0; index < task.words; index += 2) {
        const auto source = original.edge_words.at(task.offset_words + index) & 0x7fffffffu;
        const auto destination = original.edge_words.at(task.offset_words + index + 1);
        if (destination != 0xffffffffu) task_edges.push_back({source, destination, 1, false});
      }
    require(edge_keys(task_edges, original.vertices) == keys, "task/CSR edge identity mismatch");
    return result;
  }

  Words gather(const rb::Model& original) const {
    std::vector<std::uint64_t> totals(original.allocation);
    for (std::uint32_t source = 0; source < original.vertices; ++source)
      for (auto offset = offsets.at(source); offset < offsets.at(source + 1); ++offset)
        totals.at(destinations.at(offset)) += original.initial.at(source);
    Words result(totals.size());
    for (std::size_t vertex = 0; vertex < totals.size(); ++vertex) {
      require(totals[vertex] <= INT32_MAX, "CSR gather exceeds original signed domain");
      result[vertex] = static_cast<std::uint32_t>(totals[vertex]);
    }
    require(result == original.sums, "independent CSR gather mismatch");
    return result;
  }
};

inline void validate_static_graph(const prod::WeightedPartitionedPmaGraph& graph,
                                  const std::vector<Edge>& external) {
  validate_permutation(graph);
  require(graph.partition_vertices == partition_vertices && graph.vertices &&
          graph.shards.size() == (graph.vertices + partition_vertices - 1) / partition_vertices &&
          graph.physical_internal.empty(), "static production graph geometry mismatch");
  std::vector<Edge> mapped;
  mapped.reserve(external.size());
  for (const auto& edge : external) mapped.push_back({graph.external_to_internal.at(edge.source),
      graph.external_to_internal.at(edge.destination), edge.weight, edge.delete_op});
  const auto expected = edge_keys(mapped, graph.vertices);
  require(edge_keys(graph.initial_internal, graph.vertices) == expected &&
          edge_keys(graph.final_internal, graph.vertices) == expected,
          "global PMA edge conservation failed");
  std::vector<Edge> decoded;
  decoded.reserve(external.size());
  for (std::size_t partition = 0; partition < graph.shards.size(); ++partition) {
    const auto& shard = graph.shards[partition];
    require(shard.source_vertices == graph.vertices &&
            shard.destination_base == partition * partition_vertices &&
            shard.destination_vertices == std::min(partition_vertices, graph.vertices - shard.destination_base) &&
            shard.physical_updates.empty() && shard.row_bounds.size() == graph.vertices + 1 &&
            !shard.initial_pma_words.empty() && shard.initial_pma_words.size() % 16 == 0 &&
            shard.binary_heads.size() == shard.initial_pma_words.size() / 16,
            "PMA shard geometry mismatch");
    std::vector<Edge> shard_edges;
    std::size_t previous_end = 0;
    for (std::uint32_t source = 0; source < graph.vertices; ++source) {
      const auto bounds = shard.row_bounds[source];
      const std::size_t begin = bounds >> 32, end = static_cast<std::uint32_t>(bounds);
      require(begin == previous_end && begin <= end && end <= shard.initial_pma_words.size() &&
              begin % 16 == 0 && end % 16 == 0, "bad PMA row bounds");
      previous_end = end;
      for (auto slot = begin; slot < end; slot += 16) {
        const auto first = shard.initial_pma_words[slot];
        const auto head = first == prod::kWeightedPmaEmpty ? 0 : (std::uint64_t{source} << 32) | first;
        require(shard.binary_heads[slot / 16] == head, "PMA binary head mismatch");
        std::uint32_t previous = 0;
        for (auto index = slot; index < slot + 16; ++index) {
          const auto word = shard.initial_pma_words[index];
          require(index == slot || previous <= word, "PMA segment is not sorted");
          previous = word;
          if (word == prod::kWeightedPmaEmpty) continue;
          require(!(word & prod::kWeightedPmaEmpty) && prod::decode_weighted_pma_weight(word) == 1 &&
                  prod::decode_weighted_pma_destination(word) < shard.destination_vertices,
                  "bad PMA sentinel, weight or local destination");
          shard_edges.push_back({source, shard.destination_base + prod::decode_weighted_pma_destination(word), 1, false});
        }
      }
    }
    require(previous_end == shard.initial_pma_words.size() &&
            shard.row_bounds.back() == ((std::uint64_t{previous_end} << 32) | previous_end),
            "PMA terminal row mismatch");
    const auto shard_keys = edge_keys(shard_edges, graph.vertices);
    require(edge_keys(shard.initial_internal, graph.vertices) == shard_keys &&
            edge_keys(shard.final_internal, graph.vertices) == shard_keys, "shard PMA edge conservation failed");
    decoded.insert(decoded.end(), shard_edges.begin(), shard_edges.end());
  }
  require(edge_keys(decoded, graph.vertices) == expected, "decoded PMA edge conservation failed");
}

struct Preparation {
  prod::WeightedPartitionedPmaGraph graph;
  prod::WeightedPmaRuntimePlan plan;
  BankLedger ledger;
  std::vector<Buffer> buffers;

  static Preparation build(std::size_t vertices, const std::vector<Edge>& edges, std::size_t capacity) {
    (void)edge_keys(edges, vertices);
    require(capacity == (vertices + partition_vertices - 1) / partition_vertices * partition_vertices,
            "K4 capacity must cover every full destination partition");
    Preparation result;
    result.graph = prod::build_weighted_partitioned_pma_graph(vertices, partition_vertices, edges, {});
    validate_static_graph(result.graph, edges);
    result.plan = prod::build_weighted_pma_runtime_plan(result.graph, cache_segments, 23, bank_bytes,
        prod::WeightedPmaChannelPolicy::lane_aware_u55c, true);
    for (const auto& region : result.plan.regions)
      result.ledger.admit(region.channel, region.allocated_bytes + rb::guard_words * 4);
    for (const auto bank : {23, 24, 23, 24, 25, 27})
      result.ledger.admit(bank, (capacity + rb::guard_words) * 4ull);
    result.ledger.admit(27, (16 + rb::guard_words) * 4ull);
    auto packed = prod::pack_weighted_pma_runtime_buffers(result.graph, result.plan);
    for (std::size_t index = 0; index < packed.size(); ++index) {
      auto& shard = packed[index];
      const auto add = [&](std::string name, Words words) {
        const auto& region = prod::find_weighted_pma_region(result.plan, index, name);
        require(words.size() * 4 == region.logical_bytes, "packed region extent mismatch");
        result.buffers.push_back(make_buffer(std::move(name), index, region.channel,
                                           std::move(words), region.allocated_bytes));
      };
      for (std::size_t lane = 0; lane < 4; ++lane) {
        add("update" + std::to_string(lane), split_words(shard.updates[lane]));
        add("pma" + std::to_string(lane), std::move(shard.pma_words[lane]));
      }
      add("row", split_words(shard.row_bounds));
      add("binary", split_words(shard.binary_heads));
    }
    result.validate_buffers();
    return result;
  }

  const Buffer& buffer(std::size_t shard, const std::string& name) const {
    const auto found = std::find_if(buffers.begin(), buffers.end(), [&](const Buffer& candidate) {
      return candidate.shard == shard && candidate.name == name;
    });
    require(found != buffers.end(), "missing prepared buffer");
    return *found;
  }

  void validate_buffers() const {
    require(buffers.size() == plan.regions.size(), "prepared region count mismatch");
    for (const auto& region : plan.regions) {
      const auto& value = buffer(region.shard, region.name);
      require(value.bank == region.channel && value.logical_words * 4 == region.logical_bytes &&
              value.allocated_words * 4 == region.allocated_bytes && value.expected.empty() &&
              value.initial.size() == value.allocated_words + rb::guard_words,
              "prepared buffer metadata mismatch");
      for (auto index = value.logical_words; index < value.initial.size(); ++index)
        require(value.initial[index] == rb::guard, "allocation slack or trailing guard corrupted");
    }
    for (std::size_t partition = 0; partition < graph.shards.size(); ++partition) {
      const auto& shard = graph.shards[partition];
      for (std::size_t lane = 0; lane < 4; ++lane) {
        const auto& updates = buffer(partition, "update" + std::to_string(lane));
        for (std::size_t index = 0; index < updates.logical_words; ++index)
          require(updates.initial[index] == 0, "nonempty update buffer");
        const auto& pma = buffer(partition, "pma" + std::to_string(lane));
        for (std::size_t index = 0; index < pma.logical_words; ++index) {
          const auto local_segment = index / 16;
          const auto slot = (2 * local_segment + lane / 2) * 16 + index % 16;
          const bool selected = (local_segment < cache_segments) == (lane % 2 == 0);
          const auto expected = selected && slot < shard.initial_pma_words.size()
                                    ? shard.initial_pma_words[slot] : prod::kWeightedPmaEmpty;
          require(pma.initial[index] == expected, "packed PMA slot conservation failed");
        }
      }
      for (const auto* name : {"row", "binary"}) {
        const auto& value = buffer(partition, name);
        const auto& values = std::string_view(name) == "row" ? shard.row_bounds : shard.binary_heads;
        for (std::size_t index = 0; index < value.logical_words; ++index) {
          const auto expected = index / 2 < values.size()
              ? static_cast<std::uint32_t>(values[index / 2] >> (index % 2 * 32)) : 0;
          require(value.initial[index] == expected, "packed row-line or binary metadata mismatch");
        }
      }
    }
  }
};
}  // namespace original_r_k4
