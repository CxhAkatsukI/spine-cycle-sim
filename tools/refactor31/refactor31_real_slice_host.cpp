// Generic real-slice extension of the frozen refactor31 direct-FPGA host.
// The build script binds the exact host headers captured with the routed xclbin.
#include "host_split.hpp"
#include "segmented_exact_replay_reference.hpp"

#include <algorithm>
#include <cmath>
#include <chrono>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace segmented_reference = segmented_exact_reference;

struct FallbackFixture {
    std::string name;
    int num_vertices = HOST_VS_PART_MAX;
    int level = 0;
    uint32_t source = 0;
    bool real_slice = false;
    unsigned expected_path = HOST_PARTCONV_TASK_PATH_FALLBACK;
    unsigned expected_reason = HOST_PARTCONV_TASK_FALLBACK_NONE;
    std::vector<PartitionedCsrEdgeRef> edges;
    std::vector<uint32_t> active_sources;
};

static uint64_t endpoint_key(uint32_t src, uint32_t dst) {
    return ((uint64_t)src << 32) | dst;
}

static FallbackFixture load_real_slice(const std::string &path,
                                       uint32_t requested_source) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open slice: " + path);

    FallbackFixture fixture;
    fixture.name = path;
    fixture.level = 8;
    fixture.real_slice = true;
    int declared_vertices = -1;
    uint32_t max_vertex = 0;
    bool saw_vertex = false;
    std::unordered_map<uint64_t, uint16_t> minimum_weight;
    std::string line;
    while (std::getline(input, line)) {
        if (line.rfind("# vertices=", 0) == 0) {
            declared_vertices = std::stoi(line.substr(11));
            continue;
        }
        if (line.empty() || line[0] == '#') continue;
        std::istringstream row(line);
        uint64_t src64 = 0;
        uint64_t dst64 = 0;
        uint64_t weight64 = 0;
        int64_t diff = 0;
        if (!(row >> src64 >> dst64 >> weight64 >> diff)) {
            throw std::runtime_error("malformed slice row: " + line);
        }
        if (src64 >= (uint64_t)HOST_VS_PART_MAX ||
            dst64 >= (uint64_t)HOST_VS_PART_MAX || weight64 == 0 ||
            weight64 > UINT16_MAX || diff <= 0) {
            throw std::runtime_error("slice row exceeds refactor31 domain");
        }
        uint32_t src = (uint32_t)src64;
        uint32_t dst = (uint32_t)dst64;
        uint16_t weight = (uint16_t)weight64;
        uint64_t key = endpoint_key(src, dst);
        auto found = minimum_weight.find(key);
        if (found == minimum_weight.end() || weight < found->second) {
            minimum_weight[key] = weight;
        }
        max_vertex = std::max(max_vertex, std::max(src, dst));
        saw_vertex = true;
    }
    if (!saw_vertex) throw std::runtime_error("real slice has no edges");
    fixture.num_vertices = declared_vertices >= 0
                               ? declared_vertices
                               : (int)max_vertex + 1;
    if (fixture.num_vertices <= 0 ||
        fixture.num_vertices > HOST_VS_PART_MAX ||
        max_vertex >= (uint32_t)fixture.num_vertices) {
        throw std::runtime_error("slice vertex declaration is invalid");
    }

    fixture.edges.reserve(minimum_weight.size());
    std::vector<uint32_t> outdegree((size_t)fixture.num_vertices, 0);
    for (const auto &entry : minimum_weight) {
        uint32_t src = (uint32_t)(entry.first >> 32);
        uint32_t dst = (uint32_t)entry.first;
        fixture.edges.push_back({src, dst, entry.second, 1});
        outdegree[src]++;
    }
    std::sort(fixture.edges.begin(), fixture.edges.end(),
              [](const PartitionedCsrEdgeRef &left,
                 const PartitionedCsrEdgeRef &right) {
                  return std::tie(left.src, left.dst, left.weight) <
                         std::tie(right.src, right.dst, right.weight);
              });

    std::array<uint64_t, HOST_PARTITIONED_CSR_DST_PARTITIONS> family_edges{};
    for (const auto &edge : fixture.edges) {
        size_t partition = std::min<size_t>(
            edge.dst / (uint32_t)HOST_VS_PART_MAX,
            HOST_PARTITIONED_CSR_DST_PARTITIONS - 1);
        family_edges[partition]++;
    }
    bool level_selected = false;
    for (int level = 8; level < HOST_PARTITIONED_RATIO2_LEVELS; level++) {
        uint64_t capacity = partitioned_ratio2_level_partition_capacity(level);
        if (std::all_of(family_edges.begin(), family_edges.end(),
                        [capacity](uint64_t count) {
                            return count <= capacity;
                        })) {
            fixture.level = level;
            level_selected = true;
            break;
        }
    }
    if (!level_selected) {
        throw std::runtime_error("slice exceeds refactor31 L8-L10 capacity");
    }

    if (requested_source != UINT32_MAX) {
        if (requested_source >= (uint32_t)fixture.num_vertices) {
            throw std::runtime_error("requested source exceeds slice domain");
        }
        fixture.source = requested_source;
    } else {
        bool selected = false;
        for (uint32_t vertex = 0; vertex < (uint32_t)fixture.num_vertices;
             vertex++) {
            if (outdegree[vertex] >= 4 && outdegree[vertex] <= 16) {
                fixture.source = vertex;
                selected = true;
                break;
            }
        }
        if (!selected) {
            for (uint32_t vertex = 0;
                 vertex < (uint32_t)fixture.num_vertices; vertex++) {
                if (outdegree[vertex] != 0) {
                    fixture.source = vertex;
                    selected = true;
                    break;
                }
            }
        }
        if (!selected) throw std::runtime_error("slice has no source vertex");
    }
    fixture.active_sources = {fixture.source};
    return fixture;
}

