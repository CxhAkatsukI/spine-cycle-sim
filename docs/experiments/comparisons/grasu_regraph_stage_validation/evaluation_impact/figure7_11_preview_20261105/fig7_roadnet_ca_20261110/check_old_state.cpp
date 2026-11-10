#include <algorithm>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <numeric>
#include <queue>
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

int main(int argc, char **argv)
{
    if (argc != 4 || (std::string(argv[1]) != "sssp" && std::string(argv[1]) != "cc")) {
        std::cerr << "usage: check_old_state sssp|cc GRAPH SOURCE\n";
        return 2;
    }
    const bool weighted = std::string(argv[1]) == "sssp";
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
    unsigned old_hops = 0, final_hops = 0;
    const auto before = weighted ? sssp(graph, source, old_hops) : cc(graph, old_hops);
    for (unsigned i = 0; i < updates; ++i) {
        if (!(input >> src >> dst >> weight >> op) || dst >= vertices || !weight || op != 1) {
            throw std::runtime_error("expected a valid insertion");
        }
        graph.at(src).emplace_back(dst, weight);
    }
    const auto after = weighted ? sssp(graph, source, final_hops) : cc(graph, final_hops);
    const auto changed = std::inner_product(before.begin(), before.end(), after.begin(),
                                           0u, std::plus<unsigned>(), std::not_equal_to<unsigned>());
    std::cout << "vertices=" << vertices << " static_arcs=" << edges
              << " update_records=" << updates << " changed_vertices=" << changed
              << " old_max_solution_hops=" << old_hops
              << " new_max_solution_hops=" << final_hops << '\n';
}
