// Production host: 81cbe8fa597315c829ae50ac3905d0365788ee60.
// Exact transitive source identities are recorded in gr_source_pins.sha256.
#ifndef GRASU_PERSISTENT_HOST_SOURCE
#define GRASU_PERSISTENT_HOST_SOURCE \
    "/data/chuxiao/worktrees/grasu-regraph-fig8-g-once/tools/sharded_k4_native_host.cpp"
#endif
#define main grasu_setup_once_production_main
#include GRASU_PERSISTENT_HOST_SOURCE
#undef main

#include "gr_persistent_runtime.hpp"

namespace figure8_gr {

using Clock = std::chrono::steady_clock;
constexpr const char *kSourceCommit = "81cbe8fa597315c829ae50ac3905d0365788ee60";
constexpr const char *kHostSha256 =
    "d24067c75d0ee28f27128a7c5f64107fe8ceaa280775cecd195edb4937ac9ba0";

std::int64_t elapsed_ns(Clock::time_point start, Clock::time_point end)
{
    return std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
}

// Quotient/remainder avoids overflowing i*N when computing floor(i*N/B).
std::size_t boundary(std::size_t updates, unsigned batches, unsigned index)
{
    return (updates / batches) * index +
           ((updates % batches) * static_cast<std::uint64_t>(index)) / batches;
}

unsigned metadata_policy()
{
    const char *value = std::getenv("GRASU_SHARDED_METADATA_REPLICAS");
    if (!value) {
        if (setenv("GRASU_SHARDED_METADATA_REPLICAS", "4", 0)) {
            fail("cannot select default four-copy metadata policy");
        }
        return 4;
    }
    if (std::string(value) != "1" && std::string(value) != "4") {
        fail("GRASU_SHARDED_METADATA_REPLICAS must be 1 or 4");
    }
    return std::string(value) == "1" ? 1 : 4;
}

void help(const char *binary)
{
    std::cout << "Usage: " << binary
              << " --persistent-update <xclbin> <native.graph> <batch_count> <oracle.txt>\n"
              << "One measured update-only pass with persistent PMA; 1 <= batches <= updates.\n"
              << "Updates must insert previously absent edges, with no deletes or weight replacements.\n"
              << "Batches are chronological [floor(i*N/B), floor((i+1)*N/B)).\n"
              << "GRASU_SHARDED_METADATA_REPLICAS=4 (default) or 1 (explicit shared tables); no fallback.\n"
              << "Requires ORIGINAL_R_LEASE_FD, XCL_DEVICE_INDEX, GRASU_REGRAPH_EXPECT_BDF.\n"
              << "Requires GRASU_UPDATE_REPEATS=1 and initial premigration enabled.\n"
              << "Per-batch batch_ns=prepare_ns+upload_ns; update_wall_ns=launch/wait.\n"
              << "setup_inclusive_ns=layout_ns+initial upload_ns+sum(batch_ns+update_wall_ns).\n"
              << "Parsing, programming, validation/readback and logging are outside timed phases.\n"
              << "Final oracle compares every word in all trace-touched PMA segments.\n"
              << "Clock/image identity capture and bounded execution belong to the board runner.\n"
              << "Source commit: " << kSourceCommit << '\n'
              << "Host source: " << GRASU_PERSISTENT_HOST_SOURCE << '\n'
              << "Host SHA-256: " << kHostSha256 << '\n';
}

int run(const std::string &image, const std::string &input,
        unsigned batches, const std::string &oracle_path)
{
    if (update_repeat_count() != 1 || resident_batch_wall_enabled()) {
        fail("persistent update requires one pass and no resident compute mode");
    }
    const char *premigrate = std::getenv("GRASU_SHARDED_PREMIGRATE_INPUTS");
    if (premigrate && std::string(premigrate) != "1") {
        fail("persistent update requires initial premigration enabled");
    }
    const auto replicas = metadata_policy();
    require_active_min_lease();
    const auto dataset = read_dataset(input);
    const auto update_count = dataset.update_edges.size();
    if (batches == 0 || batches > update_count ||
        std::any_of(dataset.update_edges.begin(), dataset.update_edges.end(),
                    [](const auto &edge) { return edge.delete_op; })) {
        fail("persistent update requires nonempty insertion batches and 1 <= batches <= updates");
    }

    const auto layout_begin = Clock::now();
    const auto graph = build_weighted_partitioned_pma_graph(
        dataset.node_size, kPartitionSize, dataset.static_edges, dataset.update_edges);
    // Pure insertions give a one-to-one chronological logical/physical boundary.
    // Reject replacements rather than splitting their delete/insert lowering.
    if (graph.physical_internal.size() != update_count) {
        fail("persistent Fig8 accepts new-edge insertions only, not weight replacements");
    }
    auto plan = build_weighted_pma_runtime_plan(
        graph, kMaxCacheSegment, grasu::integration::kWeightedPmaRuntimeChannels,
        grasu::integration::kU55cHbmPseudoChannelBytes,
        WeightedPmaChannelPolicy::lane_aware_u55c, GRASU_REGRAPH_HOST_ROW_LINE_READ);
    if (replicas == 4) {
        plan = grasu::integration::replicate_weighted_pma_metadata(std::move(plan));
    }
    if (graph.shards.empty() || graph.shards.size() > 255) {
        fail("persistent sharded PMA requires 1..255 destination partitions");
    }
    for (const auto &shard : graph.shards) {
        if (shard.initial_pma_words.empty() ||
            shard.initial_pma_words.size() % kWeightedPmaSegmentSlots != 0 ||
            shard.initial_pma_words.size() > std::numeric_limits<unsigned>::max() ||
            shard.physical_updates.size() > std::numeric_limits<unsigned>::max()) {
            fail("persistent sharded PMA exceeds the update control ABI");
        }
    }
    // Keep full-trace update capacities/activity for production placement and
    // metadata replicas; pack and upload only each arriving batch's payload.
    const auto packed = pack_weighted_pma_runtime_buffers(graph, plan, false);
    const auto layout_end = Clock::now();

    std::cout << "GRASU_PERSISTENT_CONFIG source_commit=" << kSourceCommit
              << " host_source_sha256=" << kHostSha256
              << " metadata_replicas=" << replicas
              << " metadata_policy=" << (replicas == 1 ? "explicit_shared" : "four_copy")
              << " trace_aware_pma=1 initial_uploads=1 repeats=1 graph_compute_executed=0"
              << " update_allocation=trace_upper_bound"
              << " shards=" << graph.shards.size()
              << " hbm_graph_allocated_bytes=" << plan.total_allocated_bytes
              << " peak_channel_bytes=" << *std::max_element(
                     plan.channel_load_bytes.begin(), plan.channel_load_bytes.end())
              << " channel_capacity_bytes=" << plan.channel_capacity_bytes << std::endl;

    Device device(image);
    const auto upload_begin = Clock::now();
    device.upload_initial(plan, packed);
    const auto upload_end = Clock::now();

    std::int64_t batch_total_ns = 0;
    std::int64_t update_total_ns = 0;
    for (unsigned batch_index = 0; batch_index < batches; ++batch_index) {
        const auto begin = boundary(update_count, batches, batch_index);
        const auto end = boundary(update_count, batches, batch_index + 1);
        const auto prepare_begin = Clock::now();
        const auto batch = prepare_batch(graph, plan, begin, end);
        const auto prepare_end = Clock::now();
        device.upload_batch(batch);
        const auto batch_uploaded = Clock::now();
        device.launch_wait(batch, plan);
        const auto batch_complete = Clock::now();
        const auto prepare_ns = elapsed_ns(prepare_begin, prepare_end);
        const auto batch_upload_ns = elapsed_ns(prepare_end, batch_uploaded);
        const auto batch_ns = prepare_ns + batch_upload_ns;
        const auto update_ns = elapsed_ns(batch_uploaded, batch_complete);
        batch_total_ns += batch_ns;
        update_total_ns += update_ns;
        std::cout << "GRASU_PERSISTENT_BATCH batch=" << batch_index
                  << " updates=" << end - begin
                  << " batch_ns=" << batch_ns
                  << " update_wall_ns=" << update_ns
                  << " prepare_ns=" << prepare_ns
                  << " upload_ns=" << batch_upload_ns
                  << " begin=" << begin << " end=" << end
                  << " active_shards=" << std::count_if(
                         batch.counts.begin(), batch.counts.end(),
                         [](auto count) { return count != 0; })
                  << " status=COMPLETE" << std::endl;
    }

    // The unchanged full trace replays sequentially from the initial PMA in
    // the production reference. No per-batch reset or graph oracle is used.
    const auto validation = device.validate(graph);
    const bool pass = validation.mismatches == 0 &&
                      validation.touched_segments != 0 && validation.checked_words != 0;
    std::ofstream oracle(oracle_path);
    if (!oracle) fail("failed to open persistent oracle file: " + oracle_path);
    oracle << "status=" << (pass ? "PASS" : "FAIL")
           << " touched_segments=" << validation.touched_segments
           << " checked_words=" << validation.checked_words
           << " mismatches=" << validation.mismatches
           << " pma_mismatches=" << validation.mismatches
           << " batches=" << batches << " metadata_replicas=" << replicas << '\n';
    oracle.close();
    if (!oracle) fail("failed to write persistent oracle file: " + oracle_path);
    const auto layout_ns = elapsed_ns(layout_begin, layout_end);
    const auto upload_ns = elapsed_ns(upload_begin, upload_end);
    std::cout << "GRASU_PERSISTENT_UPDATE status=" << (pass ? "PASS" : "FAIL")
              << " vertices=" << dataset.node_size
              << " initial_edges=" << dataset.static_edges.size()
              << " logical_updates=" << update_count
              << " batches=" << batches
              << " layout_ns=" << layout_ns
              << " upload_ns=" << upload_ns
              << " batch_ns=" << batch_total_ns
              << " update_wall_ns=" << update_total_ns
              << " setup_inclusive_ns=" << layout_ns + upload_ns + batch_total_ns + update_total_ns
              << " pma_mismatches=" << validation.mismatches
              << " metadata_replicas=" << replicas
              << " trace_aware_pma=1 repeats=1"
              << " touched_segments=" << validation.touched_segments
              << " checked_words=" << validation.checked_words << std::endl;
    return pass ? EXIT_SUCCESS : EXIT_FAILURE;
}

}  // namespace figure8_gr

int main(int argc, char **argv)
{
    if (argc == 2 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "-h")) {
        figure8_gr::help(argv[0]);
        return EXIT_SUCCESS;
    }
    if (argc != 6 || std::string(argv[1]) != "--persistent-update") {
        figure8_gr::help(argv[0]);
        return EXIT_FAILURE;
    }
    try {
        return figure8_gr::run(argv[2], argv[3],
            parse_unsigned_arg(argv[4], "batch_count"), argv[5]);
    } catch (const std::exception &error) {
        std::cerr << "GRASU_PERSISTENT_UPDATE_ERROR " << error.what() << '\n';
        std::cout << "GRASU_PERSISTENT_UPDATE status=FAIL" << std::endl;
        return EXIT_FAILURE;
    }
}
