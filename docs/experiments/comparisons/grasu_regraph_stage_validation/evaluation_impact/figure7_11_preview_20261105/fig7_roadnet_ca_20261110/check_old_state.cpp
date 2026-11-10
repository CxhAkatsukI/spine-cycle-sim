#include <algorithm>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <numeric>
#include <queue>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

using Arc = std::pair<unsigned, unsigned>;
using Graph = std::vector<std::vector<Arc>>;

std::vector<unsigned> sssp(const Graph &graph, unsigned source, unsigned &max_hops)
{
    constexpr unsigned inf = std::numeric_limits<unsigned>::max();
    using Entry = std::tuple<unsigned, unsigned, unsigned>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> queue;
    std::vector<unsigned> distance(graph.size(), inf), hops(graph.size(), inf);
    distance.at(source) = hops.at(source) = 0;
    queue.emplace(0, 0, source);
    while (!queue.empty()) {
        const auto [value, depth, src] = queue.top();
        queue.pop();
        if (distance[src] != value || hops[src] != depth) continue;
        max_hops = std::max(max_hops, depth);
        for (const auto &[dst, weight] : graph[src]) {
            const Arc candidate{value + weight, depth + 1};
            if (candidate < Arc{distance[dst], hops[dst]}) {
                std::tie(distance[dst], hops[dst]) = candidate;
                queue.emplace(distance[dst], hops[dst], dst);
            }
        }
    }
    return distance;
}

std::vector<unsigned> cc(const Graph &graph, unsigned &max_hops)
{
    constexpr unsigned none = std::numeric_limits<unsigned>::max();
    std::vector<unsigned> label(graph.size(), none), depth(graph.size());
    std::vector<unsigned> queue;
    for (unsigned root = 0; root < graph.size(); ++root) {
        if (label[root] != none) continue;
        label[root] = root;
        queue.assign(1, root);
        for (std::size_t i = 0; i < queue.size(); ++i) {
            const unsigned src = queue[i];
            for (const auto &[dst, weight] : graph[src]) {
                if (label[dst] != none) continue;
                label[dst] = root;
                depth[dst] = depth[src] + 1;
                max_hops = std::max(max_hops, depth[dst]);
                queue.push_back(dst);
            }
        }
    }
    return label;
}

unsigned check_warm_sssp(const Graph &graph, std::vector<unsigned> distance,
                         const std::vector<unsigned> &expected,
                         std::vector<unsigned> frontier)
{
    constexpr unsigned inf = std::numeric_limits<unsigned>::max();
    std::sort(frontier.begin(), frontier.end());
    frontier.erase(std::unique(frontier.begin(), frontier.end()), frontier.end());
    std::vector<unsigned> candidate(graph.size(), inf), next;
    unsigned rounds = 0;
    while (!frontier.empty()) {
        for (const unsigned src : frontier) {
            if (distance[src] == inf) continue;
            for (const auto &[dst, weight] : graph[src]) {
                const unsigned value = distance[src] + weight;
                if (value >= distance[dst]) continue;
                if (candidate[dst] == inf) next.push_back(dst);
                candidate[dst] = std::min(candidate[dst], value);
            }
        }
        for (const unsigned dst : next) {
            distance[dst] = candidate[dst];
            candidate[dst] = inf;
        }
        frontier.swap(next);
        next.clear();
        ++rounds;
    }
    if (distance != expected) throw std::runtime_error("warm SSSP differs from Dijkstra");
    return rounds;
}

unsigned count_shortcut(const Graph &graph, const std::vector<unsigned> &old,
                        std::vector<unsigned> &state, unsigned src, unsigned dst,
                        unsigned weight, unsigned cap)
{
    std::priority_queue<Arc, std::vector<Arc>, std::greater<Arc>> queue;
    std::vector<unsigned> touched;
    const auto relax = [&](unsigned vertex, unsigned value) {
        if (value >= state[vertex]) return;
        if (state[vertex] == old[vertex]) touched.push_back(vertex);
        state[vertex] = value;
        queue.emplace(value, vertex);
    };
    relax(dst, old[src] + weight);
    while (!queue.empty() && touched.size() <= cap) {
        const auto [value, vertex] = queue.top();
        queue.pop();
        if (value != state[vertex]) continue;
        for (const auto &[neighbor, cost] : graph[vertex]) relax(neighbor, value + cost);
    }
    for (unsigned vertex : touched) state[vertex] = old[vertex];
    return touched.size();
}

