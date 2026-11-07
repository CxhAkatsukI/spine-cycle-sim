#pragma once

#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>
#include <vector>

// Include after the retained host defines SetupGraphImage and its CSR helpers.
namespace {

struct PersistentGraphRegion {
    size_t bank;
    size_t source_words;
    size_t target_words;
    size_t words;
};

struct PersistentDescriptorPatch {
    size_t meta_index;
    size_t target_words;
};

struct PersistentGraphPlan {
    SetupGraphImage image;
    std::vector<PersistentGraphRegion> regions;
    std::vector<PersistentDescriptorPatch> descriptor_patches;
    std::array<size_t, HOST_PARTITIONED_GRAPH_PORTS> bank_words{};
};

static size_t persistent_graph_prefix_words(
    const PartitionedCsrReferenceGraph &graph, size_t launches, bool with_edges = true
) {
    if (launches == std::numeric_limits<size_t>::max()) {
        return partitioned_fixed_all_levels_words_host();
    }
    size_t mask = 0;
    for (size_t slice = 0; slice < graph.slices.size(); ++slice) {
        if (!graph.slices[slice].edges.empty()) {
            mask |= size_t{1} << (slice % HOST_PARTITIONED_RATIO2_LEVELS);
        }
    }
    // The group OR-mask is a binary counter: each commit clears all lower
    // levels and sets at most the first zero bit. Its value increases by <=1.
    // Empty outputs only delay reaching a higher target. The highest changed
    // bit of the all-nonempty counter bounds all targets, not existing slices.
    const size_t full = (size_t{1} << HOST_PARTITIONED_RATIO2_LEVELS) - 1;
    size_t bound = mask ^ (mask + std::min(launches, full - mask));
    if (bound == 0) return 0;
    size_t highest = 0;
    while (bound >>= 1) ++highest;
    size_t words = 0;
    for (size_t level = 0; level < highest; ++level) {
        words += partitioned_fixed_level_words_host((int)level);
    }
    if (with_edges) return words + partitioned_fixed_level_words_host((int)highest);
    // Empty L0 returns before touching graph memory. Empty carries still
    // write row_offsets[0] and the full page-base array's last packed word.
    return highest == 0 ? 0 : words + (size_t)PAGE_CSR_PAGE_COUNT * 4ULL +
        ((size_t)PAGE_CSR_PAGE_BASE_COUNT + 1ULL) / 2ULL + 1;
}

// image contains only live compact payloads. Its descriptor offsets address
// those sources; apply descriptor_patches only after out-of-place relocation.
// Budgets cover the entire run; each physical invocation must consume >=1
// update. Omitted budgets retain full arenas. Neither inspects future endpoints.
static PersistentGraphPlan build_persistent_graph_plan(
    const PartitionedHotColdReferenceGraph &graph,
    size_t update_budget = std::numeric_limits<size_t>::max(),
    size_t physical_launch_budget = std::numeric_limits<size_t>::max(),
    size_t vertex_bound = MAX_N
) {
    if (vertex_bound > (size_t)MAX_N) {
        throw std::runtime_error("persistent vertex bound exceeds MAX_N");
    }
    const bool hot_enabled = !graph.classification.empty_hot_set;
    const size_t family_words = partitioned_fixed_all_levels_words_host();
    const size_t bank_limit =
        HOST_PARTITIONED_CSR_HBM_CHANNEL_BYTES / sizeof(uint64_t);
    const size_t launches = std::min(update_budget, physical_launch_budget);
    if (!hot_enabled) {
        for (const auto &slice : graph.hot.slices) {
            if (!slice.edges.empty()) {
                throw std::runtime_error("persistent hot payload requires hot classification");
            }
        }
    }

    PersistentGraphPlan plan;
    plan.bank_words.fill(1);
    plan.image.graph_words.resize(HOST_PARTITIONED_GRAPH_PORTS);
    auto &meta = plan.image.meta_words;
    meta.assign(HOST_PARTITIONED_META_WORDS, 0);
    const size_t bitmap_words = (size_t)PAGE_CSR_PAGE_COUNT * 4ULL;
    const size_t page_base_words = ((size_t)PAGE_CSR_PAGE_BASE_COUNT + 1ULL) / 2ULL;
    const std::array<size_t, 5> descriptor_words{{
        HOST_PARTITIONED_META_PAGE_BITMAP_OFFSET_WORD,
        HOST_PARTITIONED_META_PAGE_BASE_OFFSET_WORD,
        HOST_PARTITIONED_META_ROW_OFFSET_OFFSET_WORD,
        HOST_PARTITIONED_META_MASK_OFFSET_WORD,
        HOST_PARTITIONED_META_EDGE_OFFSET_WORD
    }};

    for (int group = 0; group < (hot_enabled ? 2 : 1); ++group) {
        const auto &ref = group == 0 ? graph.cold : graph.hot;
        const int partitions = group == 0 ? HOST_PARTITIONED_CSR_DST_PARTITIONS
                                          : HOST_PARTITIONED_HOT_SHARDS;
        if (ref.meta.num_partitions != partitions ||
            ref.meta.num_levels != HOST_PARTITIONED_RATIO2_LEVELS ||
            ref.slices.size() != (size_t)partitions * HOST_PARTITIONED_RATIO2_LEVELS ||
            partitions > HOST_PARTITIONED_GRAPH_PORTS) {
            throw std::runtime_error("persistent reference graph dimensions mismatch");
        }
        const size_t prefix = persistent_graph_prefix_words(ref, launches);
        const size_t empty_prefix = persistent_graph_prefix_words(ref, launches, false);
        const size_t family_base = group == 0 ? 0 : family_words;
        if (family_base > bank_limit || prefix > bank_limit - family_base) {
            throw std::runtime_error("persistent fixed arenas exceed graph bank HBM");
        }
        for (int bank = 0; bank < partitions; ++bank) {
            bool reachable = group != 0 || (size_t)bank * HOST_VS_PART_MAX < vertex_bound;
            for (int level = 0; !reachable && level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
                reachable = !ref.slice(bank, level).edges.empty();
            }
            const size_t bank_prefix = reachable ? prefix : empty_prefix;
            if (bank_prefix != 0) plan.bank_words[(size_t)bank] = std::max(
                plan.bank_words[(size_t)bank], family_base + bank_prefix);
            const int family = group == 0 ? bank : HOST_PARTITIONED_HOT_FAMILY_BASE + bank;
            auto &words = plan.image.graph_words[(size_t)bank];
            size_t level_base = group == 0 ? 0 : family_words;
            for (int level = 0; level < HOST_PARTITIONED_RATIO2_LEVELS; ++level) {
                const size_t bitmap_target = level_base;
                level_base += partitioned_fixed_level_words_host(level);
                const auto &slice = ref.slice(bank, level);
                if (slice.edges.empty()) continue;
                if (level == 0) {
                    throw std::runtime_error("persistent initial L0 must be empty");
                }
                const size_t rows = slice.rows.size();
                const size_t cap = partitioned_ratio2_level_partition_capacity(level);
                if (rows == 0 || rows > cap || slice.edges.size() > cap ||
                    slice.row_offsets.size() != rows + 1 || slice.row_masks.size() != rows ||
                    slice.row_offsets.front() != 0 ||
                    slice.row_offsets.back() != slice.edges.size()) {
                    throw std::runtime_error("persistent initial slice exceeds capacity or is malformed");
                }
                for (size_t row = 0; row < rows; ++row) {
                    if (slice.row_offsets[row] >= slice.row_offsets[row + 1]) {
                        throw std::runtime_error("persistent initial row offsets are invalid");
                    }
                }

                std::array<size_t, 5> target{{bitmap_target, 0, 0, 0, 0}};
                target[1] = target[0] + bitmap_words;
                target[2] = target[1] + page_base_words;
                target[3] = target[2] + (cap + 2ULL) / 2ULL;
                target[4] = target[3] + (cap + 3ULL) / 4ULL;
                const std::array<size_t, 5> lengths{{
                    bitmap_words, page_base_words, (rows + 2ULL) / 2ULL,
                    (rows + 3ULL) / 4ULL, slice.edges.size()
                }};
                const size_t meta_base =
                    ((size_t)family * HOST_PARTITIONED_RATIO2_LEVELS + (size_t)level) *
                    HOST_PARTITIONED_META_WORDS_PER_SLICE;
                std::array<size_t, 5> source{};
                for (size_t region = 0; region < target.size(); ++region) {
                    if (target[region] > bank_limit ||
                        lengths[region] > bank_limit - target[region]) {
                        throw std::runtime_error("persistent relocation exceeds graph bank");
                    }
                    plan.bank_words[(size_t)bank] = std::max(
                        plan.bank_words[(size_t)bank], target[region] + lengths[region]);
                    source[region] = words.size();
                    words.resize(words.size() + lengths[region], 0);
                    meta[meta_base + descriptor_words[region]] = source[region];
                    plan.regions.push_back({(size_t)bank, source[region], target[region],
                                            lengths[region]});
                    plan.descriptor_patches.push_back({meta_base + descriptor_words[region],
                                                      target[region]});
                }
                for (const auto &entry : slice.page_bitmap_by_page) {
                    if (entry.first >= (uint32_t)PAGE_CSR_PAGE_COUNT) {
                        throw std::runtime_error("persistent bitmap page is out of range");
                    }
                    for (size_t w = 0; w < 4; ++w) {
                        words[source[0] + (size_t)entry.first * 4ULL + w] = entry.second[w];
                    }
                }
                for (const auto &entry : slice.page_base_by_page) {
                    if (entry.first >= (uint32_t)PAGE_CSR_PAGE_COUNT || entry.second >= rows) {
                        throw std::runtime_error("persistent page base is out of range");
                    }
                    set_partitioned_graph_u32(words, source[1], entry.first, entry.second);
                }
                set_partitioned_graph_u32(words, source[1], PAGE_CSR_PAGE_BASE_COUNT - 1,
                                          (uint32_t)rows);
                for (size_t i = 0; i < slice.row_offsets.size(); ++i) {
                    set_partitioned_graph_u32(words, source[2], i, slice.row_offsets[i]);
                }
                for (size_t i = 0; i < rows; ++i) {
                    words[source[3] + (i >> 2)] |=
                        (uint64_t)slice.row_masks[i] << ((i & 3ULL) * 16ULL);
                }
                for (size_t i = 0; i < slice.edges.size(); ++i) {
                    words[source[4] + i] = pack_partitioned_csr_edge_host(slice.edges[i]);
                }
                meta[meta_base + HOST_PARTITIONED_META_EDGE_COUNT_WORD] = slice.edges.size();
                meta[meta_base + HOST_PARTITIONED_META_ROW_COUNT_WORD] = rows;
                meta[meta_base + HOST_PARTITIONED_META_OCCUPIED_WORD] = 1;
                set_partitioned_slice_epoch_host(meta, family, level, 1);
                uint32_t list_index = 0;
                for (const auto &entry : slice.page_bitmap_by_page) {
                    set_partitioned_page_epoch_host(meta, family, level, entry.first, 1);
                    set_partitioned_page_list_id_host(meta, family, level, list_index++, entry.first);
                }
                set_partitioned_page_list_count_host(meta, family, level, list_index);
            }
        }
    }
    for (size_t i = 0; i < graph.classification.hot_bitmap_words.size() &&
                       i < (size_t)HOST_PARTITIONED_HOT_BITMAP_WORDS; ++i) {
        meta[(size_t)HOST_PARTITIONED_META_HOT_BITMAP_BASE + i] =
            graph.classification.hot_bitmap_words[i];
    }
    for (size_t s = 0; s < graph.classification.hot_shard_edges.size() &&
                       s < (size_t)HOST_PARTITIONED_HOT_SHARDS; ++s) {
        meta[(size_t)HOST_PARTITIONED_META_HOT_SHARD_EDGE_COUNT_BASE + s] =
            graph.classification.hot_shard_edges[s];
    }
    for (size_t p = 0; p < graph.classification.cold_partition_edges.size() &&
                       p < (size_t)HOST_PARTITIONED_CSR_DST_PARTITIONS; ++p) {
        meta[(size_t)HOST_PARTITIONED_META_COLD_PARTITION_EDGE_COUNT_BASE + p] =
            graph.classification.cold_partition_edges[p];
    }
    initialize_partitioned_meta_format_host(meta, hot_enabled);
    return plan;
}

}  // namespace
