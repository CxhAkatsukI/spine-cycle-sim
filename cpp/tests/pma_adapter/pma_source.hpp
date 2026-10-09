#pragma once

#include "../original_regraph/whole_graph/compute_wiring.hpp"
#include "../publication_sources/adapter/input.hpp"
#include "spine_sim/pma_adapter/reader.hpp"

namespace pma_adapter_test {
namespace pa = spine::sim::pma_adapter;
namespace wt = original_regraph_whole_test;
namespace ac = adapter_source_control;

class PmaSource {
 public:
  using Reader = pa::Reader;
  explicit PmaSource(const ac::Input& layout) : layout_(layout) {
    std::array<std::uint64_t, 4> next{};
    for (const auto& task : layout.tasks) {
      auto& address = next[task.kernel];
      const auto rows = (std::uint64_t{layout.graph.vertices} * 8 + 63) / 64 * 64;
      const auto half_bytes = (std::uint64_t{task.slots} + 31) / 32 * 64;
      pa::Partition descriptor{{}, address, layout.graph.vertices, task.slots, 131072,
                               task.destination, 65536};
      address += rows;
      for (auto& base : descriptor.pma_addresses) { base = address; address += half_bytes; }
      wt::require(address <= 256ull * 1024 * 1024, "resident PMA input channel capacity exceeded");
      partitions_.push_back(descriptor);
    }
  }

  const wt::Input& input() const noexcept { return layout_.graph; }
  std::uint32_t physical_edges(const wt::Task& task) const { return descriptor(task).slots; }

  Reader* make(original_regraph_memory_test::MemoryFixture& memory, const std::string& name,
               spine::sim::original_regraph::ReadPort port,
               spine::sim::Fifo<spine::sim::original_regraph::EdgeBurst>& output) const {
    return memory.make<Reader>(name, memory.clock, port, output);
  }

  void initialize(original_regraph_memory_test::MemoryFixture& memory, unsigned channel,
                  const wt::Task& original) const {
    const auto ordinal = index(original);
    const auto& task = layout_.tasks[ordinal]; const auto& description = partitions_[ordinal];
    const auto rows = std::span(layout_.rows).subspan(task.row_offset, layout_.graph.vertices * 2ull);
    auto row_words = std::vector<std::uint32_t>(rows.begin(), rows.end());
    row_words.resize((row_words.size() + 15) / 16 * 16, 0);
    memory.backend->initialize_payload(channel, description.row_address, wt::bytes(row_words));
    std::array<std::vector<std::uint32_t>, 4> buffers;
    const auto half_words = (std::uint64_t{task.slots} + 31) / 32 * 16;
    for (auto& buffer : buffers) buffer.assign(half_words, 0x80000000u);
    for (unsigned segment = 0; segment < task.slots / 16; ++segment) {
      const auto parity = (segment & 1u) * 2;
      for (unsigned lane = 0; lane < 16; ++lane) {
        const auto word = layout_.pma[task.pma_offset + segment * 16 + lane];
        buffers[parity][segment / 2 * 16 + lane] = word;
        buffers[parity + 1][segment / 2 * 16 + lane] = word;
      }
    }
    for (unsigned route = 0; route < 4; ++route) {
      memory.backend->initialize_payload(channel, description.pma_addresses[route], wt::bytes(buffers[route]));
    }
  }

  void begin(Reader& reader, const wt::Task& task) const { reader.begin_partition(descriptor(task)); }

 private:
  std::size_t index(const wt::Task& task) const {
    const auto ordinal = std::uint64_t{task.partition} * 4 + task.subpartition;
    wt::require(ordinal < layout_.graph.tasks.size() && &task == &layout_.graph.tasks[ordinal], "PMA task identity mismatch");
    return ordinal;
  }
  const pa::Partition& descriptor(const wt::Task& task) const { return partitions_[index(task)]; }
  const ac::Input& layout_;
  std::vector<pa::Partition> partitions_;
};

using PmaWiring = wt::ComputeWiring<PmaSource>;

}  // namespace pma_adapter_test
