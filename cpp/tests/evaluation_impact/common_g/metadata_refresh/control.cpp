#include "model.hpp"
#include "execution.hpp"
#include <iomanip>
#include <memory>

int main(int argc, char** argv) {
  using namespace continuous_g;
  try {
    const bool board = argc == 5 && std::string(argv[1]) == "--board";
    const bool host = argc == 3 && std::string(argv[1]) == "--model-check";
    const bool stale = argc == 4 && std::string(argv[1]) == "--model-check" &&
                       std::string(argv[3]) == "--stale-metadata";
    check_input((board || host || stale) && std::string(argv[2]) == "native-metadata-refresh",
        "usage: --model-check native-metadata-refresh [--stale-metadata] | --board native-metadata-refresh xclbin device");
    unsigned index = 0;
    if (board) {
      check_input(std::string(argv[4]) == "0" || std::string(argv[4]) == "1", "device index must be 0 or 1");
      index = argv[4][0] - '0';
    }
    std::cout << std::fixed << std::setprecision(9);
    const auto begin = Clock::now();
    metadata_g::Model model;
    std::unique_ptr<Device> device;
    if (board) device = std::make_unique<Device>(argv[3], index, model);
    std::cout << "METADATA_G_SETUP {\"board\":" << (board ? "true" : "false")
              << ",\"one_time_setup_ms\":" << milliseconds(begin)
              << ",\"shards\":" << model.graph.shards.size()
              << ",\"hbm_bytes\":" << model.plan.total_allocated_bytes;
    if (board) std::cout << ",\"device_bdf\":\"" << device->session.bdf << "\"";
    std::cout << "}" << std::endl;
    metadata_g::execute(model, device.get(), stale);
    std::cout << (board ? "METADATA_G_BOARD_PASS_NOT_BASELINE_ADMISSION" : "METADATA_G_HOST_PASS_NOT_BOARD")
              << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
