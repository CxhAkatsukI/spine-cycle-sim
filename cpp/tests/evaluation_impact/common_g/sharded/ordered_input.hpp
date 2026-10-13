#pragma once

#include "spine_sim/spine_l0.hpp"

#include <charconv>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace sharded_g_test {
// This experiment consumes chronological mutations, not sorted Spine maintenance.
inline spine::sim::SpineEdgeSlice read_ordered_g_slice(std::istream &input) {
  spine::sim::SpineEdgeSlice slice;
  bool version = false, columns = false, vertices = false, name = false;
  std::string line;
  std::size_t number = 0;
  const auto fail = [&number](const std::string &reason) {
    throw std::runtime_error("ordered G slice line " + std::to_string(number) + ": " + reason);
  };
  while (std::getline(input, line)) {
    ++number;
    const auto first = line.find_first_not_of(" \t\r");
    if (first == std::string::npos) continue;
    const std::string_view text(line.data() + first, line.find_last_not_of(" \t\r") - first + 1);
    if (text.front() == '#') {
      if (text == "# spine_real_slice_version=1" && !version) version = true;
      else if (text == "# columns=src dst weight diff" && !columns) columns = true;
      else if (text.starts_with("# case=") && !name && text.size() > 7) {
        slice.case_name = std::string(text.substr(7));
        name = true;
      } else if (text.starts_with("# vertices=") && !vertices) {
        const auto value = text.substr(11);
        const auto parsed = std::from_chars(value.data(), value.data() + value.size(), slice.vertices);
        if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() ||
            slice.vertices == 0 || slice.vertices >= 65535) fail("invalid one-shard vertex count");
        vertices = true;
      } else fail("unsupported or duplicate metadata");
      continue;
    }
    if (!version || !columns || !vertices || !name) fail("four slice headers must precede records");
    std::istringstream record{std::string(text)};
    std::int64_t src{}, dst{}, weight{}, diff{};
    std::string extra;
    if (!(record >> src >> dst >> weight >> diff) || record >> extra ||
        src < 0 || dst < 0 || static_cast<std::uint64_t>(src) >= slice.vertices ||
        static_cast<std::uint64_t>(dst) >= slice.vertices || weight <= 0 || weight > 4095 ||
        (diff != -1 && diff != 1)) fail("expected in-range src dst weight unit-diff");
    slice.edges.push_back({static_cast<std::uint32_t>(src), static_cast<std::uint32_t>(dst),
                           static_cast<std::uint16_t>(weight), static_cast<std::int16_t>(diff)});
  }
  if (input.bad() || slice.edges.empty()) fail("unreadable or empty input");
  return slice;
}

inline spine::sim::SpineEdgeSlice load_ordered_g_slice(const std::string &path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open ordered G slice: " + path);
  try {
    return read_ordered_g_slice(input);
  } catch (const std::runtime_error &error) {
    throw std::runtime_error(path + ": " + error.what());
  }
}
} // namespace sharded_g_test
