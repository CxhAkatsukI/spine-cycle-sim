#include "ordered_input.hpp"

#include <iostream>

namespace {
const std::string header = "# spine_real_slice_version=1\n# case=temporal\n# vertices=4\n"
                           "# columns=src dst weight diff\n";

void rejects(const std::string &text) {
  std::istringstream input(text);
  try {
    static_cast<void>(sharded_g_test::read_ordered_g_slice(input));
  } catch (const std::runtime_error &) {
    return;
  }
  throw std::runtime_error("accepted malformed ordered input");
}
} // namespace

int main() {
  try {
    std::istringstream input(header + "3 1 4095 1\n0 2 1 -1\n3 1 4095 -1\n");
    const auto slice = sharded_g_test::read_ordered_g_slice(input);
    if (slice.vertices != 4 || slice.case_name != "temporal" || slice.edges.size() != 3 ||
        slice.edges[0].src != 3 || slice.edges[1].src != 0 || slice.edges[1].diff != -1 ||
        slice.edges[2].src != 3 || slice.edges[2].weight != 4095)
      throw std::runtime_error("record order or values changed");
    for (const auto *record : {"4 1 1 1", "-1 1 1 1", "0 4 1 1", "0 1 4096 1",
                              "0 1 0 1", "0 1 1 0", "0 1 1 2", "0 1 1", "0 1 1 x",
                              "0 1 1 1 extra", "999999999999999999999 1 1 1"})
      rejects(header + record + "\n");
    rejects(header);
    rejects("0 1 1 1\n");
    rejects(header + "# vertices=4\n0 1 1 1\n");
    rejects("# spine_real_slice_version=2\n" + header + "0 1 1 1\n");
    rejects("# spine_real_slice_version=1\n# case=x\n# vertices=65535\n"
            "# columns=src dst weight diff\n0 1 1 1\n");
    std::cout << "ordered G input: order preserved and invalid records rejected\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
