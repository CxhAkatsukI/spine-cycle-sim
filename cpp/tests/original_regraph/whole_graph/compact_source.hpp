#pragma once

#include "../frontend_wiring.hpp"
#include "input.hpp"

namespace original_regraph_whole_test {

// Only input production varies; ComputeWiring owns every downstream resource.
class CompactSource {
 public:
  using Reader = spine::sim::original_regraph::LittleEdgeReader;
  using Udf = spine::sim::original_regraph::Udf;
  CompactSource(const Input& input, Udf udf = Udf::kFixedPointPr) : input_(input), udf_(udf) {
    require(udf == Udf::kFixedPointPr || udf == Udf::kWeightedSssp, "unsupported compact source UDF");
    if (udf != Udf::kWeightedSssp) return;
    // The input owner validates weight/global-edge correspondence before packing.
    // Never infer weights or relocalize the already packed destination word.
    for (const auto& task : input.tasks) {
      require(task.words && task.words % 16 == 0 && task.offset_words <= input.edge_words.size() &&
              task.words <= input.edge_words.size() - task.offset_words,
              "weighted compact task has invalid packed extent");
      for (std::size_t word = 1; word < task.words; word += 2) {
        const auto destination = input.edge_words[task.offset_words + word];
        require((destination & 0x80000000u) || (destination & 0x7ffffu) < 65536,
                "weighted compact words must be packed and prelocalized");
      }
    }
  }
  const Input& input() const noexcept { return input_; }
  Udf udf() const noexcept { return udf_; }
  std::uint32_t physical_edges(const Task& task) const noexcept { return task.words / 2; }

  Reader* make(original_regraph_memory_test::MemoryFixture& memory, const std::string& name,
               spine::sim::original_regraph::ReadPort port,
               spine::sim::Fifo<spine::sim::original_regraph::EdgeBurst>& output) const {
    return memory.make<Reader>(name, memory.clock, port, output,
        spine::sim::original_regraph::kEdgeReaderTiming, udf_);
  }

  void initialize(original_regraph_memory_test::MemoryFixture& memory, unsigned channel,
                  const Task& task) const {
    memory.backend->initialize_payload(channel, task.address,
        bytes(std::span(input_.edge_words).subspan(task.offset_words, task.words)));
  }

  void begin(Reader& reader, const Task& task) const {
    reader.begin_partition(task.address, physical_edges(task),
        udf_ == Udf::kWeightedSssp ? 0 : task.destination);
  }

 private:
  const Input& input_;
  Udf udf_;
};

}  // namespace original_regraph_whole_test
