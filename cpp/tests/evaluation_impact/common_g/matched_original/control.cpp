#include "model.hpp"
#ifndef MATCHED_G_MODEL_ONLY
#include "execution.hpp"
#endif
#include <iostream>

int main(int argc, char** argv) {
  using namespace matched_g;
  try {
    require(argc == 3 || argc == 5, "usage: MATCHED_G --self-test PACKET or --board PACKET XCLBIN DEVICE");
    Model model(argv[2]);
    if (argc == 3 && std::string(argv[1]) == "--self-test") {
      model.advance(model.pack_batch());
      const auto words = model.check(model.expected);
      auto corrupt = model.expected;
      corrupt.front().front().back() ^= 1;
      bool rejected = false;
      try { model.check(corrupt); } catch (const std::runtime_error&) { rejected = true; }
      require(rejected, "matched G complete-state fault escaped oracle");
      std::cout << "MATCHED_G_MODEL {\"status\":\"PASS_NOT_BOARD\",\"vertices\":" << model.input.vertices
                << ",\"segments\":" << model.input.segments << ",\"updates\":" << model.input.updates.size()
                << ",\"checked_words\":" << words << ",\"identity_mapping\":true,\"unit_weight\":true"
                << ",\"same_logical_slots\":true,\"same_update_order\":true,\"route_updates\":["
                << model.route_updates[0] << ',' << model.route_updates[1] << ',' << model.route_updates[2]
                << ',' << model.route_updates[3] << "]}\n";
      return 0;
    }
#ifndef MATCHED_G_MODEL_ONLY
    require(argc == 5 && std::string(argv[1]) == "--board", "invalid matched G board command");
    const std::string index(argv[4]);
    require(index == "0" || index == "1", "known board index required");
    run(model, argv[3], unsigned(index.front() - '0'));
    return 0;
#else
    throw std::runtime_error("model-only build cannot program a board");
#endif
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
