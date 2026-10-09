#pragma once

#include "../../original_regraph/whole_graph/input.hpp"

namespace adapter_source_control {
namespace wt = original_regraph_whole_test;
using wt::require;

struct Task {
  unsigned partition{}, subpartition{}, kernel{}, destination{}, row_offset{}, pma_offset{}, slots{}, empty_control{};
};

struct Input {
  wt::Input graph;
  std::vector<Task> tasks;
  std::vector<std::uint32_t> rows, pma;

  explicit Input(const std::filesystem::path& directory) : graph(wt::Input::load(directory)) {
    const auto header = wt::read_words(directory / "adapter.u32le", 8 + graph.tasks.size() * 8);
    require(header.size() == 8 + graph.tasks.size() * 8 && header[0] == 0x504d4131 && header[1] == 1 &&
            header[2] == graph.vertices && header[3] == graph.tasks.size() && header[4] == 131072 && header[7] == 0,
            "adapter descriptor header");
    rows = wt::read_words(directory / "rows.u32le", 128ull * 1024 * 1024);
    pma = wt::read_words(directory / "pma.u32le", 128ull * 1024 * 1024);
    require(header[5] == rows.size() && header[6] == pma.size() && rows.size() == graph.tasks.size() * graph.vertices * 2ull,
            "adapter row/PMA extent");
    std::uint64_t offset = 0;
    for (unsigned index = 0; index < graph.tasks.size(); ++index) {
      const auto base = 8 + index * 8; const auto& original = graph.tasks[index];
      Task task{header[base], header[base + 1], header[base + 2], header[base + 3],
                header[base + 4], header[base + 5], header[base + 6], header[base + 7]};
      require(task.partition == original.partition && task.subpartition == original.subpartition && task.kernel == original.kernel &&
              task.destination == original.destination && task.row_offset == index * graph.vertices * 2ull &&
              task.pma_offset == offset && task.slots && task.slots % 16 == 0 && task.empty_control <= 1,
              "adapter task assignment/geometry");
      offset += task.slots; require(offset <= pma.size(), "adapter PMA bounds");
      unsigned previous = 0; std::vector<std::uint64_t> expected, observed;
      for (unsigned edge = 0; edge < original.words; edge += 2) {
        const auto source = graph.edge_words[original.offset_words + edge] & 0x7fffffff;
        const auto destination = graph.edge_words[original.offset_words + edge + 1];
        if (!(destination >> 31)) expected.push_back((std::uint64_t{source} << 32) | destination);
      }
      for (unsigned source = 0; source < graph.vertices; ++source) {
        const auto end = rows[task.row_offset + source * 2], begin = rows[task.row_offset + source * 2 + 1];
        require(begin == previous && begin <= end && end <= task.slots && begin % 16 == 0 && end % 16 == 0,
                "adapter contiguous row bounds"); previous = end;
        for (unsigned slot = begin; slot < end; ++slot) {
          const auto word = pma[task.pma_offset + slot];
          require(word == 0x80000000u || word < 65536, "adapter local destination domain");
          if (!(word >> 31)) observed.push_back((std::uint64_t{source} << 32) | (task.destination + word));
        }
      }
      require(previous == task.slots && bool(task.empty_control) == expected.empty(), "adapter row extent or empty control");
      std::sort(expected.begin(), expected.end()); std::sort(observed.begin(), observed.end());
      require(expected == observed, "adapter logical edge multiset changed");
      tasks.push_back(task);
    }
    require(offset == pma.size(), "adapter trailing PMA words");
  }
};

}  // namespace adapter_source_control
