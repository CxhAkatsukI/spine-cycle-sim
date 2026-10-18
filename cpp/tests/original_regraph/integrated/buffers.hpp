#pragma once

#include "../hardware/model.hpp"
#include <limits>
#include <string>

namespace original_r_k4 {
namespace rb = original_r_board;
using rb::Words;
using rb::require;
inline constexpr std::size_t no_shard = std::numeric_limits<std::size_t>::max();
inline constexpr std::uint64_t bank_bytes = 512ull << 20;
inline constexpr std::uint64_t buffer_bytes = 256ull << 20;

struct BankLedger {
  std::array<std::uint64_t, 32> bytes{};
  void admit(std::size_t bank, std::uint64_t allocation_bytes) {
    require(bank < bytes.size(), "invalid HBM bank");
    auto& total = bytes.at(bank);
    require(allocation_bytes < buffer_bytes &&
            allocation_bytes <= bank_bytes && total <= bank_bytes - allocation_bytes,
            "guarded buffer or aggregate bank capacity exceeded");
    total += allocation_bytes;
  }
};

// Words include allocation slack and a separate 64-byte trailing canary.
struct Buffer {
  std::string name;
  std::size_t shard{no_shard}, bank{}, logical_words{}, allocated_words{};
  Words initial, expected;

  const Words& target() const { return expected.empty() ? initial : expected; }
  void verify(const Words& actual) const {
    require(actual == target(), "full buffer, allocation slack or trailing guard mismatch");
  }
};

inline Buffer make_buffer(std::string name, std::size_t shard, std::size_t bank,
                          Words words, std::size_t allocated_bytes) {
  require(allocated_bytes % 4 == 0 && words.size() <= allocated_bytes / 4 &&
          allocated_bytes < buffer_bytes - rb::guard_words * 4,
          "invalid guarded allocation extent");
  Buffer result{std::move(name), shard, bank, words.size(), allocated_bytes / 4,
                std::move(words), {}};
  result.initial.resize(result.allocated_words + rb::guard_words, rb::guard);
  return result;
}

inline Words split_words(const std::vector<std::uint64_t>& values) {
  Words result;
  result.reserve(values.size() * 2);
  for (const auto value : values) {
    result.push_back(static_cast<std::uint32_t>(value));
    result.push_back(static_cast<std::uint32_t>(value >> 32));
  }
  return result;
}
}  // namespace original_r_k4
