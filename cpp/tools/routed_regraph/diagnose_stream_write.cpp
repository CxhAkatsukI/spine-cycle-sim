#include "spine_sim/fixed_axi_port.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <tuple>

namespace {
using namespace spine::sim;

void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}

struct Observation {
  std::uint64_t write_issue{}, write_ack{}, end{};
  std::uint64_t read_reorder_stalls{}, streamed_beats{};
  bool operator==(const Observation &) const = default;
};

Observation observe(bool stream, bool hold_consumer, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 1, .latency_cycles = 3, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 32, .response_queue_depth = 32});
  FixedAxiPort port("physical", clock, FixedAxiPortConfig{
      .memory_channels = 1, .channel = 0, .initiator_id = 1,
      .max_burst_beats = 16, .read_beat_fifo_depth = 1,
      .read_reorder_capacity = 2, .stream_read_beats = true,
      .max_pending_requests = 16, .max_outstanding_bursts = 16,
      .beat_trace_limit = 32}, backend);
  backend.fill_payload(0, 0, 512, 0x31);
  backend.fill_payload(0, 4096, 64, 0x00);
  std::vector<Component *> components{&backend, &port.requests(), &port.responses(),
                                    &port.read_beats(), &port.master()};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  require(port.requests().try_push(AxiRequest{
      .transaction_id = 1, .address = 0, .bytes = 512,
      .stream_read_beats = stream, .write_data = {}}), "read enqueue failed");
  Observation result;
  std::size_t read_acks = 0, write_acks = 0, beats = 0;
  for (std::uint64_t cycle = 0; cycle < 1000; ++cycle) {
    if (cycle == 50)
      require(port.requests().try_push(AxiRequest{
          .transaction_id = 2, .operation = MemoryOperation::kWrite,
          .address = 4096, .bytes = 64, .write_data = std::vector<std::uint8_t>(64, 0x57)}),
          "write enqueue failed");
    if (!hold_consumer || cycle >= 200) {
      AxiReadBeatResponse beat;
      if (port.read_beats().try_pop(beat)) {
        require(beat.success && beat.transaction_id == 1 && beat.parent_offset == beats * 64 &&
                beat.read_data == std::vector<std::uint8_t>(64, 0x31) && beat.last == (beats == 7),
                "stream order or payload mismatch");
        ++beats;
      }
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      require(response.success, "request failed");
      if (response.transaction_id == 1) {
        require(response.operation == MemoryOperation::kRead &&
                response.read_data == std::vector<std::uint8_t>(512, 0x31), "read result mismatch");
        ++read_acks;
      } else {
        require(response.transaction_id == 2 && response.operation == MemoryOperation::kWrite,
                "unexpected response");
        ++write_acks;
        result.write_ack = cycle;
      }
    }
    scheduler.step();
    if (read_acks == 1 && write_acks == 1 && port.idle() && backend.outstanding() == 0) {
      result.end = cycle + 1;
      break;
    }
  }
  require(result.end && beats == (stream ? 8U : 0U), "bounded diagnostic did not drain");
  const auto &stats = port.master().stats();
  require(stats.requests_accepted == 2 && stats.requests_completed == 2 &&
          stats.beats_issued == 9 && stats.beats_completed == 9 &&
          backend.inspect_payload(0, 4096, 64) == std::vector<std::uint8_t>(64, 0x57),
          "diagnostic conservation or write payload mismatch");
  result.read_reorder_stalls = stats.read_reorder_stalls;
  result.streamed_beats = stats.read_beats_streamed;
  for (const auto &beat : port.master().beat_trace())
    if (beat.operation == MemoryOperation::kWrite) result.write_issue = beat.issue_cycle;
  require(result.write_issue && result.write_ack >= result.write_issue, "write trace missing");
  for (auto *component : components) scheduler.remove_component(*component);
  return result;
}
} // namespace

int main() {
  try {
    std::cout << "{\"claim\":\"current_model_cross_operation_stall_diagnostic_not_FPGA_measurement\",\"rows\":[";
    bool first = true;
    for (const auto &[name, stream, hold] :
         {std::tuple{"held_stream", true, true}, std::tuple{"drained_stream", true, false},
          std::tuple{"ordinary_read", false, true}}) {
      const auto normal = observe(stream, hold, false);
      require(normal == observe(stream, hold, true), "component order changed observation");
      if (!first) std::cout << ',';
      first = false;
      std::cout << "{\"case\":\"" << name << "\",\"write_issue\":" << normal.write_issue
                << ",\"write_ack\":" << normal.write_ack << ",\"end\":" << normal.end
                << ",\"read_reorder_stalls\":" << normal.read_reorder_stalls
                << ",\"streamed_beats\":" << normal.streamed_beats
                << ",\"registration_order_equal\":true}";
    }
    std::cout << "]}\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