static std::vector<uint32_t> dijkstra_reference(
    const FallbackFixture &fixture) {
    const uint32_t infinity = std::numeric_limits<uint32_t>::max() / 4;
    std::vector<std::vector<std::pair<uint32_t, uint16_t>>> adjacency(
        (size_t)fixture.num_vertices);
    for (const auto &edge : fixture.edges) {
        adjacency[edge.src].push_back({edge.dst, edge.weight});
    }
    std::vector<uint32_t> distance((size_t)fixture.num_vertices, infinity);
    using QueueEntry = std::pair<uint32_t, uint32_t>;
    std::priority_queue<QueueEntry, std::vector<QueueEntry>,
                        std::greater<QueueEntry>>
        queue;
    distance[fixture.source] = 0;
    queue.push({0, fixture.source});
    while (!queue.empty()) {
        auto [value, src] = queue.top();
        queue.pop();
        if (value != distance[src]) continue;
        for (const auto &[dst, weight] : adjacency[src]) {
            uint64_t candidate = (uint64_t)value + weight;
            if (candidate < distance[dst]) {
                distance[dst] = (uint32_t)candidate;
                queue.push({distance[dst], dst});
            }
        }
    }
    return distance;
}

template <typename T>
using AlignedVector = std::vector<T, xcl::aligned_allocator<T>>;

static cl::Buffer make_bank_buffer(cl::Context &context, unsigned bank,
                                   void *host_ptr, size_t bytes) {
    cl_int err = CL_SUCCESS;
    cl_mem_ext_ptr_t ext = {bank | XCL_MEM_TOPOLOGY, host_ptr, nullptr};
    OCL_CHECK(err, cl::Buffer buffer(
                       context,
                       CL_MEM_READ_WRITE | CL_MEM_EXT_PTR_XILINX |
                           CL_MEM_USE_HOST_PTR,
                       bytes, &ext, &err));
    return buffer;
}

static FallbackFixture make_payload_single_row_one_tile() {
    FallbackFixture fixture;
    fixture.name = "payload_single_row_one_tile";
    fixture.level = 8;
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_PAYLOAD_BUDGET;
    fixture.active_sources = {0};
    fixture.edges.reserve(HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET + 1ULL);
    for (size_t i = 0; i <= HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET; i++) {
        fixture.edges.push_back(
            {0, (uint32_t)(i & (HOST_PARTITIONED_CONV_TILE_VERTICES - 1)),
             1, 1});
    }
    return fixture;
}

static FallbackFixture make_payload_exact_single_row_one_tile() {
    FallbackFixture fixture;
    fixture.name = "payload_exact_single_row_one_tile";
    fixture.level = 8;
    fixture.expected_path = HOST_PARTCONV_TASK_PATH_EXACT;
    fixture.active_sources = {0};
    fixture.edges.reserve(HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET);
    for (size_t i = 0; i < HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET; i++) {
        fixture.edges.push_back(
            {0, (uint32_t)(i & (HOST_PARTITIONED_CONV_TILE_VERTICES - 1)),
             1, 1});
    }
    return fixture;
}

static FallbackFixture make_task_capacity_over() {
    FallbackFixture fixture;
    fixture.name = "task_capacity_over";
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_CAPACITY;
    const size_t tiles = HOST_PARTITIONED_CONV_TILES_PER_PARTITION;
    if (tiles != 16 || HOST_PARTCONV_RANGE_TASK_CAPACITY % tiles != 0) {
        throw std::runtime_error("task-capacity fixture requires 16 tiles");
    }
    const size_t full_sources = HOST_PARTCONV_RANGE_TASK_CAPACITY / tiles;
    fixture.num_vertices =
        (int)((tiles - 1ULL) * HOST_PARTITIONED_CONV_TILE_VERTICES + 8192ULL +
              full_sources);
    fixture.active_sources.reserve(full_sources + 1ULL);
    fixture.edges.reserve(HOST_PARTCONV_RANGE_TASK_CAPACITY + 1ULL);
    for (uint32_t src = 0; src < (uint32_t)full_sources; src++) {
        fixture.active_sources.push_back(src);
        for (size_t tile = 0; tile < tiles; tile++) {
            uint32_t dst =
                (uint32_t)(tile * HOST_PARTITIONED_CONV_TILE_VERTICES) +
                8192U + src;
            fixture.edges.push_back({src, dst, 1, 1});
        }
    }
    fixture.active_sources.push_back((uint32_t)full_sources);
    fixture.edges.push_back({(uint32_t)full_sources, 4097, 1, 1});
    return fixture;
}

static FallbackFixture make_payload_single_row_sixteen_tiles() {
    FallbackFixture fixture;
    fixture.name = "payload_single_row_sixteen_tiles";
    fixture.level = 8;
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_PAYLOAD_BUDGET;
    fixture.active_sources = {0};
    fixture.edges.reserve(HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET + 1ULL);
    for (size_t i = 0; i <= HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET; i++) {
        fixture.edges.push_back({0, (uint32_t)(i % HOST_VS_PART_MAX), 1, 1});
    }
    return fixture;
}

static FallbackFixture make_payload_exact_single_row_sixteen_tiles() {
    FallbackFixture fixture;
    fixture.name = "payload_exact_single_row_sixteen_tiles";
    fixture.level = 8;
    fixture.expected_path = HOST_PARTCONV_TASK_PATH_EXACT;
    fixture.active_sources = {0};
    fixture.edges.reserve(HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET);
    for (size_t i = 0; i < HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET; i++) {
        fixture.edges.push_back({0, (uint32_t)(i % HOST_VS_PART_MAX), 1, 1});
    }
    return fixture;
}

static FallbackFixture make_payload_many_rows() {
    FallbackFixture fixture;
    fixture.name = "payload_many_rows";
    fixture.level = 8;
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_PAYLOAD_BUDGET;
    constexpr size_t row_count = 1024;
    const size_t payload_count = HOST_PARTCONV_RANGE_TASK_PAYLOAD_BUDGET + 1ULL;
    fixture.active_sources.reserve(row_count);
    fixture.edges.reserve(payload_count);
    for (size_t src = 0; src < row_count; src++) {
        fixture.active_sources.push_back((uint32_t)src);
        size_t count = payload_count / row_count +
                       (src < payload_count % row_count ? 1ULL : 0ULL);
        for (size_t j = 0; j < count; j++) {
            uint32_t dst = (uint32_t)((j * 1021ULL + src * 4099ULL) %
                                      (size_t)HOST_VS_PART_MAX);
            fixture.edges.push_back({(uint32_t)src, dst, 1, 1});
        }
    }
    return fixture;
}

