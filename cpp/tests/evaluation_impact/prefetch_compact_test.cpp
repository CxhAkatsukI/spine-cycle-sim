#include <iostream>
#include "prefetch_compact/sink.hpp"
#include "prefetch_compact/transport_probe.hpp"
#include "spine_sim/scheduler.hpp"

namespace {
using namespace evaluation_impact::prefetch_compact;
void store(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value) {
  if (bytes.size() < offset + 4) bytes.resize(offset + 4);
  for (unsigned i = 0; i < 4; ++i) bytes[offset + i] = value >> (8 * i);
}

std::array<std::uint64_t, 4> run(std::uint64_t latency, bool reverse,
                                std::uint64_t period, bool all_dummy, bool dual = false,
                                bool full_burst = false) {
  constexpr std::size_t vertices = 8291, half = 16;
  std::array<std::size_t, vertices> rows{};
  rows[0] = 1; rows[1] = 2; rows[4095] = 600; rows[4096] = 2; rows[8290] = 1;
  std::vector<std::uint8_t> directory((vertices + 7) / 8 * 64);
  std::array<std::vector<std::uint8_t>, 4> banks;
  std::vector<Edge> expected;
  std::size_t segment = 0;
  for (std::size_t source = 0; source < vertices; ++source) {
    const auto begin = segment * 16;
    for (std::size_t local_segment = 0; local_segment < rows[source]; ++local_segment, ++segment) {
      const auto local = segment / 2, bank = (segment % 2) * 2 + (local < half ? 0 : 1);
      for (unsigned lane = 0; lane < 16; ++lane) {
        const auto in_row = local_segment * 16 + lane;
        const auto live_count = source == 1 ? 19 : source == 4095 ? 9600 : source == 4096 ? 1 : 9;
        auto value = 0x8000'0000U;
        if (!all_dummy && source && in_row < std::size_t(live_count)) {
          const auto dst = static_cast<std::uint32_t>(in_row % 100);
          const auto weight = static_cast<std::uint32_t>(in_row % 4095 + 1);
          value = dst | (weight << 19);
          expected.push_back({static_cast<std::uint32_t>(source), dst, weight});
        }
        store(banks[bank], local * 64 + lane * 4, value);
      }
    }
    store(directory, source * 8, segment * 16);
    store(directory, source * 8 + 4, begin);
  }
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  backend.initialize_payload(0, 0, directory);
  ReGraphPmaPartition partition{.vertices = vertices, .slots = segment * 16,
      .cache_segments_per_half = half, .destination_base = 0, .destination_vertices = vertices,
      .row_base = 0, .row_channel = 0, .pma_base = {}, .pma_channel = {1, 2, 3, 4}};
  for (std::size_t bank = 0; bank < 4; ++bank) backend.initialize_payload(bank + 1, 0, banks[bank]);
  FixedAxiPort memory("port", clock, {.memory_channels = 32, .channel = 0, .initiator_id = 1,
      .stream_read_beats = true, .max_pending_requests = 16, .max_outstanding_bursts = 16,
      .response_beats_per_cycle = 1, .independent_read_write = true}, backend);
  std::unique_ptr<FixedAxiPort> odd;
  if (dual) odd = std::make_unique<FixedAxiPort>("odd-port", clock, FixedAxiPortConfig{
      .memory_channels = 32, .channel = 0, .initiator_id = 2, .stream_read_beats = true,
      .max_pending_requests = 16, .max_outstanding_bursts = 16,
      .response_beats_per_cycle = 1, .independent_read_write = true}, backend);
  Fifo<Segment> segments("segments", clock, 16);
  Fifo<ReGraphPmaPacket> packets("packets", clock, 2);
  Reader reader(clock, memory, segments, partition, 71, odd.get(),
                full_burst ? RefillPolicy::kFullBurst : RefillPolicy::kAvailableSpace);
  Compactor compactor(clock, segments, packets, vertices);
  Sink sink(clock, packets, partition, period);
  std::vector<Component*> components{&backend, &memory.requests(), &memory.responses(), &memory.read_beats(),
      &memory.master(), &segments, &packets, &reader, &compactor, &sink};
  if (odd) components.insert(components.end(), {&odd->requests(), &odd->responses(),
      &odd->read_beats(), &odd->master()});
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  std::uint64_t cycles = 0;
  for (; cycles < 1000000; ++cycles) {
    scheduler.step();
    if (reader.done() && compactor.done() && memory.idle() && (!odd || odd->idle()) && segments.empty() &&
        packets.empty() && sink.finished()) { ++cycles; break; }
  }
  check(cycles < 1000000, "synthetic candidate timeout");
  std::sort(expected.begin(), expected.end()); std::sort(sink.edges.begin(), sink.edges.end());
  check(expected == sink.edges, "synthetic weighted multiset mismatch");
  const auto& r = reader.stats();
  const auto& c = compactor.stats();
  const auto traffic = backend.traffic_stats();
  const auto completed = memory.master().stats().requests_completed +
      (odd ? odd->master().stats().requests_completed : 0);
  check(r.segments == segment && r.beats * 64 == r.bytes && r.responses == r.requests &&
      r.requests == completed && r.max_parents > 1 && r.max_parents <= (dual ? 32U : 16U) &&
      r.max_parents_per_port[0] <= 16 && r.max_parents_per_port[1] <= 16 &&
      (!dual || r.max_parents_per_port[1] > 0) && r.max_bank_lines <= 256 && r.max_pipeline <= 2 &&
      c.input_segments == segment && c.live_edges == expected.size() &&
      c.live_edges + c.input_dummy == segment * 16 && c.packets == sink.packets &&
      c.output_dummy == sink.dummy && c.packets * 8 == c.live_edges + c.output_dummy &&
      c.max_lanes <= 32 && c.max_pipeline <= 2 && traffic.reads.bytes == r.bytes &&
      traffic.writes.bytes == 0 && backend.outstanding() == 0, "synthetic finite-ledger failure");
  if (!all_dummy && period > 1) check(c.output_stalls > 0, "synthetic backpressure was not exercised");
  check(!full_burst || (r.short_pma_requests <= 4 && r.pma_requests <= r.requests),
      "synthetic full-burst parents fragmented");
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
  return {cycles, r.bytes, r.requests, c.packets};
}
}  // namespace

