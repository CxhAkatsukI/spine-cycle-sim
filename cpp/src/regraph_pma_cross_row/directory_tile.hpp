#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace spine::sim::detail {

// The synthesized candidate loads one bounded burst before its edge loop.
class PmaDirectoryTile {
public:
  static constexpr std::size_t kRows = 128;
  static constexpr std::uint64_t kLoadPipelineCycles = 3;
  explicit PmaDirectoryTile(std::size_t rows = kRows);
  [[nodiscard]] static std::size_t count(std::size_t base, std::size_t vertices, std::size_t rows = kRows);
  [[nodiscard]] static std::size_t bytes(std::size_t base, std::size_t vertices, std::size_t rows = kRows);
  bool load(std::span<const std::uint8_t> payload, std::size_t count, std::size_t slots);
  [[nodiscard]] std::uint64_t row(std::size_t offset) const;

private:
  std::vector<std::uint64_t> rows_;
};

} // namespace spine::sim::detail
