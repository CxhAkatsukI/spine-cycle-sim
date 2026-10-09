#pragma once

#include <array>
#include <cstdint>
#include <fstream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace original_regraph_layout {

inline void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

class WordFile {
 public:
  explicit WordFile(const std::string& name) : stream_(name, std::ios::binary) {
    require(stream_.good(), "cannot create layout word file");
  }
  void word(std::uint32_t value) {
    std::array<char, 4> bytes;
    for (unsigned byte = 0; byte < 4; ++byte) bytes[byte] = static_cast<char>((value >> (byte * 8)) & 255u);
    stream_.write(bytes.data(), bytes.size());
    ++words_;
  }
  template <typename Range> void append(const Range& values) {
    for (const auto value : values) word(static_cast<std::uint32_t>(value));
  }
  void close() { stream_.close(); require(stream_.good(), "layout capture close failed"); }
  std::uint64_t words() const { return words_; }
 private:
  std::ofstream stream_;
  std::uint64_t words_{};
};

inline std::vector<unsigned> permutation(const CSR& csr, unsigned seed) {
  std::vector<unsigned> new_to_old(csr.vertexNum);
  std::iota(new_to_old.begin(), new_to_old.end(), 0u);
  std::sort(new_to_old.begin(), new_to_old.end(), [&](unsigned left, unsigned right) {
    return csr.rpai[left + 1] - csr.rpai[left] > csr.rpai[right + 1] - csr.rpai[right];
  });
  std::srand(seed);
  const auto bucket = new_to_old.size() / ((csr.vertexNum + PARTITION_SIZE - 1) / PARTITION_SIZE);
  for (std::size_t begin = 0; begin + bucket <= new_to_old.size() && bucket; begin += bucket) {
    if (begin / bucket == static_cast<std::size_t>((csr.vertexNum + PARTITION_SIZE - 1) / PARTITION_SIZE)) break;
    std::random_shuffle(new_to_old.begin() + begin, new_to_old.begin() + begin + bucket);
  }
  std::vector<unsigned> old_to_new(csr.vertexNum);
  for (unsigned vertex = 0; vertex < new_to_old.size(); ++vertex) old_to_new[new_to_old[vertex]] = vertex;
  return old_to_new;
}

inline void check_reordered(const std::vector<int>& offsets, const std::vector<int>& destinations,
                            const std::vector<unsigned>& mapping, const CSR& csr) {
  for (unsigned old = 0; old < mapping.size(); ++old) {
    const auto reordered = mapping[old];
    require(offsets[old + 1] - offsets[old] == csr.rpao[reordered + 1] - csr.rpao[reordered],
            "reorder changed outdegree");
    for (int index = offsets[old]; index < offsets[old + 1]; ++index) {
      require(csr.ciao[csr.rpao[reordered] + index - offsets[old]] ==
              static_cast<int>(mapping[destinations[index]]), "reorder changed graph topology");
    }
  }
}

}  // namespace original_regraph_layout
