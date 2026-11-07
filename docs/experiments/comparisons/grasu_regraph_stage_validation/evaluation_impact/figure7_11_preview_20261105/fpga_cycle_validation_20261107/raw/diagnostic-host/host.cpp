#include "host_split.hpp"
#include "host_maintenance_backing.hpp"
#include "spine_paper_architecture_contract.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <limits>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>
#include <sys/file.h>
#include <sys/stat.h>

#ifndef CL_DEVICE_PCIE_BDF
// XRT's published extension, absent from the CPU-only compatibility header.
#define CL_DEVICE_PCIE_BDF 0x1120
#endif

namespace {

template <typename T>
using AlignedVector = std::vector<T, xcl::aligned_allocator<T>>;
using SetupGraphImage = PartitionedGraphStorage<AlignedVector<uint64_t>>;

#if SPINE_ALGORITHM_KIND < 0 || SPINE_ALGORITHM_KIND > 3
#error "host_partitioned_algorithms_smoke requires one specialized algorithm"
#endif

static const size_t kStateAlignmentWords = 1024;
static const int kWeightedSssp = 0;
static const int kConnectedComponents = 1;
static const int kResidualPagerank = 2;
static const int kFullPagerank = 3;

static size_t state_span(int num_vertices) {
    return ((size_t)num_vertices + kStateAlignmentWords - 1ULL) /
           kStateAlignmentWords * kStateAlignmentWords;
}

static size_t state_word_count(int num_vertices) {
    return SPINE_ALGORITHM_KIND >= kResidualPagerank
        ? 3ULL * state_span(num_vertices)
        : state_span(num_vertices);
}

struct IterationResult {
    std::chrono::steady_clock::time_point readback_completed;
    std::vector<uint32_t> state;
    std::vector<uint32_t> active_ids;
    std::vector<uint32_t> active_values;
    std::vector<int32_t> result;
    size_t primary_offset = 0;
    size_t auxiliary_offset = 0;
    size_t degree_offset = 0;
};

struct TimingLedger {
    uint64_t iterations = 0;
    uint64_t logical_updates = 0;
    uint64_t physical_updates = 0;
    double maintenance_input_ms = 0.0;
    double maintenance_kernel_ms = 0.0;
    double maintenance_output_ms = 0.0;
    double maintenance_device_e2e_ms = 0.0;
    double maintenance_setup_inclusive_ms = 0.0;
    double input_migration_ms = 0.0;
    double reader_ms = 0.0;
    double compute_ms = 0.0;
    double kernel_span_ms = 0.0;
    double output_migration_ms = 0.0;
    double device_e2e_ms = 0.0;
    double setup_inclusive_ms = 0.0;
    double host_dynamic_preparation_ms = 0.0;
};

static double event_duration_ms(const cl::Event &event) {
    cl_ulong start = event.getProfilingInfo<CL_PROFILING_COMMAND_START>();
    cl_ulong end = event.getProfilingInfo<CL_PROFILING_COMMAND_END>();
    if (end < start) {
        throw std::runtime_error(
            "OpenCL profiling event ended before it started");
    }
    return (double)(end - start) * 1.0e-6;
}

static double event_span_ms(const cl::Event &first, const cl::Event &second) {
    cl_ulong first_start =
        first.getProfilingInfo<CL_PROFILING_COMMAND_START>();
    cl_ulong first_end = first.getProfilingInfo<CL_PROFILING_COMMAND_END>();
    cl_ulong second_start =
        second.getProfilingInfo<CL_PROFILING_COMMAND_START>();
    cl_ulong second_end =
        second.getProfilingInfo<CL_PROFILING_COMMAND_END>();
    cl_ulong start = std::min(first_start, second_start);
    cl_ulong end = std::max(first_end, second_end);
    if (end < start) {
        throw std::runtime_error(
            "OpenCL profiling span ended before it started");
    }
    return (double)(end - start) * 1.0e-6;
}

static double event_span_ms(const std::vector<cl::Event> &events) {
    if (events.empty()) return 0.0;
    cl_ulong start = events.front().getProfilingInfo<
        CL_PROFILING_COMMAND_START>();
    cl_ulong end = events.front().getProfilingInfo<
        CL_PROFILING_COMMAND_END>();
    for (const cl::Event &event : events) {
        start = std::min(
            start,
            event.getProfilingInfo<CL_PROFILING_COMMAND_START>());
        end = std::max(
            end,
            event.getProfilingInfo<CL_PROFILING_COMMAND_END>());
    }
    if (end < start) {
        throw std::runtime_error(
            "OpenCL profiling span ended before it started");
    }
    return (double)(end - start) * 1.0e-6;
}

static uint32_t float_bits(float value) {
    uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static float bits_float(uint32_t bits) {
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

static void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

static bool close_float(float actual, float expected, float tolerance) {
    return std::fabs(actual - expected) <=
           tolerance * std::max(1.0f, std::fabs(expected));
}

static cl::Buffer make_topology_buffer(
    cl::Context &context,
    unsigned bank,
    void *host_ptr,
    size_t bytes
) {
    cl_int err = CL_SUCCESS;
    cl_mem_ext_ptr_t ext = {bank | XCL_MEM_TOPOLOGY, host_ptr, nullptr};
    const cl_mem_flags flags = CL_MEM_READ_WRITE | CL_MEM_EXT_PTR_XILINX |
                               (host_ptr ? CL_MEM_USE_HOST_PTR : 0);
    OCL_CHECK(err, cl::Buffer buffer(
                       context, flags,
                       bytes, &ext, &err));
    return buffer;
}

static std::vector<uint32_t> sorted_unique(std::vector<uint32_t> values) {
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
    return values;
}

struct SliceWorkload {
    std::string case_id;
    int num_vertices = 0;
    std::vector<std::vector<uint32_t>> adjacency;
    std::vector<std::vector<uint16_t>> weights;
};

struct DynamicUpdate {
    uint32_t src = 0;
    uint32_t dst = 0;
    uint16_t weight = 0;
    int16_t diff = 0;
};

#include "host_update_setup_once.hpp"

struct DynamicWorkload {
    SliceWorkload baseline;
    SliceWorkload final_graph;
    std::vector<DynamicUpdate> physical_updates;
    size_t logical_updates = 0;
};

static SliceWorkload make_slice_workload(
    const std::string &case_id,
    int num_vertices,
    const std::map<std::pair<uint32_t, uint32_t>, uint16_t> &edges
) {
    SliceWorkload workload;
    workload.case_id = case_id;
    workload.num_vertices = num_vertices;
    workload.adjacency.resize((size_t)num_vertices);
    workload.weights.resize((size_t)num_vertices);
    for (const auto &entry : edges) {
        workload.adjacency[(size_t)entry.first.first].push_back(
            entry.first.second);
        workload.weights[(size_t)entry.first.first].push_back(entry.second);
    }
    return workload;
}

static DynamicWorkload load_dynamic_workload(const std::string &path) {
    std::ifstream input(path);
    require(input.good(), "cannot open dynamic graph: " + path);

    uint64_t vertices = 0;
    uint64_t initial_count = 0;
    uint64_t update_count = 0;
    require(static_cast<bool>(input >> vertices >> initial_count >> update_count),
            "invalid dynamic graph header: " + path);
    require(vertices > 0 && vertices <= (uint64_t)MAX_N,
            "dynamic graph vertex count is outside compiled MAX_N");

    using EdgeMap =
        std::map<std::pair<uint32_t, uint32_t>, uint16_t>;
    EdgeMap initial_edges;
    EdgeMap live_edges;
    for (uint64_t index = 0; index < initial_count; index++) {
        uint64_t src = 0;
        uint64_t dst = 0;
        uint64_t weight = 0;
        require(static_cast<bool>(input >> src >> dst >> weight),
                "invalid initial edge " + std::to_string(index));
        require(src < vertices && dst < vertices && weight > 0 &&
                    weight <= 0x0fffU,
                "initial edge exceeds the shared G+R weight12/domain ABI");
        auto key = std::make_pair((uint32_t)src, (uint32_t)dst);
        require(initial_edges.emplace(key, (uint16_t)weight).second,
                "duplicate initial endpoint in dynamic graph");
    }
    live_edges = initial_edges;

    DynamicWorkload workload;
    workload.logical_updates = (size_t)update_count;
    workload.physical_updates.reserve((size_t)update_count * 2ULL);
    for (uint64_t index = 0; index < update_count; index++) {
        uint64_t src = 0;
        uint64_t dst = 0;
        uint64_t weight = 0;
        uint64_t type = 0;
        require(static_cast<bool>(input >> src >> dst >> weight >> type),
                "invalid update edge " + std::to_string(index));
        require(src < vertices && dst < vertices && weight > 0 &&
                    weight <= 0x0fffU && type <= 1,
                "update exceeds the shared G+R weight12/domain/type ABI");
        const auto key = std::make_pair((uint32_t)src, (uint32_t)dst);
        auto existing = live_edges.find(key);
        if (type == 0) {
            require(existing != live_edges.end() &&
                        existing->second == (uint16_t)weight,
                    "delete does not match the current weighted edge");
            workload.physical_updates.push_back(
                {(uint32_t)src, (uint32_t)dst, (uint16_t)weight, -1});
            live_edges.erase(existing);
        } else if (existing == live_edges.end()) {
            workload.physical_updates.push_back(
                {(uint32_t)src, (uint32_t)dst, (uint16_t)weight, 1});
            live_edges.emplace(key, (uint16_t)weight);
        } else {
            require(existing->second != (uint16_t)weight,
                    "insert duplicates an existing weighted edge");
            workload.physical_updates.push_back(
                {(uint32_t)src, (uint32_t)dst, existing->second, -1});
            workload.physical_updates.push_back(
                {(uint32_t)src, (uint32_t)dst, (uint16_t)weight, 1});
            existing->second = (uint16_t)weight;
        }
    }
    std::string trailing;
    require(!(input >> trailing),
            "unexpected trailing token in dynamic graph: " + trailing);
    require(workload.physical_updates.size() <=
                (size_t)HOST_PARTITIONED_RATIO2_MAX_SORT_N,
            "physical update batch exceeds compiled MAX_SORT_N");
    std::sort(
        workload.physical_updates.begin(), workload.physical_updates.end(),
        [](const DynamicUpdate &left, const DynamicUpdate &right) {
            return std::tie(left.src, left.dst, left.weight, left.diff) <
                   std::tie(right.src, right.dst, right.weight, right.diff);
        });

    const std::string case_id = path;
    workload.baseline =
        make_slice_workload(case_id + ":baseline", (int)vertices, initial_edges);
    workload.final_graph =
        make_slice_workload(case_id + ":final", (int)vertices, live_edges);
    std::cout << "DYNAMIC_GRAPH_LOAD_PASS case=" << path
              << " vertices=" << vertices
              << " initial_edges=" << initial_edges.size()
              << " logical_updates=" << workload.logical_updates
              << " physical_updates=" << workload.physical_updates.size()
              << " final_edges=" << live_edges.size() << std::endl;
    return workload;
}

static PartitionedCsrReferenceGraph build_logical_reference(
    const SliceWorkload &workload
) {
    std::vector<std::vector<PartitionedCsrEdgeRef>> levels(
        HOST_PARTITIONED_RATIO2_LEVELS);
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        for (size_t edge = 0;
             edge < workload.adjacency[(size_t)src].size(); edge++) {
            levels[0].push_back(
                {src, workload.adjacency[(size_t)src][edge],
                 workload.weights[(size_t)src][edge], 1});
        }
    }
    return build_partitioned_csr_reference(
        levels, workload.num_vertices, HOST_PARTITIONED_CSR_DST_PARTITIONS);
}

static PartitionedHotColdReferenceGraph build_compacted_hot_cold_reference(
    const SliceWorkload &workload,
    int *selected_level
) {
    std::vector<uint64_t> indegree((size_t)workload.num_vertices, 0);
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        for (uint32_t dst : workload.adjacency[(size_t)src]) {
            indegree[(size_t)dst]++;
        }
    }

    uint64_t baseline_family_capacity = 0;
    for (int level = 2; level < HOST_PARTITIONED_RATIO2_LEVELS; level++) {
        baseline_family_capacity +=
            partitioned_ratio2_level_partition_capacity(level);
    }
    PartitionedHotColdClassifierConfig config;
    config.num_vertices = (size_t)workload.num_vertices;
    config.family_edge_cap = baseline_family_capacity;
    config.cold_partition_target = baseline_family_capacity;
    config.hot_shard_edge_cap = baseline_family_capacity;
    PartitionedHotColdClassification classification =
        partitioned_classify_hot_cold_from_indegree(indegree, config);

    std::array<size_t, HOST_PARTITIONED_CSR_FAMILY_COUNT> family_counts{};
    for (uint32_t dst = 0; dst < (uint32_t)workload.num_vertices; dst++) {
        if (indegree[(size_t)dst] == 0) continue;
        const int family = partitioned_dispatch_family_host(
            dst, classification.hot_bitmap_words,
            !classification.empty_hot_set);
        require(family >= 0 && family < HOST_PARTITIONED_CSR_FAMILY_COUNT,
                "baseline classifier produced an invalid family");
        family_counts[(size_t)family] += indegree[(size_t)dst];
    }

    std::array<PartitionedCompactedBaselinePlan,
               HOST_PARTITIONED_CSR_FAMILY_COUNT> plans{};
    int highest_level = 0;
    for (int family = 0; family < HOST_PARTITIONED_CSR_FAMILY_COUNT; family++) {
        plans[(size_t)family] = plan_partitioned_compacted_baseline(
            family_counts[(size_t)family]);
        require(plans[(size_t)family].fits,
                "hot/cold baseline family exceeds aggregate Spine levels");
        highest_level = std::max(
            highest_level, plans[(size_t)family].highest_level);
    }

    std::vector<std::vector<PartitionedCsrEdgeRef>> levels(
        HOST_PARTITIONED_RATIO2_LEVELS);
    std::array<int, HOST_PARTITIONED_CSR_FAMILY_COUNT> current_level{};
    std::array<size_t, HOST_PARTITIONED_CSR_FAMILY_COUNT> used_in_level{};
    current_level.fill(HOST_PARTITIONED_RATIO2_LEVELS - 1);
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        for (size_t edge = 0;
             edge < workload.adjacency[(size_t)src].size(); edge++) {
            const uint32_t dst = workload.adjacency[(size_t)src][edge];
            const int family = partitioned_dispatch_family_host(
                dst, classification.hot_bitmap_words,
                !classification.empty_hot_set);
            int &level = current_level[(size_t)family];
            while (level >= 2 &&
                   used_in_level[(size_t)family] >=
                       plans[(size_t)family].edge_counts[(size_t)level]) {
                level--;
                used_in_level[(size_t)family] = 0;
            }
            require(level >= 2,
                    "hot/cold baseline planner lost an input edge");
            levels[(size_t)level].push_back(
                {src, dst, workload.weights[(size_t)src][edge], 1});
            used_in_level[(size_t)family]++;
        }
    }
    if (selected_level != nullptr) *selected_level = highest_level;
    return build_partitioned_hot_cold_reference(
        levels, classification, workload.num_vertices);
}

