#pragma once

#include "runtime.hpp"
#include "input.hpp"
#include <chrono>
#include <iomanip>

namespace source_retention {
using original_g_board::checked;

struct Device {
    original_g_board::Session session;
    std::array<cl::Kernel, 4> adapter, gather;
    cl::Kernel mux, apply, hbm;
    struct Shard { std::array<cl::Buffer, 4> pma; cl::Buffer rows; };
    std::vector<Shard> shards;
    cl::Buffer degree, rank, residual, stats;
    std::array<cl::Buffer, 2> source, output;

    template<class T> cl::Buffer buffer(unsigned bank, const std::vector<T>& values) {
        rb::require(bank < 32 && !values.empty() && values.size() * sizeof(T) < (256ull << 20),
                    "bounded candidate HBM allocation required");
        cl_mem_ext_ptr_t ext{}; ext.flags = bank | XCL_MEM_TOPOLOGY;
        cl_int error{};
        cl::Buffer result(session.context, CL_MEM_READ_WRITE | CL_MEM_EXT_PTR_XILINX,
                          values.size() * sizeof(T), &ext, &error);
        checked(error, "candidate allocation");
        checked(session.queue.enqueueWriteBuffer(result, CL_TRUE, 0, values.size() * sizeof(T), values.data()),
                "candidate preload");
        return result;
    }

    Device(const char* xclbin, unsigned index, const Input& input)
        : session(xclbin, index), mux(session.kernel("regraph_frontend_mux:{regraph_frontend_mux_1}")),
          apply(session.kernel("regraph_pagerank_apply:{regraph_pagerank_apply_1}")),
          hbm(session.kernel("kernelHBMWrapper:{kernelHBMWrapper_1}")) {
        rb::require(apply.getInfo<CL_KERNEL_NUM_ARGS>() == 13, "routed residual-PR apply ABI required");
        std::vector<cl::Memory> resident;
        for (unsigned w = 0; w < 4; ++w) {
            adapter[w] = session.kernel("pma_to_regraph_adapter:{pma_to_regraph_adapter_" + std::to_string(w + 1) + "}");
            gather[w] = session.kernel("lksg_stream:{lksg_stream_" + std::to_string(w + 1) + "}");
#if defined(SPINE_RETENTION_TAIL_PUBLICATION)
            checked(gather[w].setArg(5, 65536u / 2), "require tail-publication gather ABI");
#endif
        }
        for (unsigned s = 0; s < input.packed.size(); ++s) {
            Shard shard;
            const auto& packed = input.packed[s];
            for (unsigned lane = 0; lane < 4; ++lane) {
                const auto region = gp::find_weighted_pma_region(input.plan, s, "pma" + std::to_string(lane));
                shard.pma[lane] = buffer(region.channel, packed.pma_words[lane]);
                resident.push_back(shard.pma[lane]);
            }
            shard.rows = buffer(gp::find_weighted_pma_region(input.plan, s, "row").channel, packed.row_bounds);
            resident.push_back(shard.rows); shards.push_back(shard);
        }
        const std::vector<float> zeros(input.source.size());
        degree = buffer(27, input.degree); rank = buffer(25, zeros); residual = buffer(26, zeros);
        stats = buffer(27, std::vector<unsigned>(16));
        for (unsigned copy = 0; copy < 2; ++copy) {
            source[copy] = buffer(23 + copy, input.source); output[copy] = buffer(23 + copy, zeros);
            resident.push_back(source[copy]); resident.push_back(output[copy]);
        }
        for (const auto& value : {degree, rank, residual, stats}) resident.push_back(value);
        checked(session.queue.enqueueMigrateMemObjects(resident, 0), "candidate residency");
        checked(session.queue.finish(), "candidate residency finish");
    }

