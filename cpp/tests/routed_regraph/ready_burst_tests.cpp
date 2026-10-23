#include "../../src/detail/routed_regraph_transport.hpp"

#include <iostream>
#include <memory>

namespace {
using namespace spine::sim;
using namespace spine::sim::detail;
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
template<class F> void rejects(F action) {
  bool rejected = false;
  try { action(); } catch (const std::logic_error&) { rejected = true; }
  require(rejected, "malformed coverage was not rejected");
}

void coverage() {
  ReGraphBurstCoverage order(ReGraphBurstOrder::kFourWorkerAddressed);
  rejects([&] { order.reset(65535); });
  rejects([&] { order.reset(0); });
  order.reset(5 * 65536);
  rejects([&] { order.accept(1); });
  rejects([&] { order.accept(16); });
  rejects([&] { order.accept(4 * 65536); });
  for (std::size_t block = 0; block < 4096; ++block)
    for (auto worker : {3U, 1U, 2U, 0U}) order.accept(worker * 65536 + block * 16);
  rejects([&] { order.accept(0); });
  for (std::size_t block = 0; block < 4096; ++block) order.accept(4 * 65536 + block * 16);
  rejects([&] { order.accept(5 * 65536); });
  order.reset(65536);
  order.accept(0);
  rejects([&] { order.accept(0); });
  ReGraphBurstCoverage sequential;
  sequential.reset(32);
  rejects([&] { sequential.accept(16); });
  sequential.accept(0); sequential.accept(16);
  rejects([&] { sequential.accept(16); });
}

struct Observation {
  std::vector<std::size_t> rows;
  std::uint64_t cycles{}, stalls{};
  bool operator==(const Observation&) const = default;
};

Observation execute(bool ready, bool reverse) {
  constexpr std::size_t partitions = 5, rows_per_partition = 32768;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  std::array<std::unique_ptr<Fifo<ReGraphGatherRow>>, 4> storage;
  std::array<Fifo<ReGraphGatherRow>*, 4> inputs;
  for (std::size_t w = 0; w < 4; ++w) {
    storage[w] = std::make_unique<Fifo<ReGraphGatherRow>>("input" + std::to_string(w), clock, 1);
    inputs[w] = storage[w].get();
  }
  Fifo<ReGraphGatherRow> output("output", clock, 1);
  RoutedGatherMux mux("mux", clock, inputs, output, partitions, ready);
  std::vector<Component*> components{inputs[0], inputs[1], inputs[2], inputs[3], &output, &mux};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  Observation observation;
  for (std::size_t round = 0; round < 2; ++round) {
    mux.start_round();
    std::array<std::size_t, 4> produced{};
    ReGraphBurstCoverage seen(ready ? ReGraphBurstOrder::kFourWorkerAddressed : ReGraphBurstOrder::kSequential);
    seen.reset(partitions * 65536);
    std::size_t consumed = 0, base_row = 0;
    for (std::size_t cycle = 0; cycle < 2000000 && consumed < partitions * rows_per_partition; ++cycle) {
      for (std::size_t w = 0; w < 4; ++w) {
        const auto partition = w + (produced[w] / rows_per_partition) * 4;
        if (partition >= partitions || (w == 0 && cycle < 1000) ||
            (w == 2 && produced[w] == 3 && cycle < 1500)) continue;
        const auto local = produced[w] % rows_per_partition;
        const auto global = partition * rows_per_partition + local;
        if (inputs[w]->try_push(ReGraphGatherRow{.row = local,
            .candidates = {static_cast<std::uint32_t>(global * 2),
                           static_cast<std::uint32_t>(global * 2 + 1)}})) ++produced[w];
      }
      ReGraphGatherRow row;
      if (cycle % 3 == 0 && output.try_pop(row)) {
        if (consumed % 8 == 0) { base_row = row.row; seen.accept(base_row * 2); }
        require(row.row == base_row + consumed % 8, "mux interleaved a partial burst");
        require(row.candidates[0] == row.row * 2 && row.candidates[1] == row.row * 2 + 1,
                "mux changed row payload or global address");
        if (consumed == 0) require(row.row / rows_per_partition == (ready ? 1U : 0U),
                                  "ready arbitration waited for a delayed partition");
        observation.rows.push_back(row.row); ++consumed;
      }
      scheduler.step(); ++observation.cycles;
    }
    scheduler.step();
    require(mux.done() && output.empty() && consumed == partitions * rows_per_partition,
            "mux did not drain complete coverage");
    for (auto* input : inputs) require(input->empty(), "mux left an input behind");
    require(mux.rows() == (round + 1) * partitions * rows_per_partition,
            "mux restart lost cumulative ledger");
  }
  observation.stalls = output.stats().push_stalls;
  require(observation.stalls != 0, "mux output backpressure was not exercised");
  return observation;
}
} // namespace

int main() {
  try {
    coverage();
    for (bool ready : {false, true})
      require(execute(ready, false) == execute(ready, true), "mux depends on registration order");
    std::cout << "PASS: finite addressed coverage, delayed workers, partial-burst stalls, five partitions, restart and registration order\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
