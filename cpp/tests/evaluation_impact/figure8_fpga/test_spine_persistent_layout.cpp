#include "spine_setup_once_bridge.hpp"
#include "spine_persistent_bootstrap.hpp"

namespace {

struct LayoutFixture {
    PartitionedHotColdReferenceGraph graph;
    SetupInsertionBatch trace;
};

static LayoutFixture make_fixture(bool force_hot) {
    LayoutFixture fixture;
    fixture.trace.vertices = MAX_N;
    PartitionedHotColdClassification classification;
    classification.empty_hot_set = !force_hot;
    classification.hot_bitmap_words.assign(HOST_PARTITIONED_HOT_BITMAP_WORDS, 0);
    classification.cold_partition_edges.assign(HOST_PARTITIONED_CSR_DST_PARTITIONS, 0);
    classification.hot_shard_edges.assign(HOST_PARTITIONED_HOT_SHARDS, 0);
    std::vector<std::vector<PartitionedCsrEdgeRef>> levels(HOST_PARTITIONED_RATIO2_LEVELS);
    const std::array<uint32_t, 5> sources{{0, 63, 255, 256, MAX_N - 1}};
    for (int level = 1; level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
        const uint32_t dst = (uint32_t)(level % HOST_PARTITIONED_CSR_DST_PARTITIONS) *
                                 VS_PARTITION_SIZE + (uint32_t)level * 16U;
        for (int row = 0; row < 1 + level % 5; ++row) {
            levels[(size_t)level].push_back(
                {sources[(size_t)row], dst, (uint16_t)(4095 - level - row), 1});
        }
        levels[(size_t)level].push_back({0, dst + 1, (uint16_t)(level + 1), 1});
        if (force_hot) {
            const uint32_t hot_dst = dst + 512;
            partitioned_hot_bitmap_set_host(classification.hot_bitmap_words, hot_dst);
            ++classification.hot_vertex_count;
            for (int row = 0; row < 1 + level % 5; ++row) {
                levels[(size_t)level].push_back(
                    {sources[(size_t)row], hot_dst, (uint16_t)(257 + level + row), 1});
            }
        }
    }
    for (const auto &edges : levels) {
        for (const auto &edge : edges) {
            fixture.trace.old_edges.push_back({edge.src, edge.dst, edge.weight, edge.diff});
            ++classification.total_edges;
            if (partitioned_hot_bitmap_test_host(classification.hot_bitmap_words, edge.dst)) {
                ++classification.hot_edges;
                ++classification.hot_shard_edges[(size_t)partitioned_hot_shard_host(
                    edge.dst, HOST_PARTITIONED_HOT_SHARDS)];
            } else {
                ++classification.cold_edges;
                ++classification.cold_partition_edges[(size_t)partitioned_csr_dst_partition(edge.dst)];
            }
        }
    }
    fixture.graph = build_partitioned_hot_cold_reference(levels, classification, MAX_N);
    return fixture;
}

struct SparseBank {
    const PersistentGraphPlan *plan;
    size_t bank;
    size_t size() const { return plan->bank_words.at(bank); }
    uint64_t at(size_t word) const {
        require(word < size(), "sparse read exceeds fixed bank");
        for (const auto &region : plan->regions) {
            if (region.bank == bank && word >= region.target_words &&
                word - region.target_words < region.words) {
                return plan->image.graph_words.at(bank).at(
                    region.source_words + word - region.target_words);
            }
        }
        throw std::runtime_error("sparse oracle read uninitialized fixed padding");
    }
    uint64_t operator[](size_t word) const { return at(word); }
};

static void check_metadata(const LayoutFixture &fixture, const PersistentGraphPlan &plan) {
    const auto &meta = plan.image.meta_words;
    const bool hot = !fixture.graph.classification.empty_hot_set;
    require(partitioned_meta_control_valid_host(meta), "invalid metadata format");
    require(meta.at(HOST_PARTITIONED_META_HOT_ENABLED_WORD) ==
                partitioned_meta_control_host(hot), "incorrect hot control");
    for (int family = 0; family < HOST_PARTITIONED_CSR_FAMILY_COUNT; ++family) {
        const bool is_hot = family >= HOST_PARTITIONED_HOT_FAMILY_BASE;
        const int bank = is_hot ? family - HOST_PARTITIONED_HOT_FAMILY_BASE : family;
        const auto &reference = is_hot ? fixture.graph.hot : fixture.graph.cold;
        for (int level = 0; level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
            const auto &slice = reference.slice(bank, level);
            const bool live = !slice.edges.empty();
            const size_t base = ((size_t)family * HOST_PARTITIONED_RATIO2_LEVELS + level) *
                                HOST_PARTITIONED_META_WORDS_PER_SLICE;
            require(meta.at(base + HOST_PARTITIONED_META_OCCUPIED_WORD) == (live ? 1ULL : 0ULL),
                    "incorrect occupancy");
            require(meta.at(base + HOST_PARTITIONED_META_EDGE_COUNT_WORD) == slice.edges.size() &&
                    meta.at(base + HOST_PARTITIONED_META_ROW_COUNT_WORD) == slice.rows.size(),
                    "incorrect slice counts");
            require(partitioned_slice_epoch_host(meta, family, level) == (live ? 1U : 0U),
                    "incorrect slice epoch");
            require(partitioned_page_list_count_host(meta, family, level) ==
                        slice.page_bitmap_by_page.size(), "incorrect page-list count");
            uint32_t index = 0;
            for (const auto &entry : slice.page_bitmap_by_page) {
                require(partitioned_page_list_id_host(meta, family, level, index++) == entry.first,
                        "incorrect page-list entry");
            }
            for (uint32_t page = 0; page < (uint32_t)PAGE_CSR_PAGE_COUNT; ++page) {
                const uint32_t expected = slice.page_bitmap_by_page.count(page) ? 1U : 0U;
                require(partitioned_page_epoch_host(meta, family, level, page) == expected,
                        "incorrect page epoch");
            }
            if (!live) {
                for (size_t word = 2; word <= 6; ++word) {
                    require(meta.at(base + word) == 0, "empty descriptor allocated payload");
                }
            }
        }
    }
    const auto &classification = fixture.graph.classification;
    for (size_t i = 0; i < classification.hot_bitmap_words.size(); ++i) {
        require(meta.at(HOST_PARTITIONED_META_HOT_BITMAP_BASE + i) ==
                    classification.hot_bitmap_words[i], "incorrect hot bitmap");
    }
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
        require(meta.at(HOST_PARTITIONED_META_COLD_PARTITION_EDGE_COUNT_BASE + bank) ==
                    classification.cold_partition_edges[bank], "incorrect cold counter");
        require(meta.at(HOST_PARTITIONED_META_HOT_SHARD_EDGE_COUNT_BASE + bank) ==
                    classification.hot_shard_edges[bank], "incorrect hot counter");
    }
}

