#pragma once

#include "continuous_board/device.hpp"

namespace metadata_g {
using Handles = std::vector<std::array<cl_mem, 6>>;

inline Handles handles(const continuous_g::Device& device) {
  Handles result;
  for (const auto& shard : device.shards)
    result.push_back({shard.rows(), shard.binary(), shard.pma[0](), shard.pma[1](),
                      shard.pma[2](), shard.pma[3]()});
  return result;
}

inline std::vector<continuous_g::Event> refresh(continuous_g::Device& device, const Model& model,
                                              const Handles& original) {
  using namespace continuous_g;
  check_input(handles(device) == original, "metadata/PMA BO identity changed");
  checked(device.session.updates.finish(), "quiesce G before metadata refresh");
  checked(device.session.barriers.finish(), "quiesce publication before metadata refresh");
  std::vector<Event> events;
  for (unsigned shard = 0; shard < device.shards.size(); ++shard) {
    const auto& packed = model.packed[shard];
    events.push_back({"metadata_row_dma", shard, {}});
    checked(device.session.transfers.enqueueWriteBuffer(device.shards[shard].rows, CL_FALSE, 0,
        packed.row_bounds.size() * 8, packed.row_bounds.data(), nullptr, &events.back().event),
        "refresh resident rows");
    events.push_back({"metadata_binary_dma", shard, {}});
    checked(device.session.transfers.enqueueWriteBuffer(device.shards[shard].binary, CL_FALSE, 0,
        packed.binary_heads.size() * 8, packed.binary_heads.data(), nullptr, &events.back().event),
        "refresh resident binary");
  }
  checked(device.session.transfers.finish(), "complete metadata generation upload");
  check_input(handles(device) == original, "refresh reallocated metadata/PMA BOs");
  return events;
}
}  // namespace metadata_g
