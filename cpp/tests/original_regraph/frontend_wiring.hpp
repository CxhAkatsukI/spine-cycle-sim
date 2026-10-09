#pragma once

#include <algorithm>
#include <functional>

#include "frontend_support.hpp"

namespace original_regraph_frontend_test {

struct MemoryLink {
  Fifo<spine::sim::AxiRequest>* requests{};
  Fifo<spine::sim::AxiResponse>* responses{};
  Fifo<spine::sim::AxiReadBeatResponse>* beats{};
  spine::sim::AxiMaster* master{};
  rg::ReadPort ports() const { return {*requests, *responses, *beats}; }
};

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
  explicit Wiring(Options options) : options(options), clock(scheduler.add_clock_mhz("core", 210)) {
    require(options.little > 0 && options.little <= 14, "invalid Little test topology");
    backend = make<spine::sim::MockMemoryBackend>("memory", clock, spine::sim::MockMemoryConfig{
        .channels = 32, .latency_cycles = options.memory_latency,
        .accepts_per_channel_per_cycle = 1, .max_outstanding_per_channel = 512,
        .response_queue_depth = 64, .registered_round_robin_arbitration = true});
    std::vector<Fifo<rg::VertexPair>*> local_outputs;
    for (std::size_t index = 0; index < options.little; ++index) {
      const auto name = "little" + std::to_string(index);
      Path path;
      path.edge_port = port(name + ".edge_axi", index * 2 + 1, index * 2);
      path.source_port = port(name + ".source_axi", index * 2 + 2, index * 2 + 1);
      path.edges = queue<rg::EdgeBurst>(name + ".edges");
      path.requests = queue<rg::SourceRequest>(name + ".requests");
      path.responses = queue<rg::SourceResponse>(name + ".responses");
      path.updates = queue<rg::UpdateBurst>(name + ".updates");
      path.reader = make<rg::LittleEdgeReader>(name + ".reader", clock, path.edge_port.ports(), *path.edges);
      path.source = make<rg::LittleSourceMemory>(name + ".source", clock, path.source_port.ports(),
          *path.requests, *path.responses, 0, options.property_vertices * 4);
      path.scatter = make<rg::LittleScatter>(name + ".scatter", clock, *path.edges,
          *path.requests, *path.responses, *path.updates, rg::kScatterTiming, 64);
      if (options.gather) {
        rg::GatherOutputs lanes;
        for (std::size_t lane = 0; lane < lanes.size(); ++lane) {
          lanes[lane] = queue<rg::VertexPair>(name + ".lane" + std::to_string(lane));
        }
        auto* local_output = queue<rg::VertexPair>(name + ".local_output");
        path.gather = make<rg::LittleGather>(name + ".gather", clock, *path.updates, lanes);
        path.local_merge = make<rg::LittleLocalMerge>(name + ".local_merge", clock, lanes, *local_output);
        local_outputs.push_back(local_output);
      }
      paths.push_back(path);
    }
    if (options.gather) {
      merged_output = queue<rg::PropertyLine>("global_output");
      global_merge = make<rg::LittleGlobalMerge>("global_merge", clock, local_outputs, *merged_output);
    }
    if (options.reverse_registration) {
      for (auto item = owned.rbegin(); item != owned.rend(); ++item) scheduler.add_component(**item);
    } else {
      for (const auto& item : owned) scheduler.add_component(*item);
    }
  }

  ~Wiring() {
    // Masters unbind memory/FIFO callbacks; destroy them before their ports.
    while (!owned.empty()) {
      scheduler.remove_component(*owned.back());
      owned.pop_back();
    }
  }

  void begin(const std::vector<std::vector<rg::EdgeBurst>>& edges) {
    require(edges.size() == paths.size(), "frontend fixture topology mismatch");
    std::vector<std::uint8_t> properties;
    for (std::size_t vertex = 0; vertex < options.property_vertices; ++vertex) {
      append_word(properties, 17 + vertex % 31);
    }
    for (std::size_t index = 0; index < paths.size(); ++index) {
      auto& path = paths[index];
      backend->initialize_payload(index * 2, 0, edge_bytes(edges[index], options.destination_offset));
      backend->initialize_payload(index * 2 + 1, 0, properties);
      path.reader->begin_partition(0, edges[index].size() * 8, options.destination_offset);
      path.source->begin_partitions(1);
      path.scatter->begin_partition(edges[index].size() * 8);
      if (path.gather) path.gather->begin_partition(edges[index].size());
    }
  }

  bool drained() const {
    return backend->outstanding() == 0 &&
        std::all_of(paths.begin(), paths.end(), [](const auto& path) {
          return path.reader->finished() && path.source->finished() && path.scatter->finished() &&
              path.edge_port.master->idle() && path.source_port.master->idle() &&
              (!path.gather || (path.gather->finished() && path.local_merge->drained()));
        }) && (!global_merge || global_merge->drained()) &&
        std::all_of(queue_checks.begin(), queue_checks.end(), [](const auto& check) { return check(); });
  }

  Options options;
  spine::sim::Scheduler scheduler;
  spine::sim::ClockId clock;
  spine::sim::MockMemoryBackend* backend{};
  std::vector<Path> paths;
  Fifo<rg::PropertyLine>* merged_output{};
  rg::LittleGlobalMerge* global_merge{};

 private:
  template <typename T, typename... Args>
  T* make(Args&&... args) {
    auto component = std::make_unique<T>(std::forward<Args>(args)...);
    auto* pointer = component.get();
    owned.push_back(std::move(component));
    return pointer;
  }

  template <typename T>
  Fifo<T>* queue(const std::string& name) {
    auto* pointer = make<Fifo<T>>(name, clock, options.fifo_depth);
    queue_checks.push_back([pointer] {
      return pointer->empty() && pointer->stats().pushes == pointer->stats().pops &&
             pointer->stats().max_occupancy <= pointer->depth();
    });
    return pointer;
  }

  MemoryLink port(const std::string& name, unsigned initiator, std::size_t channel) {
    MemoryLink link;
    link.requests = queue<spine::sim::AxiRequest>(name + ".requests");
    link.responses = queue<spine::sim::AxiResponse>(name + ".responses");
    link.beats = queue<spine::sim::AxiReadBeatResponse>(name + ".beats");
    link.master = make<spine::sim::AxiMaster>(name, clock, axi_config(initiator, channel, options),
        *link.requests, *link.responses, *backend, link.beats);
    return link;
  }

  std::vector<std::unique_ptr<spine::sim::Component>> owned;
  std::vector<std::function<bool()>> queue_checks;
};

}  // namespace original_regraph_frontend_test
