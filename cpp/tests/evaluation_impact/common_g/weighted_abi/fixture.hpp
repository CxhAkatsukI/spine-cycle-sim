#pragma once

#include "integration/weighted_pma_graph.hpp"
#include <array>
#include <iostream>
#include <string>
#include <tuple>

namespace weighted_control {
namespace host = grasu::integration;
using Edge = host::WeightedEdgeRecord;
using EdgeMap = std::map<std::pair<unsigned, unsigned>, unsigned>;
using Slots = std::array<unsigned, 16>;
using Segment = ap_uint<512>;
inline void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
struct Fixture {
  const char* name;
  unsigned vertices, partition;
  std::vector<Edge> initial, updates;
};
inline std::vector<Fixture> fixtures() {
  std::vector<Fixture> result{{"empty", 8, 4, {}, {}},
      {"segment_weights", 128, 64, {}, {}},
      {"repeated_weights", 96, 32, {}, {}},
      {"dst19_weight12_boundary", 524288, 524288,
       {{0, 524287, 4095}, {0, 524286, 1}},
       {{0, 524287, 1}, {0, 524286, 4095}, {0, 524287, 1, true}}}};
  for (unsigned dst = 1; dst <= 120; ++dst)
    result[1].initial.push_back({0, dst, std::uint16_t(1 + dst % 7)});
  for (unsigned dst : {1u, 16u, 17u, 31u, 32u, 63u, 64u, 95u, 120u}) {
    result[1].updates.push_back({0, dst, 4095});
    result[1].updates.push_back({0, dst, 4095, true});
    result[1].updates.push_back({0, dst, 1});
  }
  for (unsigned source : {0u, 3u, 8u, 17u}) {
    result[2].initial.push_back({source, 95, 4095});
    result[2].initial.push_back({source, 33, 1});
    for (unsigned weight : {1u, 2048u, 4095u, 2u})
      result[2].updates.push_back({source, 95, std::uint16_t(weight)});
    result[2].updates.push_back({source, 33, 1, true});
    result[2].updates.push_back({source, 33, 4095});
  }
  return result;
}
inline EdgeMap external_oracle(const Fixture& fixture) {
  EdgeMap result;
  for (auto edge : fixture.initial)
    require(result.emplace(std::pair{edge.source, edge.destination}, edge.weight).second,
            "duplicate oracle initial edge");
  for (auto edge : fixture.updates) {
    auto key = std::pair{edge.source, edge.destination};
    if (edge.delete_op) {
      require(result.contains(key) && result.at(key) == edge.weight, "invalid oracle deletion");
      result.erase(key);
    } else result[key] = edge.weight;
  }
  return result;
}
inline Segment pack(const Slots& words) {
  Segment result = 0;
  for (unsigned lane = 0; lane < 16; ++lane)
    result.range(lane * 32 + 31, lane * 32) = words[lane];
  return result;
}
inline Slots unpack(const Segment& value) {
  Slots result;
  for (unsigned lane = 0; lane < 16; ++lane)
    result[lane] = value.range(lane * 32 + 31, lane * 32).to_uint();
  return result;
}
inline void edit_oracle(Slots& words, std::uint64_t raw) {
  const unsigned key = raw;
  std::vector<unsigned> live;
  for (auto word : words) if (!(word & 0x80000000u)) live.push_back(word);
  auto position = std::lower_bound(live.begin(), live.end(), key);
  if (raw >> 63) {
    require(position != live.end() && *position == key, "physical deletion absent");
    live.erase(position);
  } else {
    require(live.size() < 16 && (position == live.end() || *position != key),
            "physical insertion duplicate or full");
    live.insert(position, key);
  }
  words.fill(0x80000000u);
  std::copy(live.begin(), live.end(), words.begin());
}
}  // namespace weighted_control
