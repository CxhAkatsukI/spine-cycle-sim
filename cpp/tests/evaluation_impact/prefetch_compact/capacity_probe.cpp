#include <algorithm>
#include <iostream>
#include "reader.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace {
using namespace evaluation_impact::prefetch_compact;
constexpr std::size_t segments = 2048, half = 512;

void store(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value) {
  for (unsigned byte = 0; byte < 4; ++byte) bytes.at(offset + byte) = value >> (8 * byte);
}

class BlockedSink final : public Component {
public:
  BlockedSink(ClockId clock, Fifo<Segment>& input)
      : Component("capacity-probe-sink", clock), input_(input) {}
  void evaluate(const CycleContext& context) override {
    staged_.reset();
    if (context.domain_cycle >= 10000) {
      Segment value;
      if (input_.try_pop(value)) staged_ = value;
    }
  }
  void commit(const CycleContext&) override {
    if (!staged_) return;
    check(staged_->source == 0 && staged_->last == (count + 1 == segments),
          "capacity probe framing changed");
    for (std::size_t lane = 0; lane < 16; ++lane)
      check(staged_->words[lane] == count * 16 + lane, "capacity probe lost ring payload");
    ++count;
  }
  std::size_t count{};
private:
  Fifo<Segment>& input_;
  std::optional<Segment> staged_;
};

std::array<std::uint64_t, 4> run(std::size_t capacity, std::uint64_t latency, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  std::vector<std::uint8_t> directory(64);
  store(directory, 0, segments * 16);
  backend.initialize_payload(0, 0, directory);
  std::array<std::vector<std::uint8_t>, 4> banks;
  for (auto& bank : banks) bank.resize(segments / 2 * 64);
  for (std::size_t segment = 0; segment < segments; ++segment) {
    const auto local = segment / 2, bank = segment % 2 * 2 + (local < half ? 0 : 1);
    for (std::size_t lane = 0; lane < 16; ++lane)
      store(banks[bank], local * 64 + lane * 4, segment * 16 + lane);
  }
  for (std::size_t bank = 0; bank < banks.size(); ++bank)
    backend.initialize_payload(bank + 1, 0, banks[bank]);
  const auto configuration = [](std::uint32_t id) {
    return FixedAxiPortConfig{.memory_channels = 32, .channel = 0, .initiator_id = id,
        .stream_read_beats = true, .max_pending_requests = 16, .max_outstanding_bursts = 16,
        .response_beats_per_cycle = 1, .independent_read_write = true};
  };
  FixedAxiPort even("even", clock, configuration(1), backend);
  FixedAxiPort odd("odd", clock, configuration(2), backend);
  FixedAxiPort metadata("directory", clock, configuration(3), backend);
  Fifo<Segment> output("segments", clock, 16);
  const ReGraphPmaPartition partition{.vertices = 1, .slots = segments * 16,
      .cache_segments_per_half = half, .destination_base = 0, .destination_vertices = 1,
      .row_base = 0, .row_channel = 0, .pma_base = {}, .pma_channel = {1, 2, 3, 4}};
  Reader reader(clock, even, output, partition, 71, &odd, RefillPolicy::kFullBurst,
                3, &metadata, 2, capacity);
  BlockedSink sink(clock, output);
  std::vector<Component*> components{&backend, &output, &reader, &sink};
  for (auto* port : {&even, &odd, &metadata})
    components.insert(components.end(), {&port->requests(), &port->responses(),
        &port->read_beats(), &port->master()});
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  std::uint64_t cycles = 0;
  for (; cycles < 50000; ++cycles) {
    scheduler.step();
    if (reader.done() && sink.count == segments && output.empty() &&
        even.idle() && odd.idle() && metadata.idle()) { ++cycles; break; }
  }
  const auto& stats = reader.stats();
  check(cycles < 50000 && stats.max_bank_lines == capacity,
        "capacity probe failed to fill the declared ring");
  check(stats.requests == stats.responses && stats.max_parents_per_port[0] <= 16 &&
      stats.max_parents_per_port[1] <= 16 && stats.max_parents_per_port[2] <= 16 &&
      stats.extent_beats == 1 && stats.directory_beats == 1 &&
      stats.bytes == segments * 64 + 128 && backend.outstanding() == 0,
      "capacity probe traffic or finite credits changed");
  const std::array<std::uint64_t, 4> result{cycles, stats.max_bank_lines, stats.bytes, stats.requests};
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
  return result;
}
}  // namespace

int main() {
  try {
    for (const auto latency : {64U, 128U})
      for (const auto capacity : {256U, 512U}) {
        const auto result = run(capacity, latency, false);
        check(result == run(capacity, latency, true), "capacity probe registration-order dependence");
        std::cout << "CAPACITY_PROBE {\"latency\":" << latency << ",\"capacity\":" << capacity
            << ",\"max_bank_lines\":" << result[1] << ",\"cycles\":" << result[0]
            << ",\"bytes\":" << result[2] << ",\"requests\":" << result[3] << "}\n";
      }
    std::cout << "CAPACITY_PROBE_PASS 8 executions\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
