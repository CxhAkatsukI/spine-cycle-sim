#include "fixture.hpp"
#include "wrapper.hpp"
#include "../lifecycle/run.hpp"

int main(int argc, char **argv) {
  namespace rr = sharded_g_test::resident_real;
  try {
    if (argc != 7) throw std::invalid_argument("usage: resident real G CASE LATENCY ARM STATE GRAPH UPDATES");
    const rr::Fixture fixture(argv[5], argv[6]);
    sharded_g_test::lifecycle::run(fixture, argv[1], std::stoul(argv[2]), argv[3], argv[4], fixture.vertices,
                                 rr::check_wrapper);
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
