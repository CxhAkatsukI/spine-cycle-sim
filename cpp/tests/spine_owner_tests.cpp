#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_owner.hpp"

namespace {

using spine::sim::Scheduler;
using spine::sim::SpineOwnerKeyState;
using spine::sim::SpineOwnerScheduler;
using spine::sim::SpineOwnerSchedulerConfig;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct Fixture {
  Scheduler scheduler;
  spine::sim::ClockId clock{scheduler.add_clock_mhz("owner", 150.0)};
  SpineOwnerScheduler owner;

  explicit Fixture(SpineOwnerSchedulerConfig config = {})
      : owner("owner-scheduler", clock, config) {
    scheduler.add_component(owner);
  }

  void step() { scheduler.step(); }
};

void test_initial_dispatch_completion_closes_credit() {
  Fixture fixture;
  require(fixture.owner.quiescent(), "fresh owner scheduler is not quiescent");
  require(fixture.owner.try_activate(7), "initial activation was rejected");
  require(!fixture.owner.quiescent(), "staged activation looked quiescent");
  fixture.step();
  require(fixture.owner.state(7) == SpineOwnerKeyState{true, false, false},
          "initial activation did not enter owner FIFO");
  std::uint32_t key = 0;
  require(fixture.owner.try_dispatch(0, key) && key == 7,
          "owner dispatch returned the wrong key");
  fixture.step();
  require(fixture.owner.state(7) == SpineOwnerKeyState{false, true, false},
          "dispatch did not establish ownership");
  require(fixture.owner.try_complete(7), "owner completion was rejected");
  fixture.step();
  require(fixture.owner.quiescent(), "completed scheduler is not quiescent");
  require(fixture.owner.ledger_closed(), "completed work ledger is open");
  require(fixture.owner.stats().work_credits_created == 1 &&
              fixture.owner.stats().work_credits_retired == 1,
          "initial service credit did not close");
}

void test_inflight_reactivation_is_lossless_and_coalesced() {
  Fixture fixture;
  require(fixture.owner.try_activate(11), "initial activation was rejected");
  fixture.step();
  std::uint32_t key = 0;
  require(fixture.owner.try_dispatch(0, key), "dispatch was rejected");
  fixture.step();
  require(fixture.owner.try_activate(11), "reactivation was rejected");
  fixture.step();
  require(fixture.owner.state(11) == SpineOwnerKeyState{false, true, true},
          "reactivation did not set dirty in flight");
  require(fixture.owner.reactivation_size(0) == 1 &&
              fixture.owner.work_credits() == 2,
          "reactivation did not retain a second work credit");
  require(fixture.owner.try_activate(11), "duplicate dirty activation stalled");
  fixture.step();
  require(fixture.owner.reactivation_size(0) == 1 &&
              fixture.owner.stats().coalesced_activations == 1,
          "duplicate dirty activation was not coalesced");
  require(fixture.owner.try_complete(11), "first service did not complete");
  fixture.step();
  require(fixture.owner.state(11) == SpineOwnerKeyState{false, false, true},
          "completion lost pending reactivation state");
  fixture.step();
  require(fixture.owner.state(11) == SpineOwnerKeyState{true, false, false},
          "pending reactivation did not return to owner FIFO");
  require(fixture.owner.try_dispatch(0, key), "reactivation did not dispatch");
  fixture.step();
  require(fixture.owner.try_complete(11), "reactivation did not complete");
  fixture.step();
  require(fixture.owner.quiescent() && fixture.owner.ledger_closed(),
          "reactivation ledger did not close");
  require(fixture.owner.stats().work_credits_created == 2 &&
              fixture.owner.stats().work_credits_retired == 2,
          "reactivation credit accounting is wrong");
}

void test_owner_fifo_backpressures_without_mutating_state() {
  Fixture fixture(SpineOwnerSchedulerConfig{
      .max_vertices = 8,
      .partitions = 1,
      .vertices_per_partition = 8,
      .owner_fifo_depth = 1,
      .reactivation_fifo_depth = 1,
  });
  require(fixture.owner.try_activate(1), "first activation was rejected");
  fixture.step();
  require(!fixture.owner.try_activate(2), "full owner FIFO accepted a key");
  require(fixture.owner.state(2) == SpineOwnerKeyState{},
          "rejected owner activation mutated state");
  require(fixture.owner.stats().owner_fifo_backpressure_cycles == 1,
          "owner backpressure was not counted");
}

void test_reactivation_fifo_backpressures_without_losing_owner() {
  Fixture fixture(SpineOwnerSchedulerConfig{
      .max_vertices = 8,
      .partitions = 1,
      .vertices_per_partition = 8,
      .owner_fifo_depth = 2,
      .reactivation_fifo_depth = 1,
  });
  std::uint32_t key = 0;
  require(fixture.owner.try_activate(1), "key 1 activation failed");
  fixture.step();
  require(fixture.owner.try_dispatch(0, key), "key 1 dispatch failed");
  fixture.step();
  require(fixture.owner.try_activate(2), "key 2 activation failed");
  fixture.step();
  require(fixture.owner.try_dispatch(0, key), "key 2 dispatch failed");
  fixture.step();
  require(fixture.owner.try_activate(1), "key 1 reactivation failed");
  fixture.step();
  require(!fixture.owner.try_activate(2),
          "full reactivation FIFO accepted another owner");
  require(fixture.owner.state(2) == SpineOwnerKeyState{false, true, false},
          "rejected reactivation changed key 2 state");
  require(fixture.owner.stats().reactivation_fifo_backpressure_cycles == 1,
          "reactivation backpressure was not counted");
}

void test_partitions_dispatch_independently_in_one_cycle() {
  Fixture fixture(SpineOwnerSchedulerConfig{
      .max_vertices = 8,
      .partitions = 2,
      .vertices_per_partition = 4,
      .owner_fifo_depth = 2,
      .reactivation_fifo_depth = 2,
  });
  require(fixture.owner.try_activate(1), "partition 0 activation failed");
  fixture.step();
  require(fixture.owner.try_activate(6), "partition 1 activation failed");
  fixture.step();
  std::uint32_t first = 0;
  std::uint32_t second = 0;
  require(fixture.owner.try_dispatch(0, first) &&
              fixture.owner.try_dispatch(1, second),
          "partitions could not dispatch concurrently");
  fixture.step();
  require(first == 1 && second == 6 &&
              fixture.owner.stats().dispatches == 2,
          "parallel partition dispatch returned wrong keys");
}

void test_bounded_domain_rejects_unknown_vertex() {
  Fixture fixture(SpineOwnerSchedulerConfig{
      .max_vertices = 8,
      .partitions = 1,
      .vertices_per_partition = 8,
      .owner_fifo_depth = 2,
      .reactivation_fifo_depth = 2,
  });
  bool rejected = false;
  try {
    static_cast<void>(fixture.owner.try_activate(8));
  } catch (const std::out_of_range &) {
    rejected = true;
  }
  require(rejected, "owner scheduler accepted an out-of-domain vertex");
}

}  // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"initial_credit", test_initial_dispatch_completion_closes_credit},
      {"lossless_reactivation",
       test_inflight_reactivation_is_lossless_and_coalesced},
      {"owner_backpressure",
       test_owner_fifo_backpressures_without_mutating_state},
      {"reactivation_backpressure",
       test_reactivation_fifo_backpressures_without_losing_owner},
      {"partition_parallelism",
       test_partitions_dispatch_independently_in_one_cycle},
      {"bounded_domain", test_bounded_domain_rejects_unknown_vertex},
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
