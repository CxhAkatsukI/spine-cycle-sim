#pragma once

#include "lj08_placement.hpp"

namespace lj08 {
inline constexpr int level = HOST_PARTITIONED_RATIO2_LEVELS - 1;
static_assert(banks == HOST_PARTITIONED_CSR_DST_PARTITIONS);

template<class Visit>
void visit_base(const std::string& path, Visit visit) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    require(input.good() && input.tellg() == std::streamoff(base_edges * sizeof(DiskEdge)),
            "wrong original LJ08 base size");
    input.seekg(0);
    std::vector<DiskEdge> rows(65536);
    uint64_t last = 0;
    for (size_t offset = 0; offset < base_edges; offset += rows.size()) {
        const auto count = std::min(rows.size(), base_edges - offset);
        require(bool(input.read(reinterpret_cast<char*>(rows.data()), count * sizeof(DiskEdge))),
                "short LJ08 base read");
        for (size_t i = 0; i < count; ++i) {
            const auto [u, v, w] = rows[i];
            const uint64_t key = (uint64_t(u) << 32) | v;
            if (u >= vertices || v >= vertices || !w || w > UINT16_MAX || ((offset + i) && key <= last))
                throw std::runtime_error("invalid or unsorted LJ08 base edge at " + std::to_string(offset + i));
            last = key;
            visit(u, v, w);
        }
    }
}

template<unsigned Bits>
void set_lane(std::vector<uint64_t>& words, size_t base, size_t index, uint64_t value) {
    words.at(base + index / (64 / Bits)) |= value << ((index % (64 / Bits)) * Bits);
}

void write_family(const std::vector<DiskEdge>& edges, unsigned family,
                  std::vector<uint64_t>& graph, std::vector<uint64_t>& meta,
                  std::vector<PartitionedHbm16Word>& directory) {
    size_t bitmap = family >= banks ? partitioned_fixed_all_levels_words_host() : 0;
    for (int i = 0; i < level; ++i) bitmap += partitioned_fixed_level_words_host(i);
    const auto cap = partitioned_ratio2_level_partition_capacity(level);
    const auto page_base = bitmap + PAGE_CSR_PAGE_COUNT * 4ULL;
    const auto offsets = page_base + ((PAGE_CSR_PAGE_BASE_COUNT + 1ULL) >> 1);
    const auto masks = offsets + ((cap + 2ULL) >> 1);
    const auto payload = masks + ((cap + 3ULL) >> 2);
    require(edges.size() <= cap && payload + cap <= graph.size(), "LJ08 L10 family exceeds allocation");
    size_t pos = 0;
    uint32_t rows = 0, pages = 0, previous_page = UINT32_MAX;
    const auto family_mask = partitioned_family_directory_family_mask_host(family);
    while (pos < edges.size()) {
        const auto src = edges[pos].from;
        const auto page = src / PAGE_CSR_VERTICES_PER_PAGE;
        const auto lane = src % PAGE_CSR_VERTICES_PER_PAGE;
        if (page != previous_page) {
            set_lane<32>(graph, page_base, page, rows);
            set_partitioned_page_epoch_host(meta, family, level, page, 1);
            set_partitioned_page_list_id_host(meta, family, level, pages++, page);
            previous_page = page;
        }
        graph[bitmap + size_t(page) * 4 + lane / 64] |= uint64_t(1) << (lane % 64);
        set_lane<32>(graph, offsets, rows, pos);
        uint16_t mask = 0;
        do {
            const auto [from, dst, weight] = edges[pos];
            mask |= uint16_t(1U << partitioned_csr_dst_partition(dst));
            graph[payload + pos++] = (uint64_t(dst) << 32) | (uint64_t(weight) << 16) | 1;
        } while (pos < edges.size() && edges[pos].from == src);
        set_lane<16>(graph, masks, rows++, mask);
        partitioned_family_directory_or_host(directory, src, family_mask);
    }
    set_lane<32>(graph, offsets, rows, edges.size());
    set_lane<32>(graph, page_base, PAGE_CSR_PAGE_BASE_COUNT - 1, rows);
    const size_t m = (family * HOST_PARTITIONED_RATIO2_LEVELS + level) * HOST_PARTITIONED_META_WORDS_PER_SLICE;
    meta[m + HOST_PARTITIONED_META_EDGE_COUNT_WORD] = edges.size();
    meta[m + HOST_PARTITIONED_META_ROW_COUNT_WORD] = rows;
    meta[m + HOST_PARTITIONED_META_PAGE_BITMAP_OFFSET_WORD] = bitmap;
    meta[m + HOST_PARTITIONED_META_PAGE_BASE_OFFSET_WORD] = page_base;
    meta[m + HOST_PARTITIONED_META_ROW_OFFSET_OFFSET_WORD] = offsets;
    meta[m + HOST_PARTITIONED_META_MASK_OFFSET_WORD] = masks;
    meta[m + HOST_PARTITIONED_META_EDGE_OFFSET_WORD] = payload;
    meta[m + HOST_PARTITIONED_META_OCCUPIED_WORD] = !edges.empty();
    if (!edges.empty()) set_partitioned_slice_epoch_host(meta, family, level, 1);
    set_partitioned_page_list_count_host(meta, family, level, pages);

    for (size_t i = 0; i < edges.size(); ++i) {
        const auto [src, dst, weight] = edges[i];
        const auto word = graph[payload + i];
        require(uint32_t(word >> 32) == dst && uint16_t(word >> 16) == weight && uint16_t(word) == 1,
                "LJ08 weighted payload mismatch");
        if (i == 0 || edges[i - 1].from != src) {
            require(partitioned_graph_source_row_mask_epoch_visible_host(graph, meta, family, level, src) != 0 &&
                    (partitioned_family_directory_read_host(directory, src) & family_mask),
                    "LJ08 source missing from resident directory");
        }
    }
}

