#include "big_network.hpp"

#include <functional>
#include <iostream>

namespace {
using namespace original_regraph_test;
template <typename Exception>
void rejected(const std::function<void()>& operation) {
  try { operation(); } catch (const Exception&) { return; }
  throw std::runtime_error("Big invalid operation was not rejected");
}
void report(const char* id, const Observation& row) {
  std::cout << "BIG_CASE {\"id\":\"" << id << "\",\"cycles\":" << row.cycles
            << ",\"output_stalls\":" << row.output_stalls
            << ",\"capacity_stalls\":" << row.capacity_stalls
            << ",\"checked_words\":" << row.values.size() << "}\n";
}
void contracts() {
  Fifo<rg::RoutedUpdate> in("in", 0, 2), other("other", 0, 2), wrong("wrong", 1, 2);
  Fifo<rg::VertexPair> rows("rows", 0, 2);
  Fifo<rg::PropertyLine> lines("lines", 0, 2);
  rejected<std::invalid_argument>([&] { rg::BigOmegaSwitch invalid("bad", 0, 3, {&in, &other}, {&in, &other}); });
  rejected<std::invalid_argument>([&] { rg::BigOmegaSwitch invalid("bad", 0, 0, {&in, &in}, {&other, &wrong}); });
  rejected<std::invalid_argument>([&] { rg::BigOmegaSwitch invalid("bad", 0, 0, {&in, &other}, {&other, &wrong}); });
  rejected<std::invalid_argument>([&] { rg::BigGatherBank invalid("bad", 0, 8, in, rows); });
  rejected<std::invalid_argument>([&] { rg::BigGatherBank invalid("bad", 0, 0, wrong, rows); });
  rejected<std::invalid_argument>([&] { rg::BigGlobalMerge invalid("bad", 0, {}, lines); });
  rejected<std::invalid_argument>([&] { rg::BigGlobalMerge invalid("bad", 0, {&lines}, lines); });
  rg::BigGatherBank bank("bank", 0, 0, in, rows);
  bank.begin_partition();
  rejected<std::logic_error>([&] { bank.begin_partition(); });
  spine::sim::Scheduler scheduler;
  scheduler.add_clock_mhz("test", 210);
  scheduler.add_component(in); scheduler.add_component(rows); scheduler.add_component(bank);
  require(in.try_push({{1, 10}, false}), "negative fixture push");
  rejected<std::invalid_argument>([&] { for (unsigned cycle = 0; cycle < 20; ++cycle) scheduler.step(); });
  std::cout << "BIG_REJECTIONS {\"port_and_lifecycle_checks\":8,\"wrong_bank\":true}\n";
}
void executions() {
  const auto fixture = big_fixture(0);
  const auto expected = big_oracle(fixture);
  BigNetwork normal(3);
  const auto first = normal.run(fixture);
  require(first.values == expected, "Big normal output differs from oracle"); report("b3_registered", first);
  BigNetwork reverse(3, true);
  const auto reversed = reverse.run(fixture);
  require(reversed.values == first.values && reversed.cycles == first.cycles &&
      reversed.output_stalls == first.output_stalls && reversed.capacity_stalls == first.capacity_stalls,
      "Big registration order changed output/counters"); report("b3_reverse", reversed);
  const auto zero = normal.run(big_fixture(1));
  require(zero.values == big_oracle(big_fixture(1)), "Big URAM clear failed"); report("b3_reused_zero", zero);
  const auto repeated = normal.run(fixture);
  require(repeated.values == first.values && repeated.cycles == first.cycles &&
      repeated.output_stalls == first.output_stalls && repeated.capacity_stalls == first.capacity_stalls,
      "Big repeated partition changed results"); report("b3_reused_nonzero", repeated);
  const auto hot = big_fixture(2);
  BigNetwork hotspot(3);
  const auto hotrow = hotspot.run(hot);
  require(hotrow.values == big_oracle(hot), "Big hotspot/forwarding mismatch"); report("b3_hotspot", hotrow);
  std::uint64_t valid = 0, dummy = 0, forward = 0;
  for (const auto& path : hotspot.banks()) for (const auto& c : path) {
    valid += c.valid_updates; dummy += c.dummy_updates; forward += c.forwarded_reads;
    require(c.ends == 1 && c.partitions == 1 && c.uram_reads == c.valid_updates &&
        c.uram_writes == c.valid_updates && c.drain_read_pairs == rg::kBigBankRows &&
        c.drain_clear_pairs == rg::kBigBankRows, "Big bank work/drain conservation");
  }
  require(valid + dummy == 24000 && forward > 20000, "Big tuple conservation/forwarding not exercised");
  BigNetwork pressure(3, false, 1);
  const auto slow = pressure.run(fixture, {.source_interval=3, .pipeline_start_skew=37,
      .sink_interval=7, .sink_start=50000, .max_cycles=500000});
  require(slow.values == expected && slow.cycles > first.cycles && slow.output_stalls > 0 &&
      slow.capacity_stalls > 0, "Big finite pressure not exercised"); report("b3_depth1_slow_sink", slow);
  rg::BigTiming timing;
  timing.gather.capacity = 1;
  BigNetwork narrow(3, false, 0, timing);
  const auto limited = narrow.run(hot);
  require(limited.values == hotrow.values && limited.cycles > hotrow.cycles && limited.capacity_stalls > 0,
          "Big in-flight capacity ignored"); report("b3_one_inflight", limited);
  BigNetwork single(1);
  const auto one = single.run(big_fixture(0, 1));
  require(one.values == big_oracle(big_fixture(0, 1)), "Big singleton merger mismatch"); report("b1_registered", one);
}
}  // namespace

int main() {
  try {
    const rg::BigTiming timing;
    std::cout << "BIG_CONFIG {\"clock_mhz\":210,\"big\":3,\"big_vertices\":" << rg::kBigVertices
              << ",\"bank_rows\":" << rg::kBigBankRows << ",\"forwarding_entries\":" << rg::kForwardingEntries
              << ",\"timing\":{";
    const std::array<std::pair<const char*, rg::PipelineTiming>, 5> stages{{
        {"gather", timing.gather}, {"uram_write", {rg::kUramWriteLatency, 1, rg::kForwardingEntries}},
        {"drain", timing.drain}, {"pack", timing.pack}, {"merge", timing.merge}}};
    for (std::size_t index = 0; index < stages.size(); ++index) {
      if (index) std::cout << ',';
      const auto& [name, value] = stages[index];
      std::cout << '"' << name << "\":{\"latency\":" << value.latency << ",\"ii\":" << value.initiation_interval
                << ",\"capacity\":" << value.capacity << '}';
    }
    std::cout << "}}\n";
    contracts(); executions(); return 0;
  }
  catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
