#include <iomanip>
#include "weighted_image_manifest.hpp"

#define main ordered_sssp_fixture_main
#include "host_sssp_repair.cpp"
#undef main

#include "lj08_preload.hpp"

namespace {
std::vector<uint32_t> read_distances(const std::string& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    require(input.good() && input.tellg() == std::streamoff(lj08::vertices * sizeof(uint32_t)),
            "wrong CPU oracle vector size");
    input.seekg(0);
    std::vector<uint32_t> expected(lj08::vertices);
    require(bool(input.read(reinterpret_cast<char*>(expected.data()), expected.size() * sizeof(uint32_t))),
            "short CPU oracle read");
    return expected;
}

void check_distances(const std::vector<uint32_t>& actual, const std::vector<uint32_t>& expected,
                     const char* phase) {
    require(actual.size() == expected.size(), "result vertex count differs from oracle");
    const auto mismatch = std::mismatch(actual.begin(), actual.end(), expected.begin());
    if (mismatch.first != actual.end())
        throw std::runtime_error(std::string(phase) + " distance mismatch at vertex " +
                                 std::to_string(mismatch.first - actual.begin()));
}

void check_board() {
    const auto devices = xcl::get_xil_devices();
    require(!devices.empty(), "no Xilinx device available");
    // The repository's minimal XRT header does not declare this vendor query.
    constexpr cl_device_info pcie_bdf = 0x1120;
    char bdf[64]{};
    require(clGetDeviceInfo(devices[0](), pcie_bdf, sizeof(bdf) - 1, bdf, nullptr) == CL_SUCCESS &&
            std::string(bdf) == "0000:82:00.1", "first OpenCL device does not match the locked U55C");
    std::cout << "FIG10B_BOARD bdf=" << bdf << std::endl;
}
}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 3 && std::string(argv[1]) == "--check-base") {
            lj08::preload(argv[2], nullptr);
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--check-board") {
            check_board();
            return 0;
        }
        require(argc == 7, "usage: fig10b_host IMAGE BASE BATCH_SLICE BEFORE AFTER DELETION_PCT");
        const auto percent = std::stoul(argv[6]);
        auto batch = read_mixed(argv[3], lj08::vertices);
        const auto deletions = size_t(std::count_if(batch.begin(), batch.end(), [](const SignedEdge& edge) {
            return std::get<3>(edge) == -1;
        }));
        require(batch.size() == 512 && percent <= 100 && percent * 512 == deletions * 100,
                "wrong update count or deletion fraction");
        {
            std::ifstream manifest(std::string(argv[1]) + ".weighted-manifest");
            spine_image::validate(manifest, xcl::read_binary_file(argv[1]),
                                  SPINE_WEIGHTED_BUILD_SHA256, "hw");
        }
        check_board();
        const auto before = read_distances(argv[4]);
        const auto after = read_distances(argv[5]);
        std::cout << "FIG10B_START deletion_pct=" << percent << " policy=local hot=1" << std::endl;
        RepairRuntime device(argv[1], lj08::vertices, lj08::source, false, true);
        lj08::preload(argv[2], &device);
        device.preload_converged_distances(before);
        check_distances(device.distances(), before, "before");
        std::cout << "FIG10B_RESIDENT_CHECKPOINT_PASS" << std::endl;

        const auto start = Clock::now();
        device.mixed_batch(std::move(batch), false);
        const double publication_ms = milliseconds(start);
        const auto actual = device.distances();
        const double wall_ms = milliseconds(start);
        check_distances(actual, after, "after");
        device.flush_work();
        std::cout << "FIG10B_PASS deletion_pct=" << percent << " deletions=" << deletions
                  << " insertions=" << 512 - deletions << " wall_ms=" << std::setprecision(10) << wall_ms
                  << " publication_ms=" << publication_ms
                  << " affected=" << device.header(SR_AFFECTED) << " resets=" << device.header(SR_RESET_VERTICES)
                  << " rounds=" << device.header(SR_ROUNDS) << " records=" << device.header(SR_PHYSICAL_EDGES)
                  << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "FIG10B_FAIL " << e.what() << std::endl;
        return 1;
    }
}
