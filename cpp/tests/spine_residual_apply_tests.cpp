#include <algorithm>
#include <iostream>
#include <stdexcept>

#include "spine_sim/spine_system.hpp"

using namespace spine::sim;

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

void bitmap_test() {
  SpineResidualApplyBitmap bitmap;
  for (const std::size_t size : {130U, 65'536U, 1U, 129U}) {
    bitmap.begin_tile(size);
    std::size_t clears = 0;
    while (bitmap.clearing()) { bitmap.clear_word(); ++clears; }
    require(clears == (size + 63) / 64, "bitmap clear was not word-clocked");
    const std::vector<std::uint32_t> vertices{0, static_cast<std::uint32_t>(size - 1)};
    for (auto v : vertices) { bitmap.mark(v); bitmap.mark(v); }
    require(bitmap.count() == (size == 1 ? 1U : 2U), "duplicate marks changed count");
    bitmap.begin_scan();
    std::vector<std::uint32_t> selected;
    while (bitmap.needs_word() || bitmap.selected()) {
      if (bitmap.needs_word()) bitmap.read_word();
      else { selected.push_back(*bitmap.selected()); bitmap.consume(); }
    }
    require(selected.front() == 0 && selected.back() == size - 1 &&
        selected.size() == bitmap.count(), "bitmap lost ordering or tail bits");
  }
  bitmap.begin_tile(130);
  while (bitmap.clearing()) bitmap.clear_word();
  require(bitmap.count() == 0 && !bitmap.needs_word() && !bitmap.selected(),
          "empty tile retained stale bits");
}

struct Result {
  std::vector<std::uint32_t> rank, residual;
  SpineFrontierRunResult run;
  std::uint64_t applied{}, sparse{}, clears{}, reads{}, marks{}, fallback{};
};

Result execute(SpineResidualApplyMode mode, unsigned pattern, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 256, true});
  SpineEdgeSlice graph{.vertices = 130,
      .edges = {{.src=0, .dst=2, .weight=1, .diff=1},
                {.src=1, .dst=2, .weight=1, .diff=1},
                {.src=2, .dst=3, .weight=1, .diff=1},
                {.src=3, .dst=0, .weight=1, .diff=1}},
      .case_name = "sparse_apply_control"};
  AlgorithmPolicyConfig config{.kind=GraphAlgorithmKind::kResidualPageRank,
      .vertices=graph.vertices, .damping=0.85F, .epsilon=1e-4F,
      .residual_contract=ResidualPageRankContract::kHardwareWarmDanglingLinf};
  AlgorithmInitialState initial;
  initial.primary.assign(graph.vertices, GraphAlgorithmPolicy::float_to_word(0.01F));
  initial.auxiliary.assign(graph.vertices, GraphAlgorithmPolicy::float_to_word(0.0F));
  if (pattern == 1) {
    initial.auxiliary[129] = GraphAlgorithmPolicy::float_to_word(0.003F);
    initial.active_vertices = {129};
  } else if (pattern != 3) {
    initial.auxiliary[0] = GraphAlgorithmPolicy::float_to_word(0.02F);
    initial.auxiliary[1] = GraphAlgorithmPolicy::float_to_word(pattern == 2 ? -0.02F : -0.015F);
    initial.active_vertices = {0, 1};
  }
  initial.auxiliary[100] = GraphAlgorithmPolicy::float_to_word(5e-7F);
  SpinePageRankVerticalSliceSystem system(scheduler, clock, backend, graph,
      GraphAlgorithmPolicy(config), {}, {}, {}, 16, {}, std::nullopt,
      std::nullopt, initial, std::nullopt, SpineOwnerSchedulerConfig{});
  system.configure_residual_apply_mode(mode);
  if (reverse) scheduler.add_component(backend);
  system.register_components();
  if (!reverse) scheduler.add_component(backend);
  Result result;
  result.run = system.run_frontier_to_convergence(256, 10'000'000);
  require(result.run.converged && !result.run.failed && result.run.owner_ledger_closed &&
      result.run.owner_quiescent && backend.outstanding() == 0, "ResPR ledger did not drain");
  result.rank = system.compute().rank_words();
  result.residual = system.compute().residual_words();
  for (const auto& round : result.run.rounds) {
    const auto& c = round.compute;
    require(c.memory_requests_issued == c.memory_requests_completed,
            "Apply memory ledger is open");
    result.applied += c.vertices_applied;
    result.sparse += c.sparse_vertices_applied;
    result.clears += c.apply_bitmap_clear_cycles;
    result.reads += c.apply_bitmap_read_cycles;
    result.marks += c.apply_bitmap_marks;
    result.fallback += c.dense_fallback_tiles;
  }
  return result;
}
}  // namespace

int main() {
  try {
    bitmap_test();
    for (unsigned pattern = 0; pattern < 4; ++pattern) {
      const auto dense = execute(SpineResidualApplyMode::kDense, pattern, false);
      const auto sparse = execute(SpineResidualApplyMode::kDirtyBitmap, pattern, false);
      const auto reordered = execute(SpineResidualApplyMode::kDirtyBitmap, pattern, true);
      require(dense.rank == sparse.rank && dense.residual == sparse.residual &&
          dense.run.rounds.size() == sparse.run.rounds.size(), "sparse Apply changed numerical state");
      for (std::size_t r = 0; r < dense.run.rounds.size(); ++r) {
        require(dense.run.rounds[r].active_in == sparse.run.rounds[r].active_in &&
            dense.run.rounds[r].active_out == sparse.run.rounds[r].active_out,
            "sparse Apply changed the frontier trajectory");
      }
      require(sparse.rank == reordered.rank && sparse.residual == reordered.residual &&
          sparse.run.end_cycle == reordered.run.end_cycle,
          "registration order changed sparse Apply behavior");
      if (pattern == 1) require(sparse.fallback > 0 && sparse.applied == dense.applied,
          "nonzero dangling share bypassed dense fallback");
      if (pattern == 0 || pattern == 2) require(sparse.applied < dense.applied &&
          sparse.sparse == sparse.applied && sparse.clears > 0 && sparse.reads > 0 && sparse.marks > 0,
          "dirty selection was not finite/timed or failed to save Apply work");
      std::cout << "SPARSE_APPLY pattern=" << pattern << " dense=" << dense.run.end_cycle
          << " sparse=" << sparse.run.end_cycle << " applied=" << sparse.applied << '\n';
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
