#pragma once

namespace grasu_host_control {
struct LayoutCounts { unsigned empty_segments = 0, full_segments = 0, max_occupancy = 0; };
inline LayoutCounts verify_layout(const Input& input, const pma_dynamic_graph& graph,
                                 const unsigned long* initial, const unsigned long* updates) {
  const auto n = input.vertices;
  require(graph.node_size == n && graph.node_map.size() == n && graph.row_offset.size() == n + 1, "G host layout extent");
  std::vector<unsigned> inverse(n, n), frequency(n);
  for (unsigned i = 0; i < n; ++i) {
    require(graph.node_map[i] < n && inverse[graph.node_map[i]] == n, "G host mapping permutation"); inverse[graph.node_map[i]] = i;
  }
  std::vector<std::vector<unsigned long>> rows(n);
  std::set<unsigned long> present;
  for (unsigned i = 0; i < input.initial.size(); ++i) {
    const auto edge = mapped(input.initial[i], graph.node_map);
    require(initial[i] == edge, "G mapped initial order/value"); present.insert(edge); rows[edge >> 32].push_back(edge);
  }
  for (unsigned i = 0; i < input.updates.size(); ++i) {
    const auto edge = mapped(input.updates[i], graph.node_map);
    require(updates[i] == edge, "G mapped update order/operation");
    ++frequency[(input.updates[i] & ~EMPTY) >> 32];
    if (!(edge & EMPTY)) rows[edge >> 32].push_back(edge);
  }
  std::vector<double> priority(n, -1);
  LayoutCounts counts; unsigned slot = 0, segment = 0;
  for (unsigned vertex = 0; vertex < n; ++vertex) {
    auto& row = rows[vertex]; std::sort(row.begin(), row.end()); row.erase(std::unique(row.begin(), row.end()), row.end());
    const auto reserved = (row.size() + 15) / 16;
    if (reserved) priority[inverse[vertex]] = double(frequency[inverse[vertex]]) / reserved;
    require(graph.row_offset[vertex] == slot, "G host row-offset reservation");
    for (unsigned first = 0; first < row.size(); first += 16, ++segment) {
      require(segment < graph.binary_search.size() && graph.binary_search[segment] == row[first], "G host future-union binary head");
      std::vector<unsigned long> live;
      for (unsigned i = first; i < std::min<unsigned>(first + 16, row.size()); ++i) if (present.count(row[i])) live.push_back(row[i]);
      counts.empty_segments += live.empty(); counts.full_segments += live.size() == 16;
      counts.max_occupancy = std::max(counts.max_occupancy, unsigned(live.size()));
      for (unsigned i = 0; i < 16; ++i, ++slot)
        require(slot < graph.data.size() && graph.data[slot] == (i < live.size() ? live[i] : EMPTY), "G host compacted initial PMA slot");
    }
  }
  require(graph.row_offset.back() == slot && graph.data.size() == slot && graph.binary_search.size() == segment, "G host final reservation extent");
  for (unsigned i = 1; i < n; ++i) require(priority[inverse[i - 1]] >= priority[inverse[i]], "G hotness order");
  return counts;
}
inline unsigned locate(const pma_dynamic_graph& graph, std::uint64_t edge) {
  edge &= ~EMPTY; const auto vertex = edge >> 32;
  const auto first = graph.binary_search.begin() + graph.row_offset.at(vertex) / 16;
  const auto last = graph.binary_search.begin() + graph.row_offset.at(vertex + 1) / 16;
  const auto position = std::upper_bound(first, last, edge);
  require(position != first, "G update outside reserved search row");
  return position - graph.binary_search.begin() - 1;
}
}  // namespace grasu_host_control