static SliceWorkload load_slice_workload(const std::string &path) {
    std::ifstream input(path);
    require(input.good(), "cannot open slice: " + path);

    std::string case_id = path;
    int declared_vertices = -1;
    uint32_t max_vertex = 0;
    bool saw_edge = false;
    std::map<std::pair<uint32_t, uint32_t>, uint16_t> endpoint_weights;
    std::string line;
    size_t line_number = 0;
    while (std::getline(input, line)) {
        line_number++;
        if (line.empty()) continue;
        if (line[0] == '#') {
            const std::string case_prefix = "# case=";
            const std::string vertices_prefix = "# vertices=";
            if (line.compare(0, case_prefix.size(), case_prefix) == 0) {
                case_id = line.substr(case_prefix.size());
            } else if (line.compare(0, vertices_prefix.size(),
                                    vertices_prefix) == 0) {
                declared_vertices = std::stoi(
                    line.substr(vertices_prefix.size()));
            }
            continue;
        }

        std::istringstream row(line);
        uint64_t src = 0;
        uint64_t dst = 0;
        uint64_t weight = 0;
        int64_t diff = 0;
        std::string extra;
        require((row >> src >> dst >> weight >> diff) && !(row >> extra),
                "invalid slice row at " + path + ":" +
                    std::to_string(line_number));
        require(src <= UINT32_MAX && dst <= UINT32_MAX,
                "slice vertex ID exceeds uint32 at line " +
                    std::to_string(line_number));
        require(weight > 0 && weight <= UINT16_MAX,
                "slice weight is outside uint16 at line " +
                    std::to_string(line_number));
        require(diff == 1,
                "baseline slice must contain only live diff=1 edges at line " +
                    std::to_string(line_number));
        max_vertex = std::max(max_vertex,
                              std::max((uint32_t)src, (uint32_t)dst));
        saw_edge = true;

        const std::pair<uint32_t, uint32_t> endpoint = {
            (uint32_t)src, (uint32_t)dst};
        auto existing = endpoint_weights.find(endpoint);
        if (existing == endpoint_weights.end() || weight < existing->second) {
            endpoint_weights[endpoint] = (uint16_t)weight;
        }
    }

    require(declared_vertices > 0 || saw_edge,
            "slice has neither a positive vertex count nor an edge");
    int num_vertices = declared_vertices > 0
        ? declared_vertices
        : (int)((uint64_t)max_vertex + 1ULL);
    require(!saw_edge || max_vertex < (uint32_t)num_vertices,
            "slice edge exceeds its declared vertex domain");
    require(num_vertices <= MAX_N,
            "slice vertex count exceeds compiled MAX_N");

    SliceWorkload workload;
    workload.case_id = case_id;
    workload.num_vertices = num_vertices;
    workload.adjacency.resize((size_t)num_vertices);
    workload.weights.resize((size_t)num_vertices);
    for (const auto &entry : endpoint_weights) {
        uint32_t src = entry.first.first;
        workload.adjacency[(size_t)src].push_back(entry.first.second);
        workload.weights[(size_t)src].push_back(entry.second);
    }
    std::cout << "SLICE_LOAD_PASS case=" << workload.case_id
              << " vertices=" << workload.num_vertices
              << " endpoint_edges=" << endpoint_weights.size()
              << " path=" << path << std::endl;
    return workload;
}

static uint32_t select_default_source(const SliceWorkload &workload) {
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        size_t degree = workload.adjacency[(size_t)src].size();
        if (degree >= 4 && degree <= 16) return src;
    }
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        if (!workload.adjacency[(size_t)src].empty()) return src;
    }
    return 0;
}

