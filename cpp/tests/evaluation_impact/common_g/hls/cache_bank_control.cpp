#include "cache_bank.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
using Segment = std::array<std::uint32_t, 16>;
struct Operation { unsigned row; std::uint32_t key; bool erase; };

void apply(Segment& row, const Operation& op) {
  const auto found = std::lower_bound(row.begin(), row.end(), op.key);
  if (op.erase) {
    if (found == row.end() || *found != op.key) throw std::runtime_error("invalid test delete");
    std::move(found + 1, row.end(), found);
    row.back() = 0x80000000u;
  } else {
    if (found == row.end() || *found == op.key || row.back() < 0x80000000u)
      throw std::runtime_error("invalid test insert");
    std::move_backward(found, row.end() - 1, row.end());
    *found = op.key;
  }
}

void check(unsigned count, bool conflict, bool positions) {
  std::vector<Segment> oracle(cache_bank_depth);
  std::vector<CacheWord> memory(cache_bank_depth);
  for (unsigned row = 0; row < cache_bank_depth; ++row) {
    for (unsigned lane = 0; lane < 16; ++lane) {
      const std::uint32_t value = lane < 15 ? 2 * lane + 2
          : row % 2 ? 0xFFFFFFFFu : 0x80000000u;
      oracle[row][lane] = value;
      memory[row].range(lane * 32 + 31, lane * 32) = value;
    }
  }
  hls::stream<CacheUpdate> updates;
  std::vector<Operation> operations;
  if (positions) {
    for (unsigned pos = 0; pos < 16; ++pos) {
      const unsigned row = pos % 2 ? cache_bank_depth - 1 : 0;
      operations.push_back({row, 2 * pos + 1, false});
      operations.push_back({row, 2 * pos + 1, true});
    }
    for (const std::uint32_t key : {0u, 0x7FFFFFFFu, 0x7FF80000u, 0x7FFFFu}) {
      operations.push_back({cache_bank_depth - 1, key, false});
      operations.push_back({cache_bank_depth - 1, key, true});
    }
  } else {
    for (unsigned i = 0; i < count; ++i) {
      const unsigned row = conflict ? cache_bank_depth - 1 : (i / 2 * 127) % cache_bank_depth;
      operations.push_back({row, 17, bool(i & 1)});
    }
  }
  for (const auto& op : operations) {
    CacheUpdate word = std::uint32_t(op.row << 9);
    word.range(63, 32) = op.key;
    word[95] = op.erase;
    updates.write(word);
    apply(oracle[op.row], op);
  }
  updates.write(CacheUpdate(0xFFFFFFFFFFFFFFFFull));
  cache_bank_probe(memory.data(), updates);
  if (!updates.empty()) throw std::runtime_error("update stream not drained");
  for (unsigned row = 0; row < cache_bank_depth; ++row) {
    for (unsigned lane = 0; lane < 16; ++lane) {
      if (memory[row].range(lane * 32 + 31, lane * 32).to_uint() != oracle[row][lane])
        throw std::runtime_error("complete bank state mismatch at " + std::to_string(row));
    }
  }
  std::cout << "CACHE_BANK_PASS updates=" << operations.size()
            << " conflict=" << conflict << " positions=" << positions << '\n';
}
}  // namespace

int main() {
  try {
    check(0, false, false);
    check(0, true, true);
    check(64, true, false);
    check(256, true, false);
    check(1024, true, false);
    check(1024, false, false);
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
