#pragma once

#include "fixture.hpp"
#include "../../../original_grasu/system.hpp"

namespace sharded_g_test {
namespace gt = grasu_test;

inline std::size_t legacy_extent(const GraSuPmaLayout &part) {
  return std::max(kCache + 1, (part.segments.size() + 1) / 2);
}

inline std::vector<std::uint8_t> legacy_pma(const GraSuPmaLayout &before,
                                           const GraSuPmaLayout &after, unsigned bank) {
  auto bytes = blank(legacy_extent(before) * 64);
  for (std::size_t s = bank / 2; s < before.segments.size(); s += 2) {
    const auto owner = s % 2 * 2 + (s / 2 >= kCache);
    segment_bytes(bytes, s / 2, owner == bank ? after.segments[s] : before.segments[s]);
  }
  bytes.insert(bytes.end(), 64, 0xa5);
  return bytes;
}

inline void initialize_legacy(MemoryBackend &backend, const GraSuPmaLayout &part) {
  for (unsigned bank = 0; bank < 4; ++bank) backend.initialize_payload(bank, 0, legacy_pma(part, part, bank));
  GraSuNativeConfig config;
  config.memory_channels = 4;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.pma_base = 0;
  config.row_offset_base = gt::kRows;
  config.binary_base = gt::kBinary;
  initialize_grasu_pma_layout_payloads(backend, part, config);
}

inline void verify_legacy(MemoryBackend &backend, const GraSuPmaLayout &before,
                          const GraSuPmaLayout &after) {
  for (unsigned bank = 0; bank < 4; ++bank) {
    const auto expected = legacy_pma(before, after, bank);
    require(backend.inspect_payload(bank, 0, expected.size()) == expected,
            "legacy complete PMA, nonowner copy, padding or guard differs");
    std::vector<std::uint8_t> rows(before.vertices * 8), binary(before.binary_heads.size() * 8);
    for (std::size_t v = 0; v < before.vertices; ++v)
      put(rows, v * 8, static_cast<std::uint64_t>(before.row_slot_bounds[v].first) << 32 |
                        before.row_slot_bounds[v].second, 8);
    for (std::size_t s = 0; s < before.binary_heads.size(); ++s) put(binary, s * 8, before.binary_heads[s], 8);
    require(backend.inspect_payload(bank, gt::kRows, rows.size()) == rows &&
                backend.inspect_payload(bank, gt::kBinary, binary.size()) == binary,
            "legacy row or binary metadata changed");
  }
}

inline void begin_original(gt::System &system, const GraSuPmaLayout &part,
                            const std::vector<GraSuEdge> &updates) {
  for (unsigned cu = 0; cu < 4; ++cu) {
    std::vector<std::uint8_t> bytes((updates.size() + 3 - cu) / 4 * 8);
    std::size_t index = 0;
    for (std::size_t i = cu; i < updates.size(); i += 4) {
      const auto &edge = updates[i];
      const auto word = static_cast<std::uint64_t>(edge.source) << 32 |
          encode_grasu_pma_edge(part.local_destination(edge.destination), edge.weight) |
          (edge.delete_op ? 1ULL << 63 : 0);
      put(bytes, index++ * 8, word, 8);
    }
    if (!bytes.empty()) system.memory.backend->initialize_payload(cu, gt::kEdges, bytes);
    system.readers[cu]->begin(gt::kEdges, bytes.size() / 8);
    system.searches[cu]->begin(bytes.size() / 8, gt::kBinary, gt::kRows,
                               part.segments.size(), part.vertices);
  }
  system.dispatch->begin(updates.size());
  for (unsigned half = 0; half < 2; ++half) {
    system.stores[half]->begin();
    system.cache_dispatch[half]->begin();
    system.ddr_dispatch[half]->begin();
    for (auto *pe : system.cache[half]) pe->begin();
    for (auto *core : system.ddr[half]) core->begin(0, legacy_extent(part));
  }
  system.started = true;
}

template <class Input>
inline Observation original(const Input &f, unsigned latency) {
  Observation result;
  for (std::size_t shard = 0; shard < f.by_shard.size(); ++shard) {
    if (f.by_shard[shard].empty()) continue;
    gt::System system(16, latency, 32, false);
    initialize_legacy(*system.memory.backend, f.initial.partitions[shard]);
    begin_original(system, f.initial.partitions[shard], f.by_shard[shard]);
    std::uint64_t cycles = 0;
    while (cycles < kLimit && !system.finished()) { system.memory.scheduler.step(); ++cycles; }
    require(system.finished(), "original prepared-shard G cycle limit");
    result.cycles += cycles;
    verify_legacy(*system.memory.backend, f.initial.partitions[shard], f.expected.partitions[shard]);
    const auto traffic = system.memory.backend->traffic_stats();
    result.reads += traffic.reads.bytes;
    result.writes += traffic.writes.bytes;
    for (const auto *search : system.searches) {
      require(search->counters().reads == search->counters().acknowledgements, "original search did not drain");
      for (const auto &request : search->requests()) {
        if (request.kind) ++result.probes;
        else ++result.rows;
      }
    }
    for (unsigned half = 0; half < 2; ++half) {
      for (const auto *pe : system.cache[half]) result.cache += pe->counters().updates;
      for (const auto *pe : system.ddr[half]) result.ddr += pe->counters().updates;
    }
    for (const auto &link : system.memory.links) {
      const auto &s = link.master->stats();
      require(s.requests_accepted == s.requests_completed && s.beats_issued == s.beats_completed &&
                  s.zero_filled_write_bytes == 0, "original AXI requests or payload not conserved");
    }
  }
  result.pma_reads = result.pma_writes = f.touched() * 2 * kCache * 64 + result.ddr * 64;
  require(result.reads == f.updates.size() * 8 + result.rows * 8 + result.probes * 8 + result.pma_reads &&
              result.writes == result.pma_writes, "original complete byte ledger mismatch");
  return result;
}
} // namespace sharded_g_test
