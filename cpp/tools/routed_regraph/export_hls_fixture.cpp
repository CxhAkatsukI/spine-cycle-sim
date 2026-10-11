#include "fixture_oracle.hpp"
#include "weighted_pma_update_reference.hpp"

#include <fstream>
#include <iostream>
#include <set>

namespace {
using namespace grasu::integration;
struct Dataset { std::size_t vertices{}; std::vector<WeightedEdgeRecord> edges, updates; };
Dataset load(const std::string &path) {
  std::ifstream input(path);
  Dataset data;
  std::size_t edges{}, updates{};
  if (!(input >> data.vertices >> edges >> updates) || !data.vertices || data.vertices > 255ULL * 65536)
    throw std::invalid_argument("invalid hardware graph header");
  const auto edge = [&](bool update) {
    std::uint32_t src{}, dst{}, weight{}, type = 1;
    if (!(input >> src >> dst >> weight) || (update && !(input >> type)) ||
        src >= data.vertices || dst >= data.vertices || !weight || weight > 4095 || type > 1)
      throw std::invalid_argument("invalid hardware graph edge");
    return WeightedEdgeRecord{src, dst, static_cast<std::uint16_t>(weight), type == 0};
  };
  for (std::size_t i = 0; i < edges; ++i) data.edges.push_back(edge(false));
  for (std::size_t i = 0; i < updates; ++i) data.updates.push_back(edge(true));
  std::string trailing;
  if (input >> trailing) throw std::invalid_argument("trailing hardware graph token");
  return data;
}
class Writer {
public:
  explicit Writer(const std::string &path) : output(path, std::ios::binary) {
    if (!output) throw std::invalid_argument("cannot open fixture output");
  }
  void word(std::uint64_t value) {
    if (value > 0xffffffffULL) throw std::overflow_error("fixture u32 overflow");
    unsigned char bytes[4];
    for (std::size_t i = 0; i < 4; ++i) bytes[i] = value >> (8 * i);
    if (!output.write(reinterpret_cast<char *>(bytes), 4)) throw std::runtime_error("fixture write failed");
  }
  void finish() { output.flush(); if (!output) throw std::runtime_error("fixture flush failed"); }
private:
  std::ofstream output;
};
}

int main(int argc, char **argv) {
  try {
    if (argc != 4) throw std::invalid_argument("usage: export_hls_fixture GRAPH SOURCE OUTPUT");
    auto data = load(argv[1]);
    std::size_t consumed{};
    const auto source = std::stoul(argv[2], &consumed);
    if (consumed != std::string(argv[2]).size() || source >= data.vertices)
      throw std::invalid_argument("invalid fixture source");
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::uint16_t> old;
    for (const auto &edge : data.edges) old[{edge.source, edge.destination}] = edge.weight;
    for (const auto &edge : data.updates) {
      const auto found = old.find({edge.source, edge.destination});
      if (edge.delete_op || (found != old.end() && edge.weight > found->second))
        throw std::invalid_argument("fixture requires resident insertion/decrease SSSP");
    }
    auto graph = build_weighted_partitioned_pma_graph(data.vertices, 65536, data.edges, data.updates);
    // The board validates these exact touched segments after GraSU. Do not
    // reconstruct a compact final graph and discard reserved/padding slots.
    for (const auto &touch : build_weighted_pma_update_reference(graph, 131072))
      std::copy(touch.expected.begin(), touch.expected.end(),
          graph.shards.at(touch.shard).initial_pma_words.begin() + touch.logical_segment * 16);
    const auto initial = routed_fixture::distances(routed_fixture::adjacency(data.vertices, graph.initial_internal),
                                                  graph.external_to_internal[source]);
    const auto final_graph = routed_fixture::adjacency(data.vertices, graph.final_internal);
    const auto expected = routed_fixture::distances(final_graph, graph.external_to_internal[source]);
    std::set<std::uint32_t> sources;
    for (const auto &edge : data.updates) sources.insert(graph.external_to_internal[edge.source]);
    const std::vector<std::uint32_t> active(sources.begin(), sources.end());
    const auto rounds = routed_fixture::resident_rounds(final_graph, initial, active, expected);
    Writer output(argv[3]);
    for (auto value : {0x4b345331ULL, 1ULL, static_cast<unsigned long long>(data.vertices),
                      static_cast<unsigned long long>(graph.shards.size()), 131072ULL,
                      static_cast<unsigned long long>(rounds), static_cast<unsigned long long>(active.size())})
      output.word(value);
    for (auto value : graph.internal_to_external) output.word(value);
    for (auto value : initial) output.word(value);
    for (auto value : active) output.word(value);
    for (auto value : expected) output.word(value);
    std::size_t slots = 0;
    for (const auto &shard : graph.shards) {
      output.word(shard.physical_updates.size());
      output.word(shard.initial_pma_words.size());
      for (std::size_t v = 0; v < data.vertices; ++v) {
        output.word(shard.row_bounds[v] >> 32);
        output.word(static_cast<std::uint32_t>(shard.row_bounds[v]));
      }
      for (auto value : shard.initial_pma_words) output.word(value);
      slots += shard.initial_pma_words.size();
    }
    output.finish();
    std::cout << "vertices=" << data.vertices << " partitions=" << graph.shards.size()
              << " slots=" << slots << " rounds=" << rounds << " active=" << active.size()
              << " edges=" << graph.final_internal.size() << '\n';
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
