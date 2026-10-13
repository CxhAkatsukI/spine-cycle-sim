#include "run.hpp"

int main(int argc, char **argv) {
  namespace lc = sharded_g_test::lifecycle;
  try {
    if (argc != 5) throw std::invalid_argument("usage: resident G CASE LATENCY ARM STATE");
    const lc::Fixture fixture(argv[1]);
    lc::run(fixture, argv[1], std::stoul(argv[2]), argv[3], argv[4], lc::Fixture::kVertices);
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
