#include "spine_sim/routed_regraph_fixture.hpp"

#include <fstream>
#include <set>

namespace spine::sim {
namespace {
class Reader {
public:
  explicit Reader(const std::string &path) : stream(path, std::ios::binary | std::ios::ate) {
    if (!stream) throw std::invalid_argument("cannot open routed fixture");
    const auto size = stream.tellg();
    if (size < 28 || size % 4) throw std::invalid_argument("invalid routed fixture size");
    remaining = static_cast<std::uint64_t>(size) / 4;
    stream.seekg(0);
  }
  std::uint32_t word() {
    if (!remaining) throw std::invalid_argument("truncated routed fixture");
    --remaining;
    unsigned char bytes[4];
    if (!stream.read(reinterpret_cast<char *>(bytes), 4))
      throw std::invalid_argument("failed routed fixture read");
    return std::uint32_t(bytes[0]) | std::uint32_t(bytes[1]) << 8 |
           std::uint32_t(bytes[2]) << 16 | std::uint32_t(bytes[3]) << 24;
  }
  void require(std::uint64_t count) const {
    if (count > remaining) throw std::invalid_argument("truncated routed fixture allocation");
  }
  std::uint64_t remaining{};
private:
  std::ifstream stream;
};
}

RoutedReGraphFixture load_routed_regraph_fixture(const std::string &path) {
  Reader input(path);
  if (input.word() != 0x4b345331U || input.word() != 1)
    throw std::invalid_argument("unsupported routed fixture ABI");
  RoutedReGraphFixture f;
  const auto vertices = input.word(), partitions = input.word();
  f.cache_segments = input.word();
  f.expected_rounds = input.word();
  const auto active_count = input.word();
  if (!vertices || partitions != (std::uint64_t(vertices) + 65535) / 65536 ||
      partitions > 255 || !f.cache_segments || !f.expected_rounds || active_count > vertices)
    throw std::invalid_argument("invalid routed fixture geometry");
  input.require(std::uint64_t(vertices) * 3 + active_count + std::uint64_t(partitions) * (2 + 2ULL * vertices));
  f.layout.vertices = vertices;
  f.layout.partition_vertices = 65536;
  f.internal_to_external.resize(vertices);
  f.initial.primary.resize(vertices);
  f.expected.resize(vertices);
  std::vector<bool> seen(vertices);
  for (auto &value : f.internal_to_external) {
    value = input.word();
    if (value >= vertices || seen[value]) throw std::invalid_argument("fixture mapping is not a bijection");
    seen[value] = true;
  }
  for (auto &value : f.initial.primary) value = input.word();
  std::set<std::uint32_t> active;
  for (std::size_t i = 0; i < active_count; ++i) {
    const auto value = input.word();
    if (value >= vertices || !active.insert(value).second)
      throw std::invalid_argument("invalid fixture active vertex");
    f.initial.active_vertices.push_back(value);
  }
  for (auto &value : f.expected) value = input.word();
  for (std::size_t p = 0; p < partitions; ++p) {
    f.physical_updates.push_back(input.word());
    const auto slots = input.word();
    if (!slots || slots % 16) throw std::invalid_argument("invalid fixture PMA slots");
    input.require(2ULL * vertices + slots);
    GraSuPmaLayout part;
    part.vertices = vertices;
    part.destination_base = p * 65536;
    part.destination_vertices = std::min<std::size_t>(65536, vertices - part.destination_base);
    part.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
    part.row_slot_bounds.resize(vertices);
    for (auto &[begin, end] : part.row_slot_bounds) { begin = input.word(); end = input.word(); }
    part.segments.resize(slots / 16);
    for (auto &segment : part.segments) for (auto &value : segment) value = input.word();
    f.layout.partitions.push_back(std::move(part));
  }
  if (input.remaining) throw std::invalid_argument("trailing routed fixture data");
  return f;
}
} // namespace spine::sim
