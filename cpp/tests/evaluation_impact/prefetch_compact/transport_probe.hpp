#pragma once

#include "reader.hpp"
#include "spine_sim/scheduler.hpp"

namespace evaluation_impact::prefetch_compact {
struct TransportObservation {
  std::uint64_t cycles{}, first{}, last{}, one_cycle_gaps{}, two_cycle_gaps{}, stalls{};
  bool operator==(const TransportObservation&) const = default;
};

// A single initiator avoids evaluation-order priority in the unregistered
// sensitivity control. Neither setting changes a production profile.
inline TransportObservation transport_probe(bool registered, bool reverse) {
  constexpr std::size_t beats = 512, bytes = beats * 64;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("probe", 150);
  MockMemoryBackend backend("probe-memory", clock, {1, 3, 1, 32, 32, registered});
  FixedAxiPort port("probe-port", clock, {.memory_channels = 1, .channel = 0,
      .initiator_id = 1, .stream_read_beats = true, .max_pending_requests = 16,
      .max_outstanding_bursts = 16, .response_beats_per_cycle = 1,
      .independent_read_write = true, .beat_trace_limit = beats}, backend);
  backend.fill_payload(0, 0, bytes, 0x31);
  std::vector<Component*> components{&backend, &port.requests(), &port.responses(),
                                     &port.read_beats(), &port.master()};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  check(port.requests().try_push(AxiRequest{.transaction_id = 1, .address = 0,
      .bytes = bytes, .stream_read_beats = true, .write_data = {}}), "probe enqueue failed");
  std::size_t received = 0, acknowledged = 0;
  TransportObservation result;
  for (std::uint64_t cycle = 0; cycle < 10000; ++cycle) {
    AxiReadBeatResponse beat;
    if (port.read_beats().try_pop(beat)) {
      check(beat.success && beat.transaction_id == 1 && beat.parent_offset == received * 64 &&
          beat.last == (received + 1 == beats) && beat.read_data == std::vector<std::uint8_t>(64, 0x31),
          "probe progressive payload/order mismatch");
      ++received;
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      check(response.success && response.transaction_id == 1 && acknowledged == 0 &&
          response.operation == MemoryOperation::kRead &&
          response.read_data == std::vector<std::uint8_t>(bytes, 0x31), "probe parent mismatch");
      ++acknowledged;
    }
    scheduler.step();
    if (received == beats && acknowledged == 1 && port.idle() && backend.outstanding() == 0) {
      result.cycles = cycle + 1;
      break;
    }
  }
  const auto& stats = port.master().stats();
  const auto& trace = port.master().beat_trace();
  check(result.cycles && stats.requests_accepted == 1 && stats.requests_completed == 1 &&
      stats.beats_issued == beats && stats.beats_completed == beats && trace.size() == beats &&
      backend.traffic_stats().reads.bytes == bytes && backend.traffic_stats().writes.bytes == 0,
      "probe did not conserve/drain requests and physical reads");
  result.first = trace.front().issue_cycle;
  result.last = trace.back().issue_cycle;
  result.stalls = stats.backend_submit_stalls;
  for (std::size_t i = 1; i < trace.size(); ++i) {
    const auto gap = trace[i].issue_cycle - trace[i - 1].issue_cycle;
    result.one_cycle_gaps += gap == 1;
    result.two_cycle_gaps += gap == 2;
    check(gap == (registered ? 2U : 1U), "probe issue interval changed");
  }
  if (registered) {
    const auto* arbitration = backend.arbitration_stats();
    check(arbitration && arbitration->unique_intents == beats && arbitration->grants == beats &&
        arbitration->consumed_grants == beats && arbitration->contention_losers == 0,
        "probe arbiter conservation failed");
  }
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
  return result;
}
}  // namespace evaluation_impact::prefetch_compact
