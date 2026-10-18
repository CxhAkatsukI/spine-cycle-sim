#include "report.hpp"
#include <iostream>

namespace k4 = original_r_k4;

int main(int argc, char** argv) {
  try {
    k4::require(argc == 5 || argc == 7,
                "usage: original_r_k4_control prepare|board INPUT author_initial|csr_degree OUTPUT [XCLBIN DEVICE]");
    const bool board = std::string_view(argv[1]) == "board";
    k4::require(board ? argc == 7 : argc == 5 && std::string_view(argv[1]) == "prepare", "invalid K4 control mode");
    const auto binding = k4::rb::binding(argv[3]);
    const std::filesystem::path output(argv[4]);
    k4::require(!std::filesystem::exists(output) && !std::filesystem::is_symlink(output), "fresh output directory required");
    const auto model = k4::Model::load(argv[2], binding);
    const auto schedule = k4::Schedule::build(model.preparation.graph.shards.size());
    schedule.validate(model.preparation.graph.shards.size());
    if (board) k4::rb::require_lease(k4::rb::number(argv[6]));
    k4::require(std::filesystem::create_directory(output), "could not create fresh output directory");
    k4::rb::wt::write_words(output / "expected_gather.u32le", model.gathered_external);
    k4::rb::wt::write_words(output / "expected_payload.u32le", model.payload_external);
    k4::rb::wt::write_words(output / "external_to_internal.u32le", model.preparation.graph.external_to_internal);
    if (!board) {
      k4::write_expectations(model, output);
      k4::report(output, model, binding, schedule, "", nullptr, false);
      std::cout << "K4_BOARD_HOST_PREFLIGHT_PASS_NOT_FPGA\n";
    } else {
      k4::Device device(argv[5], k4::rb::number(argv[6]), model);
      const auto observation = device.run(model, schedule);
      k4::report(output, model, binding, schedule, device.session.bdf, &observation, false);
      device.verify(model, output);
      k4::report(output, model, binding, schedule, device.session.bdf, &observation, true);
      std::cout << "MATCHED_K4_A4_GUARDED_BOARD_CONTROL_PASS\n";
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "K4_CONTROL_REJECTED " << error.what() << '\n'; return 1;
  }
}
