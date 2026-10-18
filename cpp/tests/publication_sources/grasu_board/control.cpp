#include "model.hpp"
#ifndef ORIGINAL_G_MODEL_ONLY
#include "execution.hpp"
#endif
#include <iostream>

int main(int argc, char** argv) {
  using namespace original_g_board;
  try {
    require(argc >= 3, "usage: G_BOARD --self-test PACKET or --board PACKET XCLBIN DEVICE");
    const auto input = load(argv[2]); const Model model(input);
    if (argc == 3 && std::string(argv[1]) == "--self-test") {
      std::cout << "ORIGINAL_G_MODEL {\"status\":\"PASS_NOT_BOARD\",\"vertices\":" << input.vertices
                << ",\"segments\":" << input.segments << ",\"updates\":" << input.updates.size()
                << ",\"checked_slots_including_guards\":" << model.checked_slots << ",\"route_updates\":["
                << model.route_updates[0] << ',' << model.route_updates[1] << ',' << model.route_updates[2] << ','
                << model.route_updates[3] << "]}\n";
      return 0;
    }
#ifndef ORIGINAL_G_MODEL_ONLY
    require(argc == 5 && std::string(argv[1]) == "--board", "invalid original G board command");
    run(input, model, argv[3], number(argv[4])); return 0;
#else
    throw std::runtime_error("model-only build cannot program a board");
#endif
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
