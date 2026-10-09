#pragma once

#include "fixture_data.hpp"
#include "../original_regraph/memory_fixture.hpp"
#include "../original_regraph/whole_graph/input.hpp"
#include "spine_sim/pma_adapter/reader.hpp"

namespace pma_adapter_test {
namespace pa = spine::sim::pma_adapter;
namespace rg = spine::sim::original_regraph;
using original_regraph_whole_test::require;
using original_regraph_whole_test::bytes;

struct Options {
  std::size_t depth{8}, parents{2};
  std::uint64_t latency{64}, sink_start{}, sink_interval{1};
  bool reverse{}, bad_rows{};
  pa::Timing timing{};
};

struct Result {
  std::uint64_t cycles{};
  pa::Counters counters;
  std::vector<std::uint32_t> global;
};

inline Result run(const Data& data, Options options = {}) {
  original_regraph_memory_test::MemoryFixture memory(options.depth, options.latency);
  const auto port = memory.port("adapter.axi", 1, 0, 16, options.parents);
  auto* output = memory.queue<rg::EdgeBurst>("edges");
  auto* reader = memory.make<pa::Reader>("adapter", memory.clock, port.ports(), *output, options.timing);
  pa::Partition partition{{4096, 8192, 12288, 16384}, 0, data.vertices, data.slots,
                          data.cache_segments, data.destination, data.destination_vertices};
  auto row_words = data.rows;
  if (options.bad_rows) row_words[3] = 16;
  row_words.resize((data.vertices + 7) / 8 * 16, 0);
  memory.backend->initialize_payload(0, 0, bytes(row_words));
  for (unsigned index = 0; index < 4; ++index) {
    memory.backend->initialize_payload(0, partition.pma_addresses[index], bytes(data.buffers[index]));
  }
  memory.register_components(options.reverse);
  reader->begin_partition(partition);
  bool rejected = false;
  try { reader->begin_partition(partition); } catch (const std::logic_error&) { rejected = true; }
  require(rejected, "PMA adapter accepted an active restart");
  Result result;
  for (; result.cycles < 100000; ++result.cycles) {
    if (result.cycles >= options.sink_start && result.cycles % options.sink_interval == 0) {
      rg::EdgeBurst burst;
      if (!output->empty() && output->try_pop(burst)) {
        for (const auto& edge : burst) {
          result.global.push_back(edge.source);
          result.global.push_back((data.destination + (edge.destination & 0x7ffffu)) |
              (edge.destination & rg::kDummyDestination ? 0x80000000u : 0));
        }
      }
    }
    memory.scheduler.step();
    if (reader->finished() && output->empty() && port.master->idle()) { ++result.cycles; break; }
  }
  result.counters = reader->counters();
  require(reader->finished() && memory.drained() && result.global == data.expected_global,
          "PMA adapter timed out, lost a queue/request, or changed a packet");
  const auto traffic = memory.backend->traffic_stats();
  const auto& count = result.counters;
  require(count.tasks == 1 && count.parent_requests == data.vertices + 1 + data.slots / 16 &&
          count.parent_requests == count.acknowledgements && count.row_word_reads == data.vertices + 1 &&
          count.row_bus_bytes == (data.vertices + 1) * 64 && count.pma_bus_bytes == data.slots * 4 &&
          count.physical_edges == data.slots && count.final_bursts == 1 &&
          count.valid_edges + count.dummy_edges == count.physical_edges &&
          count.read_bytes == traffic.reads.bytes && traffic.writes.bytes == 0 &&
          count.parent_requests == port.master->stats().requests_accepted &&
          port.master->stats().requests_accepted == port.master->stats().requests_completed,
          "PMA adapter source/AXI/traffic conservation mismatch");
  return result;
}

}  // namespace pma_adapter_test
