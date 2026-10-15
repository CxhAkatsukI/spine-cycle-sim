#pragma once

#include <algorithm>
#include <cstdint>
#include <functional>
#include <map>
#include <queue>
#include <stdexcept>
#include <utility>
#include <vector>

namespace continuous_sssp {
using Edges = std::map<std::pair<unsigned, unsigned>, unsigned>;
using Values = std::vector<std::uint32_t>;
constexpr std::uint32_t kInf = 0x7ffffffeU;
constexpr std::uint32_t kActive = 0x80000000U;

inline void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

inline Values shortest_paths(unsigned vertices, const Edges& edges, unsigned source) {
  require(source < vertices, "SSSP source outside graph");
  std::vector<std::vector<std::pair<unsigned, unsigned>>> adjacency(vertices);
  for (const auto& [key, weight] : edges) {
    require(key.first < vertices && key.second < vertices && weight && weight < 4096,
            "SSSP edge outside weighted ABI");
    adjacency[key.first].emplace_back(key.second, weight);
  }
  Values distance(vertices, kInf);
  using Item = std::pair<std::uint32_t, unsigned>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> pending;
  distance[source] = 0;
  pending.emplace(0, source);
  while (!pending.empty()) {
    const auto [value, vertex] = pending.top();
    pending.pop();
    if (value != distance[vertex]) continue;
    for (const auto& [destination, weight] : adjacency[vertex]) {
      const auto next = std::min<std::uint64_t>(std::uint64_t(value) + weight, kInf);
      if (next < distance[destination]) {
        distance[destination] = next;
        pending.emplace(next, destination);
      }
    }
  }
  return distance;
}

struct Plan {
  bool fallback = false;
  Values initial;
  std::vector<unsigned> seeds;
};

inline Plan prepare(const Edges& before, const Edges& after, const Values& resident, unsigned source) {
  require(source < resident.size() && resident[source] == 0 &&
          std::all_of(resident.begin(), resident.end(), [](auto value) { return value <= kInf; }),
          "previous result must be a complete unflagged SSSP state");
  Plan plan;
  for (const auto& [key, weight] : before) {
    const auto found = after.find(key);
    if (found == after.end() || found->second > weight) plan.fallback = true;
  }
  plan.initial = plan.fallback ? Values(resident.size(), kInf) : resident;
  if (plan.fallback) {
    plan.initial[source] = 0;
    plan.seeds.push_back(source);
  } else {
    for (const auto& [key, weight] : after) {
      const auto found = before.find(key);
      if (found == before.end() || weight < found->second) plan.seeds.push_back(key.first);
    }
    std::sort(plan.seeds.begin(), plan.seeds.end());
    plan.seeds.erase(std::unique(plan.seeds.begin(), plan.seeds.end()), plan.seeds.end());
  }
  for (auto vertex : plan.seeds) {
    require(vertex < plan.initial.size(), "seed outside graph");
    plan.initial[vertex] |= kActive;
  }
  return plan;
}

struct Reference {
  Values values;
  std::vector<unsigned> active_counts;
};

inline Reference relax(const Edges& edges, const Plan& plan, unsigned limit) {
  Reference result{plan.initial, {}};
  for (unsigned round = 0; round < limit; ++round) {
    Values next = result.values;
    for (auto& value : next) value &= ~kActive;
    for (const auto& [key, weight] : edges) {
      require(key.first < next.size() && key.second < next.size(), "edge outside reference state");
      if (!(result.values[key.first] & kActive)) continue;
      const auto candidate = std::min<std::uint64_t>(
          std::uint64_t(result.values[key.first] & ~kActive) + weight, kInf);
      if (candidate < (next[key.second] & ~kActive)) next[key.second] = candidate | kActive;
    }
    const auto active = std::count_if(next.begin(), next.end(), [](auto value) { return value & kActive; });
    result.active_counts.push_back(active);
    result.values = std::move(next);
    if (!active) return result;
  }
  throw std::runtime_error("SSSP reference did not converge within the declared round limit");
}
}  // namespace continuous_sssp
