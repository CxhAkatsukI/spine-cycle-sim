#pragma once

#include <limits>

#include "regraph_layout_support.hpp"

namespace original_regraph_layout {

struct LayoutWork {
  std::uint64_t task_physical_edges{};
  std::uint64_t task_dummy_edges{};
  std::uint64_t source_allocation_rejections{};
  std::uint64_t initial_arithmetic_rejections{};
  std::uint64_t max_initial_sum{};
  std::uint64_t edge_bytes_max_channel{};
};

inline LayoutWork validate(const CSR& csr, const partition_container_dt& parts) {
  LayoutWork work;
  std::vector<std::uint64_t> expected, observed;
  std::vector<std::uint64_t> sums(csr.vertexNum, 0);
  expected.reserve(csr.edgeNum); observed.reserve(csr.edgeNum);
  for (int source = 0; source < csr.vertexNum; ++source) {
    for (int index = csr.rpao[source]; index < csr.rpao[source + 1]; ++index) {
      const auto destination = csr.ciao[index];
      expected.push_back((std::uint64_t{static_cast<unsigned>(source)} << 32) | destination);
      sums[destination] += csr.vProps[source];
    }
  }
  const auto initial = static_cast<int>((1.0f / csr.vertexNum) * std::pow(2, 30));
  const auto limit = std::numeric_limits<std::int32_t>::max();
  for (int vertex = 0; vertex < csr.vertexNum; ++vertex) {
    const auto degree = csr.rpao[vertex + 1] - csr.rpao[vertex];
    require(csr.vProps[vertex] == (degree ? initial / degree : 0), "original PR initialization mismatch");
    work.max_initial_sum = std::max(work.max_initial_sum, sums[vertex]);
    const auto damped = sums[vertex] * 108;
    const auto product = (damped >> 7) * (degree ? 65536 / degree : 0);
    if (sums[vertex] > static_cast<unsigned>(limit) || damped > static_cast<unsigned>(limit) ||
        product > static_cast<unsigned>(limit)) ++work.initial_arithmetic_rejections;
  }
  std::array<std::uint64_t, 14> edge_bytes{};
  const auto cluster = [&](const auto& collection, bool little) {
    for (const auto& part : collection) {
      for (const auto& task : part.subP) {
        require(task.kernel_id < LITTLE_KERNEL_NUM + BIG_KERNEL_NUM &&
                task.edge_array_host.size() % 16 == 0 && !task.edge_array_host.empty(),
                "invalid scheduled task alignment or kernel");
        edge_bytes[task.kernel_id] += task.edge_array_host.size() * 4;
        unsigned max_source = 0;
        for (unsigned word = 0; word < task.edge_array_host.size(); word += 2) {
          const auto source = task.edge_array_host[word] & 0x7fffffffu;
          const auto destination = task.edge_array_host[word + 1];
          require(source < static_cast<unsigned>(csr.vertexNum), "scheduled source outside graph");
          max_source = std::max(max_source, source);
          ++work.task_physical_edges;
          if (destination & 0x80000000u) {
            require(destination == 0xffffffffu, "noncanonical original dummy destination");
            ++work.task_dummy_edges;
          } else {
            require(destination >= task.dst_offset && destination - task.dst_offset < task.dst_len &&
                    destination < static_cast<unsigned>(csr.vertexNum), "scheduled destination outside partition");
            observed.push_back((std::uint64_t{source} << 32) | destination);
          }
          if (little && word % 16 != 0) {
            require((source >> 12) == ((task.edge_array_host[word - word % 16] & 0x7fffffffu) >> 12),
                    "Little burst crosses a source ping-pong window");
          }
        }
        if (little && (std::uint64_t{max_source / 4096} + 2) * 4096 > parts.vertex_property.size()) {
          ++work.source_allocation_rejections;
        }
      }
    }
  };
  cluster(parts.DP, true); cluster(parts.SP, false);
  std::sort(expected.begin(), expected.end()); std::sort(observed.begin(), observed.end());
  require(expected == observed, "scheduled tasks lost, duplicated or changed graph edges");
  require(work.task_physical_edges - work.task_dummy_edges == static_cast<unsigned>(csr.edgeNum),
          "physical/logical scheduled edge conservation failed");
  work.edge_bytes_max_channel = *std::max_element(edge_bytes.begin(), edge_bytes.end());
  require(work.edge_bytes_max_channel < 256ull * 1024 * 1024 &&
          parts.vertex_property.size() * 4ull < 256ull * 1024 * 1024, "original per-channel HBM capacity exceeded");
  return work;
}

}  // namespace original_regraph_layout
