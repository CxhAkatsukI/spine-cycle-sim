#pragma once

#include <filesystem>
#include <fstream>
#include <map>

#include "system.hpp"

namespace grasu_test {
inline std::vector<std::uint8_t> read_file(const std::filesystem::path& path) {
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  if (!file) throw std::runtime_error("cannot read G fixture: " + path.string());
  const auto size = file.tellg();
  if (size < 0 || size > (128ll << 20)) throw std::runtime_error("G fixture size bound");
  std::vector<std::uint8_t> result(static_cast<std::size_t>(size));
  file.seekg(0); file.read(reinterpret_cast<char*>(result.data()), result.size());
  if (!file) throw std::runtime_error("short G fixture read");
  return result;
}
inline void write_file(const std::filesystem::path& path, std::span<const std::uint8_t> data) {
  std::ofstream file(path, std::ios::binary);
  file.write(reinterpret_cast<const char*>(data.data()), data.size());
  if (!file) throw std::runtime_error("G capture write failed");
}

struct Batch {
  std::vector<std::uint64_t> updates;
  std::map<std::uint32_t, g::Segment> expected;
};
struct Fixture {
  explicit Fixture(const std::filesystem::path& root) : initial(read_file(root / "initial.u32le")) {
    if (initial.size() != kSegments * 64ull) throw std::runtime_error("G initial geometry");
    auto data = read_file(root / "batches.bin");
    std::size_t offset = 0;
    auto word = [&](std::size_t bytes) {
      if (offset + bytes > data.size()) throw std::runtime_error("truncated G batch fixture");
      auto result = g::little_word(std::span<const std::uint8_t>(data).subspan(offset, bytes));
      offset += bytes; return result;
    };
    const auto count = word(4);
    if (!count || count > 16) throw std::runtime_error("G batch count");
    for (std::size_t batch = 0; batch < count; ++batch) {
      Batch next;
      auto updates = word(4);
      if (updates > 65536) throw std::runtime_error("G fixture update bound");
      while (updates--) next.updates.push_back(word(8));
      auto patches = word(4);
      if (patches > kSegments) throw std::runtime_error("G patch bound");
      while (patches--) {
        const auto index = word(4);
        if (index >= kSegments || next.expected.contains(index)) throw std::runtime_error("G patch index");
        g::Segment values;
        for (auto& value : values) value = word(4);
        next.expected.emplace(index, values);
      }
      batches.push_back(std::move(next));
    }
    if (offset != data.size()) throw std::runtime_error("G fixture trailing bytes");
    binary = read_file(root / "binary.u64le"); rows = read_file(root / "rows.u64le");
    if (binary.size() != kSegments * 8ull || rows.size() != 16) throw std::runtime_error("G lookup geometry");
  }
  void initialize(System& model) const {
    for (unsigned bank = 0; bank < 4; ++bank) {
      std::vector<std::uint8_t> half(kHalf * 64ull);
      for (unsigned index = 0; index < kHalf; ++index)
        std::copy_n(initial.begin() + (index * 2 + bank / 2) * 64ull, 64, half.begin() + index * 64ull);
      auto& memory = *model.memory.backend;
      memory.initialize_payload(bank, 0, half);
      memory.fill_payload(bank, half.size(), 64, 0xa5);
      memory.initialize_payload(bank, kBinary, binary);
      memory.initialize_payload(bank, kRows, rows);
    }
  }
  std::vector<std::uint8_t> verify(System& model, const Batch& batch, const std::filesystem::path& capture) const {
    std::vector<std::uint8_t> merged(initial.size());
    for (unsigned bank = 0; bank < 4; ++bank) {
      auto actual = model.memory.backend->inspect_payload(bank, 0, kHalf * 64ull + 64);
      for (unsigned index = 0; index < kHalf; ++index) {
        const unsigned global = index * 2 + bank / 2;
        const unsigned owner = (global & 1) * 2 + (index >= g::kHotSegments);
        auto expected = g::decode_segment(std::span<const std::uint8_t>(initial).subspan(global * 64ull, 64));
        if (bank == owner && batch.expected.contains(global)) expected = batch.expected.at(global);
        if (g::decode_segment(std::span<const std::uint8_t>(actual).subspan(index * 64ull, 64)) != expected)
          throw std::runtime_error("G full buffer mismatch bank=" + std::to_string(bank) + " segment=" + std::to_string(global));
        if (bank == owner) std::copy_n(actual.begin() + index * 64ull, 64, merged.begin() + global * 64ull);
      }
      if (!std::all_of(actual.end() - 64, actual.end(), [](auto byte) { return byte == 0xa5; }))
        throw std::runtime_error("G buffer end guard changed");
      if (!capture.empty()) write_file(capture / ("bank" + std::to_string(bank) + ".bin"), actual);
    }
    return merged;
  }
  std::vector<std::uint8_t> initial, binary, rows;
  std::vector<Batch> batches;
};
}  // namespace grasu_test