class SplitAlgorithmRuntime {
  public:
    template <typename Image>
    SplitAlgorithmRuntime(
        const std::string &xclbin,
        Image &&image,
        int num_vertices,
        bool update_setup_once = false,
        bool defer_graph_residency = false
    ) : num_vertices_(num_vertices),
        state_span_(state_span(num_vertices)) {
        require(num_vertices_ > 0 && num_vertices_ <= MAX_N,
                "algorithm smoke num_vertices is outside MAX_N");
        require(!defer_graph_residency || update_setup_once,
                "only maintenance setup may defer graph residency");
        require(image.graph_words.size() ==
                    (size_t)HOST_PARTITIONED_CSR_DST_PARTITIONS,
                "algorithm smoke graph partition count mismatch");

        devices_ = xcl::get_xil_devices();
        require(!devices_.empty(), "no Xilinx device found");
        if (const char *expected = std::getenv("SPINE_EXPECT_BDF")) {
            char address[128] = {};
            require(clGetDeviceInfo(devices_[0](), CL_DEVICE_PCIE_BDF,
                                    sizeof(address), address, nullptr) ==
                        CL_SUCCESS,
                    "failed to query selected device BDF");
            require(address[sizeof(address) - 1] == '\0' &&
                        std::string(address) == expected,
                    "selected device BDF differs from exclusive board lease");
            std::cout << "SPINE_DEVICE bdf=" << address << std::endl;
        }
        context_ = cl::Context(devices_[0]);
        transfer_q_ = cl::CommandQueue(
            context_, devices_[0], CL_QUEUE_PROFILING_ENABLE);
        compute_q_ = cl::CommandQueue(
            context_, devices_[0],
            CL_QUEUE_PROFILING_ENABLE |
                CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE);

        std::vector<unsigned char> binary = xcl::read_binary_file(xclbin);
        cl::Program::Binaries binaries;
        binaries.push_back({binary.data(), binary.data() + binary.size()});
        std::vector<cl::Device> program_devices = {devices_[0]};
        cl_int program_err = CL_SUCCESS;
        program_ = cl::Program(
            context_, program_devices, binaries, nullptr, &program_err);
        require(program_err == CL_SUCCESS,
                "failed to program split algorithm xclbin: " +
                    std::to_string(program_err));
        reader_ = cl::Kernel(program_, "spine_partconv_rdmaint_kernel");
        if (!update_setup_once) {
            compute_ = cl::Kernel(program_, "spine_partconv_compute_kernel");
        }
        lifecycle_ = cl::Kernel(program_, "spine_vertex_lifecycle_kernel");

        const auto setup_start = std::chrono::steady_clock::now();
        if constexpr (std::is_same_v<Image, SetupGraphImage>) {
            meta_ = std::move(image.meta_words);
        } else {
            meta_.assign(image.meta_words.begin(), image.meta_words.end());
        }
        graph_host_.resize(HOST_PARTITIONED_GRAPH_PORTS);
        graph_buffers_.reserve(HOST_PARTITIONED_GRAPH_PORTS);
        for (int bank = 0; bank < HOST_PARTITIONED_GRAPH_PORTS; bank++) {
            auto &host_words = graph_host_[(size_t)bank];
            if ((size_t)bank < image.graph_words.size() &&
                !image.graph_words[(size_t)bank].empty()) {
                auto &source = image.graph_words[(size_t)bank];
                if constexpr (std::is_same_v<Image, SetupGraphImage>) {
                    host_words = std::move(source);
                } else {
                    host_words.assign(source.begin(), source.end());
                }
            } else {
                host_words.assign(1, 0);
            }
            if (!defer_graph_residency) {
                graph_buffers_.push_back(make_topology_buffer(
                    context_, HBM_PARTITIONED_GRAPH_BASE + (unsigned)bank,
                    host_words.data(), host_words.size() * sizeof(uint64_t)));
            }
        }

        const size_t bitmap_words = ((size_t)num_vertices_ + 127) / 128;
        const size_t family_words = ((size_t)num_vertices_ + 3) / 4;
        AlignedVector<PartitionedHbm16Word> initial_bitmap;
        AlignedVector<PartitionedHbm16Word> initial_directory;
        task_scratch_.assign(defer_graph_residency
                                 ? HOST_PARTITIONED_RATIO2_MAX_SORT_N
                                 : HOST_PARTITIONED_DIRTY_HBM16_WORDS,
                             PartitionedHbm16Word{0, 0});
        if (defer_graph_residency) {
            initial_bitmap.assign(bitmap_words, PartitionedHbm16Word{0, 0});
            initial_directory.assign(family_words, PartitionedHbm16Word{0, 0});
            visit_partitioned_family_rows_host(
                graph_host_, meta_, [&](uint32_t src, uint32_t mask) {
                    require(src < (uint32_t)num_vertices_,
                            "maintenance directory source exceeds vertex domain");
                    auto &word = initial_directory[src / 4U];
                    uint64_t &half = (src & 3U) < 2U ? word.lo : word.hi;
                    half |= (uint64_t)mask << ((src & 1U) * 32U);
                });
        } else if (update_setup_once) {
            populate_partitioned_family_directory_scratch_host(
                graph_host_, meta_, task_scratch_);
        } else {
            std::vector<PartitionedHbm16Word> family_directory;
            build_partitioned_family_directory_from_rows_host(
                graph_host_, meta_, family_directory);
            std::copy(family_directory.begin(), family_directory.end(),
                      task_scratch_.begin() +
                          (ptrdiff_t)HOST_PARTITIONED_FAMILY_DIRECTORY_OFFSET);
        }
        publish_partitioned_family_directory_host(meta_);

        if (!update_setup_once) {
            active_records_.assign((size_t)MAX_N,
                                   PartitionedActiveRecordWord());
            state_.assign(state_word_count(num_vertices_), 0);
            active_out_.assign((size_t)num_vertices_, 0);
            compute_result_.assign(HOST_CONV_RESULT_WORDS, 0);
        }
        if (!defer_graph_residency) {
            owner_.assign(std::max<size_t>(HOST_PARTITIONED_OWNER_HBM_WORDS, 1), 0);
        }
        reader_result_.assign(HOST_MAINT_RESULT_WORDS, 0);
        lifecycle_result_.assign(3, 0);

        void *scratch_host = task_scratch_.data();
        void *owner_host = owner_.data();
        if (defer_graph_residency) {
            maintenance_backing_.push_back(allocate_maintenance_backing(
                HOST_PARTITIONED_DIRTY_HBM16_WORDS * sizeof(PartitionedHbm16Word)));
            scratch_host = maintenance_backing_.back().get();
            maintenance_backing_.push_back(allocate_maintenance_backing(
                HOST_PARTITIONED_OWNER_HBM_WORDS * sizeof(uint64_t)));
            owner_host = maintenance_backing_.back().get();
        }
        d_task_scratch_ = make_topology_buffer(
            context_, HBM_PARTITIONED_SORTER_INPUT,
            scratch_host,
            HOST_PARTITIONED_DIRTY_HBM16_WORDS * sizeof(PartitionedHbm16Word));
        d_active_records_ = make_topology_buffer(
            context_, HBM_PARTITIONED_ACTIVE_BINS,
            update_setup_once ? nullptr : active_records_.data(),
            // MAINT never reads or writes active_bins. Keep its ABI argument
            // valid without allocating the unused 512-MiB propagation spool.
            (update_setup_once ? 1ULL : (size_t)MAX_N) *
                sizeof(PartitionedActiveRecordWord));
        d_meta_ = make_topology_buffer(
            context_, HBM_PARTITIONED_LEVEL_META,
            meta_.data(),
            meta_.size() * sizeof(uint64_t));
        d_reader_result_ = make_topology_buffer(
            context_, HBM_PARTITIONED_SCRATCH, reader_result_.data(),
            reader_result_.size() * sizeof(int32_t));
        if (!update_setup_once) {
            d_state_ = make_topology_buffer(
                context_, HBM_PARTITIONED_VERTEX_STATE, state_.data(),
                state_.size() * sizeof(uint32_t));
            d_active_out_ = make_topology_buffer(
                context_, HBM_PARTITIONED_ACTIVE_LISTS, active_out_.data(),
                active_out_.size() * sizeof(uint64_t));
            d_compute_result_ = make_topology_buffer(
                context_, HBM_PARTITIONED_SCRATCH, compute_result_.data(),
                compute_result_.size() * sizeof(int32_t));
        }
        d_owner_ = make_topology_buffer(
            context_, HBM_PARTITIONED_ACTIVE_BITMAP,
            owner_host,
            std::max<size_t>(HOST_PARTITIONED_OWNER_HBM_WORDS, 1) * sizeof(uint64_t));
        d_lifecycle_result_ = make_topology_buffer(
            context_, HBM_PARTITIONED_SCRATCH, lifecycle_result_.data(),
            lifecycle_result_.size() * sizeof(int32_t));

        std::vector<cl::Memory> initial = {d_lifecycle_result_};
        if (!defer_graph_residency) {
            initial.push_back(d_meta_);
            initial.push_back(d_task_scratch_);
            initial.push_back(d_owner_);
        }
        for (cl::Buffer &buffer : graph_buffers_) initial.push_back(buffer);
        const auto upload_start = std::chrono::steady_clock::now();
        cl_int err = CL_SUCCESS;
        if (defer_graph_residency) {
            // MAINT reads old bitmap/directory words, but list/bucket valid
            // lanes are device-written before use. The vertex domain stays
            // fixed; lifecycle INITIALIZE writes owner state without reading it.
            // The wrapper uploads patched metadata once after graph placement.
            // Lifecycle initialization uses owner state, not graph metadata.
            const std::vector<cl::Memory> scratch = {d_task_scratch_, d_owner_};
            OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
                scratch, CL_MIGRATE_MEM_OBJECT_CONTENT_UNDEFINED));
            for (const auto &region : {
                     std::make_pair(HOST_PARTITIONED_DIRTY_BITMAP_OFFSET,
                                    &initial_bitmap),
                     std::make_pair(HOST_PARTITIONED_FAMILY_DIRECTORY_OFFSET,
                                    &initial_directory)}) {
                OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                    d_task_scratch_, CL_FALSE,
                    region.first * sizeof(PartitionedHbm16Word),
                    region.second->size() * sizeof(PartitionedHbm16Word),
                    region.second->data()));
            }
        }
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(initial, 0));
        // Allocate device-written scratch with the static resident graph.
        // Its host contents are not inputs: the spool and NEXT_ACTIVE prefix
        // are produced by the device before consumption. Avoid an implicit
        // first-use upload of the 512-MiB unused host active-record array.
        std::vector<cl::Memory> output_scratch = {d_active_records_};
        if (!update_setup_once) output_scratch.push_back(d_active_out_);
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
                           output_scratch,
                           CL_MIGRATE_MEM_OBJECT_CONTENT_UNDEFINED));
        OCL_CHECK(err, err = transfer_q_.finish());
        const auto lifecycle_start = std::chrono::steady_clock::now();
        initialize_vertex_domain(!update_setup_once);
        const auto setup_end = std::chrono::steady_clock::now();
        setup_bootstrap_ns_ = elapsed_ns(setup_start, setup_end);
        setup_host_ns_ = elapsed_ns(setup_start, upload_start);
        setup_migrate_ns_ = elapsed_ns(upload_start, lifecycle_start);
        setup_lifecycle_ns_ = elapsed_ns(lifecycle_start, setup_end);
        if (defer_graph_residency) {
            std::cout << "SPINE_MAINT_SPARSE_INIT vertices=" << num_vertices_
                      << " bitmap_words=" << ((size_t)num_vertices_ + 127) / 128
                      << " family_words=" << ((size_t)num_vertices_ + 3) / 4
                      << " owner_host_upload=0 host_bound_scratch=1"
                      << " metadata_uploads=1 compact_host_staging=1"
                      << " uninitialized_host_backing=1" << std::endl;
        }
    }

    int64_t setup_bootstrap_ns() const { return setup_bootstrap_ns_; }

    void print_update_setup_bootstrap() const {
        std::cout << "SPINE_UPDATE_SETUP_BOOTSTRAP host_ns=" << setup_host_ns_
                  << " migrate_ns=" << setup_migrate_ns_
                  << " lifecycle_ns=" << setup_lifecycle_ns_ << std::endl;
    }

    size_t validate_updated_graph(const SetupInsertionBatch &batch) {
        require(maintenance_launched_, "update setup requires a completed update");
        std::vector<cl::Memory> readback = {d_meta_};
        for (const auto &buffer : graph_buffers_) readback.push_back(buffer);
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
                           readback, CL_MIGRATE_MEM_OBJECT_HOST));
        OCL_CHECK(err, err = transfer_q_.finish());
        return check_setup_updated_graph(graph_host_, meta_, batch);
    }

    static int64_t elapsed_ns(std::chrono::steady_clock::time_point start,
                              std::chrono::steady_clock::time_point end) {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    }

    void apply_updates(
        const std::vector<DynamicUpdate> &updates,
        size_t logical_updates
    ) {
        prepare_updates(updates, logical_updates);
        apply_prepared_updates();
    }

    void prepare_updates(
        const std::vector<DynamicUpdate> &updates,
        size_t logical_updates
    ) {
        require(!maintenance_prepared_ && !maintenance_launched_,
                "dynamic maintenance may only be prepared once per runtime");
        require(updates.size() <=
                    (size_t)HOST_PARTITIONED_RATIO2_MAX_SORT_N,
                "dynamic maintenance batch exceeds MAX_SORT_N");
        maintenance_setup_start_ = std::chrono::steady_clock::now();
        maintenance_logical_updates_ = logical_updates;
        maintenance_physical_updates_ = updates.size();

        for (size_t index = 0; index < updates.size(); index++) {
            const DynamicUpdate &update = updates[index];
            task_scratch_[index].lo =
                (uint64_t)(uint16_t)update.diff |
                ((uint64_t)update.weight << 32);
            task_scratch_[index].hi =
                ((uint64_t)update.src << 32) | (uint64_t)update.dst;
        }
        std::fill(reader_result_.begin(), reader_result_.end(), 0);

        cl_int err = CL_SUCCESS;
        auto &input_events = maintenance_input_events_;
        if (!updates.empty()) {
            input_events.emplace_back();
            OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                               d_task_scratch_, CL_FALSE, 0,
                               updates.size() * sizeof(PartitionedHbm16Word),
                               task_scratch_.data(), nullptr,
                               &input_events.back()));
        }
        input_events.emplace_back();
        OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                           d_reader_result_, CL_FALSE, 0,
                           reader_result_.size() * sizeof(int32_t),
                           reader_result_.data(), nullptr,
                           &input_events.back()));
        transfer_q_.finish();
        maintenance_prepared_ = true;
    }

    int64_t apply_prepared_updates() {
        require(maintenance_prepared_ && !maintenance_launched_,
                "dynamic maintenance requires one unconsumed prepared batch");
        maintenance_launched_ = true;
        const auto apply_start = std::chrono::steady_clock::now();
        cl_int err = CL_SUCCESS;

        int arg = 0;
        for (cl::Buffer &buffer : graph_buffers_) {
            reader_.setArg(arg++, buffer);
        }
        reader_.setArg(arg++, d_task_scratch_);
        reader_.setArg(arg++, d_active_records_);
        reader_.setArg(arg++, d_meta_);
        reader_.setArg(arg++, d_reader_result_);
        reader_.setArg(arg++, HOST_PARTITIONED_E2E_MODE_MAINT);
        reader_.setArg(arg++, (int)maintenance_physical_updates_);
        reader_.setArg(arg++, num_vertices_);

        cl::Event maintenance_event;
        const auto arguments_at = std::chrono::steady_clock::now();
        OCL_CHECK(err, err = compute_q_.enqueueTask(
                           reader_, nullptr, &maintenance_event));
        OCL_CHECK(err, err = compute_q_.finish());
        const auto kernel_completed = std::chrono::steady_clock::now();

        cl::Event output_event;
        OCL_CHECK(err, err = transfer_q_.enqueueReadBuffer(
                           d_reader_result_, CL_FALSE, 0,
                           reader_result_.size() * sizeof(int32_t),
                           reader_result_.data(), nullptr, &output_event));
        OCL_CHECK(err, err = transfer_q_.finish());
        const auto setup_end = std::chrono::steady_clock::now();

        require(reader_result_[(size_t)HOST_MAINT_RESULT_OVERFLOW] == 0,
                "dynamic maintenance reported graph overflow");
        require((uint32_t)reader_result_[
                    (size_t)HOST_MAINT_RESULT_META_FORMAT_VERSION_WORD] ==
                    HOST_PARTITIONED_META_FORMAT_VERSION,
                "dynamic maintenance reported a metadata ABI mismatch");
        require((uint32_t)reader_result_[
                    (size_t)HOST_MAINT_RESULT_DISPATCH_STATUS] ==
                    HOST_PARTITIONED_DISPATCH_STATUS_OK,
                "dynamic maintenance family dispatch failed");

        timing_.logical_updates = maintenance_logical_updates_;
        timing_.physical_updates = maintenance_physical_updates_;
        timing_.maintenance_input_ms = event_span_ms(maintenance_input_events_);
        timing_.maintenance_kernel_ms = event_duration_ms(maintenance_event);
        timing_.maintenance_output_ms = event_duration_ms(output_event);
        timing_.maintenance_device_e2e_ms =
            timing_.maintenance_input_ms + timing_.maintenance_kernel_ms +
            timing_.maintenance_output_ms;
        timing_.maintenance_setup_inclusive_ms =
            std::chrono::duration<double, std::milli>(
                setup_end - maintenance_setup_start_).count();
        std::cout << "SPINE_HOST_MAINT_PHASE arguments_ms="
                  << std::chrono::duration<double, std::milli>(
                         arguments_at - apply_start).count()
                  << " kernel_wall_ms="
                  << std::chrono::duration<double, std::milli>(
                         kernel_completed - arguments_at).count()
                  << " readback_wall_ms="
                  << std::chrono::duration<double, std::milli>(
                         setup_end - kernel_completed).count()
                  << std::endl;
        std::cout << "SPINE_DYNAMIC_MAINT_PASS logical_updates="
                  << maintenance_logical_updates_
                  << " physical_updates=" << maintenance_physical_updates_
                  << " target_level="
                  << reader_result_[(size_t)HOST_MAINT_RESULT_TARGET_LEVEL]
                  << " path="
                  << reader_result_[(size_t)HOST_MAINT_RESULT_PATH]
                  << " hot_edges="
                  << reader_result_[(size_t)HOST_MAINT_RESULT_HOT_EDGES]
                  << " cold_edges="
                  << reader_result_[(size_t)HOST_MAINT_RESULT_COLD_EDGES]
                  << std::endl;
        return elapsed_ns(apply_start, kernel_completed);
    }

    void preload_resident_state(const std::vector<uint32_t> &state) {
        require(!state_initialized_, "resident state may only be preloaded once");
        require(state.size() == state_.size(),
                "resident state buffer has the wrong specialized layout");
        std::copy(state.begin(), state.end(), state_.begin());
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                           d_state_, CL_TRUE, 0,
                           state_.size() * sizeof(uint32_t), state_.data()));
        state_initialized_ = true;
    }

    void install_host_prepared_state(
        const std::vector<uint32_t> &state,
        double host_compute_ms
    ) {
        require(state_initialized_,
                "host-prepared state requires a resident baseline");
        require(state.size() == state_.size(),
                "host-prepared state buffer has the wrong specialized layout");
        const auto transfer_start = std::chrono::steady_clock::now();
        std::copy(state.begin(), state.end(), state_.begin());
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                           d_state_, CL_TRUE, 0,
                           state_.size() * sizeof(uint32_t), state_.data()));
        const auto transfer_end = std::chrono::steady_clock::now();
        timing_.host_dynamic_preparation_ms += host_compute_ms +
            std::chrono::duration<double, std::milli>(
                transfer_end - transfer_start).count();
    }

    IterationResult read_resident_state() {
        require(state_initialized_, "resident state has not been initialized");
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = transfer_q_.enqueueReadBuffer(
                           d_state_, CL_TRUE, 0,
                           state_.size() * sizeof(uint32_t), state_.data()));
        IterationResult output;
        output.readback_completed = std::chrono::steady_clock::now();
        output.state.assign(state_.begin(), state_.end());
        return output;
    }

    IterationResult run(
        int algorithm,
        uint32_t damping_bits,
        uint32_t epsilon_bits,
        const std::vector<uint32_t> &active_sources,
        const PartitionedActiveBinFlat &frontier,
        const std::vector<uint32_t> &state,
        bool consume_maintenance_frontier = false
    ) {
        const auto setup_start = std::chrono::steady_clock::now();
        require(algorithm == SPINE_ALGORITHM_KIND,
                "host binary and xclbin algorithm kinds differ");
        require(state.size() == state_.size(),
                "algorithm state buffer has the wrong specialized layout");
        require(frontier.records.size() <= active_records_.size(),
                "algorithm active record capacity exceeded");

        // Readers consume a counted prefix; the device-generated path does
        // not consume host records at all. Never clear unused capacity.
        std::copy(frontier.records.begin(), frontier.records.end(),
                  active_records_.begin());
        bool upload_state = !state_initialized_;
        if (upload_state) {
            std::copy(state.begin(), state.end(), state_.begin());
            state_initialized_ = true;
        } else {
            require(std::equal(state.begin(), state.end(), state_.begin()),
                    "host state diverged from the device-resident state");
        }
        // Compute overwrites every element below NEXT_ACTIVE. The tail is
        // neither decoded nor used as a termination sentinel.
        std::fill(reader_result_.begin(), reader_result_.end(), 0);
        std::fill(compute_result_.begin(), compute_result_.end(), 0);
        // Only the explicitly uploaded fields below change on the host.
        // Restoring all metadata also copies the 44-MiB occupied-page lists,
        // which remain resident and are maintained by the device.
        for (int partition = 0;
             partition < HOST_PARTITIONED_CSR_DST_PARTITIONS; partition++) {
            meta_[(size_t)HOST_PARTITIONED_META_ACTIVE_BIN_OFFSET_BASE +
                  (size_t)partition] = frontier.offsets[(size_t)partition];
            meta_[(size_t)HOST_PARTITIONED_META_ACTIVE_BIN_COUNT_BASE +
                  (size_t)partition] = frontier.counts[(size_t)partition];
        }
        if (SPINE_ALGORITHM_KIND != kFullPagerank &&
            !consume_maintenance_frontier) {
            publish_device_sources(active_sources);
        }
        const auto prepared_at = std::chrono::steady_clock::now();

        cl_int err = CL_SUCCESS;
        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=input_migration_begin" << std::endl;
        std::vector<cl::Event> input_events;
        auto enqueue_write = [&](cl::Buffer &buffer, size_t offset,
                                 size_t bytes, const void *source) {
            if (bytes == 0) return;
            input_events.emplace_back();
            OCL_CHECK(err, err = transfer_q_.enqueueWriteBuffer(
                               buffer, CL_FALSE, offset, bytes, source,
                               nullptr, &input_events.back()));
        };

        if (SPINE_ALGORITHM_KIND != kFullPagerank &&
            !consume_maintenance_frontier) {
            size_t bitmap_words =
                ((size_t)num_vertices_ + 127ULL) / 128ULL;
            enqueue_write(
                d_task_scratch_,
                HOST_PARTITIONED_DIRTY_BITMAP_OFFSET *
                    sizeof(PartitionedHbm16Word),
                bitmap_words * sizeof(PartitionedHbm16Word),
                task_scratch_.data() + HOST_PARTITIONED_DIRTY_BITMAP_OFFSET);
            size_t list_words = (active_sources.size() + 3ULL) / 4ULL;
            enqueue_write(
                d_task_scratch_,
                HOST_PARTITIONED_DIRTY_LIST_OFFSET *
                    sizeof(PartitionedHbm16Word),
                list_words * sizeof(PartitionedHbm16Word),
                task_scratch_.data() + HOST_PARTITIONED_DIRTY_LIST_OFFSET);
        }
        enqueue_write(
            d_meta_,
            (size_t)HOST_PARTITIONED_META_ACTIVE_BIN_OFFSET_BASE *
                sizeof(uint64_t),
            2ULL * HOST_PARTITIONED_CSR_DST_PARTITIONS * sizeof(uint64_t),
            meta_.data() + HOST_PARTITIONED_META_ACTIVE_BIN_OFFSET_BASE);
        if (!consume_maintenance_frontier) {
            enqueue_write(
                d_meta_,
                (size_t)HOST_PARTITIONED_META_DIRTY_BASE * sizeof(uint64_t),
                (size_t)HOST_PARTITIONED_META_DIRTY_WORDS * sizeof(uint64_t),
                meta_.data() + HOST_PARTITIONED_META_DIRTY_BASE);
        }
        enqueue_write(
            d_reader_result_, 0,
            reader_result_.size() * sizeof(int32_t), reader_result_.data());
        enqueue_write(
            d_compute_result_, 0,
            compute_result_.size() * sizeof(int32_t), compute_result_.data());
        if (upload_state) {
            enqueue_write(
                d_state_, 0, state_.size() * sizeof(uint32_t), state_.data());
        }
        transfer_q_.finish();
        const auto uploaded_at = std::chrono::steady_clock::now();
        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=input_migration_end" << std::endl;

        int reader_arg = 0;
        for (cl::Buffer &buffer : graph_buffers_) {
            reader_.setArg(reader_arg++, buffer);
        }
        reader_.setArg(reader_arg++, d_task_scratch_);
        reader_.setArg(reader_arg++, d_active_records_);
        reader_.setArg(reader_arg++, d_meta_);
        reader_.setArg(reader_arg++, d_reader_result_);
        reader_.setArg(reader_arg++,
                       SPINE_ALGORITHM_KIND == kFullPagerank
                           ? HOST_PARTITIONED_E2E_MODE_FULL_DOMAIN
                           : HOST_PARTITIONED_E2E_MODE_DEVICE_DIRTY);
        reader_.setArg(reader_arg++, 0);
        reader_.setArg(reader_arg++, num_vertices_);

        int compute_arg = 0;
        compute_.setArg(compute_arg++, d_state_);
        compute_.setArg(compute_arg++, d_active_out_);
        compute_.setArg(compute_arg++, d_owner_);
        compute_.setArg(compute_arg++, d_compute_result_);
        compute_.setArg(compute_arg++, num_vertices_);
#if SPINE_ALGORITHM_KIND == 2 || SPINE_ALGORITHM_KIND == 3
        compute_.setArg(compute_arg++, full_pr_read_bank_one_ ? 1 : 0);
        compute_.setArg(compute_arg++, damping_bits);
        compute_.setArg(compute_arg++, epsilon_bits);
        compute_.setArg(compute_arg++, 0);
#else
        (void)damping_bits;
        (void)epsilon_bits;
#endif

        cl::Event compute_event;
        cl::Event reader_event;
        const auto arguments_at = std::chrono::steady_clock::now();
        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=kernel_pair_begin" << std::endl;
        OCL_CHECK(err, err = compute_q_.enqueueTask(
                           compute_, nullptr, &compute_event));
        OCL_CHECK(err, err = compute_q_.enqueueTask(
                           reader_, nullptr, &reader_event));
        compute_q_.finish();
        const auto kernels_at = std::chrono::steady_clock::now();
        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=kernel_pair_end" << std::endl;

        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=output_migration_begin" << std::endl;
        cl::Event output_event;
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
                           {d_state_, d_active_out_, d_reader_result_,
                            d_compute_result_},
                           CL_MIGRATE_MEM_OBJECT_HOST, nullptr,
                           &output_event));
        transfer_q_.finish();
        const auto readback_completed = std::chrono::steady_clock::now();
        std::cout << "KERNEL_PAIR_PHASE algorithm=" << algorithm
                  << " phase=output_migration_end" << std::endl;

        const auto setup_end = std::chrono::steady_clock::now();
        const double input_ms = event_span_ms(input_events);
        const double reader_ms = event_duration_ms(reader_event);
        const double compute_ms = event_duration_ms(compute_event);
        const double kernel_span_ms = event_span_ms(reader_event, compute_event);
        const double output_ms = event_duration_ms(output_event);
        const double setup_ms =
            std::chrono::duration<double, std::milli>(
                setup_end - setup_start).count();
        timing_.iterations++;
        std::cout << "SPINE_HW_ROUND_TIMING round=" << timing_.iterations
                  << " reader_ms=" << reader_ms
                  << " compute_ms=" << compute_ms
                  << " kernel_span_ms=" << kernel_span_ms << std::endl;
        timing_.input_migration_ms += input_ms;
        timing_.reader_ms += reader_ms;
        timing_.compute_ms += compute_ms;
        timing_.kernel_span_ms += kernel_span_ms;
        timing_.output_migration_ms += output_ms;
        timing_.device_e2e_ms += input_ms + kernel_span_ms + output_ms;
        timing_.setup_inclusive_ms += setup_ms;

        IterationResult output;
        output.readback_completed = readback_completed;
        output.state.assign(state_.begin(), state_.end());
        output.result.assign(compute_result_.begin(), compute_result_.end());
