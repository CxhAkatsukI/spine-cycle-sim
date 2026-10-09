#include "big_frontend_execution.hpp"

#include <functional>

namespace {
using namespace original_regraph_big_frontend_test;
template <typename Exception> void rejected(const std::function<void()>& call) {
  try { call(); } catch (const Exception&) { return; }
  throw std::runtime_error("Big frontend invalid operation accepted");
}
void contracts() {
  rejected<std::invalid_argument>([] { Network bad({.live=0}); });
  rejected<std::invalid_argument>([] { Network bad({.property_vertices=1}); });
  rejected<std::invalid_argument>([] { Network bad({.property_vertices=16}); execute(bad, 1); });
  Network unsorted;
  auto input = fixture(1); input[0][1].source = 100; input[0][2].source = 1;
  unsorted.begin(input);
  rejected<std::invalid_argument>([&] { for (unsigned cycle = 0; cycle < 1000; ++cycle) unsorted.memory.scheduler.step(); });
  Network domain;
  input = fixture(4); for (auto& edge : input[0]) edge.source = 1u << 30;
  domain.begin(input);
  rejected<std::invalid_argument>([&] { for (unsigned cycle = 0; cycle < 1000; ++cycle) domain.memory.scheduler.step(); });
  Network ack;
  ack.source->begin_partitions(1);
  require(ack.source_port.responses->try_push({42, spine::sim::MemoryOperation::kRead, true, std::vector<std::uint8_t>(64)}), "negative acknowledgement push");
  rejected<std::logic_error>([&] { for (unsigned cycle = 0; cycle < 3; ++cycle) ack.memory.scheduler.step(); });
  Network restart;
  restart.begin(fixture(0));
  rejected<std::logic_error>([&] { restart.source->begin_partitions(1); });
  rejected<std::logic_error>([&] { restart.scatter->begin_partition(1); });
  std::cout << "BIG_FRONTEND_REJECTIONS {\"checks\":8}\n";
}
void matrix() {
  Network baseline;
  const auto first = execute(baseline, 1); report("sorted", first);
  Network reverse({.reverse=true});
  const auto reversed = execute(reverse, 1);
  require(first.cycles == reversed.cycles && first.capacity_stalls == reversed.capacity_stalls &&
      first.response_stalls == reversed.response_stalls && first.scatter_stalls == reversed.scatter_stalls &&
      first.fork_stalls == reversed.fork_stalls, "Big frontend reversed registration changed counters"); report("reverse", reversed);
  const auto repeated = execute(baseline, 1);
  require(repeated.cycles == first.cycles && repeated.capacity_stalls == first.capacity_stalls &&
      repeated.response_stalls == first.response_stalls && repeated.scatter_stalls == first.scatter_stalls &&
      repeated.fork_stalls == first.fork_stalls, "Big frontend reuse changed counters"); report("reused", repeated);
  for (unsigned id : {0u, 2u, 3u, 4u, 5u}) {
    Network net({.destination_offset=id == 5 ? 65536u : 0u});
    const auto row = execute(net, id);
    if (id == 0 || id == 4) require(row.reads == 1, "Big line-zero compulsory read count");
    if (id == 2) require(row.cache_hits > row.reads, "Big last-cacheline hits not exercised");
    const std::array<const char*, 6> names{"line_zero", "sorted", "duplicate_lines", "gapped", "dummy_only", "offset_flags"};
    report(names[id], row);
  }
  Network latency({.latency=128}); const auto delayed = execute(latency, 1);
  require(delayed.cycles > first.cycles, "Big memory latency ignored"); report("latency128", delayed);
  Network narrow({.outstanding=1}); const auto serial = execute(narrow, 1);
  require(serial.cycles > first.cycles, "Big AXI outstanding ignored"); report("outstanding1", serial);
  Network one({.live=1}); const auto limited = execute(one, 1);
  require(limited.cycles > first.cycles && limited.capacity_stalls > first.capacity_stalls, "Big wrapper live capacity ignored"); report("live1", limited);
  Network pressure({.fifo_depth=1, .sink_start=10000, .sink_interval=7}); const auto stalled = execute(pressure, 1);
  require(stalled.cycles > first.cycles && stalled.scatter_stalls > 0 && stalled.fork_stalls > 0, "Big downstream pressure not exercised");
  report("depth1_slow_sink", stalled);
}
}  // namespace
int main() {
  try { contracts(); matrix(); return 0; }
  catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
