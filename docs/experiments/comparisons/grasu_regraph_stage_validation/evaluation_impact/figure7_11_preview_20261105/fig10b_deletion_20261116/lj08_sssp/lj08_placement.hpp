#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace lj08 {
inline constexpr unsigned vertices = 5363260;
inline constexpr size_t base_edges = 99028542;
inline constexpr unsigned source = 26;
inline constexpr unsigned max_updates = 512;
inline constexpr unsigned banks = 16;
struct DiskEdge { uint32_t from, to, weight; };
static_assert(sizeof(DiskEdge) == 12);

struct Placement {
    std::array<size_t, banks * 2> edges{};
    std::vector<uint64_t> hot_bitmap;
};

template<class HotBank>
Placement place(const std::vector<uint32_t>& degree, size_t capacity, HotBank hot_bank) {
    Placement p;
    p.hot_bitmap.resize((degree.size() + 63) / 64);
    std::vector<uint32_t> order(degree.size());
    std::iota(order.begin(), order.end(), 0);
    for (uint32_t v : order) p.edges[v >> 20] += degree[v];
    std::sort(order.begin(), order.end(), [&degree](uint32_t a, uint32_t b) {
        return degree[a] != degree[b] ? degree[a] > degree[b] : a < b;
    });
    const auto limit = capacity - max_updates;
    for (uint32_t v : order) {
        if (degree[v] == 0) break;
        auto &cold = p.edges[v >> 20];
        if (cold <= limit) continue;
        auto &hot = p.edges[banks + hot_bank(v)];
        if (hot + degree[v] > limit) continue;
        cold -= degree[v];
        hot += degree[v];
        p.hot_bitmap[v / 64] |= uint64_t(1) << (v % 64);
    }
    if (*std::max_element(p.edges.begin(), p.edges.end()) > limit)
        throw std::runtime_error("LJ08 cold/hot placement does not fit fixed L10");
    return p;
}
}