#if SPINE_ALGORITHM_KIND == 3
        output.primary_offset = full_pr_read_bank_one_ ? 0 : state_span_;
        output.degree_offset = 2ULL * state_span_;
        full_pr_read_bank_one_ = !full_pr_read_bank_one_;
#elif SPINE_ALGORITHM_KIND == 2
        output.auxiliary_offset = state_span_;
        output.degree_offset = 2ULL * state_span_;
#endif
        require(output.result[(size_t)HOST_CONV_RESULT_ALGORITHM_KIND] ==
                    SPINE_ALGORITHM_KIND,
                "kernel result reports the wrong specialized algorithm");
        int next_active = output.result[(size_t)HOST_CONV_RESULT_NEXT_ACTIVE];
        require(next_active >= 0 && next_active <= num_vertices_,
                "kernel returned invalid next-active count");
        output.active_ids.reserve((size_t)next_active);
        output.active_values.reserve((size_t)next_active);
        for (int i = 0; i < next_active; i++) {
            output.active_ids.push_back(
                (uint32_t)(active_out_[(size_t)i] >> 32));
            require(output.active_ids.back() < (uint32_t)num_vertices_,
                    "kernel returned an out-of-domain active id");
            output.active_values.push_back(
                (uint32_t)active_out_[(size_t)i]);
        }
        require(sorted_unique(output.active_ids).size() ==
                    output.active_ids.size(),
                "kernel returned duplicate active ids");
        const auto decoded_at = std::chrono::steady_clock::now();
        auto phase_ms = [](auto end, auto begin) {
            return std::chrono::duration<double, std::milli>(end - begin).count();
        };
        std::cout << "SPINE_HOST_PHASE algorithm=" << algorithm
                  << " prepare_ms=" << phase_ms(prepared_at, setup_start)
                  << " upload_wall_ms=" << phase_ms(uploaded_at, prepared_at)
                  << " arguments_ms=" << phase_ms(arguments_at, uploaded_at)
                  << " kernel_wall_ms=" << phase_ms(kernels_at, arguments_at)
                  << " readback_wall_ms=" << phase_ms(readback_completed, kernels_at)
                  << " decode_ms=" << phase_ms(decoded_at, readback_completed)
                  << " active_record_capacity=" << active_records_.size()
                  << " active_records_used=" << frontier.records.size()
                  << std::endl;
        return output;
    }

    void print_timing_summary() const {
        const char *algorithm = "weighted_sssp";
        if (SPINE_ALGORITHM_KIND == kConnectedComponents) {
            algorithm = "connected_components";
        } else if (SPINE_ALGORITHM_KIND == kResidualPagerank) {
            algorithm = "thresholded_residual_pagerank";
        } else if (SPINE_ALGORITHM_KIND == kFullPagerank) {
            algorithm = "full_pagerank";
        }
        std::cout << "SPINE_HW_TIMING algorithm=" << algorithm
                  << " logical_updates=" << timing_.logical_updates
                  << " physical_updates=" << timing_.physical_updates
                  << " maintenance_input_ms="
                  << timing_.maintenance_input_ms
                  << " maintenance_kernel_ms="
                  << timing_.maintenance_kernel_ms
                  << " maintenance_output_ms="
                  << timing_.maintenance_output_ms
                  << " maintenance_device_e2e_ms="
                  << timing_.maintenance_device_e2e_ms
                  << " maintenance_setup_inclusive_ms="
                  << timing_.maintenance_setup_inclusive_ms
                  << " iterations=" << timing_.iterations
                  << " input_migration_ms=" << timing_.input_migration_ms
                  << " reader_ms=" << timing_.reader_ms
                  << " compute_ms=" << timing_.compute_ms
                  << " kernel_span_ms=" << timing_.kernel_span_ms
                  << " output_migration_ms=" << timing_.output_migration_ms
                  << " device_e2e_ms=" << timing_.device_e2e_ms
                  << " setup_inclusive_ms=" << timing_.setup_inclusive_ms
                  << " host_dynamic_preparation_ms="
                  << timing_.host_dynamic_preparation_ms
                  << " dynamic_device_e2e_ms="
                  << timing_.maintenance_device_e2e_ms +
                         timing_.device_e2e_ms
                  << " dynamic_kernel_ms="
                  << timing_.maintenance_kernel_ms + timing_.kernel_span_ms
                  << " dynamic_setup_inclusive_ms="
                  << timing_.maintenance_setup_inclusive_ms +
                         timing_.setup_inclusive_ms +
                         timing_.host_dynamic_preparation_ms
                  << " timing_scope=maintenance_plus_iterative_algorithm_excludes_static_graph_setup"
                  << std::endl;
    }

  private:
    void publish_device_sources(const std::vector<uint32_t> &sources) {
        std::vector<uint32_t> unique = sorted_unique(sources);
        require(unique.size() == sources.size(),
                "device source frontier contains duplicate vertices");

        for (uint32_t src : previous_device_sources_) {
            size_t address = HOST_PARTITIONED_DIRTY_BITMAP_OFFSET + (src >> 7);
            unsigned bit = src & 127U;
            if (bit < 64) {
                task_scratch_[address].lo &= ~(1ULL << bit);
            } else {
                task_scratch_[address].hi &= ~(1ULL << (bit - 64U));
            }
        }

        size_t list_words = (unique.size() + 3ULL) / 4ULL;
        std::fill(task_scratch_.begin() +
                      (ptrdiff_t)HOST_PARTITIONED_DIRTY_LIST_OFFSET,
                  task_scratch_.begin() +
                      (ptrdiff_t)(HOST_PARTITIONED_DIRTY_LIST_OFFSET +
                                  list_words),
                  PartitionedHbm16Word{0, 0});

        uint64_t hash_sum = 0;
        uint64_t hash_xor = 0;
        for (size_t index = 0; index < unique.size(); index++) {
            uint32_t src = unique[index];
            require(src < (uint32_t)num_vertices_ && src < (uint32_t)MAX_N,
                    "device source exceeds the live vertex domain");

            size_t bitmap_address =
                HOST_PARTITIONED_DIRTY_BITMAP_OFFSET + (src >> 7);
            unsigned bitmap_bit = src & 127U;
            if (bitmap_bit < 64) {
                task_scratch_[bitmap_address].lo |= 1ULL << bitmap_bit;
            } else {
                task_scratch_[bitmap_address].hi |=
                    1ULL << (bitmap_bit - 64U);
            }

            PartitionedHbm16Word &list_word = task_scratch_[
                HOST_PARTITIONED_DIRTY_LIST_OFFSET + (index >> 2)];
            unsigned lane = (unsigned)(index & 3ULL);
            uint64_t &half = lane < 2 ? list_word.lo : list_word.hi;
            unsigned shift = (lane & 1U) * 32U;
            half = (half & ~(0xffffffffULL << shift)) |
                   ((uint64_t)src << shift);
            hash_sum += partitioned_dirty_hash_sum_term_host(src);
            hash_xor ^= partitioned_dirty_hash_xor_term_host(src);
        }

        device_source_generation_++;
        if (device_source_generation_ == 0) device_source_generation_ = 1;
        meta_[(size_t)HOST_PARTITIONED_META_DIRTY_COUNT_WORD] = unique.size();
        meta_[(size_t)HOST_PARTITIONED_META_DIRTY_GENERATION_WORD] =
            device_source_generation_;
        meta_[(size_t)HOST_PARTITIONED_META_DIRTY_HASH_SUM_WORD] = hash_sum;
        meta_[(size_t)HOST_PARTITIONED_META_DIRTY_HASH_XOR_WORD] = hash_xor;
        previous_device_sources_ = std::move(unique);
    }

    void initialize_vertex_domain(bool probe_transitions) {
        run_vertex_lifecycle(
            HOST_PARTITIONED_VERTEX_LIFECYCLE_INITIALIZE, 0, true);
        require(lifecycle_result_[
                    HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS] ==
                    (int32_t)HOST_PARTITIONED_VERTEX_LIFECYCLE_STATUS_OK,
                "vertex-lifecycle initialization failed with status " +
                    std::to_string(lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS]));

        if (!probe_transitions) return;

        // Exercise both successful lifecycle transitions at a drained boundary.
        int probe_vertex = num_vertices_ - 1;
        run_vertex_lifecycle(
            HOST_PARTITIONED_VERTEX_LIFECYCLE_DEACTIVATE, probe_vertex, true);
        require(lifecycle_result_[
                    HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS] ==
                    (int32_t)HOST_PARTITIONED_VERTEX_LIFECYCLE_STATUS_OK &&
                    lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_VALID] == 0,
                "vertex-lifecycle deactivate self-test failed: status=" +
                    std::to_string(lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS]) +
                    " valid=" + std::to_string(lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_VALID]));
        run_vertex_lifecycle(
            HOST_PARTITIONED_VERTEX_LIFECYCLE_ACTIVATE, probe_vertex, true);
        require(lifecycle_result_[
                    HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS] ==
                    (int32_t)HOST_PARTITIONED_VERTEX_LIFECYCLE_STATUS_OK &&
                    lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_VALID] == 1,
                "vertex-lifecycle activate self-test failed: status=" +
                    std::to_string(lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_STATUS]) +
                    " valid=" + std::to_string(lifecycle_result_[
                        HOST_PARTITIONED_VERTEX_LIFECYCLE_RESULT_VALID]));
        std::cout << "VERTEX_LIFECYCLE_HW_PASS vertex=" << probe_vertex
                  << " transitions=deactivate,activate" << std::endl;
    }

    void run_vertex_lifecycle(
        unsigned operation,
        int vertex,
        bool incident_edges_retired
    ) {
        int arg = 0;
        lifecycle_.setArg(arg++, d_owner_);
        lifecycle_.setArg(arg++, d_lifecycle_result_);
        lifecycle_.setArg(arg++, num_vertices_);
        lifecycle_.setArg(arg++, num_vertices_);
        lifecycle_.setArg(arg++, vertex);
        lifecycle_.setArg(arg++, (int)operation);
        lifecycle_.setArg(arg++, incident_edges_retired ? 1 : 0);
        cl_int err = CL_SUCCESS;
        OCL_CHECK(err, err = compute_q_.enqueueTask(lifecycle_));
        compute_q_.finish();
        OCL_CHECK(err, err = transfer_q_.enqueueMigrateMemObjects(
                           {d_lifecycle_result_},
                           CL_MIGRATE_MEM_OBJECT_HOST));
        transfer_q_.finish();
    }

    int num_vertices_;
    size_t state_span_;
    bool full_pr_read_bank_one_ = false;
    bool state_initialized_ = false;
    bool maintenance_launched_ = false;
    bool maintenance_prepared_ = false;
    size_t maintenance_logical_updates_ = 0;
    size_t maintenance_physical_updates_ = 0;
    std::chrono::steady_clock::time_point maintenance_setup_start_;
    int64_t setup_bootstrap_ns_ = 0;
    int64_t setup_host_ns_ = 0;
    int64_t setup_migrate_ns_ = 0;
    int64_t setup_lifecycle_ns_ = 0;
    std::vector<cl::Event> maintenance_input_events_;
    uint32_t device_source_generation_ = 0;
    std::vector<uint32_t> previous_device_sources_;
    std::vector<cl::Device> devices_;
    cl::Context context_;
    cl::CommandQueue transfer_q_;
    cl::CommandQueue compute_q_;
    cl::Program program_;
    cl::Kernel reader_;
    cl::Kernel compute_;
    cl::Kernel lifecycle_;
    std::vector<AlignedVector<uint64_t>> graph_host_;
    std::vector<MaintenanceHostBacking> maintenance_backing_;
    std::vector<cl::Buffer> graph_buffers_;
    AlignedVector<PartitionedHbm16Word> task_scratch_;
    AlignedVector<PartitionedActiveRecordWord> active_records_;
    AlignedVector<uint32_t> state_;
    AlignedVector<uint64_t> active_out_;
    AlignedVector<uint64_t> owner_;
    AlignedVector<uint64_t> meta_;
    AlignedVector<int32_t> reader_result_;
    AlignedVector<int32_t> compute_result_;
    AlignedVector<int32_t> lifecycle_result_;
    cl::Buffer d_task_scratch_;
    cl::Buffer d_state_;
    cl::Buffer d_active_records_;
    cl::Buffer d_active_out_;
    cl::Buffer d_meta_;
    cl::Buffer d_reader_result_;
    cl::Buffer d_compute_result_;
    cl::Buffer d_owner_;
    cl::Buffer d_lifecycle_result_;
    TimingLedger timing_;
};

