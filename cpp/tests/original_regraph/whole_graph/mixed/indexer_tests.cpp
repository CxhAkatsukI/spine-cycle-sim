#include <iostream>

#include "resources.hpp"
#include "spine_sim/original_regraph/mixed_indexer.hpp"
#include "spine_sim/original_regraph/big_merge.hpp"

namespace mt = original_regraph_mixed_test;

std::vector<mt::rg::PropertyWrite> run(bool reverse, unsigned little_delay) {
  mt::Resources memory(64);
  auto* little = memory.stream<mt::rg::PropertyLine>("little", 2);
  auto* big = memory.stream<mt::rg::PropertyLine>("big", 2);
  auto* output = memory.stream<mt::rg::PropertyWrite>("output", 1);
  auto* indexer = memory.make<mt::rg::MixedWriteIndexer>("indexer", memory.clock, *little, *big, *output);
  memory.register_components(reverse); indexer->begin(2, 2);
  std::vector<mt::rg::PropertyWrite> result;
  unsigned sent_little = 0, sent_big = 0;
  for (unsigned cycle = 0; cycle < 1000; ++cycle) {
    if (cycle >= little_delay && sent_little < 2 && !little->full()) {
      mt::rg::PropertyLine line{}; line.fill(10 + sent_little++);
      mt::require(little->try_push(line), "Little source ownership");
    }
    if (sent_big < 2 && !big->full()) {
      mt::rg::PropertyLine line{}; line.fill(20 + sent_big++);
      mt::require(big->try_push(line), "Big source ownership");
    }
    if (cycle > 20 && cycle % 7 == 0 && !output->empty()) {
      mt::rg::PropertyWrite packet; mt::require(output->try_pop(packet), "sink ownership"); result.push_back(packet);
    }
    memory.scheduler.step();
    if (indexer->finished() && memory.drained()) break;
  }
  mt::require(result.size() == 5 && result.back().end && indexer->finished(), "mixed indexer failed finite drain");
  const std::array<unsigned, 4> priority{0, 1, 2, 3}, delayed{2, 3, 0, 1};
  for (unsigned index = 0; index < 4; ++index) {
    const auto expected = little_delay ? delayed[index] : priority[index];
    mt::require(!result[index].end && result[index].index == expected &&
        std::all_of(result[index].data.begin(), result[index].data.end(), [expected](auto v) {
          return v == (expected < 2 ? 10 + expected : 20 + expected - 2);
        }), "mixed priority or independent address counter changed");
  }
  indexer->begin(0, 0);
  for (unsigned cycle = 0; cycle < 20 && !indexer->finished(); ++cycle) memory.scheduler.step();
  mt::rg::PropertyWrite end;
  mt::require(output->try_pop(end) && end.end, "empty mixed iteration must emit one end");
  memory.scheduler.step();
  mt::require(memory.drained(), "mixed empty restart conservation"); return result;
}

int main() {
  try {
    for (const unsigned delay : {0u, 10u}) {
      const auto first = run(false, delay), reverse = run(true, delay);
      mt::require(first.size() == reverse.size(), "reverse mixed output extent");
      for (unsigned i = 0; i < first.size(); ++i) mt::require(first[i].data == reverse[i].data &&
          first[i].index == reverse[i].index && first[i].end == reverse[i].end, "reverse mixed registration changed output");
    }
    mt::Resources memory(64);
    auto* little = memory.stream<mt::rg::PropertyLine>("l", 1);
    auto* big = memory.stream<mt::rg::PropertyLine>("b", 1);
    auto* output = memory.stream<mt::rg::PropertyWrite>("out", 1);
    unsigned rejected = 0;
    const auto rejection = [&](auto action) { try { action(); } catch (const std::exception&) { ++rejected; } };
    rejection([&] { mt::rg::MixedWriteIndexer bad("bad", memory.clock, *little, *little, *output); });
    auto* indexer = memory.make<mt::rg::MixedWriteIndexer>("good", memory.clock, *little, *big, *output);
    rejection([&] { indexer->begin(UINT32_MAX, 1); });
    indexer->begin(0, 1);
    rejection([&] { indexer->begin(0, 0); });
    mt::require(little->try_push({}), "negative source ownership");
    memory.register_components(); memory.scheduler.step();
    rejection([&] { memory.scheduler.step(); });
    mt::require(rejected == 4, "mixed rejection gates incomplete");
    std::cout << "MIXED_INDEXER_PASS priority delayed_big reverse finite_backpressure restart rejections=4\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
