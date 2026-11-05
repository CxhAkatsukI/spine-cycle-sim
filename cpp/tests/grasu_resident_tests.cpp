#include "evaluation_impact/handoff/memory.hpp"
#include "spine_sim/grasu_native.hpp"

#include <iostream>

using namespace spine::sim;
using handoff_test::require;

namespace {
template <typename Exception, typename Function>
void rejects(Function function, const char* message) {
  try {
    function();
  } catch (const Exception&) {
    return;
  }
  throw std::runtime_error(message);
}

void compact_payload() {
  auto layout = GraSuPmaLayout::build_partition(128, 64, 64, {}, {},
                                               GraSuPmaWordAbi::kWeightedFullWord);
  const std::vector<GraSuEdge> updates = {
      {1, 65, 7}, {2, 66, 9, true}, {3, 67, 11}, {4, 68, 13}, {5, 69, 15}};
  const auto payload = encode_grasu_compact_updates(layout, updates,
                                                   GraSuPmaWordAbi::kWeightedFullWord);
  require(payload[0].size() == 16 && payload[1].size() == 8 &&
          payload[2].size() == 8 && payload[3].size() == 8,
          "compact updates did not stripe eight-byte records across four lanes");
  for (std::size_t index = 0; index < updates.size(); ++index) {
    const auto& edge = updates[index];
    const auto expected = (std::uint64_t{edge.source} << 32) |
        (std::uint64_t{edge.weight} << 19) | (edge.destination - 64) |
        (std::uint64_t{edge.delete_op} << 63);
    for (unsigned byte = 0; byte < 8; ++byte)
      require(payload[index % 4][index / 4 * 8 + byte] ==
              static_cast<std::uint8_t>(expected >> (byte * 8)),
              "compact update local destination, delete bit or byte order changed");
  }
  rejects<std::invalid_argument>([&] {
    (void)encode_grasu_compact_updates(layout, {{0, 63, 1}},
                                     GraSuPmaWordAbi::kWeightedFullWord);
  }, "compact encoder accepted a destination outside its resident window");
}

void rolling_batches() {
  const std::vector<GraSuEdge> initial = {{0, 1, 9}, {0, 65, 7}};
  const std::vector<GraSuEdge> reserved = {{0, 2, 2}, {0, 66, 3}};
  const auto layout = GraSuPartitionedPmaLayout::build(
      128, 64, initial, reserved, GraSuPmaWordAbi::kWeightedFullWord);
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("resident-G", 150);
  MockMemoryBackend backend("resident-memory", clock, {32, 5, 1, 16, 256, true});
  GraSuNativeConfig config;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.cache_segments_per_half = 8;
  config.initialize_pma_payload = false;
  const std::vector<std::vector<GraSuEdge>> batches = {
      {{0, 2, 2}, {0, 66, 3}},
      {{0, 1, 9, true}, {0, 65, 7, true}},
      {{0, 1, 9}, {0, 65, 7}},
  };
  GraSuShardedPmaUpdateSystem engine(scheduler, clock, backend, layout, batches[0],
                                    config, 16ULL << 20, {1, 1});
  const auto plan = engine.runtime_plan();
  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard)
    initialize_grasu_pma_layout_payloads(backend, layout.partitions[shard],
        handoff_test::shard_config(plan, shard, 8));
  scheduler.add_component(backend);
  rejects<std::logic_error>([&] { engine.prepare_batch(batches[1]); },
                            "unexecuted first batch could be overwritten");
  for (std::size_t index = 0; index < batches.size(); ++index) {
    if (index) {
      rejects<std::length_error>([&] { engine.prepare_batch({reserved[0], reserved[0]}); },
                                 "resident per-shard update capacity was not enforced");
      engine.prepare_batch(batches[index]);
    }
    const auto before = backend.traffic_stats();
    engine.register_components();
    rejects<std::logic_error>([&] { engine.prepare_batch(batches[index]); },
                              "registered resident engine accepted a new batch");
    for (std::size_t cycles = 0; cycles < 100000 && !engine.done() && !engine.failed(); ++cycles) {
      scheduler.step();
      engine.advance_if_complete();
    }
    require(engine.done() && !engine.failed() && backend.outstanding() == 0,
            "resident G batch failed to drain");
    const auto counters = engine.counters();
    const auto traffic = subtract_memory_traffic(backend.traffic_stats(), before);
    require(counters.updates == 2 && counters.update_read_bytes == 16 &&
        traffic.reads.bytes == counters.update_read_bytes + counters.row_read_bytes +
                               counters.binary_read_bytes + counters.pma_read_bytes &&
        traffic.writes.bytes == counters.pma_write_bytes,
        "resident G counters did not reset or its memory ledger did not close");
    require(handoff_test::same_placement(plan, engine.runtime_plan()),
            "resident G moved its PMA or batch buffers between batches");
    engine.unregister_components();
  }
  auto expected = initial;
  expected.insert(expected.end(), reserved.begin(), reserved.end());
  require(handoff_test::edge_set(engine.live_edges()) == handoff_test::edge_set(expected),
          "later batches overwrote resident updates from earlier batches");
  handoff_test::Fixture fixture{};
  fixture.layout = layout;
  fixture.updates = reserved;
  const auto expected_layout = handoff_test::edited_layout(fixture);
  MockMemoryBackend oracle("oracle", clock, {32, 5, 1, 16, 256, true});
  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard)
    initialize_grasu_pma_layout_payloads(oracle, expected_layout.partitions[shard],
        handoff_test::shard_config(plan, shard, 8));
  require(handoff_test::graph_bytes(backend, engine.materialized_partitioned_layout(), plan) ==
          handoff_test::graph_bytes(oracle, expected_layout, plan),
          "resident final payload differs from an independent PMA oracle");
}
} // namespace

int main() {
  try {
    compact_payload();
    rolling_batches();
    std::cout << "resident compact encoding and three-batch PMA checks passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
