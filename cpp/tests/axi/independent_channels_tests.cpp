#include "../../src/detail/backend_response_selection.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "reordered_reads.hpp"

#include <iostream>
#include <map>
#include <stdexcept>

namespace {
using namespace spine::sim;
void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}

struct Result {
  std::uint64_t read_ack{}, last_write_ack{}, end{}, beats{};
  std::size_t max_bursts{};
  bool operator==(const Result &) const = default;
};

Result run(std::size_t bytes, std::size_t credit, bool independent, bool hold,
           bool reverse, bool stall_read_response = false,
           bool stall_write_response = false, bool stall_write_data = false) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock,
                            MockMemoryConfig{.channels = 1,
                                             .latency_cycles = 3,
                                             .accepts_per_channel_per_cycle = 1,
                                             .max_outstanding_per_channel = 32,
                                             .response_queue_depth = 2});
  const AxiPeriodicStall stall{1000, 200, 0};
  FixedAxiPort port(
      "physical", clock,
      FixedAxiPortConfig{.memory_channels = 1,
                         .channel = 0,
                         .initiator_id = 1,
                         .max_burst_beats = 16,
                         .read_beat_fifo_depth = 1,
                         .read_reorder_capacity = 2,
                         .stream_read_beats = true,
                         .max_pending_requests = 16,
                         .max_outstanding_bursts = credit,
                         .independent_read_write = independent,
                         .write_data_stall =
                             stall_write_data ? stall : AxiPeriodicStall{},
                         .read_response_stall =
                             stall_read_response ? stall : AxiPeriodicStall{},
                         .write_response_stall =
                             stall_write_response ? stall : AxiPeriodicStall{},
                         .burst_trace_limit = 1024,
                         .beat_trace_limit = 1024},
      backend);
  backend.fill_payload(0, 0, bytes, 0x31);
  backend.fill_payload(0, 65536, 512, 0x00);
  std::vector<Component *> components{&backend, &port.requests(),
                                      &port.responses(), &port.read_beats(),
                                      &port.master()};
  if (reverse)
    std::reverse(components.begin(), components.end());
  for (auto *component : components)
    scheduler.add_component(*component);
  require(port.requests().try_push(AxiRequest{.transaction_id = 1,
                                              .address = 0,
                                              .bytes = bytes,
                                              .stream_read_beats = true,
                                              .write_data = {}}),
          "read enqueue failed");
  Result result;
  std::size_t write_acks = 0, received = 0;
  std::array<bool, 8> seen{};
  for (std::uint64_t cycle = 0; cycle < 2000; ++cycle) {
    if (cycle >= 50 && cycle < 58) {
      const auto index = cycle - 50;
      require(port.requests().try_push(
                  AxiRequest{.transaction_id = index + 2,
                             .operation = MemoryOperation::kWrite,
                             .address = 65536 + index * 64,
                             .bytes = 64,
                             .write_data = std::vector<std::uint8_t>(
                                 64, static_cast<std::uint8_t>(0x50 + index))}),
              "write enqueue failed");
    }
    if (!hold || cycle >= 200) {
      AxiReadBeatResponse beat;
      if (port.read_beats().try_pop(beat)) {
        require(beat.success && beat.transaction_id == 1 &&
                    beat.parent_offset == received * 64 &&
                    beat.read_data == std::vector<std::uint8_t>(64, 0x31) &&
                    beat.last == (received + 1 == bytes / 64),
                "stream ordering or payload differs");
        ++received;
      }
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      require(response.success, "request failed");
      if (response.transaction_id == 1) {
        require(
            !result.read_ack && response.operation == MemoryOperation::kRead &&
                response.read_data == std::vector<std::uint8_t>(bytes, 0x31),
            "read result differs");
        result.read_ack = cycle;
      } else {
        const auto index = response.transaction_id - 2;
        require(index < 8 && !seen[index] &&
                    response.operation == MemoryOperation::kWrite,
                "write response lost or duplicated");
        seen[index] = true;
        ++write_acks;
        result.last_write_ack = cycle;
      }
    }
    scheduler.step();
    std::array<std::size_t, 2> response_counts{};
    for (std::size_t i = 0; i < backend.response_count(1); ++i)
      ++response_counts[backend.response_at(1, i).operation ==
                        MemoryOperation::kWrite];
    require(response_counts[0] <= 2 && response_counts[1] <= 2 &&
                (independent || response_counts[0] + response_counts[1] <= 2),
            "backend response direction capacity exceeded");
    if (result.read_ack && write_acks == 8 && port.idle() &&
        backend.outstanding() == 0) {
      result.end = cycle + 1;
      break;
    }
  }
  require(result.end && received == bytes / 64,
          "independent channel test did not drain");
  const auto &stats = port.master().stats();
  result.beats = stats.beats_issued;
  result.max_bursts = stats.max_outstanding_bursts;
  require(stats.requests_accepted == 9 && stats.requests_completed == 9 &&
              stats.beats_issued == bytes / 64 + 8 &&
              stats.beats_completed == stats.beats_issued,
          "parent or beat conservation failed");
  require(stats.max_outstanding_bursts <= credit * (independent ? 2 : 1),
          "directional credit limit exceeded");
  require(backend.traffic_stats_by_initiator().size() == 1,
          "one master became multiple initiators");
  for (std::size_t i = 0; i < 8; ++i)
    require(
        backend.inspect_payload(0, 65536 + i * 64, 64) ==
            std::vector<std::uint8_t>(64, static_cast<std::uint8_t>(0x50 + i)),
        "write state differs");
  std::map<std::uint64_t, std::uint64_t> issue_counts;
  for (const auto &beat : port.master().beat_trace())
    require(++issue_counts[beat.issue_cycle] == 1,
            "independence doubled physical issue bandwidth");
  if (independent && !stall_write_response && !stall_write_data)
    require(result.last_write_ack < 200,
            "read backpressure still blocked independent writes");
  if (!hold && !stall_read_response)
    require(result.read_ack < 200 || bytes > 512,
            "write stall blocked read completion");
  for (auto *component : components)
    scheduler.remove_component(*component);
  return result;
}

