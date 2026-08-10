#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_vertex_lifecycle.hpp"

namespace {

using spine::sim::FixedAxiPort;
using spine::sim::FixedAxiPortConfig;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::Scheduler;
using spine::sim::SpineVertexLifecycle;
using spine::sim::SpineVertexLifecycleConfig;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct Fixture {
  Scheduler scheduler;
  spine::sim::ClockId clock{scheduler.add_clock_mhz("lifecycle", 150.0)};
  MockMemoryBackend backend{
      "hbm", clock,
      MockMemoryConfig{
          .channels = 1,
          .latency_cycles = 3,
          .accepts_per_channel_per_cycle = 1,
          .max_outstanding_per_channel = 8,
          .response_queue_depth = 8,
      }};
  FixedAxiPort port{
      "validity", clock,
      FixedAxiPortConfig{
          .memory_channels = 1,
          .channel = 0,
          .initiator_id = 7,
          .data_width_bytes = 64,
          .max_burst_beats = 16,
          .request_fifo_depth = 2,
          .response_fifo_depth = 2,
          .read_beat_fifo_depth = 2,
          .read_reorder_capacity = 2,
          .max_pending_requests = 2,
          .max_outstanding_bursts = 2,
      },
      backend};
  SpineVertexLifecycle lifecycle{
      "vertex-lifecycle", clock,
      SpineVertexLifecycleConfig{
          .max_vertices = 128,
          .initial_valid_vertices = 4,
          .bitmap_base = 4096,
      },
      port};

  Fixture() {
    scheduler.add_component(lifecycle);
    port.register_components(scheduler);
    scheduler.add_component(backend);
  }

  void run_operation() {
    scheduler.run_until(
        [this] { return !lifecycle.busy() && port.idle(); }, 500);
    require(!lifecycle.failed(), lifecycle.failure());
  }
};

void test_activation_reads_and_writes_hbm_bitmap() {
  Fixture fixture;
  require(!fixture.lifecycle.valid(6), "dormant vertex started valid");
  require(fixture.lifecycle.try_activate(6), "activation was rejected");
  fixture.run_operation();
  require(fixture.lifecycle.valid(6), "activation did not publish validity");
  const auto &counters = fixture.lifecycle.counters();
  require(counters.bitmap_reads == 1 && counters.bitmap_writes == 1 &&
              counters.read_bytes == 8 && counters.write_bytes == 8,
          "activation did not issue one bitmap read-modify-write");
  require(counters.memory_requests_issued == 2 &&
              counters.memory_requests_completed == 2 &&
              fixture.lifecycle.request_ledger_closed(),
          "activation memory ledger did not close");
  const std::vector<std::uint8_t> payload =
      fixture.backend.inspect_payload(0, 4096, 8);
  require((payload[0] & (1U << 6)) != 0,
          "activation did not change the resident HBM bitmap");
}

void test_existing_vertex_activation_is_a_timed_read_only_noop() {
  Fixture fixture;
  require(fixture.lifecycle.try_activate(2), "valid activation was rejected");
  fixture.run_operation();
  const auto &counters = fixture.lifecycle.counters();
  require(counters.bitmap_reads == 1 && counters.bitmap_writes == 0 &&
              counters.no_op_operations == 1,
          "valid activation was not a read-only no-op");
}

void test_deactivation_requires_incident_edge_retirement() {
  Fixture fixture;
  require(!fixture.lifecycle.try_deactivate(2, false),
          "unsafe deactivation was accepted");
  require(fixture.lifecycle.valid(2) && !fixture.lifecycle.busy(),
          "unsafe deactivation changed lifecycle state");
  require(fixture.lifecycle.counters().unsafe_deactivation_rejections == 1,
          "unsafe deactivation rejection was not counted");
  require(fixture.lifecycle.try_deactivate(2, true),
          "safe deactivation was rejected");
  fixture.run_operation();
  require(!fixture.lifecycle.valid(2),
          "safe deactivation did not clear validity");
  require(fixture.lifecycle.counters().bitmap_reads == 1 &&
              fixture.lifecycle.counters().bitmap_writes == 1,
          "safe deactivation did not issue read-modify-write");
}

void test_busy_component_backpressures_second_operation() {
  Fixture fixture;
  require(fixture.lifecycle.try_activate(6), "first activation was rejected");
  require(!fixture.lifecycle.try_activate(7),
          "busy lifecycle accepted a second operation");
  require(fixture.lifecycle.counters().busy_stalls == 1,
          "busy lifecycle did not count backpressure");
  fixture.run_operation();
  require(fixture.lifecycle.valid(6) && !fixture.lifecycle.valid(7),
          "busy rejection mutated the wrong vertex");
}

void test_fixed_capacity_rejects_out_of_range_vertex() {
  Fixture fixture;
  bool rejected = false;
  try {
    static_cast<void>(fixture.lifecycle.try_activate(128));
  } catch (const std::out_of_range &) {
    rejected = true;
  }
  require(rejected, "lifecycle accepted a vertex beyond fixed capacity");
}

}  // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"activation_hbm", test_activation_reads_and_writes_hbm_bitmap},
      {"activation_noop",
       test_existing_vertex_activation_is_a_timed_read_only_noop},
      {"safe_deactivation",
       test_deactivation_requires_incident_edge_retirement},
      {"busy_backpressure", test_busy_component_backpressures_second_operation},
      {"bounded_capacity", test_fixed_capacity_rejects_out_of_range_vertex},
  };
  std::size_t failures = 0;
  for (const auto &[name, test] : tests) {
    try {
      test();
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception &error) {
      ++failures;
      std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    }
  }
  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return 1;
  }
  std::cout << tests.size() << " test(s) passed\n";
  return 0;
}
