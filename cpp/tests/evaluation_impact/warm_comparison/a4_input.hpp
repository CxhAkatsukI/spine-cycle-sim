#pragma once

#include <map>
#include <iostream>

#include "input.hpp"

namespace warm_comparison {
inline void capture_input(const Input& input, const std::filesystem::path& output) {
  ei::wt::write_words(output / "old_state.u32le", input.after.initial.primary);
  ei::wt::write_words(output / "expected.u32le",
      dijkstra(input.after.compact.vertices, input.after.edges, input.root));
  std::cout << "WARM_INPUT {\"vertices\":" << input.after.compact.vertices
      << ",\"old_edges\":" << input.before.size() << ",\"root\":" << input.root
      << ",\"oracle_rounds\":" << input.oracle.states.size() << ",\"updates\":[";
  for (std::size_t i = 0; i < input.updates.size(); ++i) {
    const auto& edge = input.updates[i];
    if (i) std::cout << ',';
    std::cout << '[' << edge.source << ',' << edge.destination << ',' << edge.weight << ']';
  }
  std::cout << "]}" << std::endl;
}

inline void attach_author_layout(Input& input, const std::filesystem::path& layout) {
  auto compact = ei::wt::Input::load_layout(layout);
  require(compact.vertices == input.after.compact.vertices &&
      compact.aligned_vertices == input.after.compact.aligned_vertices &&
      compact.logical_edges == input.after.edges.size(), "author layout changed graph geometry");
  const auto mapping = ei::wt::read_words(layout / "original_to_reordered.u32le", compact.vertices);
  require(mapping.size() == compact.vertices, "missing identity mapping");
  for (std::size_t v = 0; v < mapping.size(); ++v) require(mapping[v] == v, "IDs changed");
  using Key = std::pair<std::uint32_t, std::uint32_t>;
  std::map<Key, std::pair<std::uint16_t, std::size_t>> weights;
  std::multiset<Key> expected, actual;
  for (const auto& edge : input.after.edges) {
    auto [it, fresh] = weights.try_emplace({edge.source, edge.destination}, edge.weight, 0);
    require(fresh || it->second.first == edge.weight, "parallel weight ambiguity");
    ++it->second.second;
    expected.emplace(edge.source, edge.destination);
  }
  for (std::uint32_t src = 0; src < compact.vertices; ++src)
    for (auto i = compact.offsets[src]; i < compact.offsets[src + 1]; ++i)
      actual.emplace(src, compact.destinations[i]);
  require(expected == actual, "author CSR changed logical edge multiset");
  for (const auto& task : compact.tasks) for (unsigned i = 0; i < task.words; i += 2) {
    const auto source = compact.edge_words.at(task.offset_words + i) & 0x7fffffffu;
    auto& destination = compact.edge_words.at(task.offset_words + i + 1);
    if (destination == 0xffffffffu) continue;
    auto it = weights.find({source, destination});
    require(it != weights.end() && it->second.second > 0, "author task added or duplicated edge");
    --it->second.second;
    require(it->second.first > 0 && it->second.first < 4096, "weight outside common ABI");
    destination = (destination - task.destination) | (std::uint32_t{it->second.first} << 19);
  }
  for (const auto& [key, value] : weights) {
    (void)key;
    require(value.second == 0, "author task dropped edge");
  }
  compact.initial = input.after.compact.initial;
  input.after.compact = std::move(compact);
}
}  // namespace warm_comparison