static void check_regions(const PersistentGraphPlan &plan, bool hot) {
    require(partitioned_fixed_all_levels_words_host() == 32804886ULL,
            "test requires the frozen production constants");
    require(plan.regions.size() == plan.descriptor_patches.size() &&
                plan.regions.size() % 5 == 0, "incorrect region/patch count");
    std::array<size_t, HOST_PARTITIONED_GRAPH_PORTS> source_end{}, target_end{};
    for (size_t i = 0; i < plan.regions.size(); ++i) {
        const auto &region = plan.regions[i];
        const auto &patch = plan.descriptor_patches[i];
        const size_t family_level = patch.meta_index / HOST_PARTITIONED_META_WORDS_PER_SLICE;
        const size_t family = family_level / HOST_PARTITIONED_RATIO2_LEVELS;
        const size_t level = family_level % HOST_PARTITIONED_RATIO2_LEVELS;
        const size_t field = patch.meta_index % HOST_PARTITIONED_META_WORDS_PER_SLICE;
        require(field >= 2 && field <= 6 && level != 0, "invalid patch descriptor");
        size_t bitmap = family >= 16 ? 32804886ULL : 0;
        for (size_t l = 0; l < level; ++l) {
            const size_t cap = l == 0 ? 131072ULL : (131072ULL << l) / 16ULL;
            bitmap += 262144ULL + 32769ULL + (cap + 2) / 2 + (cap + 3) / 4 + cap;
        }
        const size_t cap = (131072ULL << level) / 16ULL;
        const std::array<size_t, 5> targets{{bitmap, bitmap + 262144ULL,
            bitmap + 294913ULL, bitmap + 294913ULL + (cap + 2) / 2,
            bitmap + 294913ULL + (cap + 2) / 2 + (cap + 3) / 4}};
        const size_t base = family_level * HOST_PARTITIONED_META_WORDS_PER_SLICE;
        const size_t rows = plan.image.meta_words.at(base + 1);
        const std::array<size_t, 5> lengths{{262144ULL, 32769ULL, (rows + 2) / 2,
            (rows + 3) / 4, (size_t)plan.image.meta_words.at(base)}};
        require(region.bank == family % 16 && region.target_words == targets[field - 2] &&
                    patch.target_words == region.target_words && region.words == lengths[field - 2],
                "fixed layout differs from frozen kernel formula");
        require(region.source_words == source_end.at(region.bank) &&
                    region.target_words >= target_end.at(region.bank), "overlapping regions");
        require(plan.image.meta_words.at(patch.meta_index) == region.source_words,
                "compact metadata does not address source payload");
        source_end[region.bank] += region.words;
        target_end[region.bank] = region.target_words + region.words;
    }
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
        require(plan.bank_words[bank] == (hot ? 65609772ULL : 32804886ULL),
                "incorrect fixed bank extent");
        require(source_end[bank] == plan.image.graph_words[bank].size() &&
                    target_end[bank] <= plan.bank_words[bank], "incorrect payload extent");
    }
}

