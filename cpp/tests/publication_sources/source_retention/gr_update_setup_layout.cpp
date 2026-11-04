// Use the pinned G+R host's layout and packing without opening an FPGA.
#define main gr_board_main
#include "sharded_k4_native_host.cpp"
#undef main

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "Usage: " << argv[0] << " graph\n";
        return 2;
    }
    try {
        const auto dataset = read_dataset(argv[1]);
        if (dataset.update_edges.empty() ||
            std::any_of(dataset.update_edges.begin(), dataset.update_edges.end(),
                        [](const auto &edge) { return edge.delete_op; })) {
            fail("expected a nonempty insertion batch");
        }
        const auto graph = build_weighted_partitioned_pma_graph(
            dataset.node_size, kPartitionSize, dataset.static_edges, dataset.update_edges);
        const auto plan = configure_sharded_metadata(build_weighted_pma_runtime_plan(
            graph, kMaxCacheSegment, grasu::integration::kWeightedPmaRuntimeChannels,
            grasu::integration::kU55cHbmPseudoChannelBytes,
            WeightedPmaChannelPolicy::lane_aware_u55c, GRASU_REGRAPH_HOST_ROW_LINE_READ));
        const auto packed = pack_weighted_pma_runtime_buffers(graph, plan, true);
        if (graph.shards.empty() || graph.shards.size() > 255 ||
            graph.shards.size() != packed.size()) {
            fail("unexpected packed shard count");
        }
        const auto peak_channel = *std::max_element(plan.channel_load_bytes.begin(),
                                                    plan.channel_load_bytes.end());
        std::cout << "GR_UPDATE_SETUP_LAYOUT_PASS path=" << argv[1]
                  << " vertices=" << dataset.node_size
                  << " parsed_old_edges=" << dataset.static_edges.size()
                  << " parsed_updates=" << dataset.update_edges.size()
                  << " physical_updates=" << graph.physical_internal.size()
                  << " shards=" << packed.size()
                  << " pma_slots=" << total_pma_slots(graph)
                  << " hbm_bytes=" << plan.total_allocated_bytes
                  << " peak_channel_bytes=" << peak_channel
                  << " channel_capacity_bytes=" << plan.channel_capacity_bytes << '\n';
    } catch (const std::exception &error) {
        std::cerr << "GR_UPDATE_SETUP_LAYOUT_FAIL path=" << argv[1]
                  << " reason=" << error.what() << '\n';
        return 1;
    }
}
