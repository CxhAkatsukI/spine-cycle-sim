#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <span>
#include <stdexcept>
#include <vector>

namespace original_regraph_whole_test {

inline void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

inline std::vector<std::uint8_t> bytes(std::span<const std::uint32_t> words) {
  std::vector<std::uint8_t> result;
  result.reserve(words.size() * 4);
  for (const auto word : words) for (unsigned byte = 0; byte < 4; ++byte) {
    result.push_back(static_cast<std::uint8_t>(word >> (byte * 8)));
  }
  return result;
}

inline std::vector<std::uint32_t> read_words(const std::filesystem::path& path,
                                            std::uint64_t maximum_words) {
  const auto size = std::filesystem::file_size(path);
  require(size % 4 == 0 && size / 4 <= maximum_words, "invalid or excessive binary input extent");
  std::ifstream stream(path, std::ios::binary);
  std::vector<std::uint32_t> result(size / 4);
  std::array<unsigned char, 4> word{};
  for (auto& value : result) {
    stream.read(reinterpret_cast<char*>(word.data()), 4);
    require(stream.good(), "truncated binary input");
    value = std::uint32_t{word[0]} | (std::uint32_t{word[1]} << 8) |
            (std::uint32_t{word[2]} << 16) | (std::uint32_t{word[3]} << 24);
  }
  return result;
}

inline void write_words(const std::filesystem::path& path, std::span<const std::uint32_t> words) {
  require(!std::filesystem::exists(path), "refusing to overwrite result capture");
  const auto payload = bytes(words);
  std::ofstream stream(path, std::ios::binary);
  stream.write(reinterpret_cast<const char*>(payload.data()), static_cast<std::streamsize>(payload.size()));
  stream.close();
  require(stream.good(), "failed to write result capture");
}

struct Task {
  std::uint32_t partition{}, subpartition{}, kernel{}, destination{}, destination_vertices{};
  std::uint32_t offset_words{}, words{};
  std::uint64_t address{};
};

struct Input {
  std::uint32_t vertices{}, logical_edges{}, aligned_vertices{}, published_vertices{}, partitions{};
  std::vector<Task> tasks;
  std::vector<std::uint32_t> edge_words, initial, degrees, offsets, destinations, sums, expected;
  std::uint64_t physical_edges{}, dummy_edges{};

  static Input load(const std::filesystem::path& directory) {
    const auto descriptor = read_words(directory / "execution.u32le", 8 + 255 * 4 * 8);
    require(descriptor.size() >= 8 && descriptor[0] == 0x3447524fu && descriptor[1] == 1,
            "invalid original A4 descriptor header");
    Input input;
    input.vertices = descriptor[2]; input.logical_edges = descriptor[3];
    input.aligned_vertices = descriptor[4]; input.published_vertices = descriptor[5];
    input.partitions = descriptor[7];
    require(input.vertices && input.logical_edges && input.partitions && input.partitions <= 255 &&
            input.aligned_vertices == (std::uint64_t{input.vertices} + 65535) / 65536 * 65536 &&
            input.published_vertices == input.partitions * 65536 &&
            input.published_vertices <= input.aligned_vertices && descriptor[6] == input.partitions * 4 &&
            descriptor.size() == 8 + descriptor[6] * 8, "unsupported A4 descriptor geometry");
    std::uint64_t offset = 0;
    std::array<std::uint64_t, 4> addresses{};
    for (std::size_t index = 8; index < descriptor.size(); index += 8) {
      Task task{descriptor[index], descriptor[index + 1], descriptor[index + 2], descriptor[index + 3],
                descriptor[index + 4], descriptor[index + 5], descriptor[index + 6], 0};
      const auto ordinal = (index - 8) / 8;
      const auto kernel = task.partition % 2 ? 3 - task.subpartition : task.subpartition;
      require(task.partition == ordinal / 4 && task.subpartition == ordinal % 4 && task.kernel == kernel &&
              task.destination == task.partition * 65536 && task.destination_vertices == 65536 &&
              task.offset_words == offset && task.words && task.words % 16 == 0 && descriptor[index + 7] == 0,
              "invalid A4 task ordering, assignment or extent");
      task.address = addresses[task.kernel];
      addresses[task.kernel] += std::uint64_t{task.words} * 4;
      require(addresses[task.kernel] < 256ull * 1024 * 1024, "A4 edge channel capacity exceeded");
      offset += task.words;
      input.tasks.push_back(task);
    }
    input.edge_words = read_words(directory / "tasks.u32le", offset);
    input.initial = read_words(directory / "initial.u32le", input.aligned_vertices);
    input.degrees = read_words(directory / "degrees.u32le", input.aligned_vertices);
    input.offsets = read_words(directory / "csr_offsets.u32le", std::uint64_t{input.vertices} + 1);
    input.destinations = read_words(directory / "csr_destinations.u32le", input.logical_edges);
    require(input.edge_words.size() == offset && input.initial.size() == input.aligned_vertices &&
            input.degrees.size() == input.aligned_vertices && input.offsets.size() == input.vertices + 1 &&
            input.destinations.size() == input.logical_edges && input.offsets.front() == 0 &&
            input.offsets.back() == input.logical_edges, "A4 input capture extent mismatch");
    input.validate_values();
    return input;
  }

  void validate_values() {
    std::vector<std::uint64_t> total(aligned_vertices, 0);
    for (unsigned source = 0; source < vertices; ++source) {
      require(offsets[source] <= offsets[source + 1] && offsets[source + 1] <= logical_edges &&
              degrees[source] == offsets[source + 1] - offsets[source] && initial[source] <= INT32_MAX,
              "CSR degree or property domain mismatch");
      for (auto edge = offsets[source]; edge < offsets[source + 1]; ++edge) {
        require(destinations[edge] < published_vertices && destinations[edge] < vertices,
                "destination exceeds admitted nonempty prefix");
        total[destinations[edge]] += initial[source];
      }
    }
    sums.resize(aligned_vertices); expected.resize(aligned_vertices);
    for (unsigned vertex = 0; vertex < aligned_vertices; ++vertex) {
      if (vertex >= vertices) require(initial[vertex] == 0 && degrees[vertex] == 0, "nonzero padded state");
      const auto damped = total[vertex] * 108;
      const auto product = (damped >> 7) * (degrees[vertex] ? 65536 / degrees[vertex] : 0);
      require(total[vertex] <= INT32_MAX && damped <= INT32_MAX && product <= INT32_MAX,
              "initial PR iteration exceeds original signed arithmetic domain");
      sums[vertex] = static_cast<std::uint32_t>(total[vertex]);
      expected[vertex] = static_cast<std::uint32_t>(product >> 16);
    }
    for (const auto& task : tasks) for (unsigned index = 0; index < task.words; index += 2) {
      const auto source = edge_words[task.offset_words + index] & 0x7fffffffu;
      const auto destination = edge_words[task.offset_words + index + 1];
      require(source < vertices && (std::uint64_t{source / 4096} + 2) * 4096 <= aligned_vertices,
              "task source/lookahead exceeds property allocation");
      ++physical_edges;
      if (destination & 0x80000000u) {
        require(destination == 0xffffffffu, "noncanonical task dummy destination");
        ++dummy_edges;
      } else require(destination >= task.destination && destination - task.destination < 65536,
                     "task destination exceeds its partition");
    }
    require(physical_edges - dummy_edges == logical_edges, "task logical/physical work mismatch");
  }
};

}  // namespace original_regraph_whole_test