static void check_fixture(bool hot) {
    const auto fixture = make_fixture(hot);
    auto plan = build_persistent_graph_plan(fixture.graph);
    check_regions(plan, hot);
    check_metadata(fixture, plan);
    require(check_setup_updated_graph(plan.image.graph_words, plan.image.meta_words,
                                      fixture.trace) == fixture.trace.old_edges.size(),
            "compact weighted graph oracle failed");
    std::vector<SparseBank> sparse;
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
        sparse.push_back({&plan, bank});
    }
    for (const auto &patch : plan.descriptor_patches) {
        plan.image.meta_words.at(patch.meta_index) = patch.target_words;
    }
    check_metadata(fixture, plan);
    require(check_setup_updated_graph(sparse, plan.image.meta_words, fixture.trace) ==
                fixture.trace.old_edges.size(), "fixed weighted graph oracle failed");
    size_t bytes = plan.image.meta_words.size() * sizeof(uint64_t);
    for (const auto &bank : plan.image.graph_words) bytes += bank.size() * sizeof(uint64_t);
    std::cout << "LAYOUT_TEST hot=" << hot << " edges=" << fixture.trace.old_edges.size()
              << " regions=" << plan.regions.size() << " host_bytes=" << bytes << '\n';
}

static void check_rejections() {
    auto fixture = make_fixture(true);
    const auto occupied = std::find_if(fixture.graph.cold.slices.begin(),
        fixture.graph.cold.slices.end(), [](const auto &slice) { return !slice.edges.empty(); });
    require(occupied != fixture.graph.cold.slices.end(), "missing rejection fixture");
    for (bool hot : {false, true}) {
        auto graph = fixture.graph;
        (hot ? graph.hot : graph.cold).slices[0] = *occupied;
        bool rejected = false;
        try { (void)build_persistent_graph_plan(graph); }
        catch (const std::runtime_error &) { rejected = true; }
        require(rejected, "occupied initial L0 was accepted");
    }
    const size_t index = (size_t)(occupied - fixture.graph.cold.slices.begin());
    const int level = (int)(index % HOST_PARTITIONED_RATIO2_LEVELS);
    fixture.graph.cold.slices[index].edges.resize(
        partitioned_ratio2_level_partition_capacity(level) + 1);
    bool rejected = false;
    try { (void)build_persistent_graph_plan(fixture.graph); }
    catch (const std::runtime_error &) { rejected = true; }
    require(rejected, "oversized initial slice was accepted");
}

