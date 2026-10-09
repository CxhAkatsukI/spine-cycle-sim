#pragma once

#include "wiring.hpp"

namespace original_regraph_mixed_test {

struct Ledger {
  std::uint64_t edge_bytes{}, little_source_bytes{}, big_source_bytes{}, valid{}, dummy{}, ends{}, hits{}, reads{}, requests{};
};

inline Ledger verify(Wiring& model, const std::filesystem::path& directory) {
  const auto& input = model.input;
  require(std::filesystem::is_directory(directory), "mixed output directory missing");
  for (unsigned replica = 0; replica < 14; ++replica) {
    const auto payload = model.memory.backend->inspect_payload(replica * 2 + 1, kOutputAddress,
        input.allocation_vertices * 4ull + 64);
    std::vector<std::uint32_t> actual(input.allocation_vertices);
    for (unsigned vertex = 0; vertex < input.allocation_vertices; ++vertex) {
      for (unsigned byte = 0; byte < 4; ++byte) actual[vertex] |= std::uint32_t{payload[vertex * 4 + byte]} << (byte * 8);
      require(actual[vertex] == input.expected[vertex], "complete mixed state replica differs from independent CSR PR oracle");
    }
    require(std::all_of(payload.end() - 64, payload.end(), [](auto byte) { return byte == 0xa5; }), "mixed writer changed guard");
    write_words(directory / ("final_replica" + std::to_string(replica) + ".u32le"), actual);
  }
  Ledger ledger;
  for (const auto& path : model.little) {
    const auto& p = path.p;
    require(path.starts.size() == input.dense && path.completions.size() == input.dense &&
        p.source->counters().rounds == p.source->counters().acknowledgements, "mixed Little lifecycle mismatch");
    ledger.edge_bytes += p.reader->counters().read_bytes;
    ledger.little_source_bytes += p.source->counters().read_bytes;
    ledger.valid += p.gather->counters().valid_updates; ledger.dummy += p.gather->counters().dummy_updates;
    ledger.ends += p.source->counters().partition_terminators;
  }
  for (const auto& path : model.big) {
    const auto& c = path.source->counters();
    require(path.starts.size() == input.sparse && path.completions.size() == input.sparse &&
        c.requests == c.responses && c.requests == c.reads + c.cache_hits && c.reads == c.acknowledgements,
        "mixed Big request/cache/lifecycle mismatch");
    ledger.edge_bytes += path.reader->counters().read_bytes; ledger.big_source_bytes += c.read_bytes;
    ledger.ends += c.partition_ends; ledger.hits += c.cache_hits; ledger.reads += c.reads; ledger.requests += c.requests;
    for (auto* sw : path.switches) {
      const auto& s = sw->counters();
      require(s.sender_tuples == s.receiver_tuples && s.sender_ends * 2 == s.receiver_ends, "mixed omega token conservation");
      for (unsigned route = 0; route < 4; ++route) {
        const auto& q = sw->route(route);
        require(q.empty() && q.stats().pushes == q.stats().pops && q.stats().max_occupancy <= q.depth(), "mixed omega private FIFO conservation");
      }
    }
    for (auto* bank : path.banks) {
      const auto& b = bank->counters(); ledger.valid += b.valid_updates; ledger.dummy += b.dummy_updates;
      require(b.partitions == input.sparse && b.ends == input.sparse && b.drain_read_pairs == input.sparse * 32768ull &&
          b.drain_read_pairs == b.drain_clear_pairs, "mixed Big bank drain/clear/end mismatch");
    }
  }
  const auto traffic = model.memory.backend->traffic_stats();
  const auto degree_bytes = input.published_vertices * 4ull;
  require(ledger.valid == input.logical_edges && ledger.dummy == input.dummy_edges && ledger.edge_bytes == input.physical_edges * 8 &&
      traffic.reads.bytes == ledger.edge_bytes + ledger.little_source_bytes + ledger.big_source_bytes + degree_bytes &&
      traffic.writes.bytes == degree_bytes * 14 && ledger.ends == input.dense * 11 + input.sparse * 3 &&
      model.writer->counters().acknowledgements == input.published_vertices / 16 * 14 &&
      model.apply->counters().degree_responses == input.published_vertices / 16, "mixed complete traffic/iteration ledger mismatch");
  return ledger;
}

}  // namespace original_regraph_mixed_test
