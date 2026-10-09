#pragma once

#include "big_frontend_fixture.hpp"
#include "spine_sim/original_regraph/big_requests.hpp"
#include "spine_sim/original_regraph/big_source_memory.hpp"
#include "spine_sim/original_regraph/big_scatter.hpp"

namespace original_regraph_big_frontend_test {
using spine::sim::Fifo;
using original_regraph_memory_test::MemoryLink;

struct Options {
  std::size_t fifo_depth{};  // Zero selects the author's named stream depths.
  std::uint64_t latency{64};
  std::size_t outstanding{16};
  std::size_t live{32};
  std::size_t property_vertices{131072};
  unsigned destination_offset{};
  bool reverse{};
  std::uint64_t sink_start{};
  std::uint64_t sink_interval{1};
};

class Network {
 public:
  explicit Network(Options options = {}) : memory(options.fifo_depth ? options.fifo_depth : 32, options.latency), options(options) {
    const auto clock = memory.clock;
    edge_port = memory.port("big.edge_axi", 1, 22, options.outstanding, 2);
    source_port = memory.port("big.source_axi", 2, 23, options.outstanding, options.outstanding);
    raw_edges = queue<rg::EdgeBurst>("big.raw_edges", 32);
    edges = queue<rg::EdgeBurst>("big.scatter_edges", 32);
    sources = queue<rg::EdgeBurst>("big.sources", 16);
    batches = queue<rg::CachelineBatch>("big.request_batches", 32);
    requests = queue<rg::CachelineRequest>("big.requests", 32);
    responses = queue<rg::CachelineResponse>("big.responses", 32);
    output = queue<rg::UpdateBurst>("big.updates", 16);
    for (unsigned lane = 0; lane < 8; ++lane) properties[lane] = queue<rg::LaneProperty>("big.lane" + std::to_string(lane), 32);
    reader = memory.make<rg::LittleEdgeReader>("big.edge_reader", clock, edge_port.ports(), *raw_edges);
    fork = memory.make<rg::BigEdgeFork>("big.edge_fork", clock, *raw_edges, *edges, *sources);
    generator = memory.make<rg::BigRequestGenerator>("big.generator", clock, *sources, *batches);
    sender = memory.make<rg::BigCachelineSender>("big.sender", clock, *batches, *requests, 65536);
    source = memory.make<rg::BigSourceMemory>("big.source", clock, source_port.ports(), *requests, *responses,
        0, options.property_vertices * 4, options.live);
    router = memory.make<rg::BigResponseRouter>("big.router", clock, *responses, properties);
    scatter = memory.make<rg::BigScatter>("big.scatter", clock, *edges, properties, *output);
    memory.register_components(options.reverse);
  }

  void begin(const std::vector<rg::EdgeBurst>& fixture) {
    std::vector<std::uint8_t> data;
    for (std::size_t vertex = 0; vertex < options.property_vertices; ++vertex) append_word(data, property(vertex));
    memory.backend->initialize_payload(22, 0, original_regraph_frontend_test::edge_bytes(fixture, options.destination_offset));
    memory.backend->initialize_payload(23, 0, data);
    reader->begin_partition(0, fixture.size() * 8, options.destination_offset);
    fork->begin_partition(fixture.size());
    generator->begin_partition(fixture.size());
    sender->begin_partition(); source->begin_partitions(1); router->begin_partition(); scatter->begin_partition(fixture.size());
  }
  bool drained() const {
    return reader->finished() && fork->finished() && generator->finished() && sender->finished() &&
        source->finished() && router->finished() && scatter->finished() && memory.drained() &&
        std::all_of(queue_checks_.begin(), queue_checks_.end(), [](const auto& check) { return check(); });
  }
  original_regraph_memory_test::MemoryFixture memory;
  Options options;
  MemoryLink edge_port, source_port;
  Fifo<rg::EdgeBurst>* raw_edges{}, *edges{}, *sources{};
  Fifo<rg::CachelineBatch>* batches{};
  Fifo<rg::CachelineRequest>* requests{};
  Fifo<rg::CachelineResponse>* responses{};
  Fifo<rg::UpdateBurst>* output{};
  rg::LanePropertyPorts properties{};
  rg::LittleEdgeReader* reader{};
  rg::BigEdgeFork* fork{};
  rg::BigRequestGenerator* generator{};
  rg::BigCachelineSender* sender{};
  rg::BigSourceMemory* source{};
  rg::BigResponseRouter* router{};
  rg::BigScatter* scatter{};
 private:
  template <typename T> Fifo<T>* queue(const std::string& name, std::size_t depth) {
    auto* pointer = memory.make<Fifo<T>>(name, memory.clock, options.fifo_depth ? options.fifo_depth : depth);
    queue_checks_.push_back([pointer] { return pointer->empty() && pointer->stats().pushes == pointer->stats().pops &&
        pointer->stats().max_occupancy <= pointer->depth(); });
    return pointer;
  }
  std::vector<std::function<bool()>> queue_checks_;
};

}  // namespace original_regraph_big_frontend_test
