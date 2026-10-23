#pragma once

#include "../input.hpp"
#include "../../warm_comparison/integrated.hpp"
#include "../../warm_comparison/spine.hpp"

namespace figure_refresh::multi {
inline void sssp(const std::string& path, const std::string& updates, std::uint32_t root,
                 const std::filesystem::path& output, const std::string& arm,
                 Scheduler& scheduler, ClockId clock, MemoryBackend& backend,
                 std::uint64_t maximum) {
  const auto input = figure_refresh::load(path, updates, root, true);
  wc::ei::wt::write_words(output / "old_state.u32le", input.after.initial.primary);
  wc::ei::wt::write_words(output / "expected.u32le",
      wc::dijkstra(input.after.compact.vertices, input.after.edges, input.root));
  if (arm == "gr") wc::integrated_with_backend(input, output, scheduler, clock, backend, false, maximum);
  else wc::spine_with_backend(input, output, scheduler, clock, backend, maximum);
}
} // namespace figure_refresh::multi
