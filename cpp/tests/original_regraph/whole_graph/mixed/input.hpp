#pragma once

#include "../input.hpp"

namespace original_regraph_mixed_test {
namespace wt = original_regraph_whole_test;
using wt::require;
using wt::bytes;
using wt::read_words;
using wt::write_words;
using wt::Task;

struct Input {
  std::uint32_t vertices{}, logical_edges{}, aligned_vertices{}, published_vertices{}, allocation_vertices{};
  std::uint32_t dense{}, sparse{};
  std::vector<Task> tasks;
  std::vector<std::uint32_t> edge_words, initial, degrees, offsets, destinations, sums, expected;
  std::uint64_t physical_edges{}, dummy_edges{};

  static Input load(const std::filesystem::path& directory, bool allow_padding) {
    const auto descriptor = read_words(directory / "mixed.u32le", 12 + 255 * 14 * 8);
    require(descriptor.size() >= 12 && descriptor[0] == 0x4d47524fu && descriptor[1] == 1,
            "invalid mixed descriptor header");
    Input input;
    input.vertices = descriptor[2]; input.logical_edges = descriptor[3];
    input.aligned_vertices = descriptor[4]; input.published_vertices = descriptor[5];
    input.allocation_vertices = descriptor[6]; input.dense = descriptor[8]; input.sparse = descriptor[9];
    require(input.vertices && input.logical_edges && input.dense == 1 && input.sparse <= 255 &&
        input.aligned_vertices == (std::uint64_t{input.vertices} + 65535) / 65536 * 65536 &&
        input.published_vertices == input.dense * 65536 + input.sparse * 524288 &&
        input.allocation_vertices == std::max(input.aligned_vertices, input.published_vertices) &&
        descriptor[10] == 11 && descriptor[11] == 3 && descriptor[6] * 4ull < 256ull * 1024 * 1024 &&
        descriptor[7] == input.dense * 11 + input.sparse * 3 && descriptor.size() == 12 + descriptor[7] * 8,
        "unsupported mixed topology/descriptor geometry");
    require(allow_padding || input.published_vertices <= input.aligned_vertices,
            "original host allocation is smaller than mixed publication extent");
    std::uint64_t offset = 0;
    std::array<std::uint64_t, 14> addresses{};
    for (unsigned ordinal = 0; ordinal < descriptor[7]; ++ordinal) {
      const auto index = 12 + ordinal * 8;
      Task task{descriptor[index], descriptor[index + 1], descriptor[index + 2], descriptor[index + 3],
                descriptor[index + 4], descriptor[index + 5], descriptor[index + 6], 0};
      const bool big = ordinal >= input.dense * 11;
      const auto relative = ordinal - (big ? input.dense * 11 : 0), kernels = big ? 3u : 11u;
      const auto partition = relative / kernels, sub = relative % kernels;
      const auto kernel = (partition % 2 ? kernels - 1 - sub : sub) + (big ? 11 : 0);
      require(task.partition == partition && task.subpartition == sub && task.kernel == kernel &&
          task.destination == (big ? input.dense * 65536 + partition * 524288 : partition * 65536) &&
          task.destination_vertices == (big ? 524288 : 65536) && task.offset_words == offset &&
          task.words && task.words % 16 == 0 && descriptor[index + 7] == unsigned(big),
          "mixed task assignment, ordering or extent invalid");
      task.address = addresses[kernel]; addresses[kernel] += task.words * 4ull;
      require(addresses[kernel] < 256ull * 1024 * 1024, "mixed edge channel capacity exceeded");
      offset += task.words; input.tasks.push_back(task);
    }
    input.edge_words = read_words(directory / "tasks.u32le", offset);
    input.initial = read_words(directory / "initial.u32le", input.aligned_vertices);
    input.degrees = read_words(directory / "degrees.u32le", input.aligned_vertices);
    input.offsets = read_words(directory / "csr_offsets.u32le", std::uint64_t{input.vertices} + 1);
    input.destinations = read_words(directory / "csr_destinations.u32le", input.logical_edges);
    require(input.edge_words.size() == offset && input.initial.size() == input.aligned_vertices &&
        input.degrees.size() == input.aligned_vertices && input.offsets.size() == input.vertices + 1 &&
        input.destinations.size() == input.logical_edges && input.offsets.front() == 0 &&
        input.offsets.back() == input.logical_edges, "mixed capture extent mismatch");
    input.initial.resize(input.allocation_vertices, 0); input.degrees.resize(input.allocation_vertices, 0);
    input.validate(); return input;
  }
  void validate();
};

}  // namespace original_regraph_mixed_test

#include "oracle.hpp"
