#pragma once

namespace original_regraph_mixed_test {

inline void Input::validate() {
  std::vector<std::uint64_t> total(allocation_vertices);
  for (unsigned source = 0; source < vertices; ++source) {
    require(offsets[source] <= offsets[source + 1] && offsets[source + 1] <= logical_edges &&
        degrees[source] == offsets[source + 1] - offsets[source] && initial[source] <= INT32_MAX,
        "mixed CSR degree/property domain mismatch");
    for (auto edge = offsets[source]; edge < offsets[source + 1]; ++edge) {
      require(destinations[edge] < vertices && destinations[edge] < published_vertices,
              "mixed CSR destination exceeds published graph prefix");
      total[destinations[edge]] += initial[source];
    }
  }
  sums.resize(allocation_vertices); expected.resize(allocation_vertices);
  for (unsigned vertex = 0; vertex < allocation_vertices; ++vertex) {
    if (vertex >= vertices) require(initial[vertex] == 0 && degrees[vertex] == 0, "nonzero padded mixed state");
    const auto damped = total[vertex] * 108;
    const auto product = (damped >> 7) * (degrees[vertex] ? 65536 / degrees[vertex] : 0);
    require(total[vertex] <= INT32_MAX && damped <= INT32_MAX && product <= INT32_MAX,
            "mixed PR iteration exceeds source signed arithmetic domain");
    sums[vertex] = static_cast<std::uint32_t>(total[vertex]);
    expected[vertex] = static_cast<std::uint32_t>(product >> 16);
  }
  for (const auto& task : tasks) {
    std::uint32_t previous_source = 0;
    for (unsigned index = 0; index < task.words; index += 2) {
      const auto source = edge_words[task.offset_words + index] & 0x7fffffffu;
      const auto destination = edge_words[task.offset_words + index + 1];
      require(source < vertices && (index == 0 || source >= previous_source), "mixed task source outside graph or unsorted");
      if (task.kernel < 11) require((std::uint64_t{source / 4096} + 2) * 4096 <= aligned_vertices,
                                   "Little lookahead exceeds original property allocation");
      previous_source = source; ++physical_edges;
      if (destination & 0x80000000u) {
        require(destination == 0xffffffffu, "noncanonical mixed dummy"); ++dummy_edges;
      } else require(destination >= task.destination && destination - task.destination < task.destination_vertices &&
                     destination < vertices, "mixed task destination outside partition");
    }
  }
  require(physical_edges - dummy_edges == logical_edges, "mixed logical/physical edge mismatch");
}

}  // namespace original_regraph_mixed_test
