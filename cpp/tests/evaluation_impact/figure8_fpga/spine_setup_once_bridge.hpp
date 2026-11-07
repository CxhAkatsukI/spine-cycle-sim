#pragma once

// Source: spine-hls-fig8-native, 475edcacc2c8e482bd497515e31e370084af78f6.
// host_partitioned_algorithms_smoke.cpp SHA256:
// bd29777b662f94f4386993e23ca6cfd2f32977f19f640aa69f8eb16d747b92c1
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

namespace {

static_assert(SPINE_ALGORITHM_KIND == 0,
              "persistent update host requires the weighted-SSSP image ABI");

class PersistentSpineRuntime final : private SplitAlgorithmRuntime {
  public:
    PersistentSpineRuntime(const std::string &xclbin, SetupGraphImage &&image,
                           int vertices)
        : SplitAlgorithmRuntime(xclbin, std::move(image), vertices, true) {}

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
        return validate_updated_graph(trace);
    }

    int target_level() const {
        return reader_result_.at(HOST_MAINT_RESULT_TARGET_LEVEL);
    }

    int maintenance_path() const {
        return reader_result_.at(HOST_MAINT_RESULT_PATH);
    }

    using SplitAlgorithmRuntime::elapsed_ns;
    using SplitAlgorithmRuntime::print_update_setup_bootstrap;
    using SplitAlgorithmRuntime::setup_bootstrap_ns;

  private:
    enum class Phase { Ready, Prepared, Complete, Failed };
    Phase phase_ = Phase::Ready;
};

}  // namespace
