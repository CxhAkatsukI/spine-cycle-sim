#pragma once

#include <hls_stream.h>

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

inline void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct PrefixComplete {};

// The upstream free-running merger has no return condition. Observe exactly
// one partition without changing its source or treating the cut as termination.
template <typename T>
class PartitionOutput final : public hls::stream_delegate<sizeof(T)> {
public:
  explicit PartitionOutput(std::size_t count) : count_(count) {}

  bool read(void *) override {
    throw std::runtime_error("output-only observer");
  }
  bool read_nb(void *) override {
    throw std::runtime_error("output-only observer");
  }
  std::size_t size() override { return 0; }

  void write(const void *value) override {
    values.push_back(*static_cast<const T *>(value));
    require(values.size() <= count_, "merger emitted excess output");
    if (values.size() == count_) {
      throw PrefixComplete{};
    }
  }

  std::vector<T> values;

private:
  std::size_t count_;
};

inline std::uint32_t oracle_pr(std::uint32_t sum, std::uint32_t degree,
                               std::uint32_t argument) {
  const auto score = argument + ((108u * sum) >> 7);
  const auto inverse_degree = degree ? 65536u / degree : 0;
  return (score * inverse_degree) >> 16;
}
