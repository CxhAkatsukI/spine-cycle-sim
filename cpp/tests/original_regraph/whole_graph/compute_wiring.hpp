#pragma once

#include "../frontend_wiring.hpp"
#include "../state_support.hpp"
#include "input.hpp"

namespace original_regraph_whole_test {
namespace rg = spine::sim::original_regraph;
using original_regraph_memory_test::MemoryFixture;
using original_regraph_memory_test::MemoryLink;
using spine::sim::Fifo;

inline constexpr std::uint64_t kOutputAddress = 64ull * 1024 * 1024;

template <typename Reader>
struct ComputePath {
  struct Components {
    MemoryLink edge_port, source_port;
    Fifo<rg::EdgeBurst>* edges{};
    Fifo<rg::SourceRequest>* requests{};
    Fifo<rg::SourceResponse>* responses{};
    Fifo<rg::UpdateBurst>* updates{};
    Reader* reader{};
    rg::LittleSourceMemory* source{};
    rg::LittleScatter* scatter{};
    rg::LittleGather* gather{};
    rg::LittleLocalMerge* local_merge{};
  } components;
  rg::GatherOutputs lanes{};
  Fifo<rg::VertexPair>* output{};
  std::vector<const Task*> tasks;
  std::vector<std::uint64_t> starts, completions;
  bool active{};

  bool ready() const {
    const auto& p = components;
    return p.reader->finished() && p.scatter->finished() && p.gather->finished() &&
        p.local_merge->drained() && output->empty() && p.edge_port.master->idle() && p.source_port.master->idle() &&
        p.edges->empty() && p.requests->empty() && p.responses->empty() && p.updates->empty() &&
        std::all_of(lanes.begin(), lanes.end(), [](const auto* queue) { return queue->empty(); });
  }
};

template <typename InputSource>
class ComputeWiring {
 public:
  ComputeWiring(InputSource source, std::size_t state_parents, std::uint64_t latency, bool reverse,
                std::size_t input_parents = 2)
      : memory(8, latency), input(source.input()), source_(std::move(source)) {
    require(state_parents > 0 && state_parents <= 16, "invalid state AXI parent credits");
    std::vector<Fifo<rg::VertexPair>*> outputs;
    for (unsigned index = 0; index < paths.size(); ++index) {
      auto& path = paths[index]; auto& p = path.components;
      const auto name = "little" + std::to_string(index);
      p.edge_port = memory.port(name + ".edge_axi", index * 2 + 1, index * 2, 16, input_parents);
      p.source_port = memory.port(name + ".source_axi", index * 2 + 2, index * 2 + 1);
      p.edges = memory.queue<rg::EdgeBurst>(name + ".edges");
      p.requests = memory.queue<rg::SourceRequest>(name + ".requests");
      p.responses = memory.queue<rg::SourceResponse>(name + ".responses");
      p.updates = memory.queue<rg::UpdateBurst>(name + ".updates");
      p.reader = source_.make(memory, name + ".reader", p.edge_port.ports(), *p.edges);
      p.source = memory.make<rg::LittleSourceMemory>(name + ".source", memory.clock, p.source_port.ports(),
          *p.requests, *p.responses, 0, input.aligned_vertices * 4ull);
      p.scatter = memory.make<rg::LittleScatter>(name + ".scatter", memory.clock, *p.edges,
          *p.requests, *p.responses, *p.updates);
      for (unsigned lane = 0; lane < path.lanes.size(); ++lane) {
        path.lanes[lane] = memory.queue<rg::VertexPair>(name + ".lane" + std::to_string(lane));
      }
      path.output = memory.queue<rg::VertexPair>(name + ".output");
      p.gather = memory.make<rg::LittleGather>(name + ".gather", memory.clock, *p.updates, path.lanes);
      p.local_merge = memory.make<rg::LittleLocalMerge>(name + ".local", memory.clock, path.lanes, *path.output);
      outputs.push_back(path.output);
    }
    merged = memory.queue<rg::PropertyLine>("merged");
    merger = memory.make<rg::LittleGlobalMerge>("global_merge", memory.clock, outputs, *merged);
    auto* indexed = memory.queue<rg::PropertyWrite>("indexed");
    auto* applied = memory.queue<rg::PropertyWrite>("applied");
    degree = memory.port("degree_axi", 100, 30, 16, state_parents);
    indexer = memory.make<rg::LittleWriteIndexer>("index", memory.clock, *merged, *indexed);
    apply = memory.make<rg::PrApply>("apply", memory.clock,
        rg::TransactionPort{*degree.requests, *degree.responses}, *indexed, *applied,
        0, input.published_vertices * 4ull);
    std::vector<rg::WriteTarget> targets;
    for (unsigned index = 0; index < paths.size(); ++index) {
      auto port = memory.port("write_axi" + std::to_string(index), 200 + index, index * 2 + 1, 16, state_parents);
      targets.push_back({{*port.requests, *port.responses}, kOutputAddress, input.aligned_vertices * 4ull});
      writers.push_back(port);
    }
    writer = memory.make<rg::PropertyBroadcastWriter>("write", memory.clock, *applied, targets);
    for (const auto& task : input.tasks) paths[task.kernel].tasks.push_back(&task);
    memory.register_components(reverse);
  }

