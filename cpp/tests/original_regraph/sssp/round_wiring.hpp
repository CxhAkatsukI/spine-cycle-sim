#pragma once

#include "fixture.hpp"
#include "spine_sim/original_regraph/property_writer.hpp"
#include "spine_sim/original_regraph/sssp_apply.hpp"
#include "spine_sim/original_regraph/write_indexer.hpp"

namespace original_regraph_sssp_test {
inline constexpr std::uint64_t kOutputAddress = 64ull << 20;

struct RoundResult {
  std::vector<std::uint32_t> state;
  std::uint64_t cycles{}, reads{}, writes{}, active{};
  bool waited_for_replica_ack{};
  bool operator==(const RoundResult&) const = default;
};

inline RoundResult run_a4(const Fixture& f, bool reverse, bool pressure) {
  original_regraph_frontend_test::Options options;
  options.little = 4;
  options.gather = true;
  options.udf = rg::Udf::kWeightedSssp;
  options.fifo_depth = pressure ? 1 : 8;
  options.outstanding = pressure ? 1 : 16;
  options.memory_latency = pressure ? 128 : 64;
  original_regraph_frontend_test::Wiring front(options);
  auto& memory = front.memory;
  auto* indexed = memory.queue<rg::PropertyWrite>("sssp.indexed");
  auto* applied = memory.queue<rg::PropertyWrite>("sssp.applied");
  const auto old = memory.port("sssp.old_state", 100, 30, options.outstanding);
  std::vector<rg::WriteTarget> targets;
  std::vector<original_regraph_memory_test::MemoryLink> writers;
  for (unsigned i = 0; i < 4; ++i) {
    const auto port = memory.port("sssp.writer" + std::to_string(i), 200 + i, i * 2 + 1, options.outstanding);
    targets.push_back({{*port.requests, *port.responses}, kOutputAddress, kPadded * 4});
    writers.push_back(port);
  }
  auto* indexer = memory.make<rg::LittleWriteIndexer>("sssp.indexer", memory.clock,
      *front.merged_output, *indexed);
  auto* apply = memory.make<rg::SsspApply>("sssp.apply", memory.clock,
      rg::TransactionPort{*old.requests, *old.responses}, *indexed, *applied,
      0, kPadded * 4, rg::kApplyPostReadTiming, pressure ? 2 : rg::kApplyLineCredits);
  auto* writer = memory.make<rg::PropertyBroadcastWriter>("sssp.writer", memory.clock,
      *applied, targets, pressure ? 2 : rg::kWriterLineCredits);
  std::vector<std::uint8_t> bytes;
  for (const auto word : f.encoded) original_regraph_frontend_test::append_word(bytes, word);
  for (unsigned i = 0; i < 4; ++i) {
    memory.backend->initialize_payload(i * 2 + 1, 0, bytes);
    memory.backend->fill_payload(i * 2 + 1, kOutputAddress, kPadded * 4 + 64, 0xa5);
  }
  memory.backend->initialize_payload(30, 0, bytes);
  memory.register_components(reverse);
  front.begin(f.compact, false);
  indexer->begin(kPadded / 16);
  apply->begin(kPadded / 16);
  writer->begin(kPadded / 16);
  RoundResult result;
  for (std::uint64_t cycle = 0; cycle < 2000000; ++cycle) {
    memory.scheduler.step();
    if (apply->finished() && !writer->finished()) result.waited_for_replica_ack = true;
    if (!front.drained() || !indexer->finished() || !apply->finished() || !writer->finished()) continue;
    result.cycles = cycle + 1;
    break;
  }
  require(result.cycles != 0, "A4 weighted full round timed out");
  for (unsigned i = 0; i < 4; ++i) {
    const auto payload = memory.backend->inspect_payload(i * 2 + 1, kOutputAddress, kPadded * 4 + 64);
    for (std::size_t v = 0; v < kPadded; ++v) {
      std::uint32_t word = 0;
      for (unsigned b = 0; b < 4; ++b) word |= std::uint32_t{payload[v * 4 + b]} << (b * 8);
      require(word == f.expected[v], "A4 weighted replica differs from independent full-round oracle");
      if (!i) result.state.push_back(word);
    }
    require(std::all_of(payload.end() - 64, payload.end(), [](auto b) { return b == 0xa5; }),
            "A4 weighted writer touched guard");
    require(writers[i].master->stats().requests_accepted == writers[i].master->stats().requests_completed,
            "A4 weighted replica acknowledgements incomplete");
  }
  result.reads = memory.backend->traffic_stats().reads.bytes;
  result.writes = memory.backend->traffic_stats().writes.bytes;
  result.active = apply->counters().active_vertices;
  std::uint64_t input_reads = 0;
  for (const auto& path : front.paths)
    input_reads += path.reader->counters().read_bytes + path.source->counters().read_bytes;
  require(result.reads == input_reads + kPadded * 4 && result.writes == kPadded * 4 * 4 &&
          apply->counters().old_state_bytes == kPadded * 4 &&
          apply->counters().old_state_responses == kPadded / 16 &&
          writer->counters().write_requests == writer->counters().acknowledgements &&
          result.waited_for_replica_ack, "A4 weighted full-round conservation/completion mismatch");
  return result;
}

inline std::vector<std::uint32_t> run_routed(const Fixture& f) {
  spine::sim::Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  spine::sim::MockMemoryBackend backend("memory", clock, {32, 64, 1, 32, 32, true});
  scheduler.add_component(backend);
  spine::sim::RoutedReGraphConfig config;
  config.fixed_rounds = 1;
  config.independent_read_write = true;
  config.adapter.empty_segment_exit_cycles = 73;
  config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
  auto layout = spine::sim::GraSuPartitionedPmaLayout::build(kVertices, 65536, f.edges, {},
      spine::sim::GraSuPmaWordAbi::kWeightedFullWord);
  spine::sim::RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), f.initial, config);
  system.register_components();
  for (std::uint64_t cycle = 0; cycle < 2000000 && !system.done(); ++cycle) {
    scheduler.step();
    system.advance_if_complete();
  }
  require(system.done() && !system.failed(), "routed weighted single round did not complete");
  require(system.rounds().size() == 1, "routed weighted full-round round count mismatch");
  require(system.encoded_state() == f.expected, "routed weighted full-round state mismatch");
  require(system.counters().live_edges == f.edges.size() && backend.outstanding() == 0,
          "routed weighted full-round edge/conservation mismatch");
  const auto state = system.encoded_state();
  for (unsigned i = 0; i < 2; ++i)
    require(system.source_state(i, 1) == state, "routed weighted source replica mismatch");
  system.unregister_components();
  scheduler.remove_component(backend);
  return state;
}
}  // namespace original_regraph_sssp_test