static size_t prefix_through(int level) {
    size_t words = 0;
    for (int l = 0; l <= level; ++l) words += partitioned_fixed_level_words_host(l);
    return words;
}

static void check_carry_bounds() {
    PartitionedCsrReferenceGraph graph;
    graph.slices.resize(HOST_PARTITIONED_RATIO2_LEVELS);
    const size_t full = (size_t{1} << HOST_PARTITIONED_RATIO2_LEVELS) - 1;
    // Include noncanonical masks and both empty/nonempty commit outcomes.
    for (size_t initial = 0; initial <= full; ++initial) {
        for (int l = 0; l < HOST_PARTITIONED_RATIO2_LEVELS; ++l) {
            graph.slices[(size_t)l].edges.resize((initial >> l) & 1);
        }
        for (size_t launches : {0ULL, 1ULL, 2ULL, 20ULL, 64ULL, 1000ULL, 2048ULL}) {
            const size_t bound = persistent_graph_prefix_words(graph, launches);
            for (bool nonempty : {false, true}) {
                size_t mask = initial;
                for (size_t step = 0; step < launches && mask != full; ++step) {
                    int target = 0;
                    while ((mask >> target) & 1) ++target;
                    require(prefix_through(target) <= bound, "carry exceeds bank bound");
                    mask &= ~((size_t{1} << target) - 1);
                    if (nonempty) mask |= size_t{1} << target;
                }
            }
        }
    }
    for (auto &slice : graph.slices) slice.edges.clear();
    graph.slices[6].edges.resize(1);
    require(persistent_graph_prefix_words(graph, 1000) == prefix_through(10),
            "L6 plus 1000 launches must reach L10");
    graph.slices[6].edges.clear();
    graph.slices[10].edges.resize(1);
    require(persistent_graph_prefix_words(graph, 1000) == prefix_through(9),
            "L10 bootstrap must leave lower update targets independent");
    require(persistent_graph_prefix_words(graph, std::numeric_limits<size_t>::max()) ==
                prefix_through(10), "default bound must retain full arenas");
    std::cout << "LAYOUT_CARRY_BOUNDS masks=" << full + 1 << " status=PASS\n";
}