static PartitionedActiveBinFlat make_frontier(
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<uint32_t> &active,
    const std::vector<uint32_t> &state,
    const std::vector<float> &inverse_degree,
    int num_vertices
) {
    std::vector<uint32_t> primary(
        state.begin(), state.begin() + num_vertices);
    PartitionedActiveBins bins =
        partitioned_active_source_binning_reference(graph, active, primary);
    (void)inverse_degree;
    return flatten_partitioned_active_bins(bins);
}

static uint64_t active_edge_count(
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<uint32_t> &active
) {
    uint64_t count = 0;
    for (uint32_t src : active) count += adjacency[(size_t)src].size();
    return count;
}

static std::vector<uint32_t> dynamic_update_sources(
    const std::vector<DynamicUpdate> &updates
) {
    std::vector<uint32_t> sources;
    sources.reserve(updates.size());
    for (const DynamicUpdate &update : updates) sources.push_back(update.src);
    return sorted_unique(std::move(sources));
}

static std::vector<uint32_t> weighted_sssp_distances(
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<std::vector<uint16_t>> &weights,
    int num_vertices,
    uint32_t source
) {
    const uint32_t infinity = 0xffffffffU;
    using QueueEntry = std::pair<uint32_t, uint32_t>;
    std::priority_queue<QueueEntry, std::vector<QueueEntry>,
                        std::greater<QueueEntry>> queue;
    std::vector<uint32_t> distance((size_t)num_vertices, infinity);
    distance[(size_t)source] = 0;
    queue.push({0, source});
    while (!queue.empty()) {
        QueueEntry current = queue.top();
        queue.pop();
        uint32_t src = current.second;
        if (current.first != distance[(size_t)src]) continue;
        for (size_t edge = 0;
             edge < adjacency[(size_t)src].size(); edge++) {
            uint32_t dst = adjacency[(size_t)src][edge];
            uint64_t candidate = (uint64_t)current.first +
                                 weights[(size_t)src][edge];
            uint32_t next = candidate >= infinity
                ? infinity
                : (uint32_t)candidate;
            if (next < distance[(size_t)dst]) {
                distance[(size_t)dst] = next;
                queue.push({next, dst});
            }
        }
    }
    return distance;
}

static std::vector<uint32_t> connected_component_labels(
    const SliceWorkload &workload
) {
    std::vector<uint32_t> parent((size_t)workload.num_vertices);
    std::iota(parent.begin(), parent.end(), 0);
    auto find_root = [&](uint32_t vertex) {
        uint32_t root = vertex;
        while (parent[(size_t)root] != root) root = parent[(size_t)root];
        while (parent[(size_t)vertex] != vertex) {
            uint32_t next = parent[(size_t)vertex];
            parent[(size_t)vertex] = root;
            vertex = next;
        }
        return root;
    };
    for (uint32_t src = 0; src < (uint32_t)workload.num_vertices; src++) {
        for (uint32_t dst : workload.adjacency[(size_t)src]) {
            uint32_t left = find_root(src);
            uint32_t right = find_root(dst);
            if (left == right) continue;
            if (left < right) parent[(size_t)right] = left;
            else parent[(size_t)left] = right;
        }
    }
    std::vector<uint32_t> labels((size_t)workload.num_vertices);
    for (uint32_t vertex = 0; vertex < (uint32_t)workload.num_vertices;
         vertex++) {
        labels[(size_t)vertex] = find_root(vertex);
    }
    return labels;
}

static std::vector<float> full_pagerank_rank(
    const SliceWorkload &workload,
    unsigned rounds,
    float damping
) {
    const int vertices = workload.num_vertices;
    std::vector<float> rank((size_t)vertices, 1.0f / (float)vertices);
    const float base = (1.0f - damping) / (float)vertices;
    for (unsigned round = 0; round < rounds; round++) {
        float dangling = 0.0f;
        for (int src = 0; src < vertices; src++) {
            if (workload.adjacency[(size_t)src].empty()) {
                dangling += rank[(size_t)src];
            }
        }
        std::vector<float> next(
            (size_t)vertices, base + damping * dangling / (float)vertices);
        for (int src = 0; src < vertices; src++) {
            size_t degree = workload.adjacency[(size_t)src].size();
            if (degree == 0) continue;
            float contribution = damping * rank[(size_t)src] / (float)degree;
            for (uint32_t dst : workload.adjacency[(size_t)src]) {
                next[(size_t)dst] += contribution;
            }
        }
        rank.swap(next);
    }
    return rank;
}

static std::vector<float> pagerank_correction_residual(
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<float> &warm_rank,
    float damping
) {
    const int vertices = (int)adjacency.size();
    const float base = (1.0f - damping) / (float)vertices;
    float dangling = 0.0f;
    for (int src = 0; src < vertices; src++) {
        if (adjacency[(size_t)src].empty()) {
            dangling += warm_rank[(size_t)src];
        }
    }
    std::vector<float> target(
        (size_t)vertices, base + damping * dangling / (float)vertices);
    for (int src = 0; src < vertices; src++) {
        size_t degree = adjacency[(size_t)src].size();
        if (degree == 0) continue;
        float contribution = damping * warm_rank[(size_t)src] / (float)degree;
        for (uint32_t dst : adjacency[(size_t)src]) {
            target[(size_t)dst] += contribution;
        }
    }
    for (int vertex = 0; vertex < vertices; vertex++) {
        target[(size_t)vertex] -= warm_rank[(size_t)vertex];
    }
    return target;
}

static void print_csv_slice(
    const std::vector<uint32_t> &values,
    size_t offset,
    size_t count
) {
    if (count == 0) {
        std::cout << '-';
        return;
    }
    for (size_t index = 0; index < count; index++) {
        if (index != 0) std::cout << ',';
        std::cout << values[offset + index];
    }
}

static void print_workload_result(
    const std::string &trace_id,
    const std::string &algorithm,
    const std::vector<uint32_t> &state,
    const std::vector<uint32_t> &active,
    int num_vertices,
    uint64_t processed_edges
) {
    if (trace_id.empty()) return;
    std::cout << "SPINE_WORKLOAD_RESULT trace_id=" << trace_id
              << " algorithm=" << algorithm << " primary_u32=";
    print_csv_slice(state, 0, (size_t)num_vertices);
    std::cout << " auxiliary_u32=";
    size_t auxiliary_offset = state.size() >= 2ULL * state_span(num_vertices)
        ? state_span(num_vertices)
        : 0;
    print_csv_slice(state, auxiliary_offset, (size_t)num_vertices);
    std::cout << " active_vertices=";
    print_csv_slice(active, 0, active.size());
    std::cout << " processed_edges=" << processed_edges
              << " overflow=0 task_error=0" << std::endl;
}