void selection_checks() {
  using namespace spine::sim::detail;
  require(!valid_response_selection(std::vector<std::size_t>{}, 3),
          "empty selection accepted");
  require(!valid_response_selection(std::vector<std::size_t>{1, 1}, 3),
          "duplicate selection accepted");
  require(!valid_response_selection(std::vector<std::size_t>{2, 1}, 3),
          "backward selection accepted");
  require(!valid_response_selection(std::vector<std::size_t>{3}, 3),
          "out-of-range selection accepted");
  std::deque<BackendResponse> queue;
  for (std::uint64_t i = 0; i < 5; ++i)
    queue.push_back({.request_id = i,
                     .read_data = {},
                     .operation = i % 2 ? MemoryOperation::kWrite
                                        : MemoryOperation::kRead});
  std::vector<BackendResponse> retired;
  retire_selected_responses(queue, std::vector<std::size_t>{1, 3}, retired);
  require(queue.size() == 3 && queue[0].request_id == 0 &&
              queue[1].request_id == 2 && queue[2].request_id == 4 &&
              retired.size() == 2 && retired[0].request_id == 1 &&
              retired[1].request_id == 3,
          "selected retirement reordered or lost responses");
  std::array<std::size_t, 2> counts{3, 2};
  retire_response_credits(counts, retired, queue.size());
  require(counts == std::array<std::size_t, 2>{3, 0},
          "direction credits differ after retirement");
  for (auto invalid :
       {std::array<std::size_t, 2>{3, 1}, std::array<std::size_t, 2>{2, 2}}) {
    bool rejected = false;
    try {
      retire_response_credits(invalid, retired, queue.size());
    } catch (const std::logic_error &) {
      rejected = true;
    }
    require(rejected, "invalid response direction credits were accepted");
  }
}
} // namespace

int main() {
  try {
    selection_checks();
    for (auto capacity : {1U, 2U, 4U, 32U})
      for (bool independent : {false, true})
        for (auto width : {1U, 4U})
          require(axi_test::check_reordered_reads(capacity, independent, false, width) ==
                      axi_test::check_reordered_reads(capacity, independent, true, width),
                  "reordered read timing depends on registration order");
    std::size_t cases = 0;
    for (auto bytes : {512U, 16384U})
      for (auto credit : {1U, 4U, 16U})
        for (bool hold : {false, true}) {
          const auto value = run(bytes, credit, true, hold, false);
          require(value == run(bytes, credit, true, hold, true),
                  "registration order changed result");
          ++cases;
        }
    for (std::size_t kind = 0; kind < 3; ++kind) {
      const auto value =
          run(512, 1, true, false, false, kind == 0, kind == 1, kind == 2);
      require(value == run(512, 1, true, false, true, kind == 0, kind == 1,
                           kind == 2),
              "stalled registration order changed result");
      ++cases;
    }
    const auto old = run(512, 16, false, true, false);
    require(old.last_write_ack >= 200 && old == run(512, 16, false, true, true),
            "legacy mode no longer reproduces retained blocking");
    std::cout << "independent_channel_controls=" << cases
              << " legacy_blocking_retained=1 PASS\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