void propose_shortcuts(const Graph &graph, unsigned source)
{
    unsigned max_hops = 0;
    const auto old = sssp(graph, source, max_hops);
    auto state = old;
    std::vector<unsigned> eligible;
    for (unsigned v = 0; v < graph.size(); ++v)
        if (!graph[v].empty() && old[v] != std::numeric_limits<unsigned>::max())
            eligible.push_back(v);
    if (eligible.size() < 2) throw std::runtime_error("not enough reachable vertices");
    std::mt19937 random(20261110);
    const std::vector<unsigned> targets = {20, 197, 1965, 19652, 196521, 982603};
    for (unsigned target : targets) {
        unsigned best_error = target, cap = target * 2;
        std::tuple<unsigned, unsigned, unsigned, unsigned> best{};
        for (unsigned attempt = 0; attempt < 96; ++attempt) {
            unsigned src = attempt % 4 == 0 ? source : eligible[random() % eligible.size()];
            unsigned dst = eligible[random() % eligible.size()];
            if (old[src] + 1 >= old[dst]) continue;
            if (std::any_of(graph[src].begin(), graph[src].end(),
                            [dst](Arc arc) { return arc.first == dst; })) continue;
            unsigned difference = old[dst] - old[src];
            unsigned weight = attempt % 3 == 0 ? 1u : std::min(4095u, difference - 1);
            const unsigned count = count_shortcut(graph, old, state, src, dst, weight, cap);
            const unsigned error = count < target ? target - count : count - target;
            if (count > cap || error >= best_error) continue;
            best_error = error;
            best = {src, dst, weight, count};
            if (error <= target / 20) break;
        }
        const auto [src, dst, weight, changed] = best;
        if (changed >= target / 2)
            std::cout << target << ' ' << src << ' ' << dst << ' ' << weight << ' ' << changed << '\n';
    }
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        std::cerr << "usage: check_old_state sssp|cc|sssp-probe GRAPH SOURCE\n";
        return 2;
    }
    const std::string mode(argv[1]);
    if (mode != "sssp" && mode != "cc" && mode != "sssp-probe") return 2;
    const bool weighted = mode == "sssp";
    const unsigned source = std::stoul(argv[3]);
    std::ifstream input(argv[2]);
    unsigned vertices, edges, updates;
    if (!(input >> vertices >> edges >> updates)) throw std::runtime_error("invalid header");
    Graph graph(vertices);
    unsigned src, dst, weight, op;
    for (unsigned i = 0; i < edges; ++i) {
        if (!(input >> src >> dst >> weight) || dst >= vertices || !weight) {
            throw std::runtime_error("invalid initial arc");
        }
        graph.at(src).emplace_back(dst, weight);
    }
    if (mode == "sssp-probe") {
        propose_shortcuts(graph, source);
        return 0;
    }
    unsigned old_hops = 0, final_hops = 0;
    const auto before = weighted ? sssp(graph, source, old_hops) : cc(graph, old_hops);
    std::vector<unsigned> updated_sources;
    for (unsigned i = 0; i < updates; ++i) {
        if (!(input >> src >> dst >> weight >> op) || dst >= vertices || !weight || op != 1) {
            throw std::runtime_error("expected a valid insertion");
        }
        graph.at(src).emplace_back(dst, weight);
        if (weighted) updated_sources.push_back(src);
    }
    const auto after = weighted ? sssp(graph, source, final_hops) : cc(graph, final_hops);
    const auto changed = std::inner_product(before.begin(), before.end(), after.begin(),
                                           0u, std::plus<unsigned>(), std::not_equal_to<unsigned>());
    std::cout << "vertices=" << vertices << " static_arcs=" << edges
              << " update_records=" << updates << " changed_vertices=" << changed
              << " old_max_solution_hops=" << old_hops
              << " new_max_solution_hops=" << final_hops;
    if (weighted) {
        const unsigned rounds = check_warm_sssp(graph, before, after, updated_sources);
        std::cout << " warm_frontier_rounds=" << rounds;
    } else {
        std::vector<unsigned> component_sizes(vertices);
        unsigned real_vertices = 0;
        for (unsigned v = 0; v < vertices; ++v) {
            // RN's missing external IDs are isolated; valid road vertices have neighbors.
            if (graph[v].empty()) continue;
            ++real_vertices;
            ++component_sizes[before[v]];
        }
        const auto largest = std::max_element(component_sizes.begin(), component_sizes.end());
        std::cout << " real_vertices=" << real_vertices
                  << " old_largest_component_size=" << *largest
                  << " old_largest_component_label=" << largest - component_sizes.begin()
                  << " old_label_zero_component_size=" << component_sizes[0];
    }
    std::cout << '\n';
}