static void validate_common(
    const std::string &algorithm,
    int iteration,
    const IterationResult &actual,
    uint64_t expected_edges
) {
    std::cout << "KERNEL_PAIR_RESULT algorithm=" << algorithm
              << " iteration=" << iteration
              << " overflow="
              << actual.result[(size_t)HOST_CONV_RESULT_OVERFLOW]
              << " task_error="
              << actual.result[(size_t)HOST_CONV_RESULT_TASK_ERROR]
              << " task_path="
              << actual.result[(size_t)HOST_CONV_RESULT_TASK_PATH]
              << " fallback_reason="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_TASK_FALLBACK_REASON]
              << " task_count="
              << actual.result[(size_t)HOST_CONV_RESULT_TASK_COUNT]
              << " processed_edges="
              << actual.result[(size_t)HOST_CONV_RESULT_PROCESSED_EDGES]
              << " source_status="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_SOURCE_PROTOCOL_STATUS]
              << " source_requests="
              << actual.result[(size_t)HOST_CONV_RESULT_SOURCE_REQUESTS]
              << " dirty_count="
              << actual.result[(size_t)HOST_CONV_RESULT_DIRTY_COUNT]
              << " owner_status="
              << actual.result[(size_t)HOST_CONV_RESULT_OWNER_STATUS]
              << " owner_credits="
              << actual.result[(size_t)HOST_CONV_RESULT_OWNER_CREDITS]
              << " owner_created="
              << actual.result[(size_t)HOST_CONV_RESULT_OWNER_CREATED]
              << " owner_retired="
              << actual.result[(size_t)HOST_CONV_RESULT_OWNER_RETIRED]
              << " owner_reactivations="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_OWNER_REACTIVATIONS]
              << " owner_queued="
              << actual.result[(size_t)HOST_CONV_RESULT_OWNER_QUEUED]
              << " owner_fifo_backpressure="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_OWNER_FIFO_BACKPRESSURE]
              << " reactivation_fifo_backpressure="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_REACTIVATION_FIFO_BACKPRESSURE]
              << " owner_fifo_max_occupancy="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_OWNER_FIFO_MAX_OCCUPANCY]
              << " reactivation_fifo_max_occupancy="
              << actual.result[
                     (size_t)HOST_CONV_RESULT_REACTIVATION_FIFO_MAX_OCCUPANCY]
              << std::endl;
    require(actual.result[(size_t)HOST_CONV_RESULT_OVERFLOW] == 0,
            algorithm + " iteration " + std::to_string(iteration) +
                " overflowed");
    require(actual.result[(size_t)HOST_CONV_RESULT_TASK_ERROR] == 0,
            algorithm + " iteration " + std::to_string(iteration) +
                " reported task error " +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_ERROR]));
    require(actual.result[(size_t)HOST_CONV_RESULT_OWNER_STATUS] == 0,
            algorithm + " iteration " + std::to_string(iteration) +
                " reported owner error " +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_OWNER_STATUS]));
    require(actual.result[(size_t)HOST_CONV_RESULT_OWNER_DISPATCHED] ==
                actual.result[(size_t)HOST_CONV_RESULT_OWNER_COMPLETED],
            algorithm + " iteration " + std::to_string(iteration) +
                " did not complete every dispatched source");
    require(actual.result[
                (size_t)HOST_CONV_RESULT_OWNER_FIFO_MAX_OCCUPANCY] <=
                SPINE_ALIGNMENT_OWNER_FIFO_DEPTH &&
                actual.result[
                    (size_t)HOST_CONV_RESULT_REACTIVATION_FIFO_MAX_OCCUPANCY] <=
                    SPINE_ALIGNMENT_REACTIVATION_FIFO_DEPTH,
            algorithm + " iteration " + std::to_string(iteration) +
                " exceeded a bounded owner FIFO");
    uint64_t processed_edges = (uint64_t)(uint32_t)actual.result[
        (size_t)HOST_CONV_RESULT_PROCESSED_EDGES];
    require(processed_edges == expected_edges,
            algorithm + " iteration " + std::to_string(iteration) +
                " processed-edge mismatch: expected=" +
                std::to_string(expected_edges) + " actual=" +
                std::to_string(processed_edges) + " task_path=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_PATH]) + " task_count=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_COUNT]) +
                " active_records=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_ACTIVE_RECORDS]) +
                " row_lookups=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_ROW_LOOKUPS]) +
                " family_probes=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_FAMILY_PROBES]) +
                " family_skips=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_FAMILY_SKIPS]) +
                " fallback_reason=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TASK_FALLBACK_REASON]) +
                " touched_tiles=" +
                std::to_string(actual.result[
                    (size_t)HOST_CONV_RESULT_TOUCHED_TILES]));
}

static void test_weighted_sssp(
    SplitAlgorithmRuntime &runtime,
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<std::vector<uint16_t>> &weights,
    const std::vector<float> &inverse_degree,
    int num_vertices,
    uint32_t source,
    bool one_step,
    bool enforce_tiny_contract,
    const SliceWorkload *resident_baseline = nullptr,
    const std::vector<DynamicUpdate> *dynamic_updates = nullptr,
    const std::string &trace_id = ""
) {
    const uint32_t infinity = 0xffffffffU;
    require(source < (uint32_t)num_vertices,
            "weighted SSSP source is outside the vertex domain");
    const bool resident_dynamic = resident_baseline != nullptr;
    const std::vector<uint32_t> final_oracle = resident_dynamic
        ? weighted_sssp_distances(
              adjacency, weights, num_vertices, source)
        : std::vector<uint32_t>();
    std::vector<uint32_t> state(state_word_count(num_vertices), infinity);
    std::vector<uint32_t> active;
    if (resident_dynamic) {
        require(dynamic_updates != nullptr,
                "resident SSSP requires the dynamic update batch");
        std::vector<uint32_t> distance =
            weighted_sssp_distances(
                resident_baseline->adjacency, resident_baseline->weights,
                resident_baseline->num_vertices, source);
        std::copy(distance.begin(), distance.end(), state.begin());
        active = dynamic_update_sources(*dynamic_updates);
        runtime.preload_resident_state(state);
    } else {
        state[(size_t)source] = 0;
        active = {source};
    }

    int iterations = 0;
    uint64_t last_processed_edges = 0;
    const int iteration_limit = one_step ? 1 : num_vertices;
    while (!active.empty() && iterations < iteration_limit) {
        std::vector<uint32_t> expected(state.begin(),
                                       state.begin() + num_vertices);
        std::vector<uint8_t> changed((size_t)num_vertices, 0);
        for (uint32_t src : active) {
            for (size_t edge = 0; edge < adjacency[(size_t)src].size(); edge++) {
                uint32_t dst = adjacency[(size_t)src][edge];
                uint32_t proposed = state[(size_t)src] +
                                    (uint32_t)weights[(size_t)src][edge];
                if (proposed < expected[(size_t)dst]) {
                    expected[(size_t)dst] = proposed;
                    changed[(size_t)dst] = 1;
                }
            }
        }
        std::vector<uint32_t> expected_active;
        for (int vid = 0; vid < num_vertices; vid++) {
            if (changed[(size_t)vid]) expected_active.push_back((uint32_t)vid);
        }

        PartitionedActiveBinFlat frontier = make_frontier(
            graph, active, state, inverse_degree, num_vertices);
        last_processed_edges = active_edge_count(adjacency, active);
        IterationResult actual = runtime.run(
            kWeightedSssp, 0, 0, active, frontier, state,
            resident_dynamic && iterations == 0);
        validate_common("weighted SSSP", iterations, actual,
                        last_processed_edges);
        for (int vid = 0; vid < num_vertices; vid++) {
            if (resident_dynamic) {
                require(actual.state[(size_t)vid] <= state[(size_t)vid],
                        "resident weighted SSSP increased a distance at vertex " +
                            std::to_string(vid));
                require(actual.state[(size_t)vid] >= final_oracle[(size_t)vid],
                        "resident weighted SSSP undershot Dijkstra at vertex " +
                            std::to_string(vid));
            } else {
                require(actual.state[(size_t)vid] == expected[(size_t)vid],
                        "weighted SSSP distance mismatch at vertex " +
                            std::to_string(vid));
            }
        }
        if (!resident_dynamic) {
            require(sorted_unique(actual.active_ids) == expected_active,
                    "weighted SSSP next frontier mismatch at iteration " +
                        std::to_string(iterations));
        }
        std::cout << "ALGORITHM_STEP_PASS name=weighted_sssp iteration="
                  << iterations << std::endl;
        state = std::move(actual.state);
        active = sorted_unique(std::move(actual.active_ids));
        iterations++;
    }

    if (one_step) {
        require(iterations == 1, "weighted SSSP one-step case did not execute");
        print_workload_result(trace_id, "weighted_sssp", state, active,
                              num_vertices, last_processed_edges);
        std::cout << "ALGORITHM_PASS name=weighted_sssp iterations=1 "
                     "coverage=one_step"
                  << std::endl;
        return;
    }

    require(active.empty(), "weighted SSSP did not converge");
    if (resident_dynamic) {
        require(std::equal(final_oracle.begin(), final_oracle.end(),
                           state.begin()),
                "resident weighted SSSP final distances differ from Dijkstra");
    }
    if (enforce_tiny_contract) {
        require(state[0] == 0 && state[1] == 1 && state[2] == infinity &&
                    state[(size_t)num_vertices - 1ULL] == 1,
                "weighted SSSP final distances changed");
    }
    std::cout << "ALGORITHM_PASS name=weighted_sssp iterations="
              << iterations << std::endl;
}

static void test_connected_components(
    SplitAlgorithmRuntime &runtime,
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<float> &inverse_degree,
    int num_vertices,
    bool one_step,
    bool enforce_tiny_contract,
    int diagnostic_active_source = -2,
    const SliceWorkload *resident_baseline = nullptr,
    const std::vector<DynamicUpdate> *dynamic_updates = nullptr,
    const std::string &trace_id = ""
) {
    std::vector<uint32_t> state(state_word_count(num_vertices), 0);
    const bool resident_dynamic = resident_baseline != nullptr;
    if (resident_dynamic) {
        require(dynamic_updates != nullptr,
                "resident CC requires the dynamic update batch");
        std::vector<uint32_t> labels =
            connected_component_labels(*resident_baseline);
        std::copy(labels.begin(), labels.end(), state.begin());
        runtime.preload_resident_state(state);
    } else {
        for (int vid = 0; vid < num_vertices; vid++) state[(size_t)vid] = vid;
    }
    std::vector<uint32_t> active;
    if (resident_dynamic) {
        active = dynamic_update_sources(*dynamic_updates);
    } else if (diagnostic_active_source == -2) {
        active.resize((size_t)num_vertices);
        std::iota(active.begin(), active.end(), 0);
    } else if (diagnostic_active_source >= 0 ||
               diagnostic_active_source == -4 ||
               diagnostic_active_source == -5) {
        active.push_back((uint32_t)(diagnostic_active_source == -4 ||
                                            diagnostic_active_source == -5
                                        ? 2
                                        : diagnostic_active_source));
    }

    int iterations = 0;
    uint64_t last_processed_edges = 0;
    const int iteration_limit = one_step ? 1 : num_vertices;
    const bool force_empty_step = diagnostic_active_source == -1;
    while ((!active.empty() || (force_empty_step && iterations == 0)) &&
           iterations < iteration_limit) {
        std::vector<uint32_t> expected(state.begin(),
                                       state.begin() + num_vertices);
        std::vector<uint32_t> expected_active;
        std::vector<uint8_t> changed((size_t)num_vertices, 0);
        for (uint32_t src : active) {
            uint32_t label = state[(size_t)src];
            for (uint32_t dst : adjacency[(size_t)src]) {
                if (label < expected[(size_t)dst]) {
                    expected[(size_t)dst] = label;
                    changed[(size_t)dst] = 1;
                }
            }
        }
        for (int vid = 0; vid < num_vertices; vid++) {
            if (changed[(size_t)vid]) expected_active.push_back(vid);
        }

        PartitionedActiveBinFlat frontier = make_frontier(
            graph, active, state, inverse_degree, num_vertices);
        uint64_t expected_edges = active_edge_count(adjacency, active);
        last_processed_edges = expected_edges;
        if (diagnostic_active_source == -4 ||
            diagnostic_active_source == -5) {
            PartitionedActiveSourceRecord diagnostic_record;
            diagnostic_record.src = 2;
            diagnostic_record.src_value = state[2];
            if (diagnostic_active_source == -5) {
                diagnostic_record.level_partition_masks[0] = 1;
            }
            frontier.records.assign(
                1, pack_partitioned_active_record_host(diagnostic_record));
            for (int partition = 0;
                 partition < HOST_PARTITIONED_CSR_DST_PARTITIONS;
                 partition++) {
                frontier.offsets[(size_t)partition] = 1;
                frontier.counts[(size_t)partition] = 0;
            }
            frontier.offsets[0] = 0;
            frontier.counts[0] = 1;
        }
        IterationResult actual = runtime.run(
            kConnectedComponents, 0, 0, active, frontier, state,
            resident_dynamic && iterations == 0);
        validate_common("CC", iterations, actual, expected_edges);
        for (int vid = 0; vid < num_vertices; vid++) {
            require(actual.state[(size_t)vid] == expected[(size_t)vid],
                    "CC label mismatch at vertex " + std::to_string(vid));
        }
        require(sorted_unique(actual.active_ids) == expected_active,
                "CC next frontier mismatch at iteration " +
                    std::to_string(iterations));
        for (size_t i = 0; i < actual.active_ids.size(); i++) {
            uint32_t vertex = actual.active_ids[i];
            require(actual.active_values[i] == actual.state[(size_t)vertex],
                    "CC active payload mismatch at iteration " +
                        std::to_string(iterations) + " vertex=" +
                        std::to_string(vertex) + " payload=" +
                        std::to_string(actual.active_values[i]) + " state=" +
                        std::to_string(actual.state[(size_t)vertex]));
        }
        std::cout << "ALGORITHM_STEP_PASS name=connected_components iteration="
                  << iterations << std::endl;
        state = std::move(actual.state);
        active = sorted_unique(std::move(actual.active_ids));
        iterations++;
    }

    if (one_step) {
        require(iterations == 1, "CC one-step case did not execute");
        print_workload_result(trace_id, "connected_components", state, active,
                              num_vertices, last_processed_edges);
        std::cout << "ALGORITHM_PASS name=connected_components iterations=1 "
                     "coverage=one_step"
                  << std::endl;
        return;
    }

    require(active.empty(), "CC did not converge");
    if (enforce_tiny_contract) {
        require(state[0] == 0 && state[1] == 0 &&
                    state[(size_t)num_vertices - 1ULL] == 0,
                "CC connected component did not select minimum label");
        require(state[2] == 2,
                "CC changed an isolated component");
    }
    std::cout << "ALGORITHM_PASS name=connected_components iterations="
              << iterations << std::endl;
}

