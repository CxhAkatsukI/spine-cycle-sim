#pragma once

#include "pma_source.hpp"

namespace pma_adapter_test {

struct Observation {
  std::uint64_t cycles{}, checked{};
  std::array<std::vector<std::uint64_t>, 4> reader_finishes, compute_starts, frontend_finishes;
  std::vector<std::uint64_t> publication_finishes;
};

inline bool frontend_drained(const wt::ComputePath<pa::Reader>& path) {
  const auto& p = path.components;
  return p.scatter->finished() && p.gather->finished() && p.local_merge->drained() &&
      path.output->empty() && p.source_port.master->idle() && p.edges->empty() &&
      p.requests->empty() && p.responses->empty() && p.updates->empty() &&
      std::all_of(path.lanes.begin(), path.lanes.end(), [](const auto* queue) { return queue->empty(); });
}

inline Observation execute(PmaWiring& model, std::uint64_t maximum) {
  const auto& input = model.input;
  Observation result;
  auto& cycles = result.cycles;
  auto& checked = result.checked;
  for (; cycles < maximum; ++cycles) {
    const auto pops = model.merged->stats().pops;
    const auto* front = model.merged->front();
    const auto packet = front ? std::optional<wt::rg::PropertyLine>(*front) : std::nullopt;
    std::array<std::uint64_t, 4> before{};
    for (unsigned index = 0; index < 4; ++index) before[index] = model.paths[index].components.scatter->pipeline().accepted;
    model.memory.scheduler.step();
    if (model.merged->stats().pops != pops) {
      wt::require(packet.has_value() && model.merged->stats().pops == pops + 1, "PMA/R missed a consumed merged line");
      for (const auto value : *packet) {
        wt::require(checked < input.published_vertices && value == input.sums[checked], "PMA/R pre-Apply CSR oracle mismatch");
        ++checked;
      }
    }
    for (unsigned index = 0; index < 4; ++index) {
      const auto& path = model.paths[index];
      if (!path.active) continue;
      if (result.reader_finishes[index].size() < path.starts.size() && path.components.reader->finished()) {
        result.reader_finishes[index].push_back(cycles + 1);
      }
      if (result.compute_starts[index].size() < path.starts.size() &&
          path.components.scatter->pipeline().accepted > before[index]) result.compute_starts[index].push_back(cycles + 1);
      if (result.compute_starts[index].size() == path.starts.size() &&
          result.frontend_finishes[index].size() < path.starts.size() && frontend_drained(path)) {
        result.frontend_finishes[index].push_back(cycles + 1);
      }
    }
    while (result.publication_finishes.size() < input.partitions &&
        model.writer->counters().acknowledgements >= (result.publication_finishes.size() + 1) * 4096 * 4) {
      result.publication_finishes.push_back(cycles + 1);
    }
    model.advance(cycles + 1);
    if (model.finished()) { ++cycles; break; }
    if ((cycles + 1) % 1000000 == 0) std::cout << "PMA_R_PROGRESS cycles=" << cycles + 1 << " checked_sum_words=" << checked << std::endl;
  }
  wt::require(model.finished() && checked == input.published_vertices, "PMA/R complete graph execution timed out or lost merged output");
  return result;
}

inline void capture_state(const PmaWiring& model, const std::filesystem::path& directory) {
  const auto& input = model.input;
  for (unsigned replica = 0; replica < 4; ++replica) {
    const auto payload = model.memory.backend->inspect_payload(replica * 2 + 1, wt::kOutputAddress,
                                                                input.aligned_vertices * 4ull + 64);
    std::vector<std::uint32_t> actual(input.aligned_vertices);
    for (unsigned vertex = 0; vertex < input.aligned_vertices; ++vertex) {
      std::uint32_t value = 0;
      for (unsigned byte = 0; byte < 4; ++byte) value |= std::uint32_t{payload[vertex * 4 + byte]} << (byte * 8);
      wt::require(value == input.expected[vertex], "PMA/R full state replica differs from CSR PR oracle");
      actual[vertex] = value;
    }
    wt::require(std::all_of(payload.end() - 64, payload.end(), [](auto byte) { return byte == 0xa5; }), "PMA/R changed writer allocation guard");
    wt::write_words(directory / ("final_replica" + std::to_string(replica) + ".u32le"), actual);
  }
}

}  // namespace pma_adapter_test
