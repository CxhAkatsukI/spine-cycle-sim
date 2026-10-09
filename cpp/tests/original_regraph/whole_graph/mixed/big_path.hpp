#pragma once

#include "resources.hpp"
#include "spine_sim/original_regraph/big_requests.hpp"
#include "spine_sim/original_regraph/big_source_memory.hpp"
#include "spine_sim/original_regraph/big_scatter.hpp"
#include "spine_sim/original_regraph/big_merge.hpp"
#include "spine_sim/original_regraph/edge_reader.hpp"

namespace original_regraph_mixed_test {

struct BigPath : Tasks {
  MemoryLink edge_port, source_port;
  Fifo<rg::EdgeBurst>* raw{}, *edges{}, *sources{};
  Fifo<rg::CachelineBatch>* batches{};
  Fifo<rg::CachelineRequest>* requests{};
  Fifo<rg::CachelineResponse>* responses{};
  std::array<Fifo<rg::LaneProperty>*, 8> properties{};
  Fifo<rg::UpdateBurst>* updates{};
  rg::LittleEdgeReader* reader{};
  rg::BigEdgeFork* fork{};
  rg::BigRequestGenerator* generator{};
  rg::BigCachelineSender* sender{};
  rg::BigSourceMemory* source{};
  rg::BigResponseRouter* router{};
  rg::BigScatter* scatter{};
  std::array<rg::RoutedPorts, 4> layers{};
  rg::BigDispatch* dispatch{};
  std::vector<rg::BigOmegaSwitch*> switches;
  std::array<Fifo<rg::VertexPair>*, 8> rows{};
  std::array<rg::BigGatherBank*, 8> banks{};
  Fifo<rg::PropertyLine>* output{};
  rg::BigResultPacker* packer{};

  BigPath(Resources& memory, unsigned index, std::uint64_t property_bytes) {
    const auto name = "big" + std::to_string(index);
    const auto clock = memory.clock;
    edge_port = memory.port(name + ".edge_axi", index * 2 + 1, index * 2);
    source_port = memory.port(name + ".source_axi", index * 2 + 2, index * 2 + 1, 16, 16);
    raw = memory.stream<rg::EdgeBurst>(name + ".raw", 32);
    edges = memory.stream<rg::EdgeBurst>(name + ".edges", 32);
    sources = memory.stream<rg::EdgeBurst>(name + ".sources", 16);
    batches = memory.stream<rg::CachelineBatch>(name + ".batches", 32);
    requests = memory.stream<rg::CachelineRequest>(name + ".requests", 32);
    responses = memory.stream<rg::CachelineResponse>(name + ".responses", 32);
    updates = memory.stream<rg::UpdateBurst>(name + ".updates", 16);
    reader = memory.make<rg::LittleEdgeReader>(name + ".reader", clock, edge_port.ports(), *raw);
    fork = memory.make<rg::BigEdgeFork>(name + ".fork", clock, *raw, *edges, *sources);
    generator = memory.make<rg::BigRequestGenerator>(name + ".generator", clock, *sources, *batches);
    sender = memory.make<rg::BigCachelineSender>(name + ".sender", clock, *batches, *requests);
    source = memory.make<rg::BigSourceMemory>(name + ".source", clock, source_port.ports(), *requests, *responses, 0, property_bytes, 32);
    for (unsigned lane = 0; lane < 8; ++lane) properties[lane] = memory.stream<rg::LaneProperty>(name + ".property" + std::to_string(lane), 32);
    router = memory.make<rg::BigResponseRouter>(name + ".router", clock, *responses, properties);
    scatter = memory.make<rg::BigScatter>(name + ".scatter", clock, *edges, properties, *updates);
    for (unsigned stage = 0; stage < 4; ++stage) for (unsigned lane = 0; lane < 8; ++lane) {
      layers[stage][lane] = memory.stream<rg::RoutedUpdate>(name + ".layer" + std::to_string(stage) + ".lane" + std::to_string(lane), stage ? 2 : 16);
    }
    dispatch = memory.make<rg::BigDispatch>(name + ".dispatch", clock, *updates, layers[0]);
    for (unsigned stage = 0; stage < 3; ++stage) for (unsigned pair = 0; pair < 4; ++pair) {
      switches.push_back(memory.make<rg::BigOmegaSwitch>(name + ".switch" + std::to_string(stage * 4 + pair), clock, 2 - stage,
          std::array{layers[stage][pair], layers[stage][pair + 4]}, std::array{layers[stage + 1][pair * 2], layers[stage + 1][pair * 2 + 1]}, 2));
    }
    for (unsigned bank = 0; bank < 8; ++bank) {
      rows[bank] = memory.stream<rg::VertexPair>(name + ".row" + std::to_string(bank), 4);
      banks[bank] = memory.make<rg::BigGatherBank>(name + ".bank" + std::to_string(bank), clock, bank, *layers[3][bank], *rows[bank]);
    }
    output = memory.stream<rg::PropertyLine>(name + ".packed", 8);
    packer = memory.make<rg::BigResultPacker>(name + ".packer", clock, rows, *output);
  }
  bool ready() const {
    if (!reader->finished() || !fork->finished() || !generator->finished() || !sender->finished() || !router->finished() ||
        !scatter->finished() || !dispatch->finished() || !packer->finished() || !output->empty() ||
        !edge_port.master->idle() || !source_port.master->idle()) return false;
    for (auto* sw : switches) if (!sw->drained()) return false;
    for (auto* bank : banks) if (!bank->finished()) return false;
    return true;
  }
  void begin(const Task& task) {
    const auto bursts = task.words / 16;
    reader->begin_partition(task.address, task.words / 2, task.destination);
    fork->begin_partition(bursts); generator->begin_partition(bursts); sender->begin_partition();
    router->begin_partition(); scatter->begin_partition(bursts); dispatch->begin_partition(bursts);
    for (auto* sw : switches) sw->begin_partition();
    for (auto* bank : banks) bank->begin_partition();
    packer->begin_partition();
  }
};

}  // namespace original_regraph_mixed_test
