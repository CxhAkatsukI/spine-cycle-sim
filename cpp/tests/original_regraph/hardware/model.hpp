#pragma once

#include <algorithm>
#include "../whole_graph/mixed/input.hpp"
#include <string_view>

namespace original_r_board {
namespace wt = original_regraph_whole_test;
using Words = std::vector<std::uint32_t>;
using wt::require;
constexpr unsigned guard_words = 16;
constexpr std::uint32_t guard = 0xa55a5aa5u;

enum class Binding { author_initial, csr_degree };

inline Binding binding(std::string_view name) {
  if (name == "author_initial") return Binding::author_initial;
  require(name == "csr_degree", "explicit author_initial or csr_degree binding required");
  return Binding::csr_degree;
}

inline std::uint32_t apply(std::uint64_t sum, std::uint32_t divisor) {
  require(sum <= INT32_MAX && divisor <= INT32_MAX, "PR input outside signed source domain");
  const auto damped = sum * 108;
  require(damped <= INT32_MAX, "PR damping overflows signed source arithmetic");
  const auto product = (damped >> 7) * (divisor ? 65536 / divisor : 0);
  require(product <= INT32_MAX, "PR division overflows signed source arithmetic");
  return static_cast<std::uint32_t>(product >> 16);
}

inline Words guarded(Words words) {
  words.insert(words.end(), guard_words, guard);
  return words;
}

struct Model {
  unsigned vertices{}, logical_edges{}, aligned{}, published{}, allocation{}, little{}, big{}, dense{}, sparse{};
  Binding divisor_binding{};
  std::vector<wt::Task> tasks;
  Words edge_words, initial, degrees, sums, expected;
  std::uint64_t physical_edges{}, dummy_edges{}, extra_padding{};

  template<class Input> void take(Input&& input) {
    vertices = input.vertices; logical_edges = input.logical_edges;
    aligned = input.aligned_vertices; published = input.published_vertices;
    tasks = std::move(input.tasks); edge_words = std::move(input.edge_words);
    initial = std::move(input.initial); degrees = std::move(input.degrees);
    sums = std::move(input.sums); physical_edges = input.physical_edges; dummy_edges = input.dummy_edges;
  }

  static Model load(const std::filesystem::path& directory, std::string_view topology, Binding selected) {
    const bool mixed = topology == "original_example";
    require(mixed || topology == "a4", "explicit a4 or original_example topology required");
    for (const auto* name : {"tasks.u32le", "initial.u32le", "degrees.u32le", "csr_offsets.u32le",
                            "csr_destinations.u32le", mixed ? "mixed.u32le" : "execution.u32le"}) {
      const auto path = directory / name;
      require(!std::filesystem::is_symlink(path) && std::filesystem::is_regular_file(path),
              "regular non-symlink admitted input required");
    }
    Model model;
    if (mixed) {
      auto input = original_regraph_mixed_test::Input::load(directory, true);
      model.little = 11; model.big = 3; model.dense = input.dense; model.sparse = input.sparse;
      model.allocation = input.allocation_vertices;
      model.take(std::move(input));
    } else {
      auto input = wt::Input::load(directory);
      model.little = 4; model.dense = input.partitions; model.allocation = input.aligned_vertices;
      model.take(std::move(input));
    }
    model.divisor_binding = selected;
    model.extra_padding = model.allocation - model.aligned;
    model.validate_tasks();
    model.expected.assign(model.allocation + guard_words, guard);
    const auto& divisor = selected == Binding::author_initial ? model.initial : model.degrees;
    for (unsigned vertex = 0; vertex < model.published; ++vertex)
      model.expected[vertex] = apply(model.sums[vertex], divisor[vertex]);
    model.validate_capacity();
    return model;
  }

  void validate_tasks() const {
    std::vector<std::uint64_t> gathered(allocation);
    for (const auto& task : tasks) {
      unsigned previous = 0;
      for (unsigned index = 0; index < task.words; index += 2) {
        const auto source = edge_words[task.offset_words + index] & 0x7fffffffu;
        const auto destination = edge_words[task.offset_words + index + 1];
        require(index == 0 || source >= previous, "task sources must be nondecreasing");
        previous = source;
        if (destination == 0xffffffffu) continue;
        require(destination < vertices && destination < published, "task destination outside published graph");
        gathered[destination] += initial[source];
      }
    }
    require(gathered.size() == sums.size() && std::equal(gathered.begin(), gathered.end(), sums.begin()),
            "task gather differs from independent CSR oracle");
  }

  void validate_capacity() const {
    constexpr std::uint64_t max_buffer = 256ull * 1024 * 1024, bank_capacity = 512ull * 1024 * 1024;
    require(allocation >= std::max(aligned, published) && initial.size() == allocation &&
            degrees.size() == allocation && expected.size() == allocation + guard_words,
            "state allocation must include publication and guards");
    require((allocation + guard_words) * 4ull < max_buffer &&
            2 * (allocation + guard_words) * 4ull < bank_capacity, "guarded state exceeds HBM capacity");
    std::array<std::uint64_t, 14> bytes{};
    for (const auto& task : tasks) {
      require(task.kernel < little + big && (task.words + guard_words) * 4ull < max_buffer,
              "guarded edge buffer exceeds HBM capacity");
      bytes[task.kernel] += (task.words + guard_words) * 4ull;
      require(bytes[task.kernel] < bank_capacity, "all resident tasks exceed edge bank capacity");
    }
  }

  Words source() const { return guarded(initial); }
  Words divisor() const { return guarded(divisor_binding == Binding::author_initial ? initial : degrees); }
  Words output() const { return Words(allocation + guard_words, guard); }
  Words edges(unsigned ordinal) const {
    const auto& task = tasks.at(ordinal);
    return guarded(Words(edge_words.begin() + task.offset_words,
                         edge_words.begin() + task.offset_words + task.words));
  }
  void verify(const Words& actual, const Words& target, const char* message) const {
    require(actual == target, message);
  }
};
}  // namespace original_r_board
