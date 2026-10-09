#pragma once

#include "../frontend_wiring.hpp"
#include "input.hpp"

namespace original_regraph_whole_test {

// Only input production varies; ComputeWiring owns every downstream resource.
class CompactSource {
 public:
  using Reader = spine::sim::original_regraph::LittleEdgeReader;
  CompactSource(const Input& input) : input_(input) {}
  const Input& input() const noexcept { return input_; }
  std::uint32_t physical_edges(const Task& task) const noexcept { return task.words / 2; }

  Reader* make(original_regraph_memory_test::MemoryFixture& memory, const std::string& name,
               spine::sim::original_regraph::ReadPort port,
               spine::sim::Fifo<spine::sim::original_regraph::EdgeBurst>& output) const {
    return memory.make<Reader>(name, memory.clock, port, output);
  }

  void initialize(original_regraph_memory_test::MemoryFixture& memory, unsigned channel,
                  const Task& task) const {
    memory.backend->initialize_payload(channel, task.address,
        bytes(std::span(input_.edge_words).subspan(task.offset_words, task.words)));
  }

  void begin(Reader& reader, const Task& task) const {
    reader.begin_partition(task.address, physical_edges(task), task.destination);
  }

 private:
  const Input& input_;
};

}  // namespace original_regraph_whole_test
