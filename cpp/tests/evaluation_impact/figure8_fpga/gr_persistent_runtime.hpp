#pragma once

// Included after the pinned native host, which owns the OpenCL ABI helpers.
namespace figure8_gr {

using UpdateLanes = grasu::integration::WeightedPmaUpdateLanes;

struct Batch {
    std::vector<UpdateLanes> updates;
    std::vector<std::size_t> counts;
};

inline Batch prepare_batch(const WeightedPartitionedPmaGraph &graph,
                          const WeightedPmaRuntimePlan &plan,
                          std::size_t begin, std::size_t end)
{
    Batch batch{std::vector<UpdateLanes>(graph.shards.size()),
                std::vector<std::size_t>(graph.shards.size(), 0)};
    for (std::size_t index = begin; index < end; ++index) {
        const auto &edge = graph.physical_internal.at(index);
        const auto shard = edge.destination / graph.partition_vertices;
        const auto lane = batch.counts.at(shard)++ % kK4Frontends;
        batch.updates.at(shard).at(lane).push_back(
            grasu::integration::pack_weighted_update(
                edge.source,
                grasu::integration::encode_weighted_pma_word(
                    edge.destination - graph.shards.at(shard).destination_base,
                    edge.weight), edge.delete_op));
    }
    for (std::size_t shard = 0; shard < batch.updates.size(); ++shard) {
        for (std::size_t lane = 0; lane < kK4Frontends; ++lane) {
            if (batch.updates[shard][lane].size() >
                plan.shards.at(shard).update_alloc_counts[lane]) {
                fail("persistent batch exceeds reserved update buffer");
            }
        }
    }
    return batch;
}

namespace {

class Device {
  public:
    explicit Device(const std::string &image)
    {
        const auto device = select_xilinx_device();
        cl_int error = CL_SUCCESS;
        context_ = cl::Context(device, nullptr, nullptr, nullptr, &error);
        check_cl(error, "create persistent context");
        const auto make_queue = [&](const char *name) {
            auto queue = cl::CommandQueue(context_, device,
                CL_QUEUE_PROFILING_ENABLE | CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE,
                &error);
            check_cl(error, name);
            return queue;
        };
        transfer_ = make_queue("create persistent transfer queue");
        update_ = make_queue("create persistent update queue");
        completion_ = make_queue("create persistent completion queue");
        const auto image_bytes = read_binary_file(image);
        cl::Program::Binaries binaries{{image_bytes.data(), image_bytes.size()}};
        program_ = cl::Program(context_, {device}, binaries, nullptr, &error);
        check_cl(error, "program persistent device");
        for (std::size_t lane = 0; lane < kK4Frontends; ++lane) {
            search_[lane] = kernel("bin_search:{bin_search_" +
                                   std::to_string(lane + 1) + "}");
        }
        dispatch_ = kernel("dispatch:{dispatch_1}");
        cache_[0] = kernel("process_cache:{process_cache_1}");
        cache_[1] = kernel("process_cache:{process_cache_2}");
        ddr_[0] = kernel("process_ddr:{process_ddr_1}");
        ddr_[1] = kernel("process_ddr:{process_ddr_2}");
        barrier_ = kernel("pma_completion_barrier:{pma_completion_barrier_1}");
    }

    void upload_initial(const WeightedPmaRuntimePlan &plan,
                        const std::vector<WeightedPmaPackedShardBuffers> &packed)
    {
        shards_.resize(packed.size());
        try {
            for (std::size_t shard = 0; shard < packed.size(); ++shard) {
                auto &buffers = shards_[shard];
                const auto &host = packed[shard];
                const auto allocate = [&](const std::string &name,
                                          cl_mem_ext_ptr_t &ext, std::size_t bytes,
                                          cl_mem_flags access) {
                    ext = ext_ptr(static_cast<unsigned>(
                        find_weighted_pma_region(plan, shard, name).channel));
                    return make_buffer(context_, access | CL_MEM_EXT_PTR_XILINX,
                                       bytes, &ext, name);
                };
                for (std::size_t lane = 0; lane < kK4Frontends; ++lane) {
                    buffers.update_dev[lane] = allocate(
                        "update" + std::to_string(lane), buffers.update_ext[lane],
                        plan.shards[shard].update_alloc_counts[lane] * sizeof(std::uint64_t),
                        CL_MEM_READ_ONLY);
                    buffers.pma_dev[lane] = allocate(
                        "pma" + std::to_string(lane), buffers.pma_ext[lane],
                        host.pma_words[lane].size() * sizeof(std::uint32_t),
                        CL_MEM_READ_WRITE);
                    write_device_buffer(transfer_, buffers.pma_dev[lane],
                        host.pma_words[lane].size() * sizeof(std::uint32_t),
                        host.pma_words[lane].data(), "initial PMA");
                }
                buffers.row_dev = allocate("row", buffers.row_ext,
                    host.row_bounds.size() * sizeof(std::uint64_t), CL_MEM_READ_ONLY);
                buffers.binary_dev = allocate("binary", buffers.binary_ext,
                    host.binary_heads.size() * sizeof(std::uint64_t), CL_MEM_READ_ONLY);
                write_device_buffer(transfer_, buffers.row_dev,
                    host.row_bounds.size() * sizeof(std::uint64_t),
                    host.row_bounds.data(), "initial rows");
                write_device_buffer(transfer_, buffers.binary_dev,
                    host.binary_heads.size() * sizeof(std::uint64_t),
                    host.binary_heads.data(), "initial binary heads");
                allocate_sharded_metadata_replicas(
                    context_, transfer_, plan, shard, host, buffers);
            }
            check_cl(transfer_.finish(), "complete persistent initial writes");
            // Only initial graph/metadata residency; no future updates are uploaded here.
            premigrate_sharded_inputs(transfer_, shards_, false, false);
            check_cl(transfer_.finish(), "complete persistent initial residency");
        } catch (...) {
            transfer_.finish();
            throw;
        }
    }