int main() {
  try {
    for (auto registered : {false, true}) {
      const auto value = transport_probe(registered, false);
      check(value == transport_probe(registered, true), "probe depends on registration order");
      std::cout << "TRANSPORT_PROBE {\"registered\":" << (registered ? "true" : "false")
          << ",\"beats\":512,\"cycles\":" << value.cycles << ",\"first_issue\":" << value.first
          << ",\"last_issue\":" << value.last << ",\"one_cycle_gaps\":" << value.one_cycle_gaps
          << ",\"two_cycle_gaps\":" << value.two_cycle_gaps
          << ",\"backend_submit_stalls\":" << value.stalls << "}\n";
    }
    for (auto latency : {64U, 128U})
      for (auto period : {1U, 5U})
        for (auto all_dummy : {false, true})
          check(run(latency, false, period, all_dummy) == run(latency, true, period, all_dummy),
                "synthetic candidate depends on registration order");
    std::cout << "PREFETCH_COMPACT_TEST PASS 16 executions\n";
    for (auto latency : {64U, 128U})
      for (auto period : {1U, 5U})
        for (auto all_dummy : {false, true})
          check(run(latency, false, period, all_dummy, true) == run(latency, true, period, all_dummy, true),
                "dual-port candidate depends on registration order");
    std::cout << "DUAL_PORT_PREFETCH_TEST PASS 16 executions\n";
    for (auto dual : {false, true})
      for (auto latency : {64U, 128U})
        for (auto period : {1U, 5U})
          for (auto all_dummy : {false, true})
            check(run(latency, false, period, all_dummy, dual, true) ==
                  run(latency, true, period, all_dummy, dual, true),
                  "full-burst candidate depends on registration order");
    std::cout << "FULL_BURST_PREFETCH_TEST PASS 32 executions\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
