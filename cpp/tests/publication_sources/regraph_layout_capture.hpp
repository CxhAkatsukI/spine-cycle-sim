#pragma once

#include "regraph_layout_support.hpp"

namespace original_regraph_layout {

inline void capture(const std::string& directory, const CSR& csr,
                    const std::vector<unsigned>& mapping, const partition_container_dt& partitions) {
  const auto words = [&](const char* name, const auto& values) {
    WordFile file(directory + "/" + name);
    file.append(values);
    file.close();
  };
  words("original_to_reordered.u32le", mapping);
  words("csr_offsets.u32le", csr.rpao);
  words("csr_destinations.u32le", csr.ciao);
  words("initial.u32le", partitions.vertex_property);
  words("degrees.u32le", partitions.outdegree_host);
  WordFile original(directory + "/partitions.u32le"), tasks(directory + "/tasks.u32le");
  for (unsigned index = 0; index < partitions.num_partitions; ++index) {
    const auto& part = partitions.P[index];
    std::cout << "ORIGINAL_LAYOUT_PARTITION {\"id\":" << index << ",\"offset_words\":" << original.words()
              << ",\"words\":" << part.edge_array_host.size() << ",\"dst_offset\":" << part.dst_offset
              << ",\"dst_len\":" << part.dst_len << "}\n";
    original.append(part.edge_array_host);
  }
  const auto cluster = [&](const char* kind, const auto& collection) {
    for (unsigned index = 0; index < collection.size(); ++index) {
      for (unsigned sub = 0; sub < collection[index].subP.size(); ++sub) {
        const auto& task = collection[index].subP[sub];
        std::cout << "ORIGINAL_LAYOUT_TASK {\"kind\":\"" << kind << "\",\"partition\":" << index
                  << ",\"subpartition\":" << sub << ",\"kernel\":" << task.kernel_id
                  << ",\"offset_words\":" << tasks.words() << ",\"words\":" << task.edge_array_host.size()
                  << ",\"dst_offset\":" << task.dst_offset << ",\"dst_len\":" << task.dst_len << "}\n";
        tasks.append(task.edge_array_host);
      }
    }
  };
  cluster("dense", partitions.DP);
  cluster("sparse", partitions.SP);
  original.close(); tasks.close();
}

}  // namespace original_regraph_layout
