#pragma once

#include <algorithm>
#include <fstream>
#include <set>

namespace grasu_host_control {
struct Input {
  unsigned vertices;
  std::vector<unsigned long> initial, updates;
  std::set<unsigned long> final_edges;
};
inline Input inspect(const char* path) {
  std::ifstream stream(path); std::uint64_t vertices, initial, updates;
  require(bool(stream >> vertices >> initial >> updates), "G host input header");
  require(vertices > 0 && vertices <= 262208 && initial <= 524416 && updates <= 524416, "G host input extent");
  Input result{unsigned(vertices), {}, {}, {}};
  for (std::uint64_t i = 0; i < initial + updates; ++i) {
    std::uint64_t source, destination, operation = 1;
    require(bool(stream >> source >> destination) && source < vertices && destination < vertices, "G host input vertex");
    if (i >= initial) require(bool(stream >> operation) && operation <= 1, "G host input operation");
    auto edge = (source << 32) | destination;
    if (i < initial) {
      require(result.final_edges.insert(edge).second, "G initial duplicate"); result.initial.push_back(edge);
    } else {
      if (operation) require(result.final_edges.insert(edge).second, "G duplicate insertion");
      else require(result.final_edges.erase(edge) == 1, "G absent deletion");
      result.updates.push_back(edge | (std::uint64_t(!operation) << 63));
    }
  }
  std::string trailing; require(!(stream >> trailing), "G host input trailing fields");
  return result;
}
inline std::uint64_t mapped(std::uint64_t edge, const std::vector<unsigned>& mapping) {
  return (edge & EMPTY) | (std::uint64_t(mapping.at((edge & ~EMPTY) >> 32)) << 32) | mapping.at(edge & 0xffffffffu);
}
inline void word64(std::ostream& output, std::uint64_t value) {
  grasu_control::word(output, value); grasu_control::word(output, value >> 32);
}
template<class Values> inline void capture(const std::string& directory, const char* name, const Values& values, unsigned bytes) {
  std::ofstream stream(directory + "/" + name, std::ios::binary); require(stream.is_open(), "G host capture open");
  for (auto value : values) {
    if (bytes == 4) grasu_control::word(stream, value);
    else word64(stream, value);
  }
  stream.close(); require(stream.good(), "G host capture write");
}
}  // namespace grasu_host_control