static FallbackFixture make_active_gate_one_tile() {
    FallbackFixture fixture;
    fixture.name = "active_gate_one_tile";
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_ACTIVE_GATE;
    const size_t count = HOST_PARTCONV_RANGE_TASK_ACTIVE_GATE + 1ULL;
    fixture.active_sources.reserve(count);
    fixture.edges.reserve(count);
    for (size_t i = 0; i < count; i++) {
        uint32_t src = (uint32_t)(HOST_PARTITIONED_CONV_TILE_VERTICES + i);
        fixture.active_sources.push_back(src);
        fixture.edges.push_back(
            {src, (uint32_t)(i % HOST_PARTITIONED_CONV_TILE_VERTICES), 1, 1});
    }
    return fixture;
}

static FallbackFixture make_active_exact_one_tile() {
    FallbackFixture fixture;
    fixture.name = "active_exact_one_tile";
    fixture.expected_path = HOST_PARTCONV_TASK_PATH_EXACT;
    const size_t count = HOST_PARTCONV_RANGE_TASK_ACTIVE_GATE;
    fixture.active_sources.reserve(count);
    fixture.edges.reserve(count);
    for (size_t i = 0; i < count; i++) {
        uint32_t src = (uint32_t)(HOST_PARTITIONED_CONV_TILE_VERTICES + i);
        fixture.active_sources.push_back(src);
        fixture.edges.push_back(
            {src, (uint32_t)(i % HOST_PARTITIONED_CONV_TILE_VERTICES), 1, 1});
    }
    return fixture;
}

static FallbackFixture make_active_gate_many_tiles() {
    FallbackFixture fixture;
    fixture.name = "active_gate_many_tiles";
    fixture.expected_reason = HOST_PARTCONV_TASK_FALLBACK_ACTIVE_GATE;
    const size_t count = HOST_PARTCONV_RANGE_TASK_ACTIVE_GATE + 1ULL;
    fixture.active_sources.reserve(count);
    fixture.edges.reserve(count);
    for (size_t i = 0; i < count; i++) {
        uint32_t src = (uint32_t)(HOST_VS_PART_MAX - 1ULL - i);
        uint32_t dst = (uint32_t)((i * (size_t)HOST_VS_PART_MAX) / count);
        fixture.active_sources.push_back(src);
        fixture.edges.push_back({src, dst, 1, 1});
    }
    return fixture;
}

static FallbackFixture make_active_exact_many_tiles() {
    FallbackFixture fixture;
    fixture.name = "active_exact_many_tiles";
    fixture.expected_path = HOST_PARTCONV_TASK_PATH_EXACT;
    const size_t count = HOST_PARTCONV_RANGE_TASK_ACTIVE_GATE;
    fixture.active_sources.reserve(count);
    fixture.edges.reserve(count);
    for (size_t i = 0; i < count; i++) {
        uint32_t src = (uint32_t)(HOST_VS_PART_MAX - 1ULL - i);
        uint32_t dst = (uint32_t)((i * (size_t)HOST_VS_PART_MAX) / count);
        fixture.active_sources.push_back(src);
        fixture.edges.push_back({src, dst, 1, 1});
    }
    return fixture;
}

static FallbackFixture make_fixture(const std::string &name) {
    if (name == "task_capacity_over") return make_task_capacity_over();
    if (name == "payload_exact_single_row_one_tile") {
        return make_payload_exact_single_row_one_tile();
    }
    if (name == "payload_single_row_one_tile") {
        return make_payload_single_row_one_tile();
    }
    if (name == "payload_exact_single_row_sixteen_tiles") {
        return make_payload_exact_single_row_sixteen_tiles();
    }
    if (name == "payload_single_row_sixteen_tiles") {
        return make_payload_single_row_sixteen_tiles();
    }
    if (name == "payload_many_rows") return make_payload_many_rows();
    if (name == "active_exact_one_tile") return make_active_exact_one_tile();
    if (name == "active_gate_one_tile") return make_active_gate_one_tile();
    if (name == "active_exact_many_tiles") {
        return make_active_exact_many_tiles();
    }
    if (name == "active_gate_many_tiles") return make_active_gate_many_tiles();
    throw std::runtime_error("unknown fallback fixture: " + name);
}

template <typename T>
static void write_binary(const std::string &path, const T *data, size_t count) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("cannot open fixture output: " + path);
    out.write(reinterpret_cast<const char *>(data),
              (std::streamsize)(count * sizeof(T)));
    if (!out) throw std::runtime_error("cannot write fixture output: " + path);
}

template <typename T, typename Allocator>
static void write_binary(const std::string &path,
                         const std::vector<T, Allocator> &data) {
    write_binary(path, data.data(), data.size());
}

static void dump_fixture(
    const std::string &directory, const FallbackFixture &fixture,
    const PartitionedGraphImage &image, const PartitionedActiveBinFlat &active,
    const std::vector<uint32_t> &initial_vs,
    const std::vector<uint32_t> &expected_vs,
    const std::vector<uint32_t> &expected_active) {
    for (size_t p = 0; p < image.graph_words.size(); p++) {
        write_binary(directory + "/graph" + std::to_string(p) + ".bin",
                     image.graph_words[p]);
    }
    write_binary(directory + "/meta.bin", image.meta_words);
    write_binary(directory + "/active.bin", active.records);
    write_binary(directory + "/vertex_initial.bin", initial_vs);
    write_binary(directory + "/vertex_expected.bin", expected_vs);
    write_binary(directory + "/active_expected.bin", expected_active);

    std::ofstream manifest(directory + "/fixture.txt", std::ios::trunc);
    if (!manifest) throw std::runtime_error("cannot open fixture manifest");
    manifest << "name=" << fixture.name << '\n'
             << "num_vertices=" << fixture.num_vertices << '\n'
             << "level=" << fixture.level << '\n'
             << "edges=" << fixture.edges.size() << '\n'
             << "active_sources=" << fixture.active_sources.size() << '\n'
             << "active_records=" << active.records.size() << '\n'
             << "expected_active=" << expected_active.size() << '\n'
             << "expected_path=" << fixture.expected_path << '\n'
             << "expected_reason=" << fixture.expected_reason << '\n';
}

static double event_duration_ms(const cl::Event &event) {
    uint64_t start = event.getProfilingInfo<CL_PROFILING_COMMAND_START>();
    uint64_t end = event.getProfilingInfo<CL_PROFILING_COMMAND_END>();
    return (double)(end - start) / 1e6;
}

enum class MalformedPosition { None, First, Middle, Last };

static MalformedPosition parse_malformed_position(const std::string &value) {
    if (value == "first") return MalformedPosition::First;
    if (value == "middle") return MalformedPosition::Middle;
    if (value == "last") return MalformedPosition::Last;
    throw std::runtime_error("unknown malformed position: " + value);
}