  void initialize() {
    const auto properties = bytes(input.initial), degrees = bytes(input.degrees);
    for (unsigned index = 0; index < paths.size(); ++index) {
      memory.backend->initialize_payload(index * 2 + 1, 0, properties);
      memory.backend->fill_payload(index * 2 + 1, kOutputAddress, input.aligned_vertices * 4ull, 0);
      memory.backend->fill_payload(index * 2 + 1, kOutputAddress + input.aligned_vertices * 4ull, 64, 0xa5);
      for (const auto* task : paths[index].tasks) {
        source_.initialize(memory, index * 2, *task);
      }
    }
    memory.backend->initialize_payload(30, 0, degrees);
  }

  void begin() {
    const auto lines = input.published_vertices / 16;
    indexer->begin(lines); apply->begin(lines, 0); writer->begin(lines);
    for (auto& path : paths) path.components.source->begin_partitions(input.partitions);
    advance(0);
  }

  void advance(std::uint64_t cycle) {
    for (auto& path : paths) {
      if (path.active && path.ready()) {
        path.completions.push_back(cycle); path.active = false;
      }
      if (path.active || path.starts.size() == path.tasks.size()) continue;
      require(path.ready(), "next partition launched before its own path drained");
      const auto& task = *path.tasks[path.starts.size()];
      if (task.partition && writer->counters().acknowledgements < std::uint64_t{task.partition} * 4096 * 4) {
        ++overlapped_task_starts;
      }
      source_.begin(*path.components.reader, task);
      path.components.scatter->begin_partition(source_.physical_edges(task));
      path.components.gather->begin_partition(source_.physical_edges(task) / 8);
      path.starts.push_back(cycle); path.active = true;
    }
  }

  bool finished() const {
    return indexer->finished() && apply->finished() && writer->finished() && merger->drained() &&
        std::all_of(paths.begin(), paths.end(), [](const auto& path) {
          return !path.active && path.completions.size() == path.tasks.size() && path.components.source->finished();
        }) && memory.drained();
  }

  MemoryFixture memory;
  const Input& input;
  std::array<ComputePath<typename InputSource::Reader>, 4> paths;
  Fifo<rg::PropertyLine>* merged{};
  rg::LittleGlobalMerge* merger{};
  MemoryLink degree;
  std::vector<MemoryLink> writers;
  rg::LittleWriteIndexer* indexer{};
  rg::PrApply* apply{};
  rg::PropertyBroadcastWriter* writer{};
  std::uint64_t overlapped_task_starts{};

 private:
  InputSource source_;
};

}  // namespace original_regraph_whole_test
