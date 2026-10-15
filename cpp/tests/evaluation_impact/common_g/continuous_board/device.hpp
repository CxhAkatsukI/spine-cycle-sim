#pragma once

#include "xrt.hpp"

namespace continuous_g {
struct DeviceShard {
  std::array<cl::Buffer, 4> updates, pma;
  cl::Buffer rows, binary;
};

struct Device {
  Session session;
  std::vector<DeviceShard> shards;
  std::array<cl::Kernel, 4> search;
  cl::Kernel dispatch, cache0, cache1, ddr0, ddr1, barrier;

  Device(const char* xclbin, unsigned index, const Model& model) : session(xclbin, index),
      shards(model.graph.shards.size()),
      dispatch(session.kernel("dispatch:{dispatch_1}")),
      cache0(session.kernel("process_cache:{process_cache_1}")),
      cache1(session.kernel("process_cache:{process_cache_2}")),
      ddr0(session.kernel("process_ddr:{process_ddr_1}")),
      ddr1(session.kernel("process_ddr:{process_ddr_2}")),
      barrier(session.kernel("pma_completion_barrier:{pma_completion_barrier_1}")) {
    for (unsigned lane = 0; lane < 4; ++lane)
      search[lane] = session.kernel("bin_search:{bin_search_" + std::to_string(lane + 1) + "}");
    for (unsigned shard = 0; shard < shards.size(); ++shard) {
      auto allocate = [&](const std::string& name, std::size_t bytes, cl_mem_flags flags) {
        const auto& region = host::find_weighted_pma_region(model.plan, shard, name);
        check_input(bytes == region.logical_bytes, "allocation differs from host runtime plan");
        return session.buffer(region.channel, bytes, flags);
      };
      for (unsigned lane = 0; lane < 4; ++lane) {
        const auto& words = model.packed[shard].pma_words[lane];
        shards[shard].updates[lane] = allocate("update" + std::to_string(lane),
            model.packed[shard].updates[lane].size() * 8, CL_MEM_READ_ONLY);
        shards[shard].pma[lane] = allocate("pma" + std::to_string(lane), words.size() * 4, CL_MEM_READ_WRITE);
        checked(session.transfers.enqueueWriteBuffer(shards[shard].pma[lane], CL_FALSE,
            0, words.size() * 4, words.data()), "initial PMA upload");
      }
      const auto& packed = model.packed[shard];
      shards[shard].rows = allocate("row", packed.row_bounds.size() * 8, CL_MEM_READ_ONLY);
      shards[shard].binary = allocate("binary", packed.binary_heads.size() * 8, CL_MEM_READ_ONLY);
      checked(session.transfers.enqueueWriteBuffer(shards[shard].rows, CL_FALSE, 0,
          packed.row_bounds.size() * 8, packed.row_bounds.data()), "initial rows upload");
      checked(session.transfers.enqueueWriteBuffer(shards[shard].binary, CL_FALSE, 0,
          packed.binary_heads.size() * 8, packed.binary_heads.data()), "initial binary upload");
    }
    checked(session.transfers.finish(), "finish initial upload");
  }

  std::vector<Event> transfer(const std::vector<BatchShard>& batch) {
    std::vector<Event> events;
    for (unsigned shard = 0; shard < shards.size(); ++shard)
      for (unsigned lane = 0; lane < 4; ++lane) {
        if (!batch[shard].counts[lane]) continue;
        events.push_back({"update_dma", shard, {}});
        checked(session.transfers.enqueueWriteBuffer(shards[shard].updates[lane], CL_FALSE, 0,
            batch[shard].lanes[lane].size() * 8, batch[shard].lanes[lane].data(), nullptr,
            &events.back().event), "batch update DMA");
      }
    checked(session.transfers.finish(), "finish batch DMA");
    return events;
  }

  std::vector<Event> run(const std::vector<BatchShard>& batch) {
    std::vector<Event> events;
    for (unsigned shard = 0; shard < shards.size(); ++shard) {
      auto& buffers = shards[shard];
      for (unsigned lane = 0; lane < 4; ++lane) {
        unsigned argument = 0;
        checked(search[lane].setArg(argument++, buffers.updates[lane]), "set search update");
        for (unsigned i = 0; i < 4; ++i)
          checked(search[lane].setArg(argument++, buffers.binary), "set search binary alias");
        for (unsigned i = 0; i < 4; ++i)
          checked(search[lane].setArg(argument++, buffers.rows), "set search row alias");
        checked(search[lane].setArg(argument++, batch[shard].counts[lane]), "set search size");
      }
      checked(dispatch.setArg(0, static_cast<unsigned>(batch[shard].physical.size())), "set dispatch size");
      checked(cache0.setArg(0, buffers.pma[0]), "set cache0");
      checked(cache1.setArg(0, buffers.pma[2]), "set cache1");
      for (unsigned i = 0; i < 4; ++i) {
        checked(ddr0.setArg(i, buffers.pma[1]), "set ddr0 alias");
        checked(ddr1.setArg(i, buffers.pma[3]), "set ddr1 alias");
      }
      const std::array<const char*, 9> names{"cache0", "cache1", "ddr0", "ddr1", "dispatch",
                                            "search0", "search1", "search2", "search3"};
      std::array<cl::Kernel*, 9> kernels{&cache0, &cache1, &ddr0, &ddr1, &dispatch,
                                       &search[0], &search[1], &search[2], &search[3]};
      for (unsigned i = 0; i < kernels.size(); ++i) {
        events.push_back({names[i], shard, {}});
        checked(session.updates.enqueueTask(*kernels[i], nullptr, &events.back().event), "enqueue G kernel");
      }
      events.push_back({"barrier", shard, {}});
      checked(session.barriers.enqueueTask(barrier, nullptr, &events.back().event), "enqueue publication barrier");
      checked(session.updates.flush(), "flush G producers");
      checked(session.barriers.flush(), "flush completion consumer");
      checked(session.updates.finish(), "wait for G kernels");
      checked(session.barriers.finish(), "wait for publication barrier");
    }
    return events;
  }

  std::vector<Words> readback(const Model& model) {
    auto observed = model.expected;
    for (unsigned shard = 0; shard < shards.size(); ++shard) {
      for (unsigned port = 0; port < 4; ++port)
        checked(session.transfers.enqueueReadBuffer(shards[shard].pma[port], CL_FALSE, 0,
            observed[shard][port].size() * 4, observed[shard][port].data()), "read complete PMA");
      // Metadata must remain immutable at the same addresses across all batches.
      for (bool binary : {false, true}) {
        const auto& expected = binary ? model.packed[shard].binary_heads : model.packed[shard].row_bounds;
        std::vector<std::uint64_t> actual(expected.size());
        checked(session.transfers.enqueueReadBuffer(binary ? shards[shard].binary : shards[shard].rows,
            CL_TRUE, 0, actual.size() * 8, actual.data()), "read metadata");
        check_input(actual == expected, "resident metadata changed");
      }
    }
    checked(session.transfers.finish(), "finish verification readback");
    return observed;
  }
};
}  // namespace continuous_g
