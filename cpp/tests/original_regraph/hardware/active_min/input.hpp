#pragma once

#include "../model.hpp"
#include "../sssp_weighted/edge_word.hpp"

namespace original_r_board::active_min {

enum class Policy { cc, weighted_sssp };
constexpr std::uint32_t active = 0x80000000u;
constexpr std::uint32_t value_mask = active - 1;
constexpr std::uint32_t infinity = 0x7ffffffeu;

inline std::uint64_t edge_key(unsigned source, unsigned dest, unsigned weight) {
  // The author A4 descriptor admits at most 255 64K-vertex partitions.
  require(source < (1u << 24) && dest < (1u << 24) && weight < (1u << 12),
          "edge outside A4 key domain");
  return (std::uint64_t{source} << 36) | (std::uint64_t{dest} << 12) | weight;
}

inline void verify_compact_edges(const wt::Input& layout, const Words& edge_words,
                                 const Words& weights, Policy policy) {
  const bool weighted = policy == Policy::weighted_sssp;
  require(edge_words.size() == layout.edge_words.size() &&
          weights.size() == (weighted ? layout.logical_edges : 0), "invalid edge overlay extent");
  std::vector<std::uint64_t> logical, compact;
  logical.reserve(layout.logical_edges);
  compact.reserve(layout.logical_edges);
  for (unsigned source = 0; source < layout.vertices; ++source)
    for (auto i = layout.offsets[source]; i < layout.offsets[source + 1]; ++i) {
      const auto weight = weighted ? weights[i] : 0;
      require(!weighted || weight != 0, "weighted SSSP requires positive 12-bit weights");
      logical.push_back(edge_key(source, layout.destinations[i], weight));
    }
  for (const auto& task : layout.tasks) {
    unsigned previous = 0, window = 0;
    for (unsigned word = 0; word < task.words; word += 2) {
      const auto i = task.offset_words + word;
      require(edge_words[i] == layout.edge_words[i], "overlay changed author task source");
      const auto source = edge_words[i] & value_mask;
      if (word % 16 == 0) window = source / 4096;
      require(source >= previous && source / 4096 == window, "invalid author source window in burst");
      previous = source;
      const auto dest = layout.edge_words[i + 1];
      const auto packed = edge_words[i + 1];
      if (dest == 0xffffffffu || !weighted) {
        require(packed == dest, "overlay changed unweighted destination or padding");
        if (dest == 0xffffffffu) continue;
      }
      const auto weight = weighted ? a4_weighted::weight(packed) : 0;
      require(!weighted || (weight != 0 && packed == a4_weighted::pack(dest - task.destination, weight)),
              "weighted overlay destination or flags differ from author task");
      compact.push_back(edge_key(source, dest, weight));
    }
  }
  std::sort(logical.begin(), logical.end());
  std::sort(compact.begin(), compact.end());
  require(logical == compact, "task edge multiset differs from independent CSR");
}

inline Words one_round(const wt::Input& layout, const Words& state,
                       const Words& weights, Policy policy) {
  const bool weighted = policy == Policy::weighted_sssp;
  require(state.size() == layout.aligned_vertices && layout.published_vertices == layout.aligned_vertices &&
          weights.size() == (weighted ? layout.logical_edges : 0),
          "active-min control requires complete old-state publication");
  Words result = state;
  for (unsigned vertex = 0; vertex < layout.vertices; ++vertex) {
    const auto value = state[vertex] & value_mask;
    require(weighted ? value <= infinity : value < layout.vertices,
            "active-min input state outside algorithm domain");
    result[vertex] = value;
  }
  for (auto vertex = layout.vertices; vertex < layout.aligned_vertices; ++vertex)
    require(state[vertex] == 0, "nonzero active-min padded state");
  for (unsigned source = 0; source < layout.vertices; ++source) {
    const auto value = state[source] & value_mask;
    if (!(state[source] & active) || (weighted && value == infinity)) continue;
    for (auto i = layout.offsets[source]; i < layout.offsets[source + 1]; ++i) {
      const std::uint64_t candidate = std::uint64_t{value} + (weighted ? weights[i] : 0);
      if (weighted) require(candidate < infinity, "weighted candidate reaches infinity");
      auto& target = result[layout.destinations[i]];
      if (candidate < (target & value_mask)) target = static_cast<std::uint32_t>(candidate) | active;
    }
  }
  return result;
}

struct Input {
  wt::Input layout;
  Words state, expected;

  static Input load(const std::filesystem::path& directory, Policy policy) {
    const bool weighted = policy == Policy::weighted_sssp;
    for (const auto* name : {"execution.u32le", "tasks.u32le", "initial.u32le", "degrees.u32le",
                            "csr_offsets.u32le", "csr_destinations.u32le",
                            weighted ? "sssp_initial.u32le" : "cc_initial.u32le"}) {
      require(std::filesystem::is_regular_file(directory / name) &&
              !std::filesystem::is_symlink(directory / name), "regular active-min input required");
    }
    Input result;
    auto& layout = result.layout;
    layout = wt::Input::load_layout(directory);
    Words weights, overlay;
    if (weighted) {
      for (const auto* name : {"sssp_tasks.u32le", "sssp_weights.u32le"})
        require(std::filesystem::is_regular_file(directory / name) &&
                !std::filesystem::is_symlink(directory / name), "regular weighted overlay required");
      weights = wt::read_words(directory / "sssp_weights.u32le", layout.logical_edges);
      overlay = wt::read_words(directory / "sssp_tasks.u32le", layout.edge_words.size());
    }
    verify_compact_edges(layout, weighted ? overlay : layout.edge_words, weights, policy);
    if (weighted) layout.edge_words = std::move(overlay);
    result.state = wt::read_words(directory / (weighted ? "sssp_initial.u32le" : "cc_initial.u32le"),
                                 layout.aligned_vertices);
    result.expected = one_round(layout, result.state, weights, policy);
    return result;
  }
};

inline Model board_model(Input&& input) {
  Model result;
  result.little = 4;
  result.dense = input.layout.partitions;
  result.allocation = input.layout.aligned_vertices;
  result.take(std::move(input.layout));
  result.initial = std::move(input.state);
  result.expected = guarded(std::move(input.expected));
  result.validate_capacity();
  return result;
}
}  // namespace original_r_board::active_min
