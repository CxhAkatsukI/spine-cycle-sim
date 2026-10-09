#include <ctime>

#include "graph.cpp"
#include "graph_preprocess.cpp"
#include "partition_schedule.cpp"
#include "dataPrepare.cpp"
#include "regraph_layout_capture.hpp"
#include "regraph_layout_validation.hpp"

namespace { unsigned pinned_seed = 73; }

// The original DBG calls time() before srand(); pin only that environmental input.
extern "C" std::time_t time(std::time_t* value) noexcept {
  if (value) *value = pinned_seed;
  return pinned_seed;
}

// Upstream declares but never defines this destructor; no algorithm is changed.
CSR::~CSR() = default;

int main(int argc, char** argv) {
  using namespace original_regraph_layout;
  try {
    require(argc == 5, "usage: layout GRAPH OUTPUT_DIR SEED DENSE_PARTITIONS");
    pinned_seed = static_cast<unsigned>(std::stoul(argv[3]));
    Graph graph(argv[1]);
    CSR csr(graph);
    const auto offsets = csr.rpao, destinations = csr.ciao;
    const auto mapping = permutation(csr, pinned_seed);
    reorderGraph(&csr);
    check_reordered(offsets, destinations, mapping, csr);
    initializeProperty(&csr);
    auto partitions = partitionGraph(&csr);
    partitions.num_dense_partitions = static_cast<unsigned>(std::stoul(argv[4]));
    schedulePartitions(partitions);
    require(partitions.num_partitions > 0, "layout has no nonempty partitions");
    for (unsigned index = 0; index < partitions.num_partitions; ++index) {
      require(partitions.P[index].num_edges > 0 && partitions.P[index].dst_offset == index * PARTITION_SIZE,
              "original partition scheduler assumes a contiguous nonempty destination prefix");
    }
    const auto work = validate(csr, partitions);
    capture(argv[2], csr, mapping, partitions);
    std::cout << "PUBLICATION_LAYOUT {\"kind\":\"original_regraph_host_layout\",\"passed\":true,"
              << "\"vertices\":" << csr.vertexNum << ",\"logical_edges\":" << csr.edgeNum
              << ",\"little\":" << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
              << ",\"seed\":" << pinned_seed << ",\"partitions\":" << partitions.num_partitions
              << ",\"dense_partitions\":" << partitions.num_dense_partitions
              << ",\"sparse_groups\":" << partitions.num_sparse_partitions
              << ",\"aligned_vertices\":" << partitions.vertex_property.size()
              << ",\"task_physical_edges\":" << work.task_physical_edges
              << ",\"task_dummy_edges\":" << work.task_dummy_edges
              << ",\"source_allocation_rejections\":" << work.source_allocation_rejections
              << ",\"initial_arithmetic_rejections\":" << work.initial_arithmetic_rejections
              << ",\"max_initial_sum\":" << work.max_initial_sum
              << ",\"edge_bytes_max_channel\":" << work.edge_bytes_max_channel << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
