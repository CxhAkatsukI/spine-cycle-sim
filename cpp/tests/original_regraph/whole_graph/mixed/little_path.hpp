#pragma once

#include "resources.hpp"
#include "../../frontend_wiring.hpp"

namespace original_regraph_mixed_test {

struct LittlePath : Tasks {
  original_regraph_frontend_test::Path p;
  rg::GatherOutputs lanes{};
  Fifo<rg::VertexPair>* output{};

  LittlePath(Resources& memory, unsigned index, std::uint64_t property_bytes) {
    const auto name = "little" + std::to_string(index);
    const auto clock = memory.clock;
    p.edge_port = memory.port(name + ".edge_axi", index * 2 + 1, index * 2);
    p.source_port = memory.port(name + ".source_axi", index * 2 + 2, index * 2 + 1);
    p.edges = memory.stream<rg::EdgeBurst>(name + ".edges", 32);
    p.requests = memory.stream<rg::SourceRequest>(name + ".requests", 32);
    p.responses = memory.stream<rg::SourceResponse>(name + ".responses", 32);
    p.updates = memory.stream<rg::UpdateBurst>(name + ".updates", 8);
    p.reader = memory.make<rg::LittleEdgeReader>(name + ".reader", clock, p.edge_port.ports(), *p.edges);
    p.source = memory.make<rg::LittleSourceMemory>(name + ".source", clock, p.source_port.ports(),
        *p.requests, *p.responses, 0, property_bytes);
    p.scatter = memory.make<rg::LittleScatter>(name + ".scatter", clock, *p.edges, *p.requests, *p.responses, *p.updates);
    for (unsigned lane = 0; lane < 8; ++lane) lanes[lane] = memory.stream<rg::VertexPair>(name + ".lane" + std::to_string(lane), 8);
    output = memory.stream<rg::VertexPair>(name + ".output", 8);
    p.gather = memory.make<rg::LittleGather>(name + ".gather", clock, *p.updates, lanes);
    p.local_merge = memory.make<rg::LittleLocalMerge>(name + ".merge", clock, lanes, *output);
  }
  bool ready() const {
    return p.reader->finished() && p.scatter->finished() && p.gather->finished() && p.local_merge->drained() &&
        p.edges->empty() && p.requests->empty() && p.responses->empty() && p.updates->empty() && output->empty() &&
        p.edge_port.master->idle() && p.source_port.master->idle() &&
        std::all_of(lanes.begin(), lanes.end(), [](auto* q) { return q->empty(); });
  }
  void begin(const Task& task) {
    p.reader->begin_partition(task.address, task.words / 2, task.destination);
    p.scatter->begin_partition(task.words / 2); p.gather->begin_partition(task.words / 16);
  }
};

}  // namespace original_regraph_mixed_test
