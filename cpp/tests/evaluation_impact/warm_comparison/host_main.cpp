#include <chrono>
#include <fstream>
#include <iostream>
#include <string>

#include "host_preparation.hpp"

namespace wh = warm_host;
namespace {
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

void self_test() {
  const std::vector<wh::GraSuEdge> updates{{3, 65537, 4095, false}, {1, 2, 1, false},
      {3, 65536, 2, false}, {3, 65539, 3, false}, {3, 65540, 4, false}, {3, 65541, 5, false}};
  wh::validate(70000, updates);
  const auto packed = wh::prepare_spine(updates);
  const auto decoded = wh::decode_spine_sort_edges(packed);
  require(decoded.size() == updates.size() && decoded.front().src == 1 && decoded[1].dst == 65536,
          "Spine sorting or ABI failure");
  auto sorted = updates;
  std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
    return std::tie(a.source, a.destination) < std::tie(b.source, b.destination);
  });
  for (std::size_t i = 0; i < decoded.size(); ++i)
    require(decoded[i] == wh::SpineEdgeRecord{sorted[i].source, sorted[i].destination, sorted[i].weight, 1},
            "Spine complete round-trip failure");
  const auto gr = wh::prepare_grasu(70000, updates);
  require(gr.shards.size() == 2 && gr.source_seeds == std::vector<std::uint32_t>{1, 3},
          "GraSU partition or seed failure");
  std::vector<std::size_t> counts(2);
  for (const auto& edge : updates) {
    const auto shard = edge.destination / wh::kPartitionVertices;
    const auto index = counts[shard]++;
    const auto word = gr.shards[shard][index % 4][index / 4];
    const auto low = static_cast<std::uint32_t>(word);
    require((word >> 32) == edge.source && wh::decode_grasu_pma_destination(low) +
        shard * wh::kPartitionVertices == edge.destination && wh::decode_grasu_pma_weight(low) == edge.weight,
        "GraSU four-lane complete round-trip failure");
  }
  require(gr.shards[0][3] == std::vector<std::uint64_t>{0}, "missing native empty-lane padding");
  for (const auto& bad : std::vector<wh::GraSuEdge>{{70000, 0, 1, false}, {0, 70000, 1, false},
      {0, 1, 0, false}, {0, 1, 4096, false}, {0, 1, 1, true}}) {
    bool rejected = false;
    try { wh::validate(70000, {bad}); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "invalid common ABI accepted");
  }
}

template<class Prepare> double measure(Prepare prepare, std::size_t iterations) {
  const auto begin = std::chrono::steady_clock::now();
  for (std::size_t i = 0; i < iterations; ++i) {
    auto prepared = prepare();
    // Escape the whole output without adding checksum traversal to the timed interval.
    asm volatile("" : : "g"(&prepared) : "memory");
  }
  const auto elapsed = std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now() - begin);
  return elapsed.count() / iterations;
}

void print_samples(const char* name, const std::vector<double>& samples) {
  std::cout << '"' << name << "\":[";
  for (std::size_t i = 0; i < samples.size(); ++i) std::cout << (i ? "," : "") << samples[i];
  std::cout << ']';
}
}  // namespace

int main(int argc, char** argv) try {
  self_test();
  if (argc == 2 && std::string(argv[1]) == "--self-test") {
    std::cout << "HOST_SELF_TEST PASS\n";
    return 0;
  }
  require(argc == 2, "usage: warm_host_preparation batch.txt | --self-test");
  std::ifstream file(argv[1]);
  std::uint32_t vertices{};
  std::size_t count{};
  require(bool(file >> vertices >> count) && count > 0 && count <= 65536, "invalid batch header");
  std::vector<wh::GraSuEdge> updates;
  for (std::size_t i = 0; i < count; ++i) {
    std::uint32_t src{}, dst{}, weight{};
    require(bool(file >> src >> dst >> weight) && weight <= wh::kGraSuPmaWeightMask, "invalid record");
    updates.push_back({src, dst, static_cast<std::uint16_t>(weight), false});
  }
  std::string trailing;
  require(!(file >> trailing), "unexpected trailing input");
  wh::validate(vertices, updates);
  const auto spine = [&] { return wh::prepare_spine(updates); };
  const auto gr = [&] { return wh::prepare_grasu(vertices, updates); };
  for (unsigned i = 0; i < 20; ++i) { (void)measure(spine, 1000); (void)measure(gr, 1000); }
  std::vector<double> s(100), g(100);
  for (std::size_t i = 0; i < s.size(); ++i) {
    if (i % 2) { s[i] = measure(spine, 1000); g[i] = measure(gr, 1000); }
    else { g[i] = measure(gr, 1000); s[i] = measure(spine, 1000); }
  }
  std::cout.precision(17);
  std::cout << "HOST_PREPARATION {\"vertices\":" << vertices << ",\"updates\":[";
  for (std::size_t i = 0; i < updates.size(); ++i)
    std::cout << (i ? "," : "") << '[' << updates[i].source << ',' << updates[i].destination << ',' << updates[i].weight << ']';
  const auto prepared = gr();
  std::size_t packed_words = 0;
  for (const auto& shard : prepared.shards) for (const auto& lane : shard) packed_words += lane.size();
  std::cout << "],\"partition_vertices\":65536,\"iterations_per_sample\":1000,\"warmup_blocks\":20,"
      "\"self_test\":true,\"source_seed_count\":" << prepared.source_seeds.size()
      << ",\"spine_payload_bytes\":" << spine().size() << ",\"gr_lane_allocation_bytes\":" << packed_words * 8 << ',';
  print_samples("spine_ns_per_batch", s); std::cout << ','; print_samples("gr_ns_per_batch", g);
  std::cout << "}\n";
  return 0;
} catch (const std::exception& error) {
  std::cerr << error.what() << '\n';
  return 1;
}
