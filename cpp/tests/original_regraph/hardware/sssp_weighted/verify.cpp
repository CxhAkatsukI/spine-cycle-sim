#include <algorithm>
#include <array>
#include <stdexcept>
#include <vector>

using uint = unsigned int;
#include "acc_data_types.h"
#include "acc_scatter.h"

namespace {
constexpr uint active = VERTEX_ACTIVE_BIT_MASK;
constexpr uint inf = SSSP_INF;
using State = std::array<uint, 8>;

struct Edge { uint source, destination, weight; };

void require(bool condition)
{
    if (!condition) throw std::runtime_error("weighted A4 scatter contract failed");
}

update_set_dt run_scatter(const State& state, const edge_burst_dt& burst)
{
    hls::stream<ppb_request_dt> requests;
    hls::stream<ppb_response_dt> responses;
    hls::stream<edge_burst_dt> edges;
    hls::stream<update_set_dt> updates;

    ppb_response_dt line{};
    line.addr = 0;
    line.end_flag = false;
    line.data = 0;
    for (auto i = state.rbegin(); i != state.rend(); ++i) {
        line.data <<= 32;
        line.data |= ap_uint<512>(*i);
    }
    responses.write(line);
    line.addr = SRC_BUFFER_SIZE >> 4;
    responses.write(line);
    line.end_flag = true;
    responses.write(line);

    edges.write(burst);
    accScatter(requests, responses, edges, updates, NUM_EDGE_PER_BURST);
    require(!updates.empty() && edges.empty() && responses.empty());
    const auto result = updates.read();
    require(updates.empty());
    while (!requests.empty()) requests.read();
    return result;
}

void check_scatter()
{
    // Inactive and unreachable sources, saturation, zero destination and
    // distance, and distinct weights to expose lane mix-ups.
    constexpr State state{active, 5, active | inf, active | (inf - 1),
        active | 123, active | 66, active | 47, active | 77};
    constexpr State weights{19, 99, 5, 4095, 1, 4, 3, 11};
    constexpr State destinations{0, 1, 65535, 2047, 3, 7, 128, 127};
    constexpr State expected{active | 19, 0, 0, active | inf,
        active | 124, active | 70, active | 50, active | 88};
    edge_burst_dt burst;
    for (uint i = 0; i < weights.size(); ++i) {
        require(a4_weighted::encodable(destinations[i], weights[i]));
        burst.edges[i].src = i;
        burst.edges[i].dst = a4_weighted::pack(destinations[i], weights[i]);
        if (i == 7) burst.edges[i].dst |= a4_weighted::dummy;
    }
    const auto result = run_scatter(state, burst);
    for (uint i = 0; i < expected.size(); ++i) {
        require(result.tuples[i].update == expected[i]);
        const auto destination = destinations[i] | (i == 7 ? 1u << 19 : 0);
        require(result.tuples[i].dst == destination);
    }
}

State dijkstra(const std::vector<Edge>& edges)
{
    State result;
    result.fill(inf);
    result[0] = 0;
    std::array<bool, 8> settled{};
    for (uint step = 0; step < result.size(); ++step) {
        uint next = result.size();
        for (uint v = 0; v < result.size(); ++v)
            if (!settled[v] && (next == result.size() || result[v] < result[next])) next = v;
        if (next == result.size() || result[next] == inf) break;
        settled[next] = true;
        for (const auto& edge : edges)
            if (edge.source == next)
                result[edge.destination] = std::min(result[edge.destination], result[next] + edge.weight);
    }
    return result;
}

State superstep(const State& state, const std::vector<Edge>& edges)
{
    std::array<State, 4> lanes{};
    for (uint base = 0; base < edges.size(); base += NUM_EDGE_PER_BURST) {
        edge_burst_dt burst;
        for (uint slot = 0; slot < NUM_EDGE_PER_BURST; ++slot) {
            if (base + slot < edges.size()) {
                const auto& edge = edges[base + slot];
                burst.edges[slot].src = edge.source;
                burst.edges[slot].dst = a4_weighted::pack(edge.destination, edge.weight);
            } else {
                burst.edges[slot].src = 0;
                burst.edges[slot].dst = a4_weighted::dummy;
            }
        }
        const auto updates = run_scatter(state, burst);
        auto& lane = lanes[(base / NUM_EDGE_PER_BURST) % lanes.size()];
        for (const auto& update : updates.tuples) {
            const uint destination = update.dst.to_uint();
            if ((destination & (1u << 19)) == 0)
                lane.at(destination) = PROP_COMPUTE_STAGE3(lane.at(destination), update.update.to_uint());
        }
    }
    State result;
    for (uint v = 0; v < result.size(); ++v) {
        uint gathered = 0;
        for (const auto& lane : lanes) gathered = PROP_COMPUTE_STAGE4(gathered, lane[v]);
        result[v] = applyFunc(gathered, state[v], 0, 0);
    }
    return result;
}

void check_insertions()
{
    const std::vector<Edge> old{{0, 1, 15}, {0, 4, 27}, {1, 2, 20}, {1, 3, 1},
        {2, 3, 1}, {2, 5, 2}, {3, 4, 4}, {4, 1, 1}, {4, 5, 30}, {5, 6, 2}, {7, 6, 1}};
    const std::vector<Edge> batch{{0, 2, 2}, {3, 7, 2}};
    auto updated = old;
    auto state = dijkstra(old);
    for (const auto& edge : batch) state[edge.source] |= active;
    updated.insert(updated.end(), batch.begin(), batch.end());
    std::stable_sort(updated.begin(), updated.end(),
        [](const Edge& a, const Edge& b) { return a.source < b.source; });
    const auto expected = dijkstra(updated);
    for (uint round = 0; round < state.size(); ++round) {
        state = superstep(state, updated);
        if (std::none_of(state.begin(), state.end(), [](uint p) { return IS_ACTIVE_VERTEX(p); })) {
            require(state == expected);
            return;
        }
    }
    require(false);
}
}  // namespace

int main()
{
    require(!a4_weighted::encodable(0, 0));
    require(!a4_weighted::encodable(0, 4096));
    require(!a4_weighted::encodable(1u << 19, 1));
    require(a4_weighted::weight(a4_weighted::pack((1u << 19) - 1, 4095)) == 4095);
    require(a4_weighted::gather_destination(a4_weighted::dummy) == 1u << 19);
    check_scatter();
    check_insertions();
}