static void test_residual_pagerank(
    SplitAlgorithmRuntime &runtime,
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<float> &inverse_degree,
    int num_vertices,
    uint32_t source,
    bool one_step,
    bool enforce_tiny_contract,
    const SliceWorkload *resident_baseline = nullptr,
    const std::string &trace_id = ""
) {
    const float damping = 0.85f;
    const float initial_residual = (1.0f - damping) / (float)num_vertices;
    const float epsilon = enforce_tiny_contract
        ? initial_residual * 0.35f
        : 1.0e-6f;
    require(source < (uint32_t)num_vertices,
            "residual PageRank source is outside the vertex domain");
    const bool resident_dynamic = resident_baseline != nullptr;
    std::vector<float> residual((size_t)num_vertices, 0.0f);
    std::vector<float> rank((size_t)num_vertices, 0.0f);
    const size_t span = state_span(num_vertices);
    std::vector<uint32_t> state(state_word_count(num_vertices),
                                float_bits(0.0f));
    std::vector<uint32_t> active;
    if (resident_dynamic) {
        rank = full_pagerank_rank(*resident_baseline, 128, damping);
        std::vector<uint32_t> resident_state = state;
        for (int vid = 0; vid < num_vertices; vid++) {
            resident_state[(size_t)vid] = float_bits(rank[(size_t)vid]);
            resident_state[2ULL * span + (size_t)vid] =
                (uint32_t)resident_baseline->adjacency[(size_t)vid].size();
        }
        runtime.preload_resident_state(resident_state);

        const auto correction_start = std::chrono::steady_clock::now();
        residual = pagerank_correction_residual(
            adjacency, rank, damping);
        for (int vid = 0; vid < num_vertices; vid++) {
            state[(size_t)vid] = float_bits(rank[(size_t)vid]);
            state[span + (size_t)vid] = float_bits(residual[(size_t)vid]);
            state[2ULL * span + (size_t)vid] =
                (uint32_t)adjacency[(size_t)vid].size();
            if (std::fabs(residual[(size_t)vid]) > epsilon) {
                active.push_back((uint32_t)vid);
            }
        }
        const auto correction_end = std::chrono::steady_clock::now();
        runtime.install_host_prepared_state(
            state,
            std::chrono::duration<double, std::milli>(
                correction_end - correction_start).count());
    } else {
        residual[(size_t)source] = initial_residual;
        state[span + (size_t)source] = float_bits(residual[(size_t)source]);
        for (int vid = 0; vid < num_vertices; vid++) {
            state[2ULL * span + (size_t)vid] =
                (uint32_t)adjacency[(size_t)vid].size();
        }
        active = {source};
    }

    int iterations = 0;
    uint64_t last_processed_edges = 0;
    const int iteration_limit = one_step ? 1 : std::max(256, num_vertices);
    while (!active.empty() && iterations < iteration_limit) {
        std::vector<float> source_residual((size_t)num_vertices, 0.0f);
        for (uint32_t src : active) {
            source_residual[(size_t)src] = residual[(size_t)src];
            rank[(size_t)src] += residual[(size_t)src];
            residual[(size_t)src] = 0.0f;
        }
        std::vector<uint8_t> touched((size_t)num_vertices, 0);
        for (uint32_t src : active) {
            float contribution = damping * source_residual[(size_t)src] *
                                 inverse_degree[(size_t)src];
            for (uint32_t dst : adjacency[(size_t)src]) {
                residual[(size_t)dst] += contribution;
                touched[(size_t)dst] = 1;
            }
        }
        std::vector<uint32_t> expected_active;
        for (int vid = 0; vid < num_vertices; vid++) {
            if (touched[(size_t)vid] &&
                std::fabs(residual[(size_t)vid]) > epsilon) {
                expected_active.push_back(vid);
            }
        }

        PartitionedActiveBinFlat frontier = make_frontier(
            graph, active, state, inverse_degree, num_vertices);
        uint64_t expected_edges = active_edge_count(adjacency, active);
        last_processed_edges = expected_edges;
        IterationResult actual = runtime.run(
            kResidualPagerank,
            float_bits(damping), float_bits(epsilon), active, frontier, state);
        validate_common("residual PageRank", iterations, actual,
                        expected_edges);
        for (int vid = 0; vid < num_vertices; vid++) {
            require(close_float(
                        bits_float(actual.state[(size_t)vid]),
                        rank[(size_t)vid], 2.0e-5f),
                    "residual PageRank rank mismatch at vertex " +
                        std::to_string(vid));
            require(close_float(
                        bits_float(actual.state[actual.auxiliary_offset +
                                                (size_t)vid]),
                        residual[(size_t)vid], 2.0e-5f),
                    "residual PageRank residual mismatch at vertex " +
                        std::to_string(vid));
            require(actual.state[actual.degree_offset + (size_t)vid] ==
                        adjacency[(size_t)vid].size(),
                    "residual PageRank changed out-degree state");
        }
        require(sorted_unique(actual.active_ids) == expected_active,
                "residual PageRank next frontier mismatch at iteration " +
                    std::to_string(iterations));
        for (size_t i = 0; i < actual.active_ids.size(); i++) {
            float payload = bits_float(actual.active_values[i]);
            float stored = bits_float(
                actual.state[actual.auxiliary_offset +
                             (size_t)actual.active_ids[i]]);
            require(close_float(payload, stored, 1.0e-6f),
                    "residual PageRank active payload mismatch");
        }
        std::cout << "ALGORITHM_STEP_PASS name=residual_pagerank iteration="
                  << iterations << std::endl;
        state = std::move(actual.state);
        active = sorted_unique(std::move(actual.active_ids));
        iterations++;
    }

    if (one_step) {
        require(iterations == 1,
                "residual PageRank one-step case did not execute");
        print_workload_result(trace_id, "residual_pagerank", state, active,
                              num_vertices, last_processed_edges);
        std::cout << "ALGORITHM_PASS name=residual_pagerank iterations=1 "
                     "coverage=one_step"
                  << std::endl;
        return;
    }

    require(active.empty(), "residual PageRank did not meet epsilon");
    if (enforce_tiny_contract) {
        require(iterations == 3,
                "residual PageRank threshold scenario changed iteration count");
    }
    std::cout << "ALGORITHM_PASS name=residual_pagerank iterations="
              << iterations << " epsilon=" << epsilon << std::endl;
}

static void test_residual_signed_cancellation(
    SplitAlgorithmRuntime &runtime,
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<float> &inverse_degree,
    int num_vertices
) {
    const float damping = 0.85f;
    const float positive = 0.1f;
    const uint32_t remote_source = (uint32_t)num_vertices - 1U;
    const size_t span = state_span(num_vertices);
    std::vector<uint32_t> state(state_word_count(num_vertices),
                                float_bits(0.0f));
    state[span + 1ULL] = float_bits(positive);
    state[span + (size_t)remote_source] = float_bits(-positive);
    for (int vid = 0; vid < num_vertices; vid++) {
        state[2ULL * span + (size_t)vid] =
            (uint32_t)adjacency[(size_t)vid].size();
    }
    std::vector<uint32_t> active = {1, remote_source};
    PartitionedActiveBinFlat frontier = make_frontier(
        graph, active, state, inverse_degree, num_vertices);

    IterationResult actual = runtime.run(
        kResidualPagerank,
        float_bits(damping), float_bits(1.0e-6f), active, frontier, state);
    validate_common("residual PageRank signed cancellation", 0, actual,
                    active_edge_count(adjacency, active));
    require(actual.active_ids.empty(),
            "cancelled residual incorrectly activated its destination");
    for (int vid = 0; vid < num_vertices; vid++) {
        require(close_float(
                    bits_float(actual.state[actual.auxiliary_offset +
                                            (size_t)vid]),
                    0.0f, 1.0e-6f),
                "signed residual cancellation left a residual");
    }
    require(close_float(
                bits_float(actual.state[1]),
                positive, 1.0e-6f),
            "positive residual was not accumulated into rank");
    require(close_float(
                bits_float(actual.state[(size_t)remote_source]),
                -positive, 1.0e-6f),
            "negative residual was not accumulated into rank");
    std::cout << "ALGORITHM_STEP_PASS "
                 "name=residual_pagerank_signed_cancellation iteration=0"
              << std::endl;
    std::cout << "ALGORITHM_PASS name=residual_pagerank_signed_cancellation"
              << std::endl;
}

static void test_full_pagerank(
    SplitAlgorithmRuntime &runtime,
    const PartitionedCsrReferenceGraph &graph,
    const std::vector<std::vector<uint32_t>> &adjacency,
    const std::vector<float> &inverse_degree,
    int num_vertices,
    bool one_step,
    const std::string &trace_id = ""
) {
    const float damping = 0.85f;
    const int iteration_count = one_step ? 1 : 3;
    std::vector<float> rank((size_t)num_vertices,
                            1.0f / (float)num_vertices);
    const size_t span = state_span(num_vertices);
    std::vector<uint32_t> state(state_word_count(num_vertices),
                                float_bits(0.0f));
    for (int vid = 0; vid < num_vertices; vid++) {
        state[(size_t)vid] = float_bits(rank[(size_t)vid]);
        state[2ULL * span + (size_t)vid] =
            (uint32_t)adjacency[(size_t)vid].size();
    }
    std::vector<uint32_t> active((size_t)num_vertices);
    std::iota(active.begin(), active.end(), 0);
    uint64_t last_processed_edges = 0;

    for (int iteration = 0; iteration < iteration_count; iteration++) {
        float dangling_rank = 0.0f;
        for (int vid = 0; vid < num_vertices; vid++) {
            if (adjacency[(size_t)vid].empty()) {
                dangling_rank += rank[(size_t)vid];
            }
        }
        float inverse_vertices = 1.0f / (float)num_vertices;
        float base = ((1.0f - damping) + damping * dangling_rank) *
                     inverse_vertices;
        std::vector<float> expected((size_t)num_vertices, base);
        for (int src = 0; src < num_vertices; src++) {
            if (adjacency[(size_t)src].empty()) continue;
            float contribution = damping * rank[(size_t)src] *
                                 inverse_degree[(size_t)src];
            for (uint32_t dst : adjacency[(size_t)src]) {
                expected[(size_t)dst] += contribution;
            }
        }

        PartitionedActiveBinFlat frontier = make_frontier(
            graph, active, state, inverse_degree, num_vertices);
        IterationResult actual = runtime.run(
            kFullPagerank, float_bits(damping),
            float_bits(1.0e-6f),
            active, frontier, state);
        last_processed_edges = active_edge_count(adjacency, active);
        validate_common("full PageRank", iteration, actual,
                        last_processed_edges);
        for (int vid = 0; vid < num_vertices; vid++) {
            require(close_float(bits_float(
                                    actual.state[actual.primary_offset +
                                                 (size_t)vid]),
                                expected[(size_t)vid], 2.0e-4f),
                    "full PageRank rank mismatch at vertex " +
                        std::to_string(vid));
            require(actual.state[actual.degree_offset + (size_t)vid] ==
                        adjacency[(size_t)vid].size(),
                    "full PageRank changed out-degree state");
        }
        std::vector<uint32_t> expected_active((size_t)num_vertices);
        std::iota(expected_active.begin(), expected_active.end(), 0);
        require(sorted_unique(actual.active_ids) == expected_active,
                "full PageRank did not return the all-vertex frontier");
        for (size_t i = 0; i < actual.active_ids.size(); i++) {
            float payload = bits_float(actual.active_values[i]);
            float stored = bits_float(
                actual.state[actual.primary_offset +
                             (size_t)actual.active_ids[i]]);
            require(close_float(payload, stored, 1.0e-6f),
                    "full PageRank active payload mismatch");
        }
        std::cout << "ALGORITHM_STEP_PASS name=full_pagerank iteration="
                  << iteration << std::endl;
        rank = std::move(expected);
        state = std::move(actual.state);
        active = sorted_unique(std::move(actual.active_ids));
    }

    float rank_sum = std::accumulate(rank.begin(), rank.end(), 0.0f);
    require(close_float(rank_sum, 1.0f, 5.0e-4f),
            "full PageRank lost probability mass");
    size_t dangling_vertices = 0;
    for (const auto &neighbors : adjacency) {
        if (neighbors.empty()) dangling_vertices++;
    }
    if (one_step) {
        print_workload_result(trace_id, "full_pagerank", state, active,
                              num_vertices, last_processed_edges);
    }
    std::cout << "ALGORITHM_PASS name=full_pagerank iterations="
              << iteration_count << " dangling_vertices="
              << dangling_vertices;
    if (one_step) std::cout << " coverage=one_step";
    std::cout << std::endl;
}

#include "host_resident_benchmark.hpp"

