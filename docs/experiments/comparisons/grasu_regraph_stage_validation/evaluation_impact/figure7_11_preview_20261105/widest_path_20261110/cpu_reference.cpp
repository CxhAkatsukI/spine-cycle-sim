// Independent max-min oracle for the frozen weighted Fig. 7 graph format.
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <queue>
#include <stdexcept>
#include <utility>
#include <vector>

using Vertex = uint32_t;
using Width = uint32_t;
using State = std::vector<Width>;
constexpr Width kMaxCapacity = 4095;  // Existing common weighted edge ABI.
constexpr Width kSourceWidth = std::numeric_limits<Width>::max();

struct Edge {
  Vertex dst;
  Width capacity;
};
using Graph = std::vector<std::vector<Edge>>;

struct Batch {
  Graph graph;
  std::vector<std::pair<Vertex, Edge>> insertions;
  uint64_t old_edges;
};

static Batch read_batch(std::istream& input, uint64_t source) {
  uint64_t vertices, edges, updates;
  if (!(input >> vertices >> edges >> updates) || source >= vertices ||
      vertices > std::numeric_limits<Vertex>::max()) {
    throw std::runtime_error("invalid graph header or source");
  }
  Batch batch{Graph(vertices), {}, edges};
  auto read_edge = [&]() -> std::pair<Vertex, Edge> {
    uint64_t src, dst, capacity;
    if (!(input >> src >> dst >> capacity) || src >= vertices ||
        dst >= vertices || capacity == 0 || capacity > kMaxCapacity) {
      throw std::runtime_error("invalid edge or unsupported capacity");
    }
    return {static_cast<Vertex>(src),
            {static_cast<Vertex>(dst), static_cast<Width>(capacity)}};
  };
  for (uint64_t i = 0; i < edges; ++i) {
    const auto [src, edge] = read_edge();
    batch.graph[src].push_back(edge);
  }
  for (uint64_t i = 0; i < updates; ++i) {
    auto record = read_edge();
    int operation;
    if (!(input >> operation) || operation != 1) {
      throw std::runtime_error("expected an insertion");
    }
    batch.insertions.push_back(record);
  }
  input >> std::ws;
  if (!input.eof() || input.bad()) {
    throw std::runtime_error("extra records after the batch");
  }
  return batch;
}

static State solve(const Graph& graph, Vertex source) {
  State width(graph.size());
  std::priority_queue<std::pair<Width, Vertex>> ready;
  width[source] = kSourceWidth;
  ready.emplace(width[source], source);
  while (!ready.empty()) {
    const auto [value, src] = ready.top();
    ready.pop();
    if (value != width[src]) continue;
    for (const auto& [dst, capacity] : graph[src]) {
      const Width candidate = std::min(value, capacity);
      if (candidate <= width[dst]) continue;
      width[dst] = candidate;
      ready.emplace(candidate, dst);
    }
  }
  return width;
}

struct Repair {
  State width;
  uint64_t waves = 0;
  uint64_t edge_visits = 0;
};

static Repair repair(const Batch& batch, const State& before) {
  Repair result{before};
  auto& width = result.width;
  std::vector<bool> queued(width.size());
  std::vector<Vertex> frontier, next;
  auto improve = [&](Vertex dst, Width candidate, std::vector<Vertex>& queue) {
    if (candidate <= width[dst]) return;
    width[dst] = candidate;
    if (!queued[dst]) {
      queued[dst] = true;
      queue.push_back(dst);
    }
  };
  for (const auto& [src, edge] : batch.insertions) {
    improve(edge.dst, std::min(before[src], edge.capacity), frontier);
  }
  std::vector<Width> frontier_widths;
  while (!frontier.empty()) {
    ++result.waves;
    frontier_widths.clear();
    for (const Vertex src : frontier) {
      queued[src] = false;
      frontier_widths.push_back(width[src]);
    }
    for (size_t i = 0; i < frontier.size(); ++i) {
      for (const auto& [dst, capacity] : batch.graph[frontier[i]]) {
        ++result.edge_visits;
        improve(dst, std::min(frontier_widths[i], capacity), next);
      }
    }
    frontier.swap(next);
    next.clear();
  }
  return result;
}

static uint64_t fingerprint(const State& state) {
  uint64_t hash = 14695981039346656037ull;
  for (const Width width : state) {
    for (unsigned shift = 0; shift < 32; shift += 8) {
      hash ^= (width >> shift) & 0xffu;
      hash *= 1099511628211ull;
    }
  }
  return hash;
}

int main(int argc, char** argv) {
  try {
    if (argc != 3 && argc != 4) {
      throw std::runtime_error("usage: cpu_reference GRAPH SOURCE [STATE_TSV]");
    }
    size_t parsed;
    const auto source = std::stoull(argv[2], &parsed);
    if (argv[2][parsed] != '\0') throw std::runtime_error("invalid source");
    std::ifstream input(argv[1]);
    auto batch = read_batch(input, source);
    const State before = solve(batch.graph, static_cast<Vertex>(source));
    for (const auto& [src, edge] : batch.insertions) {
      batch.graph[src].push_back(edge);
    }
    const State after = solve(batch.graph, static_cast<Vertex>(source));
    const auto repaired = repair(batch, before);
    if (after != repaired.width) {
      throw std::runtime_error("incremental repair differs from full recompute");
    }
    uint64_t changed = 0, old_reachable = 0, new_reachable = 0;
    for (size_t i = 0; i < before.size(); ++i) {
      if (after[i] < before[i]) throw std::runtime_error("non-monotone insertion");
      changed += (before[i] != after[i]);
      old_reachable += (before[i] != 0);
      new_reachable += (after[i] != 0);
    }
    if (argc == 4) {
      std::ofstream state(argv[3]);
      state << "vertex\told_width\tnew_width\n";
      for (size_t i = 0; i < before.size(); ++i) {
        state << i << '\t' << before[i] << '\t' << after[i] << '\n';
      }
      state.close();
      if (!state) throw std::runtime_error("could not write the full state");
    }
    std::cout << before.size() << ',' << batch.old_edges << ','
              << batch.insertions.size() << ',' << source << ',' << old_reachable
              << ',' << new_reachable << ',' << changed << ',' << repaired.waves
              << ',' << repaired.edge_visits << ',' << std::hex
              << std::setfill('0') << std::setw(16) << fingerprint(before) << ','
              << std::setw(16) << fingerprint(after) << ",PASS\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
