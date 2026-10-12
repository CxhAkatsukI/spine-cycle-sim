#pragma once

#include "oracle.hpp"
#include "../original_regraph/whole_graph/compact_source.hpp"
#include "../original_regraph/whole_graph/compute_wiring.hpp"

namespace evaluation_impact {
inline void a4(const st::Input& input, const Oracle& oracle, const std::filesystem::path& output,
               std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  auto compact = input.compact;
  std::uint64_t total = 0, reads = 0, writes = 0;
  wt::ComputeOptions options;
  options.udf = rg::Udf::kWeightedSssp;
  options.memory = {150, 32, 32};
  options.apply_timing = rg::kSsspSchedulePostReadTiming;
  options.sssp_response_anchored = true;
  for (std::size_t round = 0; round < oracle.states.size(); ++round) {
    wt::ComputeWiring<wt::CompactSource, rg::SsspApply> model(
        wt::CompactSource(compact, rg::Udf::kWeightedSssp), 2, latency, reverse, 2, options);
    model.initialize(); model.begin();
    std::uint64_t cycles = 0;
    while (total + cycles < maximum && !model.finished()) {
      model.memory.scheduler.step(); model.advance(++cycles);
    }
    st::require(model.finished(), "A4 convergence demo exceeded total cycle limit");
    total += cycles;
    for (unsigned copy = 0; copy < 4; ++copy) {
      const auto payload = model.memory.backend->inspect_payload(copy * 2 + 1, wt::kOutputAddress,
                                                                compact.aligned_vertices * 4ull + 64);
      st::require(std::equal(payload.begin(), payload.end() - 64, wt::bytes(oracle.states[round]).begin()),
                  "A4 full state differs from synchronous oracle");
      st::require(std::all_of(payload.end() - 64, payload.end(), [](auto b) { return b == 0xa5; }),
                  "A4 state guard modified");
      if (round + 1 == oracle.states.size())
        wt::write_words(output / ("replica" + std::to_string(copy) + ".u32le"), oracle.states[round]);
    }
    const auto traffic = model.memory.backend->traffic_stats();
    std::uint64_t edge_reads = 0, source_reads = 0, valid = 0, dummy = 0;
    for (const auto& path : model.paths) {
      edge_reads += path.components.reader->counters().read_bytes;
      source_reads += path.components.source->counters().read_bytes;
      valid += path.components.gather->counters().valid_updates;
      dummy += path.components.gather->counters().dummy_updates;
      st::require(path.starts.size() == compact.partitions && path.completions.size() == compact.partitions &&
                  path.components.source->counters().rounds == path.components.source->counters().acknowledgements,
                  "A4 partition acknowledgement mismatch");
    }
    st::require(valid == compact.logical_edges && dummy == compact.dummy_edges &&
                edge_reads == compact.physical_edges * 8 &&
                traffic.reads.bytes == edge_reads + source_reads + compact.published_vertices * 4ull &&
                traffic.writes.bytes == compact.published_vertices * 16ull &&
                model.apply->counters().active_vertices == oracle.active[round] &&
                model.writer->counters().write_requests == model.writer->counters().acknowledgements,
                "A4 per-round traffic/active ledger mismatch");
    reads += traffic.reads.bytes; writes += traffic.writes.bytes;
    std::cout << "DEMO_ROUND {\"arm\":\"a4\",\"round\":" << round
              << ",\"cycles\":" << cycles << ",\"active\":" << oracle.active[round] << "}\n";
    compact.initial = oracle.states[round];
  }
  std::cout << "DEMO_RESULT {\"arm\":\"a4\",\"cycles\":" << total
            << ",\"rounds\":" << oracle.states.size() << ",\"read_bytes\":" << reads
            << ",\"write_bytes\":" << writes << ",\"replicas\":4,\"passed\":true}\n";
}
}  // namespace evaluation_impact