void preload(const std::string& path, RepairRuntime* device) {
    const size_t bank_words = 2 * partitioned_fixed_all_levels_words_host();
    auto both_orientations = [](size_t bytes) { return 2 * ((bytes + 4095) & ~4095ULL); };
    require(both_orientations(bank_words * 8) <= SPINE_REPAIR_BANK_BYTES &&
            both_orientations(HOST_PARTITIONED_META_BYTES) <= SPINE_REPAIR_BANK_BYTES &&
            both_orientations(HOST_PARTITIONED_DIRTY_HBM16_BYTES) <= SPINE_REPAIR_BANK_BYTES &&
            size_t(SpineRepairLayout(vertices).mixed_words) * 32 <= SPINE_REPAIR_BANK_BYTES,
            "LJ08 graph, metadata, input or workspace exceeds HBM bank capacity");
    std::vector<uint32_t> in(vertices), out(vertices);
    visit_base(path, [&](uint32_t u, uint32_t v, uint32_t) { ++out[u]; ++in[v]; });
    const auto max_in = *std::max_element(in.begin(), in.end());
    const auto max_out = *std::max_element(out.begin(), out.end());
    require(std::max(max_in, max_out) + max_updates <= SPINE_REPAIR_ROW_CAPACITY, "LJ08 row overflow");
    const auto hot_bank = [](uint32_t v) { return partitioned_hot_shard_host(v, banks); };
    for (int reverse = 0; reverse < 2; ++reverse) {
        const auto p = place(reverse ? out : in, partitioned_ratio2_level_partition_capacity(level), hot_bank);
        std::array<std::vector<DiskEdge>, 2 * banks> families;
        for (unsigned i = 0; i < 2 * banks; ++i) families[i].reserve(p.edges[i]);
        visit_base(path, [&](uint32_t u, uint32_t v, uint32_t w) {
            if (reverse) std::swap(u, v);
            const auto f = partitioned_hot_bitmap_test_host(p.hot_bitmap, v)
                         ? banks + hot_bank(v) : unsigned(partitioned_csr_dst_partition(v));
            families.at(f).push_back({u, v, w});
        });
        std::vector<uint64_t> graph(bank_words), meta(HOST_PARTITIONED_META_WORDS);
        std::vector<PartitionedHbm16Word> directory(HOST_PARTITIONED_FAMILY_DIRECTORY_WORDS);
        initialize_partitioned_meta_format_host(meta, true);
        meta[HOST_PARTITIONED_META_FAMILY_DIRECTORY_VALID_WORD] = 1;
        std::copy(p.hot_bitmap.begin(), p.hot_bitmap.end(), meta.begin() + HOST_PARTITIONED_META_HOT_BITMAP_BASE);
        for (unsigned bank = 0; bank < banks; ++bank) {
            if (bank) std::fill(graph.begin(), graph.end(), 0);
            for (unsigned f : {bank, bank + banks}) {
                auto& edges = families[f];
                require(edges.size() == p.edges[f], "LJ08 family placement mismatch");
                if (reverse) std::sort(edges.begin(), edges.end(), [](const auto& a, const auto& b) {
                    return std::tie(a.from, a.to) < std::tie(b.from, b.to);
                });
                write_family(edges, f, graph, meta, directory);
            }
            meta[HOST_PARTITIONED_META_COLD_PARTITION_EDGE_COUNT_BASE + bank] = p.edges[bank];
            meta[HOST_PARTITIONED_META_HOT_SHARD_EDGE_COUNT_BASE + bank] = p.edges[banks + bank];
            if (device) device->preload_graph_bank(reverse, bank, graph);
        }
        validate_partitioned_page_list_metadata_host(meta);
        if (device) device->preload_graph_index(reverse, meta, directory);
        std::cout << "LJ08_LAYOUT_PASS reverse=" << reverse << " edges=" << base_edges
                  << " max_family=" << *std::max_element(p.edges.begin(), p.edges.end()) << std::endl;
    }
    std::cout << "LJ08_BASE_PASS vertices=" << vertices << " edges=" << base_edges
              << " max_in=" << max_in << " max_out=" << max_out
              << " graph_bytes_per_bank=" << both_orientations(bank_words * 8)
              << " meta_bytes_per_bank=" << both_orientations(HOST_PARTITIONED_META_BYTES)
              << " input_bytes_per_bank=" << both_orientations(HOST_PARTITIONED_DIRTY_HBM16_BYTES) << std::endl;
}
}