static void require_update_setup_lease() {
    const char *fd_text = std::getenv("ORIGINAL_R_LEASE_FD");
    const char *index = std::getenv("XCL_DEVICE_INDEX");
    const char *bdf = std::getenv("SPINE_EXPECT_BDF");
    require(fd_text && *fd_text && index &&
                (std::string(index) == "0" || std::string(index) == "1") &&
                bdf && *bdf,
            "update setup requires an exclusive PCI lease");
    char *end = nullptr;
    const long fd = std::strtol(fd_text, &end, 10);
    struct stat descriptor{}, path{};
    const std::string lock = std::string("/tmp/chuxiao-sharded-k4-board-") + index + ".lock";
    require(*end == '\0' && fd >= 0 && fd <= INT32_MAX &&
                fstat((int)fd, &descriptor) == 0 && lstat(lock.c_str(), &path) == 0 &&
                S_ISREG(path.st_mode) && descriptor.st_dev == path.st_dev &&
                descriptor.st_ino == path.st_ino && flock((int)fd, LOCK_EX | LOCK_NB) == 0,
            "update setup descriptor does not exclusively lock the selected board");
}

static void run_update_setup_once(const std::string &xclbin, const std::string &graph) {
    require_update_setup_lease();
    const SetupInsertionBatch batch = read_setup_insertion_batch(graph);
    const auto layout_start = std::chrono::steady_clock::now();
    auto image = serialize_partitioned_hot_cold_graph_reference<AlignedVector<uint64_t>>(
        build_compacted_hot_cold_reference(setup_baseline_workload(batch), nullptr),
        PartitionedActiveBinFlat{});
    const auto layout_end = std::chrono::steady_clock::now();
    SplitAlgorithmRuntime runtime(xclbin, std::move(image), batch.vertices, true);
    const auto pack_start = std::chrono::steady_clock::now();
    auto updates = batch.inserts;
    std::sort(updates.begin(), updates.end(), [](const auto &lhs, const auto &rhs) {
        return std::tie(lhs.src, lhs.dst, lhs.weight) < std::tie(rhs.src, rhs.dst, rhs.weight);
    });
    runtime.prepare_updates(updates, updates.size());
    const auto batch_ready = std::chrono::steady_clock::now();
    const int64_t update_ns = runtime.apply_prepared_updates();
    const size_t checked_edges = runtime.validate_updated_graph(batch);
    const int64_t layout_ns = runtime.elapsed_ns(layout_start, layout_end);
    const int64_t bootstrap_ns = runtime.setup_bootstrap_ns();
    const int64_t batch_ns = runtime.elapsed_ns(pack_start, batch_ready);
    require(layout_ns > 0 && bootstrap_ns > 0 && batch_ns > 0 && update_ns > 0,
            "update setup timings must be positive");
    runtime.print_update_setup_bootstrap();
    std::cout << "SPINE_UPDATE_SETUP_ONCE status=PASS vertices=" << batch.vertices
              << " initial_edges=" << batch.old_edges.size()
              << " logical_updates=" << updates.size()
              << " layout_ns=" << layout_ns << " bootstrap_ns=" << bootstrap_ns
              << " batch_ns=" << batch_ns << " update_wall_ns=" << update_ns
              << " setup_inclusive_ns=" << layout_ns + bootstrap_ns + batch_ns + update_ns
              << " repeats=1 checked_edges=" << checked_edges << std::endl;
}

}  // namespace

int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    std::cerr.setf(std::ios::unitbuf);
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0]
                  << " <algorithm-specialized-split.xclbin> [--one-step]"
                     " [--slice PATH | --dynamic-graph PATH]"
                     " [--source VERTEX] [--dump-state] [--resident-benchmark]\n"
                  << "       " << argv[0]
                  << " <xclbin> --update-setup-once --dynamic-graph PATH"
                  << std::endl;
        return 1;
    }

    try {
        if (argc >= 3 && std::string(argv[2]) == "--update-setup-once") {
            require(argc == 5 && std::string(argv[3]) == "--dynamic-graph",
                    "update setup accepts exactly one native insertion batch");
            run_update_setup_once(argv[1], argv[4]);
            return 0;
        }
        bool one_step = false;
        bool dump_state = false;
        bool resident_benchmark = false;
        bool source_explicit = false;
        uint32_t source = 0;
        std::string slice_path;
        std::string dynamic_graph_path;
        for (int arg = 2; arg < argc; arg++) {
            std::string option = argv[arg];
            if (option == "--one-step") {
                one_step = true;
            } else if (option == "--dump-state") {
                dump_state = true;
            } else if (option == "--resident-benchmark") {
                resident_benchmark = true;
            } else if (option == "--slice") {
                require(arg + 1 < argc, "--slice requires a path");
                slice_path = argv[++arg];
            } else if (option == "--dynamic-graph") {
                require(arg + 1 < argc,
                        "--dynamic-graph requires a path");
                dynamic_graph_path = argv[++arg];
            } else if (option == "--source") {
                require(arg + 1 < argc, "--source requires a vertex ID");
                unsigned long parsed = std::stoul(argv[++arg]);
                require(parsed <= UINT32_MAX,
                        "--source exceeds the uint32 vertex domain");
                source = (uint32_t)parsed;
                source_explicit = true;
            } else {
                throw std::runtime_error("unsupported option: " + option);
            }
        }

        require(slice_path.empty() || dynamic_graph_path.empty(),
                "--slice and --dynamic-graph are mutually exclusive");
        const bool dynamic_run = !dynamic_graph_path.empty();
        require(!resident_benchmark ||
                    (dynamic_run && !one_step && !dump_state &&
                     SPINE_ALGORITHM_KIND != kFullPagerank),
                "--resident-benchmark requires a dynamic SSSP/CC/ResPR "
                "convergence run without --one-step or --dump-state");
        const bool enforce_tiny_contract =
            slice_path.empty() && dynamic_graph_path.empty();
        SliceWorkload workload;
        SliceWorkload baseline_workload;
        std::vector<DynamicUpdate> physical_updates;
        size_t logical_updates = 0;
        if (enforce_tiny_contract) {
            require(VS_PARTITION_SIZE >= 2,
                    "algorithm smoke requires VS_PARTITION_SIZE >= 2");
            const int remote_vertex = VS_PARTITION_SIZE + 1;
            workload.case_id = "tiny_two_partition";
            workload.num_vertices = remote_vertex + 1;
            require(MAX_N >= workload.num_vertices,
                    "algorithm smoke MAX_N is too small for two partitions");
            workload.adjacency.resize((size_t)workload.num_vertices);
            workload.weights.resize((size_t)workload.num_vertices);
            workload.adjacency[0] = {1, (uint32_t)remote_vertex};
            workload.weights[0] = {1, 1};
            workload.adjacency[1] = {0};
            workload.weights[1] = {1};
            workload.adjacency[(size_t)remote_vertex] = {0};
            workload.weights[(size_t)remote_vertex] = {1};
            baseline_workload = workload;
        } else if (dynamic_run) {
            DynamicWorkload dynamic =
                load_dynamic_workload(dynamic_graph_path);
            baseline_workload = std::move(dynamic.baseline);
            workload = std::move(dynamic.final_graph);
            physical_updates = std::move(dynamic.physical_updates);
            logical_updates = dynamic.logical_updates;
            if (!source_explicit) source = select_default_source(workload);
        } else {
            workload = load_slice_workload(slice_path);
            baseline_workload = workload;
            if (!source_explicit) source = select_default_source(workload);
        }
        require(source < (uint32_t)workload.num_vertices,
                "selected source is outside the vertex domain");

        require(HOST_PARTITIONED_CSR_DST_PARTITIONS <=
                    HOST_PARTITIONED_GRAPH_PORTS,
                "algorithm smoke logical partitions exceed physical ports");
        const int num_vertices = workload.num_vertices;
        const auto &adjacency = workload.adjacency;
        const auto &weights = workload.weights;

        PartitionedCsrReferenceGraph graph;
        PartitionedGraphImage image;
        int baseline_level = 0;
        size_t baseline_hot_vertices = 0;
        uint64_t baseline_hot_edges = 0;
        if (dynamic_run) {
            PartitionedHotColdReferenceGraph baseline_graph =
                build_compacted_hot_cold_reference(
                    baseline_workload, &baseline_level);
            baseline_hot_vertices =
                baseline_graph.classification.hot_vertex_count;
            baseline_hot_edges = baseline_graph.classification.hot_edges;
            PartitionedActiveBinFlat empty_frontier;
            image = serialize_partitioned_hot_cold_graph_reference(
                baseline_graph, empty_frontier);
            graph = build_logical_reference(workload);
        } else {
            std::vector<std::vector<PartitionedCsrEdgeRef>> levels(
                HOST_PARTITIONED_RATIO2_LEVELS);
            for (uint32_t src = 0; src < (uint32_t)num_vertices; src++) {
                for (size_t edge = 0;
                     edge < adjacency[(size_t)src].size(); edge++) {
                    levels[0].push_back(
                        {src, adjacency[(size_t)src][edge],
                         weights[(size_t)src][edge], 1});
                }
            }
            graph = build_partitioned_csr_reference(
                levels, num_vertices,
                HOST_PARTITIONED_CSR_DST_PARTITIONS);
            PartitionedActiveBinFlat empty_frontier;
            image = serialize_partitioned_graph_reference(
                graph, empty_frontier);
        }

        std::vector<float> inverse_degree((size_t)num_vertices, 0.0f);
        for (int vid = 0; vid < num_vertices; vid++) {
            if (!adjacency[(size_t)vid].empty()) {
                inverse_degree[(size_t)vid] =
                    1.0f / (float)adjacency[(size_t)vid].size();
            }
        }

        SplitAlgorithmRuntime runtime(argv[1], image, num_vertices);
        if (resident_benchmark) {
            const ResidentBenchmarkResult result = run_resident_benchmark(
                runtime, baseline_workload, workload, physical_updates,
                logical_updates, source);
            std::cout << "SPINE_RESIDENT_BENCHMARK_PASS algorithm="
                      << SPINE_ALGORITHM_KIND
                      << " case=" << workload.case_id
                      << " vertices=" << num_vertices
                      << " source=" << source
                      << " iterations=" << result.iterations
                      << " logical_updates=" << logical_updates
                      << " physical_updates=" << physical_updates.size()
                      << " boundary=resident_update_to_final_readback_wall_including_host_relaunch"
                      << " wall_ms=" << result.wall_ms
                      << " final_validation=outside_wall"
                      << " full_state_readback=each_round"
                      << " host_correction_included="
                      << (SPINE_ALGORITHM_KIND == kResidualPagerank ? 1 : 0)
                      << std::endl;
            runtime.print_timing_summary();
            return 0;
        }
        if (dynamic_run) {
            runtime.apply_updates(physical_updates, logical_updates);
        }
        const bool monotonic_resident_update =
            dynamic_run &&
            std::all_of(physical_updates.begin(), physical_updates.end(),
                        [](const DynamicUpdate &update) {
                            return update.diff > 0;
                        });
        const std::string trace_id =
            (!enforce_tiny_contract && dump_state)
                ? workload.case_id
                : std::string();
#if SPINE_ALGORITHM_KIND == 0
        test_weighted_sssp(runtime, graph, adjacency, weights, inverse_degree,
                           num_vertices, source, one_step,
                           enforce_tiny_contract,
                           monotonic_resident_update ? &baseline_workload : nullptr,
                           monotonic_resident_update ? &physical_updates : nullptr,
                           trace_id);
        std::cout << "PARTITIONED_ALGORITHM_PASS algorithm=weighted_sssp";
#elif SPINE_ALGORITHM_KIND == 1
        test_connected_components(runtime, graph, adjacency, inverse_degree,
                                  num_vertices, one_step,
                                  enforce_tiny_contract, -2,
                                  monotonic_resident_update ? &baseline_workload : nullptr,
                                  monotonic_resident_update ? &physical_updates : nullptr,
                                  trace_id);
        std::cout << "PARTITIONED_ALGORITHM_PASS algorithm=connected_components";
#elif SPINE_ALGORITHM_KIND == 2
        test_residual_pagerank(runtime, graph, adjacency, inverse_degree,
                               num_vertices, source, one_step,
                               enforce_tiny_contract,
                               dynamic_run ? &baseline_workload : nullptr,
                               trace_id);
        if (!one_step && enforce_tiny_contract) {
            SplitAlgorithmRuntime cancellation_runtime(
                argv[1], image, num_vertices);
            test_residual_signed_cancellation(
                cancellation_runtime, graph, adjacency, inverse_degree,
                num_vertices);
        }
        std::cout << "PARTITIONED_ALGORITHM_PASS "
                     "algorithm=thresholded_residual_pagerank";
#else
        test_full_pagerank(runtime, graph, adjacency, inverse_degree,
                           num_vertices, one_step, trace_id);
        std::cout << "PARTITIONED_ALGORITHM_PASS algorithm=full_pagerank";
#endif
        const char *coverage = one_step ? "one_step" : "converged";
#if SPINE_ALGORITHM_KIND == 3
        coverage = one_step ? "one_step" : "three_iterations";
#endif
        std::cout << " vertices=" << num_vertices
                  << " partitions=" << HOST_PARTITIONED_CSR_DST_PARTITIONS
                  << " source=" << source
                  << " case=" << workload.case_id
                  << " dynamic_run=" << (dynamic_run ? 1 : 0)
                  << " resident_update="
                  << (monotonic_resident_update ? 1 : 0)
                  << " logical_updates=" << logical_updates
                  << " physical_updates=" << physical_updates.size()
                  << " baseline_level=" << baseline_level
                  << " baseline_hot_vertices=" << baseline_hot_vertices
                  << " baseline_hot_edges=" << baseline_hot_edges
                  << " coverage=" << coverage << std::endl;
        runtime.print_timing_summary();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "PARTITIONED_ALGORITHMS_FAIL " << error.what()
                  << std::endl;
        return 1;
    }
}
