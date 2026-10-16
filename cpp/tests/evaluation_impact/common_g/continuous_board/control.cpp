#include "execution.hpp"
#include <iomanip>
#include <memory>

int main(int argc, char** argv) {
  using namespace continuous_g;
  try {
    const bool board = argc == 5 && std::string(argv[1]) == "--board";
    const bool model_only = argc == 3 && std::string(argv[1]) == "--model-check";
    check_input(board || model_only, "usage: --model-check input | --board input xclbin device-index");
    unsigned device_index = 0;
    if (board) {
      check_input(std::string(argv[4]) == "0" || std::string(argv[4]) == "1", "device index must be 0 or 1");
      device_index = argv[4][0] - '0';
    }
    std::cout << std::fixed << std::setprecision(9);
    const auto setup_begin = Clock::now();
    Model model(argv[2]);
    std::unique_ptr<Device> device;
    if (board) device = std::make_unique<Device>(argv[3], device_index, model);
    std::cout << "CONTINUOUS_G_SETUP {\"board\":" << (board ? "true" : "false")
              << ",\"one_time_setup_ms\":" << milliseconds(setup_begin)
              << ",\"shards\":" << model.graph.shards.size()
              << ",\"hbm_bytes\":" << model.plan.total_allocated_bytes;
    if (board) std::cout << ",\"device_bdf\":\"" << device->session.bdf << "\"";
    std::cout << "}" << std::endl;
    run_batches(model, device.get());
    std::cout << (board ? "CONTINUOUS_G_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
                       : "CONTINUOUS_G_HOST_MODEL_PASS_NOT_BOARD") << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
