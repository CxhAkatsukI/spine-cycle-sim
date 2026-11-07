#pragma once

// Source: spine-hls-fig8-native, base 475edcacc2c8e482bd497515e31e370084af78f6
// plus maintenance-only allocation, residency and scratch-initialization repairs.
// host_partitioned_algorithms_smoke.cpp SHA256:
// 8f227f9983354d7cca314ec71c581fd815376cc3c290f45f7c086ad12683b073
// Preload dependencies before changing access on the retained host's runtime.
#include "host_split.hpp"
#include "spine_paper_architecture_contract.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <limits>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>
#include <sys/file.h>
#include <sys/stat.h>

#ifndef SPINE_SETUP_ONCE_HOST_SOURCE
#define SPINE_SETUP_ONCE_HOST_SOURCE \
    "/data/chuxiao/worktrees/spine-hls-fig8-native/tests/test_integration/host_partitioned_algorithms_smoke.cpp"
#endif

#pragma push_macro("main")
#pragma push_macro("private")
#define main spine_retained_setup_once_main
#define private protected
#include SPINE_SETUP_ONCE_HOST_SOURCE
#pragma pop_macro("private")
#pragma pop_macro("main")

#include "spine_persistent_layout.hpp"

namespace {

static_assert(SPINE_ALGORITHM_KIND == 0,
              "persistent update host requires the weighted-SSSP image ABI");

class PersistentSpineRuntime final : private SplitAlgorithmRuntime {
  public:
    PersistentSpineRuntime(const std::string &xclbin, PersistentGraphPlan &&plan,
                           int vertices)
        : SplitAlgorithmRuntime(xclbin, std::move(plan.image), vertices, true, true) {
        const auto start = std::chrono::steady_clock::now();
        bank_words_ = plan.bank_words;
        // Build the directory from compact host data, but upload the graph
        // only once, directly into the kernel's fixed carry addresses.
        std::vector<cl::Buffer> fixed;
        std::vector<cl::Memory> allocate;
        for (size_t bank = 0; bank < bank_words_.size(); ++bank) {
            maintenance_backing_.push_back(allocate_maintenance_backing(
                bank_words_[bank] * sizeof(uint64_t)));
            fixed.push_back(make_topology_buffer(
                context_, HBM_PARTITIONED_GRAPH_BASE + (unsigned)bank,
                maintenance_backing_.back().get(),
                bank_words_[bank] * sizeof(uint64_t)));
            allocate.push_back(fixed.back());
        }
        const auto allocated_at = std::chrono::steady_clock::now();
        cl_int err = CL_SUCCESS;
        // Only live serialized regions are inputs. Empty pages are protected
        // by their zero metadata epochs; do not upload gigabytes of padding.
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
            allocate, CL_MIGRATE_MEM_OBJECT_CONTENT_UNDEFINED));
        for (const auto &region : plan.regions) {
            OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                fixed.at(region.bank), CL_FALSE,
                region.target_words * sizeof(uint64_t),
                region.words * sizeof(uint64_t),
                graph_host_.at(region.bank).data() + region.source_words));
        }
        for (const auto &patch : plan.descriptor_patches) {
            meta_.at(patch.meta_index) = patch.target_words;
        }
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects({d_meta_}, 0));
        OCL_CHECK(err, err = transfer_q_.finish());
        graph_buffers_ = std::move(fixed);
        const auto completed_at = std::chrono::steady_clock::now();
        relocation_ns_ = elapsed_ns(start, completed_at);
        arena_allocate_ns_ = elapsed_ns(start, allocated_at);
        live_upload_ns_ = elapsed_ns(allocated_at, completed_at);
    }

    void prepare_batch(const std::vector<DynamicUpdate> &updates) {
        require(phase_ == Phase::Ready || phase_ == Phase::Complete,
                "persistent maintenance requires a drained successful batch");
        require(!updates.empty(), "persistent maintenance batch is empty");
        require(phase_ != Phase::Complete ||
                    (maintenance_prepared_ && maintenance_launched_),
                "persistent maintenance completion state is inconsistent");
        // Only invocation bookkeeping is reset. Never re-upload stale graph,
        // metadata, directory, or dirty-generation contents from host memory.
        phase_ = Phase::Failed;
        maintenance_prepared_ = false;
        maintenance_launched_ = false;
        maintenance_input_events_.clear();
        timing_ = TimingLedger{};
        prepare_updates(updates, updates.size());
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.finish());
        phase_ = Phase::Prepared;
    }

    int64_t complete_batch() {
        require(phase_ == Phase::Prepared,
                "persistent maintenance requires an unconsumed prepared batch");
        phase_ = Phase::Failed;
        // The retained method waits for maintenance, reads/checks its status,
        // and returns only launch-to-kernel-completion wall time (no readback).
        const int64_t update_ns = apply_prepared_updates();
        phase_ = Phase::Complete;
        return update_ns;
    }

    size_t validate_final_graph(const SetupInsertionBatch &trace) {
        require(phase_ == Phase::Complete,
                "persistent graph validation requires completed maintenance");
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.enqueueReadBuffer(
            d_meta_, CL_TRUE, 0, meta_.size() * sizeof(uint64_t), meta_.data()));
        for (size_t bank = 0; bank < bank_words_.size(); ++bank) {
            graph_host_[bank].resize(bank_words_[bank]);
            OCL_CHECK(err, err = transfer_q_.enqueueReadBuffer(
                graph_buffers_[bank], CL_TRUE, 0,
                bank_words_[bank] * sizeof(uint64_t), graph_host_[bank].data()));
        }
        return check_setup_updated_graph(graph_host_, meta_, trace);
    }

    int target_level() const {
        return reader_result_.at(HOST_MAINT_RESULT_TARGET_LEVEL);
    }

    int maintenance_path() const {
        return reader_result_.at(HOST_MAINT_RESULT_PATH);
    }

    using SplitAlgorithmRuntime::elapsed_ns;
    int64_t setup_bootstrap_ns() const {
        return SplitAlgorithmRuntime::setup_bootstrap_ns() + relocation_ns_;
    }

    void print_update_setup_bootstrap() const {
        SplitAlgorithmRuntime::print_update_setup_bootstrap();
        std::cout << "SPINE_PERSISTENT_LAYOUT fixed=1 relocation_ns="
                  << relocation_ns_ << " arena_allocate_ns=" << arena_allocate_ns_
                  << " live_upload_ns=" << live_upload_ns_
                  << " graph_uploads=1 bank_words=" << bank_words_[0]
                  << std::endl;
    }

  private:
    enum class Phase { Ready, Prepared, Complete, Failed };
    Phase phase_ = Phase::Ready;
    std::array<size_t, HOST_PARTITIONED_GRAPH_PORTS> bank_words_{};
    int64_t relocation_ns_ = 0;
    int64_t arena_allocate_ns_ = 0;
    int64_t live_upload_ns_ = 0;
};

}  // namespace
