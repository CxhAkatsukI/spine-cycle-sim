#include "network.hpp"

#include <functional>
#include <iostream>

namespace {
using namespace original_regraph_test;

template <typename Exception>
void rejected(const std::function<void()>& operation) {
  try { operation(); } catch (const Exception&) { return; }
  throw std::runtime_error("invalid operation was not rejected");
}

void pipeline_edges() {
  rg::detail::LatencyPipe<unsigned> pipe({2, 1, 1});
  pipe.stage_accept(7, 0);
  pipe.commit(0);
  require(!pipe.ready(1) && pipe.ready(2) && *pipe.ready(2) == 7, "pipeline latency");
  pipe.stage_retire();
  require(!pipe.can_accept(2), "full pipeline must not allow same-edge fallthrough");
  pipe.commit(2);
  require(pipe.drained() && pipe.can_accept(3), "pipeline did not drain");
  pipe.stage_accept(8, 3);
  rejected<std::logic_error>([&] { pipe.stage_accept(9, 3); });
  pipe.commit(3);
  rg::detail::LatencyPipe<unsigned> throttled({2, 3, 2});
  throttled.stage_accept(1, 0);
  throttled.commit(0);
  require(!throttled.can_accept(1) && throttled.can_accept(3), "pipeline II");
  for (const auto timing : {rg::PipelineTiming{0, 1, 1}, {1, 0, 1}, {1, 1, 0}}) {
    rejected<std::invalid_argument>([&] { rg::detail::LatencyPipe<unsigned> bad(timing); });
  }
}

void port_contracts() {
  Fifo<rg::UpdateBurst> input("input", 0, 1);
  Fifo<rg::VertexPair> output("output", 0, 1);
  Fifo<rg::VertexPair> other_clock("other_clock", 1, 1);
  Fifo<rg::PropertyLine> lines("lines", 0, 1);
  rg::GatherOutputs repeated;
  repeated.fill(&output);
  rejected<std::invalid_argument>([&] { rg::LittleGather bad("bad", 0, input, repeated); });
  rejected<std::invalid_argument>([&] { rg::LittleLocalMerge bad("bad", 0, repeated, output); });
  rejected<std::invalid_argument>([&] { rg::LittleGlobalMerge bad("bad", 0, {}, lines); });
  rejected<std::invalid_argument>([&] {
    rg::LittleGlobalMerge bad("bad", 0, {&output, &output}, lines);
  });
  rejected<std::invalid_argument>([&] {
    rg::LittleGlobalMerge bad("bad", 0, {&other_clock}, lines);
  });
  std::array<std::unique_ptr<Fifo<rg::VertexPair>>, rg::kGatherLanes> owned;
  rg::GatherOutputs valid;
  for (std::size_t lane = 0; lane < rg::kGatherLanes; ++lane) {
    owned[lane] = std::make_unique<Fifo<rg::VertexPair>>("lane", 0, 1);
    valid[lane] = owned[lane].get();
  }
  rg::LittleGather live("live", 0, input, valid);
  live.begin_partition(1);
  rejected<std::logic_error>([&] { live.begin_partition(1); });
}

void report(const char* id, const Observation& row) {
  std::cout << "GATHER_CASE {\"id\":\"" << id << "\",\"cycles\":" << row.cycles
            << ",\"output_stalls\":" << row.output_stalls
            << ",\"capacity_stalls\":" << row.capacity_stalls
            << ",\"checked_words\":" << row.values.size() << "}\n";
}

void network_invariants() {
  const auto fixture = stress_fixture(4, 1000);
  const auto expected = oracle(fixture);
  Network normal(4);
  auto first = normal.run(fixture);
  require(first.values == expected, "normal gather/merge differs from oracle");
  require(normal.gather(0).counters().forwarded_reads > 0, "RAW fixture did not forward");
  require(normal.gather(0).counters().valid_updates +
          normal.gather(0).counters().dummy_updates == 8000, "tuple conservation");
  require(normal.gather(0).counters().uram_writes ==
          normal.gather(0).counters().valid_updates, "URAM update conservation");
  report("a4_registered", first);

  Network reversed(4, 8, {}, true);
  const auto reverse = reversed.run(fixture);
  require(reverse.values == expected && reverse.cycles == first.cycles &&
          reverse.output_stalls == first.output_stalls &&
          reverse.capacity_stalls == first.capacity_stalls,
          "component registration order changed numerical result/counters");
  report("a4_reverse_registration", reverse);

  Network slow(4, 1);
  const auto stalled = slow.run(fixture, {.source_interval = 3,
      .pipeline_start_skew = 137, .sink_interval = 23, .sink_start = 50000});
  require(stalled.values == expected && stalled.output_stalls > 0 &&
          stalled.capacity_stalls > 0 && stalled.cycles > first.cycles,
          "finite-buffer stress did not conserve values/stall");
  report("a4_depth1_skew_slow_sink", stalled);

  rg::LittleTiming constrained;
  constrained.gather.capacity = 1;
  Network narrow(4, 8, constrained);
  const auto limited = narrow.run(fixture);
  require(limited.values == expected && limited.cycles > first.cycles &&
          limited.capacity_stalls > 0, "in-flight capacity was ignored");
  report("a4_one_inflight_gather", limited);

  const auto eleven_fixture = stress_fixture(11, 257);
  Network eleven(11);
  const auto eleven_row = eleven.run(eleven_fixture, {.pipeline_start_skew = 31});
  require(eleven_row.values == oracle(eleven_fixture), "11-way merger mismatch");
  report("a11_little_component", eleven_row);

  const auto zero = normal.run(std::vector<std::vector<rg::UpdateBurst>>(4));
  require(std::all_of(zero.values.begin(), zero.values.end(),
                      [](auto value) { return value == 0; }),
          "URAM values leaked across partition drain/restart");
  require(normal.gather(0).counters().partitions == 2, "partition reuse count");
  report("a4_reused_zero_burst_partition", zero);

  const auto repeated = normal.run(fixture);
  require(repeated.values == first.values && repeated.cycles == first.cycles,
          "repeated partition changed output/cycles after clear");
  report("a4_reused_nonzero_partition", repeated);
}
}  // namespace

int main() {
  try {
    std::cout << configuration_record() << '\n';
    pipeline_edges();
    port_contracts();
    network_invariants();
    std::cout << "Original ReGraph finite gather/merge tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
