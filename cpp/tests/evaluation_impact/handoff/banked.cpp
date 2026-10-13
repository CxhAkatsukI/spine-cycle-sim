#include "execution.hpp"

int main() {
  try {
    for (auto [vertices, cache, empty] : {std::tuple{129U, 1U, false},
        std::tuple{65569U, 1U, false}, std::tuple{131105U, 8U, false}, std::tuple{65569U, 1U, true}}) {
      const auto old = handoff_test::run(vertices, cache, empty, false);
      const auto next = handoff_test::run(vertices, cache, empty, false, true);
      handoff_test::require(next == handoff_test::run(vertices, cache, empty, true, true),
                           "finite sharded handoff depends on R registration order");
      handoff_test::require(std::tie(old.r_cycles, old.reads, old.writes, old.rounds) ==
                           std::tie(next.r_cycles, next.reads, next.writes, next.rounds),
                           "changing G search changed R traffic or convergence timing");
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
