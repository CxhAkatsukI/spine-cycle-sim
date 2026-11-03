#include "input.hpp"
#include <iostream>

namespace am = original_r_board::active_min;
namespace rb = original_r_board;

template<class Function> void rejects(Function fn) {
  try { fn(); } catch (const std::runtime_error&) { return; }
  rb::require(false, "invalid active-min input was accepted");
}

void write_fixture(const std::filesystem::path& output, rb::wt::Input input, rb::Words packed,
                   const rb::Words& weights, const rb::Words& cc, const rb::Words& sssp) {
  using rb::wt::write_words;
  rb::require(std::filesystem::create_directory(output), "fresh test fixture directory required");
  rb::Words descriptor{0x3447524fu, 1, input.vertices, input.logical_edges, input.aligned_vertices,
                       input.published_vertices, 4, 1};
  for (unsigned lane = 0; lane < 4; ++lane) {
    const auto offset = static_cast<unsigned>(lane == 0 ? 0 : input.edge_words.size());
    descriptor.insert(descriptor.end(), {0, lane, lane, 0, 65536, offset, lane == 0 ? 32u : 16u, 0});
    if (lane == 0) continue;
    for (unsigned edge = 0; edge < 8; ++edge) {
      input.edge_words.insert(input.edge_words.end(), {0, 0xffffffffu});
      packed.insert(packed.end(), {0, 0xffffffffu});
    }
  }
  rb::Words degrees(input.aligned_vertices, 0);
  for (unsigned source = 0; source < input.vertices; ++source)
    degrees[source] = input.offsets[source + 1] - input.offsets[source];
  write_words(output / "execution.u32le", descriptor);
  write_words(output / "tasks.u32le", input.edge_words);
  write_words(output / "initial.u32le", rb::Words(input.aligned_vertices, 0));
  write_words(output / "degrees.u32le", degrees);
  write_words(output / "csr_offsets.u32le", input.offsets);
  write_words(output / "csr_destinations.u32le", input.destinations);
  write_words(output / "cc_initial.u32le", cc);
  write_words(output / "sssp_initial.u32le", sssp);
  write_words(output / "sssp_weights.u32le", weights);
  write_words(output / "sssp_tasks.u32le", packed);
}

int main(int argc, char** argv) {
  using rb::Words;
  using am::Policy;
  constexpr auto A = am::active;
  rb::wt::Input input;
  input.vertices = 4097;
  input.logical_edges = 3;
  input.aligned_vertices = input.published_vertices = 65536;
  input.offsets.resize(input.vertices + 1, 2);
  input.offsets[0] = 0;
  input.offsets.back() = 3;
  input.destinations = {1, 2, 1};
  input.tasks = {{0, 0, 0, 0, 65536, 0, 32, 0}};
  input.edge_words.resize(32, 0xffffffffu);
  for (unsigned i = 0; i < 32; i += 2) input.edge_words[i] = i < 16 ? 0 : 4096;
  input.edge_words[1] = 1; input.edge_words[3] = 2; input.edge_words[17] = 1;
  auto packed = input.edge_words;
  const Words weights{8, 3, 1};
  packed[1] = a4_weighted::pack(1, 8);
  packed[3] = a4_weighted::pack(2, 3);
  packed[17] = a4_weighted::pack(1, 1);
  am::verify_compact_edges(input, packed, weights, Policy::weighted_sssp);
  am::verify_compact_edges(input, input.edge_words, {}, Policy::cc);
  Words state(input.aligned_vertices, 0);
  state[0] = 4 | A; state[1] = am::infinity; state[2] = 7 | A; state[4096] = 6 | A;
  const auto sssp = state;
  const auto distances = am::one_round(input, state, weights, Policy::weighted_sssp);
  rb::require(distances[0] == 4 && distances[1] == (7 | A) && distances[2] == 7 &&
              distances[4096] == 6, "weighted one-round oracle differs");
  state[0] = A; state[1] = 2; state[2] = 0 | A; state[4096] = 1 | A;
  const auto labels = am::one_round(input, state, {}, Policy::cc);
  rb::require(labels[0] == 0 && labels[1] == A && labels[2] == 0 && labels[4096] == 1,
              "CC one-round oracle differs");
  const auto cc = state;
  auto wrong = packed;
  wrong[1] = a4_weighted::pack(1, 7);
  rejects([&] { am::verify_compact_edges(input, wrong, weights, Policy::weighted_sssp); });
  wrong[1] = packed[1] | A;
  rejects([&] { am::verify_compact_edges(input, wrong, weights, Policy::weighted_sssp); });
  auto bad_layout = input;
  bad_layout.edge_words[3] = 1;
  rejects([&] { am::verify_compact_edges(bad_layout, bad_layout.edge_words, {}, Policy::cc); });
  bad_layout = input;
  bad_layout.edge_words[14] = 4096;
  rejects([&] { am::verify_compact_edges(bad_layout, bad_layout.edge_words, {}, Policy::cc); });
  state[input.vertices] = 1;
  rejects([&] { am::one_round(input, state, {}, Policy::cc); });

  rb::require(argc <= 3, "usage: input_tests [ARCHIVED_A4 [FRESH_FIXTURE_OUTPUT]]");
  if (argc >= 2) {
    // A real archived author capture can validate task geometry without inventing a workload.
    const auto layout = rb::wt::Input::load_layout(argv[1]);
    am::verify_compact_edges(layout, layout.edge_words, {}, Policy::cc);
    std::cout << "Author A4 compact layout verified: " << layout.vertices << " vertices, "
              << layout.logical_edges << " logical edges, " << layout.tasks.size() << " tasks\n";
  }
  if (argc == 3) {
    write_fixture(argv[2], input, packed, weights, cc, sssp);
    rb::require(am::Input::load(argv[2], Policy::cc).expected == labels, "loaded CC fixture differs");
    rb::require(am::Input::load(argv[2], Policy::weighted_sssp).expected == distances,
                "loaded weighted SSSP fixture differs");
  }
  std::cout << "Active-min A4 input checks passed (offline only)\n";
}