    void upload_batch(const Batch &batch)
    {
        std::vector<cl::Memory> inputs;
        try {
            for (std::size_t shard = 0; shard < shards_.size(); ++shard) {
                for (std::size_t lane = 0; lane < kK4Frontends; ++lane) {
                    if (batch.updates[shard][lane].empty()) continue;
                    upload_sharded_update_lane(
                        transfer_, shards_[shard], batch.updates[shard], lane);
                    inputs.push_back(shards_[shard].update_dev[lane]);
                }
            }
            check_cl(transfer_.finish(), "complete persistent batch writes");
            if (!inputs.empty()) {
                check_cl(transfer_.enqueueMigrateMemObjects(inputs, 0),
                         "migrate persistent batch updates");
                check_cl(transfer_.finish(), "complete persistent batch upload");
            }
        } catch (...) {
            transfer_.finish();
            throw;
        }
    }

    void launch_wait(const Batch &batch, const WeightedPmaRuntimePlan &plan)
    {
        for (std::size_t shard = 0; shard < shards_.size(); ++shard) {
            if (batch.counts[shard] == 0) continue;
            auto &buffers = shards_[shard];
            for (std::size_t lane = 0; lane < kK4Frontends; ++lane) {
                int arg = 0;
                check_cl(search_[lane].setArg(arg++, buffers.update_dev[lane]),
                         "set persistent search updates");
                for (int copy = 0; copy < 4; ++copy) {
                    check_cl(search_[lane].setArg(arg++, sharded_search_binary(buffers, lane)),
                             "set persistent search binary");
                }
                for (int copy = 0; copy < 4; ++copy) {
                    check_cl(search_[lane].setArg(arg++, sharded_search_row(buffers, lane)),
                             "set persistent search rows");
                }
                check_cl(search_[lane].setArg(arg++, static_cast<unsigned>(
                    batch.updates[shard][lane].size())), "set persistent search count");
            }
            check_cl(dispatch_.setArg(0, static_cast<unsigned>(batch.counts[shard])),
                     "set persistent dispatch count");
            for (std::size_t half = 0; half < 2; ++half) {
                check_cl(cache_[half].setArg(0, buffers.pma_dev[half * 2]),
                         "set persistent cache PMA");
                bind_sharded_cache_extent(cache_[half], plan.shards[shard], half, 3);
                for (int arg = 0; arg < 4; ++arg) {
                    check_cl(ddr_[half].setArg(arg, buffers.pma_dev[half * 2 + 1]),
                             "set persistent DDR PMA");
                }
            }
            // Zero-count search lanes still participate in the dispatch protocol.
            for (auto &cu : cache_) check_cl(update_.enqueueTask(cu), "launch persistent cache");
            for (auto &cu : ddr_) check_cl(update_.enqueueTask(cu), "launch persistent DDR");
            check_cl(update_.enqueueTask(dispatch_), "launch persistent dispatch");
            for (auto &cu : search_) check_cl(update_.enqueueTask(cu), "launch persistent search");
            // The stream consumer must be submitted before waiting for its producers.
            check_cl(completion_.enqueueTask(barrier_), "launch persistent barrier");
            check_cl(update_.flush(), "flush persistent producers");
            check_cl(completion_.flush(), "flush persistent barrier");
            check_cl(update_.finish(), "wait for persistent update");
            check_cl(completion_.finish(), "wait for persistent completion barrier");
        }
    }

    PmaUpdateValidation validate(const WeightedPartitionedPmaGraph &graph)
    {
        return validate_device_pma_updates(transfer_, graph, kMaxCacheSegment, shards_);
    }

  private:
    cl::Kernel kernel(const std::string &name)
    {
        cl_int error = CL_SUCCESS;
        cl::Kernel result(program_, name.c_str(), &error);
        check_cl(error, "create persistent " + name);
        return result;
    }

    cl::Context context_;
    cl::CommandQueue transfer_, update_, completion_;
    cl::Program program_;
    std::array<cl::Kernel, 4> search_;
    std::array<cl::Kernel, 2> cache_, ddr_;
    cl::Kernel dispatch_, barrier_;
    std::vector<DeviceShard> shards_;
};

}  // namespace

}  // namespace figure8_gr
