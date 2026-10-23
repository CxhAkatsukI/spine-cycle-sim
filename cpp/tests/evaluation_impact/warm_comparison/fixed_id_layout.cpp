#include <numeric>

#include "graph.cpp"
#include "graph_preprocess.cpp"
#include "partition_schedule.cpp"
#include "dataPrepare.cpp"
#include "../../publication_sources/regraph_layout_capture.hpp"
#include "../../publication_sources/regraph_layout_validation.hpp"

CSR::~CSR() = default;

int main(int argc, char** argv) {
  using namespace original_regraph_layout;
  try {
    require(argc == 3, "usage: fixed_id_layout GRAPH OUTPUT");
    Graph graph(argv[1]);
    CSR csr(graph);
    std::vector<unsigned> mapping(csr.vertexNum);
    std::iota(mapping.begin(), mapping.end(), 0);
    // IDs were fixed by the common input; a second DBG permutation would change it.
    initializeProperty(&csr);
    auto partitions = partitionGraph(&csr);
    partitions.num_dense_partitions = partitions.num_partitions;
    schedulePartitions(partitions);
    require(partitions.num_partitions > 0, "layout has no nonempty partitions");
    for (unsigned p = 0; p < partitions.num_partitions; ++p)
      require(partitions.P[p].num_edges > 0 && partitions.P[p].dst_offset == p * PARTITION_SIZE,
              "nonempty contiguous destination prefix required");
    const auto work = validate(csr, partitions);
    capture(argv[2], csr, mapping, partitions);
    std::cout << "PUBLICATION_LAYOUT {\"kind\":\"original_regraph_host_layout\",\"passed\":true,"
              << "\"vertices\":" << csr.vertexNum << ",\"logical_edges\":" << csr.edgeNum
              << ",\"little\":" << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
              << ",\"seed\":0,\"partitions\":" << partitions.num_partitions
              << ",\"dense_partitions\":" << partitions.num_dense_partitions
              << ",\"sparse_groups\":" << partitions.num_sparse_partitions
              << ",\"aligned_vertices\":" << partitions.vertex_property.size()
              << ",\"task_physical_edges\":" << work.task_physical_edges
              << ",\"task_dummy_edges\":" << work.task_dummy_edges
              << ",\"source_allocation_rejections\":" << work.source_allocation_rejections
              << ",\"initial_arithmetic_rejections\":" << work.initial_arithmetic_rejections
              << ",\"max_initial_sum\":" << work.max_initial_sum
              << ",\"edge_bytes_max_channel\":" << work.edge_bytes_max_channel << "}\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
