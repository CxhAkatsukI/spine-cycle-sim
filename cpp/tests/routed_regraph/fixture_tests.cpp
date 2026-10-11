#include "spine_sim/routed_regraph_fixture.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>

namespace {
using namespace spine::sim;
void require(bool value) { if (!value) throw std::runtime_error("routed fixture gate failed"); }
std::vector<std::uint32_t> fixture() {
  std::vector<std::uint32_t> words{0x4b345331, 1, 129, 1, 131072, 1, 1};
  for (std::uint32_t v = 0; v < 129; ++v) words.push_back(v);
  for (std::uint32_t v = 0; v < 129; ++v) words.push_back(v ? 0xffffffffU : 0);
  words.push_back(0);
  for (std::uint32_t v = 0; v < 129; ++v) words.push_back(v ? 0xffffffffU : 0);
  words.insert(words.end(), {0, 16});
  for (std::uint32_t v = 0; v < 129; ++v) { words.push_back(v ? 16 : 0); words.push_back(16); }
  words.insert(words.end(), 16, kGraSuPmaEmpty);
  return words;
}
void write(const std::filesystem::path &path, const std::vector<std::uint32_t> &words) {
  std::ofstream file(path, std::ios::binary);
  for (auto value : words)
    for (unsigned byte = 0; byte < 4; ++byte) file.put(static_cast<char>(value >> (byte * 8)));
  file.flush();
  require(static_cast<bool>(file));
}
}

int main() {
  const auto path = std::filesystem::temp_directory_path() /
      ("routed-fixture-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  try {
    auto words = fixture();
    write(path, words);
    const auto f = load_routed_regraph_fixture(path.string());
    require(f.layout.vertices == 129 && f.layout.partitions.size() == 1 && f.expected_rounds == 1 &&
            f.cache_segments == 131072 && f.initial.active_vertices == std::vector<std::uint32_t>{0} &&
            f.layout.partitions[0].segments[0][0] == kGraSuPmaEmpty && f.expected[0] == 0 &&
            f.expected[128] == 0xffffffffU && f.internal_to_external[128] == 128);
    std::size_t rejected = 0;
    const auto reject = [&](std::vector<std::uint32_t> invalid) {
      write(path, invalid);
      try { (void)load_routed_regraph_fixture(path.string()); }
      catch (const std::invalid_argument &) { ++rejected; return; }
      throw std::runtime_error("invalid fixture admitted");
    };
    auto invalid = words; invalid[0] = 0; reject(invalid);
    invalid = words; invalid[1] = 2; reject(invalid);
    invalid = words; invalid[3] = 2; reject(invalid);
    invalid = words; invalid[4] = 0; reject(invalid);
    invalid = words; invalid[6] = 130; reject(invalid);
    invalid = words; invalid[8] = 0; reject(invalid);
    invalid = words; invalid[7 + 129 * 2] = 129; reject(invalid);
    invalid = words; invalid.pop_back(); reject(invalid);
    invalid = words; invalid.push_back(42); reject(invalid);
    invalid = words; invalid[7 + 129 * 3 + 1 + 1] = 17; reject(invalid);
    require(rejected == 10);
    std::filesystem::remove(path);
    std::cout << "PASS: routed fixture roundtrip and ten format/shape rejections\n";
  } catch (const std::exception &error) {
    std::filesystem::remove(path);
    std::cerr << error.what() << '\n';
    return 1;
  }
}
