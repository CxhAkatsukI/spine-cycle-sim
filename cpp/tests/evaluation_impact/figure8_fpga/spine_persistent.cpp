#include "spine_setup_once_bridge.hpp"
#include "spine_persistent_input.hpp"
#include "spine_persistent_schedule.hpp"
#include "spine_persistent_bootstrap.hpp"

#include <charconv>

namespace {

static void persistent_usage(std::ostream &out, const char *binary) {
    out << "Usage: " << binary
        << " <xclbin> --persistent-update --dynamic-graph <native.graph>"
           " --batches <N>\n"
        << "One pass; chronological floor(i*updates/N) batches; bootstrap once.\n"
        << "Maintenance only, no propagation. Fixed carry layout; bootstrap L10.\n"
        << "Logical batches use capacity-safe physical launches of <=8192 updates.\n"
        << "batch_ns includes host preparation and input DMA; update_wall_ns"
           " ends at kernel completion.\n"
        << "Input parsing, programming, status/graph readback, and oracle are"
           " outside the reported sum.\n"
        << "Board execution requires ORIGINAL_R_LEASE_FD, XCL_DEVICE_INDEX,"
           " and SPINE_EXPECT_BDF.\n"
        << "Setup-once source: " << SPINE_SETUP_ONCE_HOST_SOURCE << '\n';
}

static size_t persistent_batch_count(const char *text) {
    const std::string value(text);
    size_t batches = 0;
    const auto parsed = std::from_chars(
        value.data(), value.data() + value.size(), batches);
    require(parsed.ec == std::errc{} &&
                parsed.ptr == value.data() + value.size() && batches > 0,
            "--batches requires a positive integer");
    return batches;
}

static void run_persistent_update(const std::string &xclbin,
                                  const std::string &path, size_t batches) {
    require_update_setup_lease();
    const SetupInsertionBatch trace = read_persistent_insertion_trace(path, batches);
    const auto layout_start = std::chrono::steady_clock::now();
    size_t launch_budget = 0;
    for (size_t index = 0; index < batches; ++index) {
        const size_t begin = persistent_batch_boundary(index, trace.inserts.size(), batches);
        const size_t end = persistent_batch_boundary(index + 1, trace.inserts.size(), batches);
        launch_budget += persistent_schedule::spans(begin, end).size();
    }
    auto plan = build_persistent_graph_plan(
        build_persistent_reference(trace), trace.inserts.size(), launch_budget, trace.vertices);
    const auto layout_end = std::chrono::steady_clock::now();
    PersistentSpineRuntime runtime(xclbin, std::move(plan), trace.vertices);
    const int64_t layout_ns = runtime.elapsed_ns(layout_start, layout_end);
    const int64_t bootstrap_ns = runtime.setup_bootstrap_ns();
    int64_t batch_ns = 0, update_wall_ns = 0;
    size_t consumed = 0, physical_launches = 0;
    for (size_t index = 0; index < batches; ++index) {
        const size_t begin = persistent_batch_boundary(index, trace.inserts.size(), batches);
        const size_t end = persistent_batch_boundary(index + 1, trace.inserts.size(), batches);
        require(begin == consumed && end > begin && end <= trace.inserts.size(),
                "persistent chronological batch coverage is inconsistent");
        int64_t preparation_ns = 0, completion_ns = 0;
        size_t sublaunches = 0;
        for (const auto span : persistent_schedule::spans(begin, end)) {
            const auto pack_start = std::chrono::steady_clock::now();
            std::vector<DynamicUpdate> updates(trace.inserts.begin() + span.begin,
                                               trace.inserts.begin() + span.end);
            // Establish chronological subwindows before sorting for the ABI.
            std::stable_sort(updates.begin(), updates.end(), [](const auto &lhs, const auto &rhs) {
                return std::tie(lhs.src, lhs.dst, lhs.weight, lhs.diff) <
                       std::tie(rhs.src, rhs.dst, rhs.weight, rhs.diff);
            });
            runtime.prepare_batch(updates);
            preparation_ns += runtime.elapsed_ns(
                pack_start, std::chrono::steady_clock::now());
            completion_ns += runtime.complete_batch();
            ++physical_launches;
            ++sublaunches;
        }
        require(preparation_ns > 0 && completion_ns > 0,
                "persistent batch timings must be positive");
        batch_ns += preparation_ns;
        update_wall_ns += completion_ns;
        consumed = end;
        std::cout << "SPINE_PERSISTENT_BATCH batch=" << index
                  << " updates=" << end - begin
                  << " physical_launches=" << sublaunches
                  << " batch_ns=" << preparation_ns
                  << " update_wall_ns=" << completion_ns
                  << " begin=" << begin << " end=" << end
                  << " target_level=" << runtime.target_level()
                  << " path=" << runtime.maintenance_path() << std::endl;
    }
    require(consumed == trace.inserts.size() && layout_ns > 0 && bootstrap_ns > 0,
            "persistent update coverage or setup timing is invalid");
    // Full graph migration and the independent old-plus-all-inserts oracle
    // occur only after every measured maintenance invocation has completed.
    const size_t checked_edges = runtime.validate_final_graph(trace);
    runtime.print_update_setup_bootstrap();
    std::cout << "SPINE_PERSISTENT_UPDATE status=PASS vertices=" << trace.vertices
              << " bootstrap_level=" << kPersistentBootstrapLevel
              << " initial_edges=" << trace.old_edges.size()
              << " logical_updates=" << consumed << " batches=" << batches
              << " physical_launches=" << physical_launches
              << " layout_ns=" << layout_ns << " bootstrap_ns=" << bootstrap_ns
              << " batch_ns=" << batch_ns << " update_wall_ns=" << update_wall_ns
              << " setup_inclusive_ns=" << layout_ns + bootstrap_ns + batch_ns + update_wall_ns
              << " checked_edges=" << checked_edges << std::endl;
}

}  // namespace

int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    std::cerr.setf(std::ios::unitbuf);
    if (argc == 2 && (std::string(argv[1]) == "--help" ||
                      std::string(argv[1]) == "-h")) {
        persistent_usage(std::cout, argv[0]);
        return 0;
    }
    if (argc != 7) {
        persistent_usage(std::cerr, argv[0]);
        return 2;
    }
    try {
        require(std::string(argv[2]) == "--persistent-update" &&
                    std::string(argv[3]) == "--dynamic-graph" &&
                    std::string(argv[5]) == "--batches",
                "expected --persistent-update --dynamic-graph PATH --batches N");
        const size_t batches = persistent_batch_count(argv[6]);
        run_persistent_update(argv[1], argv[4], batches);
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "SPINE_PERSISTENT_UPDATE status=FAIL error=" << error.what()
                  << std::endl;
        return 1;
    }
}
