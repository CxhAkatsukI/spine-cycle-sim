#pragma once

#include "little_path.hpp"
#include "big_path.hpp"
#include "../../state_support.hpp"
#include "spine_sim/original_regraph/mixed_indexer.hpp"

namespace original_regraph_mixed_test {

class Wiring {
 public:
  Wiring(const Input& input, std::size_t state_parents, std::uint64_t latency, bool reverse)
      : memory(latency), input(input) {
    require(state_parents && state_parents <= 16, "invalid mixed state parent credits");
    std::vector<Fifo<rg::VertexPair>*> little_outputs;
    std::vector<Fifo<rg::PropertyLine>*> big_outputs;
    for (unsigned index = 0; index < 11; ++index) {
      little.emplace_back(memory, index, input.allocation_vertices * 4ull);
      little_outputs.push_back(little.back().output);
    }
    for (unsigned index = 11; index < 14; ++index) {
      big.emplace_back(memory, index, input.allocation_vertices * 4ull);
      big_outputs.push_back(big.back().output);
    }
    little_merged = memory.stream<rg::PropertyLine>("little.merged", 8);
    big_merged = memory.stream<rg::PropertyLine>("big.merged", 8);
    little_merge = memory.make<rg::LittleGlobalMerge>("little.merge", memory.clock, little_outputs, *little_merged);
    big_merge = memory.make<rg::BigGlobalMerge>("big.merge", memory.clock, big_outputs, *big_merged);
    indexed = memory.stream<rg::PropertyWrite>("indexed", 8);
    auto* applied = memory.stream<rg::PropertyWrite>("applied", 8);
    indexer = memory.make<rg::MixedWriteIndexer>("mixed.index", memory.clock, *little_merged, *big_merged, *indexed);
    degree = memory.port("degree_axi", 100, 30, 16, state_parents);
    apply = memory.make<rg::PrApply>("apply", memory.clock, rg::TransactionPort{*degree.requests, *degree.responses},
        *indexed, *applied, 0, input.allocation_vertices * 4ull);
    std::vector<rg::WriteTarget> targets;
    for (unsigned index = 0; index < 14; ++index) {
      auto port = memory.port("write_axi" + std::to_string(index), 200 + index, index * 2 + 1, 16, state_parents);
      targets.push_back({{*port.requests, *port.responses}, kOutputAddress, input.allocation_vertices * 4ull});
      writers.push_back(port);
    }
    writer = memory.make<rg::PropertyBroadcastWriter>("writer", memory.clock, *applied, targets);
    for (const auto& task : input.tasks) {
      if (task.kernel < 11) little[task.kernel].tasks.push_back(&task);
      else big[task.kernel - 11].tasks.push_back(&task);
    }
    memory.register_components(reverse);
  }
  void begin() {
    const auto properties = bytes(input.initial), degrees = bytes(input.degrees);
    for (unsigned index = 0; index < 14; ++index) {
      memory.backend->initialize_payload(index * 2 + 1, 0, properties);
      memory.backend->fill_payload(index * 2 + 1, kOutputAddress, input.allocation_vertices * 4ull, 0);
      memory.backend->fill_payload(index * 2 + 1, kOutputAddress + input.allocation_vertices * 4ull, 64, 0xa5);
    }
    for (const auto& task : input.tasks) memory.backend->initialize_payload(task.kernel * 2, task.address,
        bytes(std::span(input.edge_words).subspan(task.offset_words, task.words)));
    memory.backend->initialize_payload(30, 0, degrees);
    const auto lines = input.published_vertices / 16;
    indexer->begin(input.dense * 4096, input.sparse * 32768); apply->begin(lines, 0); writer->begin(lines);
    for (auto& path : little) path.p.source->begin_partitions(input.dense);
    if (input.sparse) {
      for (auto& path : big) path.source->begin_partitions(input.sparse);
      big_merge->begin_partitions(input.sparse);
    }
    advance(0);
  }
  template <typename Paths> void advance_paths(Paths& paths, std::uint64_t cycle) {
    for (auto& path : paths) {
      if (path.active && path.ready()) { path.completions.push_back(cycle); path.active = false; }
      if (path.active || path.starts.size() == path.tasks.size()) continue;
      require(path.ready(), "mixed next task before its own path drained");
      path.begin(*path.tasks[path.starts.size()]); path.starts.push_back(cycle); path.active = true;
    }
  }
  void advance(std::uint64_t cycle) { advance_paths(little, cycle); advance_paths(big, cycle); }
  bool finished() const {
    const auto paths_done = [](const auto& paths) { return std::all_of(paths.begin(), paths.end(), [](const auto& path) {
      return !path.active && path.completions.size() == path.tasks.size();
    }); };
    return indexer->finished() && apply->finished() && writer->finished() && little_merge->drained() &&
        big_merge->finished() && paths_done(little) && paths_done(big) && memory.drained() &&
        std::all_of(little.begin(), little.end(), [](const auto& p) { return p.p.source->finished(); }) &&
        std::all_of(big.begin(), big.end(), [](const auto& p) { return p.source->finished(); });
  }
  Resources memory;
  const Input& input;
  std::vector<LittlePath> little;
  std::vector<BigPath> big;
  Fifo<rg::PropertyLine>* little_merged{}, *big_merged{};
  Fifo<rg::PropertyWrite>* indexed{};
  rg::LittleGlobalMerge* little_merge{};
  rg::BigGlobalMerge* big_merge{};
  rg::MixedWriteIndexer* indexer{};
  rg::PrApply* apply{};
  rg::PropertyBroadcastWriter* writer{};
  MemoryLink degree;
  std::vector<MemoryLink> writers;
};

}  // namespace original_regraph_mixed_test