static size_t malformed_active_index(MalformedPosition position,
                                     size_t active_count) {
    if (active_count == 0) {
        throw std::runtime_error("malformed fixture has no active source");
    }
    if (position == MalformedPosition::First) return 0;
    if (position == MalformedPosition::Middle) return active_count / 2;
    if (position == MalformedPosition::Last) return active_count - 1;
    throw std::runtime_error("malformed position was not selected");
}

static bool same_task_scratch(
    const AlignedVector<PartitionedHbm16Word> &actual,
    const AlignedVector<PartitionedHbm16Word> &expected) {
    return actual.size() == expected.size() &&
           std::memcmp(actual.data(), expected.data(),
                       actual.size() * sizeof(PartitionedHbm16Word)) == 0;
}

static bool same_active_records(
    const AlignedVector<PartitionedActiveRecordWord> &actual,
    const AlignedVector<PartitionedActiveRecordWord> &expected) {
    return actual.size() == expected.size() &&
           std::memcmp(actual.data(), expected.data(),
                       actual.size() * sizeof(PartitionedActiveRecordWord)) ==
               0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0]
                  << " <split.xclbin> <fixture|--slice path>"
                     " [--source vertex] [--max-rounds count]"
                     " [--dump-dir directory]"
                     " [--malformed first|middle|last]"
                     " [--repeat-launches count] [--recover-after-malformed]"
                  << std::endl;
        return 1;
    }
    try {
        std::string dump_dir;
        MalformedPosition malformed_position = MalformedPosition::None;
        int repeat_launches = 1;
        int max_rounds = 4096;
        uint32_t requested_source = UINT32_MAX;
        bool recover_after_malformed = false;
        std::string fixture_name = argv[2];
        int option_start = 3;
        std::string real_slice_path;
        if (fixture_name == "--slice") {
            if (argc < 4) throw std::runtime_error("--slice requires a path");
            real_slice_path = argv[3];
            option_start = 4;
        }
        for (int i = option_start; i < argc; i++) {
            if (std::string(argv[i]) == "--dump-dir" && i + 1 < argc) {
                dump_dir = argv[++i];
            } else if (std::string(argv[i]) == "--source" &&
                       i + 1 < argc) {
                requested_source = (uint32_t)std::stoul(argv[++i]);
            } else if (std::string(argv[i]) == "--max-rounds" &&
                       i + 1 < argc) {
                max_rounds = std::stoi(argv[++i]);
                if (max_rounds <= 0) {
                    throw std::runtime_error("max-rounds must be positive");
                }
            } else if (std::string(argv[i]) == "--malformed" &&
                       i + 1 < argc) {
                malformed_position = parse_malformed_position(argv[++i]);
            } else if (std::string(argv[i]) == "--repeat-launches" &&
                       i + 1 < argc) {
                repeat_launches = std::stoi(argv[++i]);
                if (repeat_launches <= 0) {
                    throw std::runtime_error(
                        "repeat-launches must be positive");
                }
            } else if (std::string(argv[i]) ==
                       "--recover-after-malformed") {
                recover_after_malformed = true;
            } else {
                throw std::runtime_error("unknown argument: " +
                                         std::string(argv[i]));
            }
        }
        if (recover_after_malformed &&
            malformed_position == MalformedPosition::None) {
            throw std::runtime_error(
                "recover-after-malformed requires --malformed");
        }

        FallbackFixture fixture = real_slice_path.empty()
                                      ? make_fixture(fixture_name)
                                      : load_real_slice(real_slice_path,
                                                        requested_source);
        if (fixture.real_slice &&
            (malformed_position != MalformedPosition::None ||
             recover_after_malformed || !dump_dir.empty())) {
            throw std::runtime_error(
                "real-slice mode does not accept malformed/dump options");
        }
        std::vector<std::vector<PartitionedCsrEdgeRef>> levels(
            HOST_PARTITIONED_RATIO2_LEVELS);
        levels[(size_t)fixture.level] = fixture.edges;
        PartitionedCsrReferenceGraph graph = build_partitioned_csr_reference(
            levels, fixture.num_vertices, HOST_PARTITIONED_CSR_DST_PARTITIONS);

        const uint32_t inf = std::numeric_limits<uint32_t>::max() / 4;
        std::vector<uint32_t> initial_vs((size_t)fixture.num_vertices, inf);
        for (uint32_t src : fixture.active_sources) initial_vs[src] = 0;
        PartitionedActiveBins bins = partitioned_active_source_binning_reference(
            graph, fixture.active_sources, initial_vs);
        PartitionedActiveBinFlat active = flatten_partitioned_active_bins(bins);
        PartitionedGraphImage image =
            serialize_partitioned_graph_reference(graph, active);
        PartitionedRangeTaskModelResult exact_model =
            build_partitioned_range_tasks_reference(image, active,
                                                    fixture.num_vertices);
        if (!fixture.real_slice &&
            (exact_model.stats.path != fixture.expected_path ||
            exact_model.stats.fallback_reason != fixture.expected_reason ||
             exact_model.stats.error != HOST_PARTCONV_TASK_ERROR_NONE)) {
            throw std::runtime_error(
                "fixture does not select intended path: path=" +
                std::to_string(exact_model.stats.path) + " reason=" +
                std::to_string(exact_model.stats.fallback_reason) + " error=" +
                std::to_string(exact_model.stats.error) + " active=" +
                std::to_string(exact_model.stats.active_records) + " payloads=" +
                std::to_string(exact_model.stats.construction_payloads));
        }

        std::vector<uint32_t> expected_vs = initial_vs;
        std::vector<uint64_t> expected_bitmap(
            partitioned_hbm_active_bitmap_words(expected_vs.size()), 0);
        std::vector<uint32_t> expected_active;
        if (!fixture.real_slice) {
            expected_active = partitioned_convergence_iteration_hbm_reference(
                graph, bins, expected_vs, expected_bitmap);
            std::sort(expected_active.begin(), expected_active.end());
        }
        if (!dump_dir.empty()) {
            dump_fixture(dump_dir, fixture, image, active, initial_vs,
                         expected_vs, expected_active);
        }

        int malformed_bank = -1;
        size_t malformed_word_index = 0;
        size_t malformed_index = 0;
        uint64_t valid_payload_word = 0;
        uint64_t malformed_payload_word = 0;
        uint64_t reference_validated_payloads = 0;
        std::vector<uint64_t> valid_malformed_bank;
        if (malformed_position != MalformedPosition::None) {
            if (fixture.name != "active_gate_one_tile" || fixture.level != 0) {
                throw std::runtime_error(
                    "malformed traversal fixtures require "
                    "active_gate_one_tile");
            }
            malformed_index = malformed_active_index(
                malformed_position, fixture.active_sources.size());
            const uint32_t malformed_src =
                fixture.active_sources[malformed_index];
            malformed_bank = 0;
            PartitionedRangeTaskRowHost malformed_row =
                partitioned_range_task_lookup_row_host(
                    image, malformed_bank, 0, fixture.level, malformed_src);
            if (!malformed_row.present ||
                malformed_row.end != malformed_row.start + 1U) {
                throw std::runtime_error(
                    "malformed traversal source does not own one payload");
            }
            malformed_word_index =
                (size_t)malformed_row.edge_offset + malformed_row.start;
            valid_malformed_bank =
                image.graph_words[(size_t)malformed_bank];
            valid_payload_word = valid_malformed_bank[malformed_word_index];
            malformed_payload_word =
                ((uint64_t)(uint32_t)fixture.num_vertices << 32) |
                (valid_payload_word & 0xffffffffULL);
            image.graph_words[(size_t)malformed_bank]
                             [malformed_word_index] = malformed_payload_word;

            segmented_reference::Workload workload;
            workload.num_vertices = (uint32_t)fixture.num_vertices;
            workload.declared_active_records = fixture.active_sources.size();
            workload.families.push_back(
                segmented_reference::Family{0, 0, 0, false});
            workload.active.reserve(fixture.active_sources.size());
            workload.rows.reserve(fixture.active_sources.size());
            for (size_t i = 0; i < fixture.active_sources.size(); i++) {
                segmented_reference::ActiveRecord source;
                source.source = fixture.active_sources[i];
                source.source_value = initial_vs[source.source];
                source.family_enabled = {1};
                workload.active.push_back(source);

                PartitionedRangeTaskRowHost row =
                    partitioned_range_task_lookup_row_host(
                        image, 0, 0, fixture.level, source.source);
                if (!row.present || row.end != row.start + 1U) {
                    throw std::runtime_error(
                        "independent malformed workload lost a source row");
                }
                segmented_reference::RowSlot slot;
                slot.family = 0;
                slot.active_ordinal = (uint32_t)i;
                slot.level = (uint8_t)fixture.level;
                slot.edge_offset = row.edge_offset + row.start;
                slot.graph_bank_words =
                    image.graph_words[0].size();
                slot.clipped_begin = 0;
                slot.clipped_end = 1;
                slot.payloads.push_back(
                    image.graph_words[0][slot.edge_offset]);
                workload.rows.push_back(std::move(slot));
            }
            segmented_reference::PreflightResult preflight =
                segmented_reference::preflight(
                    workload, segmented_reference::Fallback::ActiveGate);
            if (preflight.error != segmented_reference::Error::Destination ||
                preflight.begin_emitted || preflight.ack_eligible ||
                preflight.external_mutations != 0 ||
                preflight.emitted_stream_words != 0 ||
                preflight.counters.validation_payloads != malformed_index) {
                throw std::runtime_error(
                    "independent malformed preflight did not fail atomically");
            }
            reference_validated_payloads =
                preflight.counters.validation_payloads;
        }

        std::vector<AlignedVector<uint64_t>> graph_host(
            HOST_PARTITIONED_GRAPH_PORTS);
        for (int p = 0; p < HOST_PARTITIONED_GRAPH_PORTS; p++) {
            const std::vector<uint64_t> &source = image.graph_words[(size_t)p];
            graph_host[(size_t)p].assign(source.begin(), source.end());
            if (graph_host[(size_t)p].empty()) graph_host[(size_t)p].push_back(0);
        }
        AlignedVector<uint64_t> meta(image.meta_words.begin(),
                                     image.meta_words.end());
        const AlignedVector<uint64_t> initial_meta = meta;
        size_t active_record_capacity = active.records.size();
        if (fixture.real_slice) {
            std::vector<uint32_t> all_sources((size_t)fixture.num_vertices);
            for (uint32_t vertex = 0;
                 vertex < (uint32_t)fixture.num_vertices; vertex++) {
                all_sources[vertex] = vertex;
            }
            PartitionedActiveBins all_bins =
                partitioned_active_source_binning_reference(
                    graph, all_sources, initial_vs);
            PartitionedActiveBinFlat all_active =
                flatten_partitioned_active_bins(all_bins);
            active_record_capacity =
                std::max(active_record_capacity, all_active.records.size());
        }
        AlignedVector<PartitionedActiveRecordWord> active_host(
            std::max<size_t>(active_record_capacity, 1));
        std::copy(active.records.begin(), active.records.end(),
                  active_host.begin());
        if (active_host.empty()) active_host.resize(1);
        const AlignedVector<PartitionedActiveRecordWord> initial_active_host =
            active_host;
        const PartitionedHbm16Word task_sentinel = {
            UINT64_C(0x5a5aa5a53c3cc3c3),
            UINT64_C(0xc3c33c3ca5a55a5a)};
        AlignedVector<PartitionedHbm16Word> task_scratch(
            HOST_PARTCONV_RANGE_TASK_SCRATCH_WORDS, task_sentinel);
        const AlignedVector<PartitionedHbm16Word> initial_task_scratch =
            task_scratch;
        AlignedVector<uint32_t> vertex_state(initial_vs.begin(), initial_vs.end());
        AlignedVector<uint64_t> active_out(
            std::max<size_t>(1, (size_t)fixture.num_vertices), 0);
        AlignedVector<uint64_t> active_bitmap(HOST_ACTIVE_BMP_WORDS, 0);
        AlignedVector<int32_t> reader_result(HOST_MAINT_RESULT_WORDS, 0);
        AlignedVector<int32_t> compute_result(HOST_CONV_RESULT_WORDS, 0);

        auto devices = xcl::get_xil_devices();
        auto file_buf = xcl::read_binary_file(argv[1]);
        cl::Program::Binaries binaries;
        binaries.push_back({file_buf.data(), file_buf.data() + file_buf.size()});
        cl::Context context(devices[0]);
        cl::CommandQueue queue(
            context, devices[0],
            CL_QUEUE_PROFILING_ENABLE | CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE);
        std::vector<cl::Device> selected = {devices[0]};
        cl_int program_error = CL_SUCCESS;
        cl::Program program(context, selected, binaries, nullptr, &program_error);
        if (program_error != CL_SUCCESS) {
            throw std::runtime_error("failed to program accepted xclbin");
        }
        cl::Kernel reader(program, "spine_partconv_rdmaint_kernel");
        cl::Kernel compute(program, "spine_partconv_compute_kernel");

        std::vector<cl::Buffer> graph_buffers;
        for (int p = 0; p < HOST_PARTITIONED_GRAPH_PORTS; p++) {
            graph_buffers.push_back(make_bank_buffer(
                context, HBM_PARTITIONED_GRAPH_BASE + (unsigned)p,
                graph_host[(size_t)p].data(),
                graph_host[(size_t)p].size() * sizeof(uint64_t)));
        }
        cl::Buffer d_scratch = make_bank_buffer(
            context, HBM_PARTITIONED_SORTER_INPUT, task_scratch.data(),
            task_scratch.size() * sizeof(PartitionedHbm16Word));
        cl::Buffer d_active = make_bank_buffer(
            context, HBM_PARTITIONED_ACTIVE_BINS, active_host.data(),
            active_host.size() * sizeof(PartitionedActiveRecordWord));
        cl::Buffer d_meta = make_bank_buffer(
            context, HBM_PARTITIONED_LEVEL_META, meta.data(),
            meta.size() * sizeof(uint64_t));
        cl::Buffer d_reader_result = make_bank_buffer(
            context, HBM_PARTITIONED_SCRATCH, reader_result.data(),
            reader_result.size() * sizeof(int32_t));
        cl::Buffer d_vs = make_bank_buffer(
            context, HBM_PARTITIONED_VERTEX_STATE, vertex_state.data(),
            vertex_state.size() * sizeof(uint32_t));
        cl::Buffer d_active_out = make_bank_buffer(
            context, HBM_PARTITIONED_ACTIVE_LISTS, active_out.data(),
            active_out.size() * sizeof(uint64_t));
        cl::Buffer d_active_bitmap = make_bank_buffer(
            context, HBM_PARTITIONED_ACTIVE_BITMAP, active_bitmap.data(),
            active_bitmap.size() * sizeof(uint64_t));
        cl::Buffer d_compute_result = make_bank_buffer(
            context, HBM_PARTITIONED_SCRATCH, compute_result.data(),
            compute_result.size() * sizeof(int32_t));

        std::vector<cl::Memory> to_device;
        for (cl::Buffer &buffer : graph_buffers) to_device.push_back(buffer);
        to_device.insert(to_device.end(),
                         {d_scratch, d_active, d_meta, d_reader_result, d_vs,
                          d_active_out, d_active_bitmap, d_compute_result});
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = queue.enqueueMigrateMemObjects(to_device, 0));
        queue.finish();

        int arg = 0;
        for (cl::Buffer &buffer : graph_buffers) reader.setArg(arg++, buffer);
        reader.setArg(arg++, d_scratch);
        reader.setArg(arg++, d_active);
        reader.setArg(arg++, d_meta);
        reader.setArg(arg++, d_reader_result);
        reader.setArg(arg++, HOST_PARTITIONED_E2E_MODE_HOST_ACTIVE);
        reader.setArg(arg++, 0);
        reader.setArg(arg++, fixture.num_vertices);

        arg = 0;
        compute.setArg(arg++, d_vs);
        compute.setArg(arg++, d_active_out);
        compute.setArg(arg++, d_active_bitmap);
        compute.setArg(arg++, d_compute_result);
        compute.setArg(arg++, fixture.num_vertices);

        struct LaunchPlan {
            bool malformed = false;
            std::string label;
        };
        std::vector<LaunchPlan> launches;
        if (malformed_position != MalformedPosition::None) {
            launches.push_back({true, "malformed"});
            if (recover_after_malformed) {
                for (int i = 0; i < repeat_launches; i++) {
                    launches.push_back(
                        {false, "recovery-" + std::to_string(i + 1)});
                }
            } else {
                for (int i = 1; i < repeat_launches; i++) {
                    launches.push_back(
                        {true, "malformed-" + std::to_string(i + 1)});
                }
            }
        } else if (fixture.real_slice) {
            launches.reserve((size_t)max_rounds);
            for (int i = 0; i < max_rounds; i++) {
                launches.push_back({false, "real-sssp-" +
                                               std::to_string(i + 1)});
            }
        } else {
            for (int i = 0; i < repeat_launches; i++) {
                launches.push_back(
                    {false, "valid-" + std::to_string(i + 1)});
            }
        }

        const size_t logical_bitmap_words =
            partitioned_hbm_active_bitmap_words(initial_vs.size());
        const uint64_t active_out_sentinel =
            UINT64_C(0xd15ea5ed4b1d4b1d);
        int errors = 0;
        bool device_has_malformed_payload =
            malformed_position != MalformedPosition::None;
        std::vector<uint32_t> current_active = fixture.active_sources;
        uint64_t total_reader_cycles = 0;
        uint64_t total_compute_cycles = 0;
        uint64_t total_paired_cycles = 0;
        uint64_t total_processed_edges = 0;
        size_t completed_rounds = 0;
        std::vector<uint32_t> real_outdegree((size_t)fixture.num_vertices, 0);
        if (fixture.real_slice) {
            for (const auto &edge : fixture.edges) real_outdegree[edge.src]++;
        }
        for (size_t launch_index = 0; launch_index < launches.size();
             launch_index++) {
            const LaunchPlan &plan = launches[launch_index];
            uint64_t expected_edges_this_round = fixture.edges.size();
            if (fixture.real_slice) {
                if (current_active.empty()) break;
                bins = partitioned_active_source_binning_reference(
                    graph, current_active, expected_vs);
                active = flatten_partitioned_active_bins(bins);
                if (active.records.size() > active_host.size()) {
                    throw std::runtime_error(
                        "real frontier exceeds preallocated active records");
                }
                std::fill(active_host.begin(), active_host.end(),
                          PartitionedActiveRecordWord());
                std::copy(active.records.begin(), active.records.end(),
                          active_host.begin());
                std::copy(initial_meta.begin(), initial_meta.end(),
                          meta.begin());
                for (int partition = 0;
                     partition < HOST_PARTITIONED_CSR_DST_PARTITIONS;
                     partition++) {
                    meta[(size_t)HOST_PARTITIONED_META_ACTIVE_BIN_OFFSET_BASE +
                         (size_t)partition] =
                        active.offsets[(size_t)partition];
                    meta[(size_t)HOST_PARTITIONED_META_ACTIVE_BIN_COUNT_BASE +
                         (size_t)partition] =
                        active.counts[(size_t)partition];
                }
                expected_edges_this_round = 0;
                for (uint32_t src : current_active) {
                    expected_edges_this_round += real_outdegree[src];
                }
                std::fill(expected_bitmap.begin(), expected_bitmap.end(), 0);
                expected_active =
                    partitioned_convergence_iteration_hbm_reference(
                        graph, bins, expected_vs, expected_bitmap);
                std::sort(expected_active.begin(), expected_active.end());
            }
            if (malformed_bank >= 0 &&
                device_has_malformed_payload != plan.malformed) {
                graph_host[(size_t)malformed_bank][malformed_word_index] =
                    plan.malformed ? malformed_payload_word
                                   : valid_payload_word;
                OCL_CHECK(err, err = queue.enqueueMigrateMemObjects(
                                   {graph_buffers[(size_t)malformed_bank]}, 0));
                queue.finish();
                device_has_malformed_payload = plan.malformed;
            }

            if (!fixture.real_slice) {
                std::copy(initial_vs.begin(), initial_vs.end(),
                          vertex_state.begin());
            }
            std::fill(active_out.begin(), active_out.end(),
                      active_out_sentinel);
            std::fill(active_bitmap.begin(), active_bitmap.end(), 0);
            const bool poison_bitmap =
                !fixture.real_slice &&
                (launches.size() > 1 || plan.malformed);
            if (poison_bitmap) {
                for (size_t i = 0; i < logical_bitmap_words; i++) {
                    active_bitmap[i] =
                        UINT64_C(0xa5a55a5af00f0ff0) ^ (uint64_t)i;
                }
            }
            const AlignedVector<uint64_t> bitmap_before = active_bitmap;
            std::fill(task_scratch.begin(), task_scratch.end(), task_sentinel);
            if (!fixture.real_slice) {
                std::copy(initial_active_host.begin(),
                          initial_active_host.end(), active_host.begin());
                std::copy(initial_meta.begin(), initial_meta.end(),
                          meta.begin());
            }
            std::fill(reader_result.begin(), reader_result.end(), 0);
            std::fill(compute_result.begin(), compute_result.end(), 0);
            const AlignedVector<uint64_t> meta_before = meta;
            OCL_CHECK(err, err = queue.enqueueMigrateMemObjects(
                               {d_scratch, d_active, d_meta, d_reader_result,
                                d_vs, d_active_out, d_active_bitmap,
                                d_compute_result},
                               0));
            queue.finish();

            cl::Event compute_event;
            cl::Event reader_event;
            auto wall_start = std::chrono::steady_clock::now();
            OCL_CHECK(err, err = queue.enqueueTask(
                               compute, nullptr, &compute_event));
            OCL_CHECK(err, err = queue.enqueueTask(
                               reader, nullptr, &reader_event));
            queue.finish();
            auto wall_end = std::chrono::steady_clock::now();

            std::vector<cl::Memory> from_device = {
                d_vs,           d_active_out, d_active_bitmap,
                d_compute_result, d_reader_result, d_scratch,
                d_active,       d_meta};
            if (malformed_bank >= 0) {
                from_device.push_back(
                    graph_buffers[(size_t)malformed_bank]);
            }
            OCL_CHECK(err, err = queue.enqueueMigrateMemObjects(
                               from_device, CL_MIGRATE_MEM_OBJECT_HOST));
            queue.finish();

            int launch_errors = 0;
            std::vector<uint32_t> actual_active;
            if (plan.malformed) {
                if (compute_result[HOST_CONV_RESULT_OVERFLOW] != 1 ||
                    compute_result[HOST_CONV_RESULT_TASK_PATH] !=
                        (int)fixture.expected_path ||
                    compute_result[HOST_CONV_RESULT_TASK_FALLBACK_REASON] !=
                        (int)fixture.expected_reason ||
                    compute_result[HOST_CONV_RESULT_TASK_ERROR] !=
                        (int)HOST_PARTCONV_TASK_ERROR_DESTINATION ||
                    compute_result[HOST_CONV_RESULT_PROCESSED_EDGES] != 0 ||
                    compute_result[HOST_CONV_RESULT_NEXT_ACTIVE] != 0 ||
                    compute_result[HOST_CONV_RESULT_SEGMENT_COUNT] != 0 ||
                    compute_result[HOST_CONV_RESULT_SEGMENT_TASKS] != 0 ||
                    reader_result[HOST_MAINT_RESULT_DIRTY_ACK_ELIGIBLE] != 0) {
                    launch_errors++;
                }
                if (!std::equal(vertex_state.begin(), vertex_state.end(),
                                initial_vs.begin(), initial_vs.end()) ||
                    std::any_of(active_out.begin(), active_out.end(),
                                [active_out_sentinel](uint64_t word) {
                                    return word != active_out_sentinel;
                                }) ||
                    active_bitmap != bitmap_before) {
                    launch_errors++;
                }
            } else {
                if (compute_result[HOST_CONV_RESULT_OVERFLOW] != 0 ||
                    (!fixture.real_slice &&
                     compute_result[HOST_CONV_RESULT_TASK_PATH] !=
                         (int)fixture.expected_path) ||
                    (!fixture.real_slice &&
                     compute_result[HOST_CONV_RESULT_TASK_FALLBACK_REASON] !=
                         (int)fixture.expected_reason) ||
                    compute_result[HOST_CONV_RESULT_TASK_ERROR] != 0 ||
                    compute_result[HOST_CONV_RESULT_PROCESSED_EDGES] !=
                        (int)expected_edges_this_round ||
                    compute_result[HOST_CONV_RESULT_NEXT_ACTIVE] !=
                        (int)expected_active.size()) {
                    launch_errors++;
                }

                int next_count =
                    std::max(0, compute_result[HOST_CONV_RESULT_NEXT_ACTIVE]);
                actual_active.reserve((size_t)next_count);
                for (int i = 0; i < next_count; i++) {
                    actual_active.push_back(
                        (uint32_t)(active_out[(size_t)i] >> 32));
                }
                std::sort(actual_active.begin(), actual_active.end());
                if (actual_active != expected_active ||
                    !std::equal(vertex_state.begin(), vertex_state.end(),
                                expected_vs.begin(), expected_vs.end()) ||
                    std::any_of(active_bitmap.begin(), active_bitmap.end(),
                                [](uint64_t word) { return word != 0; })) {
                    launch_errors++;
                }
            }

            if (!fixture.real_slice &&
                ((fixture.expected_path == HOST_PARTCONV_TASK_PATH_FALLBACK &&
                  !same_task_scratch(task_scratch, initial_task_scratch)) ||
                 !same_active_records(active_host, initial_active_host))) {
                launch_errors++;
            }
            for (size_t i = 0; i < meta.size(); i++) {
                if (i == (size_t)HOST_PARTITIONED_META_DIRTY_LAST_MODE_WORD ||
                    i ==
                        (size_t)HOST_PARTITIONED_META_DIRTY_LAST_STATUS_WORD) {
                    continue;
                }
                if (meta[i] != meta_before[i]) {
                    launch_errors++;
                    break;
                }
            }
            if (meta[(size_t)HOST_PARTITIONED_META_DIRTY_LAST_MODE_WORD] !=
                    (uint64_t)HOST_PARTITIONED_E2E_MODE_HOST_ACTIVE ||
                meta[(size_t)HOST_PARTITIONED_META_DIRTY_LAST_STATUS_WORD] !=
                    (uint64_t)(uint32_t)
                        reader_result[HOST_MAINT_RESULT_DIRTY_STATUS]) {
                launch_errors++;
            }
            if (malformed_bank >= 0) {
                const std::vector<uint64_t> &expected_graph =
                    plan.malformed ? image.graph_words[(size_t)malformed_bank]
                                   : valid_malformed_bank;
                if (!std::equal(graph_host[(size_t)malformed_bank].begin(),
                                graph_host[(size_t)malformed_bank].end(),
                                expected_graph.begin(),
                                expected_graph.end())) {
                    launch_errors++;
                }
            }

            double reader_ms = event_duration_ms(reader_event);
            double compute_ms = event_duration_ms(compute_event);
            double wall_ms =
                std::chrono::duration<double, std::milli>(wall_end - wall_start)
                    .count();
            errors += launch_errors;
            total_reader_cycles +=
                (uint64_t)std::llround(reader_ms * 160000.0);
            total_compute_cycles +=
                (uint64_t)std::llround(compute_ms * 160000.0);
            total_paired_cycles += (uint64_t)std::llround(
                std::max(reader_ms, compute_ms) * 160000.0);
            total_processed_edges +=
                (uint64_t)(uint32_t)
                    compute_result[HOST_CONV_RESULT_PROCESSED_EDGES];
            completed_rounds++;
            std::cout << "SEGMENTED_FALLBACK_HW "
                      << (launch_errors == 0 ? "PASS" : "FAIL")
                      << " case=" << fixture.name
                      << " launch=" << (launch_index + 1)
                      << " phase=" << plan.label
                      << " malformed_index="
                      << (plan.malformed ? (long long)malformed_index : -1LL)
                      << " reference_validated="
                      << (plan.malformed ? reference_validated_payloads : 0)
                      << " vertices=" << fixture.num_vertices
                      << " edges=" << fixture.edges.size()
                      << " active_sources="
                      << (fixture.real_slice ? current_active.size()
                                             : fixture.active_sources.size())
                      << " active_records=" << active.records.size()
                      << " next_active="
                      << compute_result[HOST_CONV_RESULT_NEXT_ACTIVE]
                      << " processed="
                      << compute_result[HOST_CONV_RESULT_PROCESSED_EDGES]
                      << " path="
                      << compute_result[HOST_CONV_RESULT_TASK_PATH]
                      << " fallback="
                      << compute_result[HOST_CONV_RESULT_TASK_FALLBACK_REASON]
                      << " task_error="
                      << compute_result[HOST_CONV_RESULT_TASK_ERROR]
                      << " ack_eligible="
                      << reader_result[HOST_MAINT_RESULT_DIRTY_ACK_ELIGIBLE]
                      << " reader_ms=" << reader_ms
                      << " compute_ms=" << compute_ms
                      << " conv_ms=" << std::max(reader_ms, compute_ms)
                      << " wall_ms=" << wall_ms
                      << " errors=" << launch_errors << std::endl;
            std::cout << "SEGMENTED_FALLBACK_READER_RESULT";
            for (int32_t word : reader_result) std::cout << ' ' << word;
            std::cout << '\n' << "SEGMENTED_FALLBACK_COMPUTE_RESULT";
            for (int32_t word : compute_result) std::cout << ' ' << word;
            std::cout << std::endl;
            if (fixture.real_slice) current_active = std::move(actual_active);
        }
        if (fixture.real_slice) {
            if (!current_active.empty()) {
                throw std::runtime_error(
                    "real-slice SSSP did not converge within max-rounds");
            }
            std::vector<uint32_t> independent = dijkstra_reference(fixture);
            size_t mismatch_count = 0;
            for (size_t i = 0; i < independent.size(); i++) {
                if (vertex_state[i] != independent[i]) mismatch_count++;
            }
            if (mismatch_count != 0) errors++;
            std::cout << "REFACTOR31_REAL_SLICE_HW "
                      << (errors == 0 ? "PASS" : "FAIL")
                      << " slice=" << real_slice_path
                      << " source=" << fixture.source
                      << " vertices=" << fixture.num_vertices
                      << " graph_edges=" << fixture.edges.size()
                      << " resident_level=" << fixture.level
                      << " rounds=" << completed_rounds
                      << " processed_edges=" << total_processed_edges
                      << " reader_cycles=" << total_reader_cycles
                      << " compute_cycles=" << total_compute_cycles
                      << " paired_cycles=" << total_paired_cycles
                      << " dijkstra_mismatches=" << mismatch_count
                      << " reference_validated="
                      << (mismatch_count == 0 ? 1 : 0)
                      << " errors=" << errors << std::endl;
        }
        return errors == 0 ? 0 : 1;
    } catch (const std::exception &error) {
        std::cerr << "SEGMENTED_FALLBACK_HW ERROR " << error.what()
                  << std::endl;
        return 1;
    }
}
