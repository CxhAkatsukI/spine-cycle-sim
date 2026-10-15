#include "device.hpp"
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
              << ",\"hbm_bytes\":" << model.plan.total_allocated_bytes << "}" << std::endl;
    for (unsigned batch = 0; batch < 3; ++batch) {
      const auto begin = Clock::now();
      const auto updates = model.pack_batch(batch);
      const double preparation_ms = milliseconds(begin);
      auto phase = Clock::now();
      const auto transfers = board ? device->transfer(updates) : std::vector<Event>{};
      const double transfer_wall_ms = milliseconds(phase);
      phase = Clock::now();
      const auto kernels = board ? device->run(updates) : std::vector<Event>{};
      const double launch_wait_ms = milliseconds(phase);
      const double g_ready_wall_ms = milliseconds(begin);
      phase = Clock::now();
      model.advance(batch, updates);
      const double oracle_ms = milliseconds(phase);
      phase = Clock::now();
      const auto observed = board ? device->readback(model) : model.expected;
      const double verification_readback_ms = milliseconds(phase);
      const auto words = model.check(observed);
      if (!board && batch) {
        std::vector<Words> restored;
        for (const auto& shard : model.packed) restored.push_back(shard.pma_words);
        bool rejected = false;
        try { model.check(restored); } catch (const std::runtime_error&) { rejected = true; }
        check_input(rejected, "restore-between-batches fault escaped oracle");
      }
      const auto [busy_ms, span_ms] = event_window(kernels);
      for (const auto* events : {&transfers, &kernels}) for (const auto& event : *events) {
        const auto times = event.times();
        std::cout << "CONTINUOUS_G_EVENT {\"batch\":" << batch << ",\"shard\":" << event.shard
                  << ",\"role\":\"" << event.role << "\",\"queued_ns\":" << times[0]
                  << ",\"submit_ns\":" << times[1] << ",\"start_ns\":" << times[2]
                  << ",\"end_ns\":" << times[3] << "}" << std::endl;
      }
      std::cout << "CONTINUOUS_G_ROW {\"batch\":" << batch << ",\"board\":" << (board ? "true" : "false")
                << ",\"updates\":" << model.ends[batch + 1] - model.ends[batch]
                << ",\"edges\":" << model.state.size() << ",\"checked_words\":" << words
                << ",\"host_preparation_ms\":" << preparation_ms << ",\"transfer_wall_ms\":" << transfer_wall_ms
                << ",\"launch_wait_ms\":" << launch_wait_ms << ",\"g_ready_wall_ms\":" << g_ready_wall_ms
                << ",\"kernel_busy_ms\":" << busy_ms << ",\"kernel_span_ms\":" << span_ms
                << ",\"oracle_ms\":" << oracle_ms << ",\"verification_readback_ms\":" << verification_readback_ms
                << ",\"complete_state_pass\":true,\"metadata_pass\":true,\"restored_pma\":false}" << std::endl;
    }
    std::cout << (board ? "CONTINUOUS_G_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
                       : "CONTINUOUS_G_HOST_MODEL_PASS_NOT_BOARD") << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
