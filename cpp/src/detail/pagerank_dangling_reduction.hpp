#pragma once

#include <array>
#include <cstddef>

namespace spine::sim::detail {

// regraph_pagerank_{source_prepare,apply}: sixteen lanes, eight FP32 banks.
class PageRankDanglingReduction {
public:
  static constexpr std::size_t lanes = 16, banks = 8, cycles = lanes * banks;

  void add(std::size_t vertex, float value) {
    partials_[vertex % lanes][(vertex / lanes) % banks] += value;
  }
  [[nodiscard]] float partial(std::size_t step) const {
    return partials_[step / banks][step % banks];
  }

private:
  std::array<std::array<float, banks>, lanes> partials_{};
};

} // namespace spine::sim::detail