static void check_bootstrap() {
    auto fixture = make_fixture(false);
    fixture.graph = build_persistent_reference(fixture.trace);
    int highest = -1;
    std::array<size_t, HOST_PARTITIONED_GRAPH_PORTS> initial_end{};
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
        for (int level = 0; level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
            const auto &slice = fixture.graph.cold.slice((int)bank, level);
            if (slice.edges.empty()) continue;
            require(level >= kPersistentBootstrapLevel, "bootstrap occupied a lower level");
            const size_t cap = partitioned_ratio2_level_partition_capacity(level);
            initial_end[bank] = prefix_through(level - 1) + 294913ULL +
                (cap + 2) / 2 + (cap + 3) / 4 + slice.edges.size();
            highest = std::max(highest, level);
        }
    }
    require(highest == kPersistentBootstrapLevel, "small bootstrap chose wrong level");
    auto plan = build_persistent_graph_plan(fixture.graph, 4096, 20);
    const size_t target_end = persistent_graph_prefix_words(fixture.graph.cold, 20);
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
        require(plan.bank_words[bank] == std::max(target_end, initial_end[bank]),
                "bootstrap bank misses initial or future carry level");
        require(plan.bank_words[bank] < partitioned_fixed_all_levels_words_host(),
                "immutable bootstrap retained unused capacity tail");
    }
    check_metadata(fixture, plan);
    require(check_setup_updated_graph(plan.image.graph_words, plan.image.meta_words,
                                      fixture.trace) == fixture.trace.old_edges.size(),
            "bootstrap compact graph oracle failed");
    std::vector<SparseBank> sparse;
    for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) sparse.push_back({&plan, bank});
    for (const auto &patch : plan.descriptor_patches) {
        plan.image.meta_words.at(patch.meta_index) = patch.target_words;
    }
    require(check_setup_updated_graph(sparse, plan.image.meta_words, fixture.trace) ==
                fixture.trace.old_edges.size(), "bootstrap fixed graph oracle failed");
    std::cout << "LAYOUT_BOOTSTRAP minimum_level=" << kPersistentBootstrapLevel
              << " edges=" << fixture.trace.old_edges.size() << " status=PASS\n";
}

static void check_vertex_bounds() {
    SetupInsertionBatch trace;
    trace.vertices = HOST_VS_PART_MAX - 1;
    trace.old_edges = {{0, 0, 17, 1}, {(uint32_t)trace.vertices - 1, 1, 257, 1}};
    const auto graph = build_persistent_reference(trace);
    require(graph.classification.empty_hot_set, "vertex fixture unexpectedly hot");
    for (size_t launches : {1ULL, 20ULL, 1000ULL}) {
        auto plan = build_persistent_graph_plan(graph, 8192, launches, trace.vertices);
        const int highest = launches == 1 ? 0 : launches == 20 ? 4 : 9;
        const size_t terminator_end = highest == 0 ? 1 : prefix_through(highest - 1) + 294914ULL;
        for (size_t bank = 1; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) {
            require(plan.bank_words[bank] == terminator_end,
                    "unreachable cold bank retained edge payload or lost terminators");
        }
        std::array<size_t, HOST_PARTITIONED_GRAPH_PORTS> expected;
        expected.fill(terminator_end);
        expected[0] = persistent_graph_prefix_words(graph.cold, launches);
        for (const auto &region : plan.regions) {
            expected[region.bank] = std::max(expected[region.bank], region.target_words + region.words);
        }
        require(plan.bank_words == expected, "bank bounds exceed live payload and future writes");
        require(check_setup_updated_graph(plan.image.graph_words, plan.image.meta_words, trace) == 2,
                "vertex-bounded compact oracle failed");
        std::vector<SparseBank> sparse;
        for (size_t bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; ++bank) sparse.push_back({&plan, bank});
        for (const auto &patch : plan.descriptor_patches) {
            plan.image.meta_words.at(patch.meta_index) = patch.target_words;
        }
        require(check_setup_updated_graph(sparse, plan.image.meta_words, trace) == 2,
                "vertex-bounded fixed oracle failed");
    }
    auto hot = make_fixture(true);
    const auto plan = build_persistent_graph_plan(hot.graph, 20, 20, 0);
    const size_t hot_end = partitioned_fixed_all_levels_words_host() +
        persistent_graph_prefix_words(hot.graph.hot, 20);
    for (size_t words : plan.bank_words) require(words >= hot_end, "vertex bound pruned hot arena");
    std::cout << "LAYOUT_VERTEX_BOUNDS status=PASS\n";
}

}  // namespace

int main() {
    try {
        check_fixture(false);
        check_fixture(true);
        check_rejections();
        check_carry_bounds();
        check_bootstrap();
        check_vertex_bounds();
        std::cout << "SPINE_PERSISTENT_LAYOUT_TEST status=PASS\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "SPINE_PERSISTENT_LAYOUT_TEST status=FAIL error=" << error.what() << '\n';
        return 1;
    }
}
