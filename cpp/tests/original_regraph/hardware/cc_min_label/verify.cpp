#include <algorithm>
#include <array>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <utility>
#include <vector>

// Compile against the unchanged public template with this alternate UDF on
// the include path, just as an A4 kernel would select its algorithm.
#include "fpga_application.h"

#ifdef COMPARE_INTEGRATED_CC
#include <ap_int.h>
namespace integrated {
#include <regraph_cc/l2.h>
}
#endif

namespace {
using Edge = std::pair<unsigned, unsigned>;
using State = std::vector<prop_t>;
constexpr unsigned vertices = 43;
constexpr unsigned a4_lanes = 4;

void require(bool condition)
{
    if (!condition) throw std::runtime_error("A4 minimum-label CC contract failed");
}

State component_labels(const std::vector<Edge>& edges)
{
    std::vector<std::vector<unsigned>> neighbors(vertices);
    for (const auto& [a, b] : edges) {
        neighbors.at(a).push_back(b);
        neighbors.at(b).push_back(a);
    }
    State labels(vertices, vertices);
    for (unsigned root = 0; root < vertices; ++root) {
        if (labels[root] != vertices) continue;
        std::vector<unsigned> pending{root};
        labels[root] = root;
        while (!pending.empty()) {
            const auto source = pending.back();
            pending.pop_back();
            for (auto destination : neighbors[source]) {
                if (labels[destination] != vertices) continue;
                labels[destination] = root;
                pending.push_back(destination);
            }
        }
    }
    return labels;
}

State round(const State& state, const std::vector<Edge>& edges)
{
    std::array<State, a4_lanes> lanes;
    for (auto& lane : lanes) lane.assign(vertices, 0);
    for (unsigned ordinal = 0; ordinal < edges.size(); ++ordinal) {
        const auto [source, destination] = edges[ordinal];
        auto& target = lanes[ordinal % a4_lanes][destination];
        const auto update = PROP_COMPUTE_STAGE0(state[source]);
        if (IS_ACTIVE_VERTEX(update)) target = PROP_COMPUTE_STAGE3(target, update);
    }
    State next(vertices);
    for (unsigned v = 0; v < vertices; ++v) {
        prop_t merged = 0;
        for (const auto& lane : lanes) merged = PROP_COMPUTE_STAGE4(merged, lane[v]);
        next[v] = applyFunc(merged, state[v], 0, 0);
    }
    return next;
}

void check_insertions(std::vector<Edge> edges, const std::vector<Edge>& insertions)
{
    State state = component_labels(edges);
    for (const auto& [a, b] : insertions) {
        state[a] |= cc_active;
        state[b] |= cc_active;
    }
    edges.insert(edges.end(), insertions.begin(), insertions.end());
    const auto target = component_labels(edges);
    for (unsigned step = 0; step < vertices; ++step) {
        state = round(state, edges);
        if (std::none_of(state.begin(), state.end(), [](auto p) { return (p & cc_active) != 0; })) {
            require(state == target);
            require(round(state, edges) == state);
            return;
        }
    }
    require(false);
}
}  // namespace

int main()
{
    require(std::numeric_limits<prop_t>::digits == 32);
    require(PROP_COMPUTE_STAGE0(7) == 0);
    require(PROP_COMPUTE_STAGE0(cc_active) == cc_active);
    require(!IS_ACTIVE_VERTEX(7) && IS_ACTIVE_VERTEX(cc_active));
    require(PROP_COMPUTE_STAGE3(0, cc_active | cc_label) == (cc_active | cc_label));
    require(PROP_COMPUTE_STAGE4(cc_active | cc_label, cc_active) == cc_active);
    require(applyFunc(cc_active, 7, 0, 0) == cc_active);
    require(applyFunc(cc_active, cc_active, 0, 0) == 0);
    require(applyFunc(0, cc_active | cc_label, 0, 0) == cc_label);

#ifdef COMPARE_INTEGRATED_CC
    constexpr std::array<prop_t, 8> payloads{
        0, 1, 7, cc_label, cc_active, cc_active | 1, cc_active | 7, cc_active | cc_label,
    };
    for (const auto lhs : payloads) {
        require(IS_ACTIVE_VERTEX(ap_uint<32>(lhs)) == integrated::regraph_cc_is_active(lhs));
        require(PROP_COMPUTE_STAGE0(lhs) == integrated::scatterFunc(lhs, 0).to_uint());
        for (const auto rhs : payloads) {
            require(PROP_COMPUTE_STAGE3(lhs, rhs) == integrated::gatherFunc(lhs, rhs).to_uint());
            require(applyFunc(lhs, rhs, 0, 0) == integrated::applyFunc(lhs, rhs, 0, 0).to_uint());
        }
    }
#endif

    check_insertions({}, {});
    std::vector<Edge> old;
    for (unsigned v = 2; v < vertices; ++v) {
        old.emplace_back(v - 1, v);
        old.emplace_back(v, v - 1);
    }
    check_insertions(old, {{0, 1}, {1, 0}});

    std::mt19937 rng(2917);
    for (unsigned trial = 0; trial < 64; ++trial) {
        std::vector<Edge> edges, added;
        for (unsigned e = 0; e < trial + 5; ++e) {
            const unsigned a = rng() % vertices, b = rng() % vertices;
            auto& target = e % 5 == 0 ? added : edges;
            target.emplace_back(a, b);
            target.emplace_back(b, a);
        }
        std::shuffle(edges.begin(), edges.end(), rng);
        check_insertions(edges, added);
    }
}
