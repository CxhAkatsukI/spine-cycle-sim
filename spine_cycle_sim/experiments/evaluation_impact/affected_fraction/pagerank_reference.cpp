// Host-only FP32 reference. Arithmetic order matches the resident Spine oracle.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

using Adjacency = std::vector<std::vector<uint32_t>>;
constexpr float damping = .85f;

struct Input {
    Adjacency old_graph, new_graph;
};

Input load(const char* path) {
    std::ifstream stream(path);
    uint32_t vertices, edges, updates;
    if (!(stream >> vertices >> edges >> updates) || !vertices) throw std::runtime_error("bad graph");
    Input result{Adjacency(vertices), Adjacency(vertices)};
    for (uint32_t index = 0; index < edges + updates; ++index) {
        uint32_t src, dst, weight;
        int diff = 1;
        if (!(stream >> src >> dst >> weight) || src >= vertices || dst >= vertices)
            throw std::runtime_error("bad edge");
        if (index >= edges && (!(stream >> diff) || diff != 1)) throw std::runtime_error("insertions required");
        if (index < edges) result.old_graph[src].push_back(dst);
        result.new_graph[src].push_back(dst);
    }
    for (auto* graph : {&result.old_graph, &result.new_graph}) {
        for (auto& row : *graph) {
            std::sort(row.begin(), row.end());
            if (std::adjacent_find(row.begin(), row.end()) != row.end())
                throw std::runtime_error("duplicate destination");
        }
    }
    return result;
}

std::vector<float> step(const Adjacency& graph, const std::vector<float>& rank) {
    const auto vertices = graph.size();
    const float base = (1.f - damping) / static_cast<float>(vertices);
    float dangling = 0.f;
    for (size_t src = 0; src < vertices; ++src) if (graph[src].empty()) dangling += rank[src];
    std::vector<float> next(vertices, base + damping * dangling / static_cast<float>(vertices));
    for (size_t src = 0; src < vertices; ++src) {
        if (graph[src].empty()) continue;
        const float contribution = damping * rank[src] / static_cast<float>(graph[src].size());
        for (auto dst : graph[src]) next[dst] += contribution;
    }
    return next;
}

void evaluate(const char* path, float epsilon) {
    auto input = load(path);
    const auto& graph = input.new_graph;
    const size_t vertices = graph.size();
    std::vector<float> rank(vertices, 1.f / static_cast<float>(vertices));
    for (unsigned round = 0; round < 128; ++round) rank = step(input.old_graph, rank);
    const auto old = rank;
    auto residual = step(graph, rank);
    std::vector<float> inverse(vertices), payload(vertices);
    std::vector<uint32_t> active;
    for (size_t vertex = 0; vertex < vertices; ++vertex) {
        residual[vertex] -= rank[vertex];
        inverse[vertex] = graph[vertex].empty() ? 0.f : 1.f / static_cast<float>(graph[vertex].size());
        if (std::fabs(residual[vertex]) > epsilon) active.push_back(vertex);
    }
    const auto initial = active.size();
    uint64_t traversed = 0, served = 0;
    unsigned rounds = 0;
    while (!active.empty() && rounds < 256) {
        std::fill(payload.begin(), payload.end(), 0.f);
        std::vector<uint8_t> touched(vertices, 0);
        for (auto src : active) {
            payload[src] = residual[src];
            rank[src] += residual[src];
            residual[src] = 0.f;
        }
        served += active.size();
        for (auto src : active) {
            const float contribution = damping * payload[src] * inverse[src];
            traversed += graph[src].size();
            for (auto dst : graph[src]) {
                residual[dst] += contribution;
                touched[dst] = 1;
            }
        }
        active.clear();
        for (size_t vertex = 0; vertex < vertices; ++vertex)
            if (touched[vertex] && std::fabs(residual[vertex]) > epsilon) active.push_back(vertex);
        ++rounds;
    }
    uint64_t changed = 0, changed_epsilon = 0;
    double l1 = 0;
    for (size_t vertex = 0; vertex < vertices; ++vertex) {
        const float delta = std::fabs(rank[vertex] - old[vertex]);
        changed += delta != 0.f;
        changed_epsilon += delta > epsilon;
        l1 += delta;
    }
    std::cout << "{\"converged\":" << (active.empty() ? "true" : "false")
              << ",\"changed_vertices\":" << changed << ",\"changed_above_epsilon\":" << changed_epsilon
              << ",\"initial_active\":" << initial << ",\"rounds\":" << rounds
              << ",\"reference_edges_traversed\":" << traversed << ",\"reference_sources_served\":" << served
              << ",\"rank_delta_l1\":" << l1 << "}\n";
    if (!active.empty()) throw std::runtime_error("CPU PR did not converge within 256 rounds");
}

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: pagerank_reference dynamic.graph epsilon");
        const float epsilon = std::stof(argv[2]);
        if (!(epsilon > 0.f) || !std::isfinite(epsilon)) throw std::runtime_error("invalid epsilon");
        evaluate(argv[1], epsilon);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