    void run(const Input& input, unsigned repeat) {
        const unsigned vertices = input.reference.vertices;
#if defined(SPINE_RETENTION_TAIL_PUBLICATION)
        const unsigned bursts = (vertices + 15u) / 16u;
#else
        const unsigned bursts = input.source.size() / 16;
#endif
        const std::vector<float> zeros(input.source.size());
        checked(session.queue.enqueueWriteBuffer(rank, CL_TRUE, 0, zeros.size() * 4, zeros.data()), "restore rank");
        checked(session.queue.enqueueWriteBuffer(residual, CL_TRUE, 0, zeros.size() * 4, zeros.data()), "restore residual");
        std::vector<cl::Event> events(2 + 3 * shards.size());
        const auto begin = std::chrono::steady_clock::now();
        for (unsigned i = 0; i < 4; ++i) checked(hbm.setArg(i, source[i % 2]), "bind source");
        for (unsigned i = 0; i < 2; ++i) checked(hbm.setArg(4 + i, output[i]), "bind output");
        for (unsigned w = 0; w < 4; ++w)
            checked(hbm.setArg(6 + w, unsigned((shards.size() + 3 - w) / 4)), "bind worker partitions");
        unsigned arg = 0;
        for (const auto& b : {rank, residual, degree, stats}) checked(apply.setArg(arg++, b), "bind apply state");
        checked(apply.setArg(arg++, bursts), "bind bursts");
        checked(apply.setArg(arg++, vertices), "bind vertices");
        checked(apply.setArg(arg++, 108.0F / 128.0F), "bind common damping");
        checked(apply.setArg(arg++, 0.0F), "bind zero threshold");
        checked(apply.setArg(arg++, 0.0F), "bind zero base");
        checked(apply.setArg(arg++, 0.0F), "bind zero dangling");
        checked(apply.setArg(arg++, true), "bind correction identity with zero rank");
        checked(session.queue.enqueueTask(hbm, nullptr, &events[0]), "launch HBM");
        checked(session.queue.enqueueTask(apply, nullptr, &events[1]), "launch apply");
        for (unsigned s = 0; s < shards.size(); ++s) {
            const auto w = s % 4;
            for (unsigned lane = 0; lane < 4; ++lane) checked(adapter[w].setArg(lane, shards[s].pma[lane]), "bind PMA");
            checked(adapter[w].setArg(4, shards[s].rows), "bind rows");
            checked(adapter[w].setArg(5, vertices), "bind source count");
            const auto slots = unsigned(input.plan.shards[s].pma_slot_count);
            checked(adapter[w].setArg(6, slots), "bind slots");
            checked(adapter[w].setArg(7, 131072u), "bind cache boundary");
            checked(adapter[w].setArg(8, s * 65536u), "bind destination base");
            const auto dst_vertices = unsigned(input.graph.shards[s].destination_vertices);
            checked(adapter[w].setArg(9, dst_vertices), "bind destination count");
            checked(gather[w].setArg(1, slots), "bind gather slots");
            checked(gather[w].setArg(2, 0u), "bind uncompressed groups");
            checked(gather[w].setArg(3, s * 65536u), "bind gather base");
            checked(gather[w].setArg(4, s < 4), "initialize each gather worker");
            checked(mux.setArg(4, w), "bind mux worker");
            // Gather packets carry two destinations; Apply beats carry sixteen.
#if defined(SPINE_RETENTION_TAIL_PUBLICATION)
            const unsigned packets = ((dst_vertices + 15u) / 16u) * 8u;
            checked(gather[w].setArg(5, packets), "bind gather publication rows");
#else
            const unsigned packets = 65536u / 2;
#endif
            checked(mux.setArg(5, packets), "bind mux packets");
            std::vector<cl::Event> aw, gw, mw;
            if (s >= 4) { aw.push_back(events[2 + 3 * (s - 4)]); gw.push_back(events[3 + 3 * (s - 4)]); }
            if (s) mw.push_back(events[4 + 3 * (s - 1)]);
            checked(session.queue.enqueueTask(adapter[w], aw.empty() ? nullptr : &aw, &events[2 + 3 * s]), "launch adapter");
            checked(session.queue.enqueueTask(gather[w], gw.empty() ? nullptr : &gw, &events[3 + 3 * s]), "launch gather");
            checked(session.queue.enqueueTask(mux, mw.empty() ? nullptr : &mw, &events[4 + 3 * s]), "launch mux");
        }
        checked(session.queue.finish(), "finish candidate pipeline");
        const double wall = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count();
        // With zero old rank, correction residual is exactly the unrounded gather sum.
        session.verify(rank, zeros); session.verify(residual, input.sums);
        for (unsigned copy = 0; copy < 2; ++copy) {
            session.verify(source[copy], input.source); session.verify(output[copy], input.payload);
        }
        session.verify(degree, input.degree);
        std::vector<unsigned> status(16);
        checked(session.queue.enqueueReadBuffer(stats, CL_TRUE, 0, status.size() * 4, status.data()), "read stats");
        rb::require(status[0] == 0 && status[4] == vertices, "candidate status failed");
        cl_ulong first = UINT64_MAX, last = 0;
        for (unsigned i = 0; i < events.size(); ++i) {
            const auto start = events[i].getProfilingInfo<CL_PROFILING_COMMAND_START>();
            const auto end = events[i].getProfilingInfo<CL_PROFILING_COMMAND_END>();
            rb::require(end > start, "nonpositive candidate event");
            first = std::min(first, start); last = std::max(last, end);
            std::cout << "RETENTION_EVENT {\"repeat\":" << repeat << ",\"ordinal\":" << i
                      << ",\"start_ns\":" << start << ",\"end_ns\":" << end << "}\n";
        }
        std::cout << std::setprecision(17) << "RETENTION_RESULT {\"repeat\":" << repeat
                  << ",\"correctness\":true,\"event_span_ns\":" << last - first
                  << ",\"resident_wall_ms\":" << wall << "}\n" << std::flush;
    }
};
}  // namespace source_retention
