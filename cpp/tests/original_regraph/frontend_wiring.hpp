#pragma once

#include <algorithm>
#include <functional>

#include "frontend_support.hpp"

namespace original_regraph_frontend_test {

using original_regraph_memory_test::MemoryLink;

struct Path {
  MemoryLink edge_port;
  MemoryLink source_port;
  Fifo<rg::EdgeBurst>* edges{};
  Fifo<rg::SourceRequest>* requests{};
  Fifo<rg::SourceResponse>* responses{};
  Fifo<rg::UpdateBurst>* updates{};
  rg::LittleEdgeReader* reader{};
  rg::LittleSourceMemory* source{};
  rg::LittleScatter* scatter{};
  rg::LittleGather* gather{};
  rg::LittleLocalMerge* local_merge{};
};

class Wiring {
 public:
  explicit Wiring(Options options)
      : memory(options.fifo_depth, options.memory_latency), options(options),
        scheduler(memory.scheduler), clock(memory.clock), backend(memory.backend) {
    require(options.little > 0 && options.little <= 14, "invalid Little test topology");
    std::vector<Fifo<rg::VertexPair>*> local_outputs;
    for (std::size_t index = 0; index < options.little; ++index) {
      const auto name = "little" + std::to_string(index);
      Path path;
      path.edge_port = memory.port(name + ".edge_axi", index * 2 + 1, index * 2, options.outstanding);
      path.source_port = memory.port(name + ".source_axi", index * 2 + 2, index * 2 + 1, options.outstanding);
      path.edges = memory.queue<rg::EdgeBurst>(name + ".edges");
      path.requests = memory.queue<rg::SourceRequest>(name + ".requests");
      path.responses = memory.queue<rg::SourceResponse>(name + ".responses");
      path.updates = memory.queue<rg::UpdateBurst>(name + ".updates");
      path.reader = memory.make<rg::LittleEdgeReader>(name + ".reader", clock, path.edge_port.ports(), *path.edges);
      path.source = memory.make<rg::LittleSourceMemory>(name + ".source", clock, path.source_port.ports(),
          *path.requests, *path.responses, 0, options.property_vertices * 4);
      path.scatter = memory.make<rg::LittleScatter>(name + ".scatter", clock, *path.edges,
          *path.requests, *path.responses, *path.updates, rg::kScatterTiming, 64);
      if (options.gather) {
        rg::GatherOutputs lanes;
        for (std::size_t lane = 0; lane < lanes.size(); ++lane) {
          lanes[lane] = memory.queue<rg::VertexPair>(name + ".lane" + std::to_string(lane));
        }
        auto* local_output = memory.queue<rg::VertexPair>(name + ".local_output");
        path.gather = memory.make<rg::LittleGather>(name + ".gather", clock, *path.updates, lanes);
        path.local_merge = memory.make<rg::LittleLocalMerge>(name + ".local_merge", clock, lanes, *local_output);
        local_outputs.push_back(local_output);
      }
      paths.push_back(path);
    }
    if (options.gather) {
      merged_output = memory.queue<rg::PropertyLine>("global_output");
      global_merge = memory.make<rg::LittleGlobalMerge>("global_merge", clock, local_outputs, *merged_output);
    }
    memory.register_components(options.reverse_registration);
  }

  void begin(const std::vector<std::vector<rg::EdgeBurst>>& edges,
             bool initialize_properties = true, std::uint64_t property_address = 0) {
    require(edges.size() == paths.size(), "frontend fixture topology mismatch");
    std::vector<std::uint8_t> properties;
    for (std::size_t vertex = 0; vertex < options.property_vertices; ++vertex) {
      append_word(properties, 17 + vertex % 31);
    }
    for (std::size_t index = 0; index < paths.size(); ++index) {
      auto& path = paths[index];
      backend->initialize_payload(index * 2, 0, edge_bytes(edges[index], options.destination_offset));
      if (initialize_properties) backend->initialize_payload(index * 2 + 1, property_address, properties);
      path.reader->begin_partition(0, edges[index].size() * 8, options.destination_offset);
      path.source->begin_partitions(1, property_address);
      path.scatter->begin_partition(edges[index].size() * 8);
      if (path.gather) path.gather->begin_partition(edges[index].size());
    }
  }

  bool drained() const {
    return memory.drained() &&
        std::all_of(paths.begin(), paths.end(), [](const auto& path) {
          return path.reader->finished() && path.source->finished() && path.scatter->finished() &&
              path.edge_port.master->idle() && path.source_port.master->idle() &&
              (!path.gather || (path.gather->finished() && path.local_merge->drained()));
        }) && (!global_merge || global_merge->drained());
  }

  original_regraph_memory_test::MemoryFixture memory;
  Options options;
  spine::sim::Scheduler& scheduler;
  spine::sim::ClockId clock;
  spine::sim::MockMemoryBackend* backend{};
  std::vector<Path> paths;
  Fifo<rg::PropertyLine>* merged_output{};
  rg::LittleGlobalMerge* global_merge{};

};

}  // namespace original_regraph_frontend_test
