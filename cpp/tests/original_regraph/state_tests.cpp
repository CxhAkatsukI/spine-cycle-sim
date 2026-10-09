#include "state_execution.hpp"

namespace {
using namespace original_regraph_state_test;

void test_state_matrix() {
  StateWiring basic(128);
  const auto baseline = basic.run("a4_state", 0);
  const auto reused = basic.run("a4_state_reused", 0);
  require(baseline == reused, "reused state path changed values/cycles/counters");
  StateWiring reverse(128, {.reverse_registration = true});
  require(baseline == reverse.run("a4_state_reverse", 0), "state registration order changed results");
  StateWiring narrow(128, {.fifo_depth = 1, .apply_credits = 1, .writer_credits = 1});
  const auto pressured = narrow.run("a4_state_one_credit", 0);
  require(pressured.values == baseline.values && pressured.cycles > baseline.cycles &&
          pressured.apply_credit_stalls,
          "Apply credit limit did not propagate backpressure or changed output");
  StateWiring write_narrow(128, {.fifo_depth = 1, .writer_credits = 1});
  const auto write_pressure = write_narrow.run("a4_state_one_writer_credit", 0);
  require(write_pressure.values == baseline.values && write_pressure.cycles > baseline.cycles &&
          write_pressure.writer_credit_stalls && write_pressure.apply_output_stalls,
          "writer credit limit did not propagate upstream or changed output");
  StateWiring slow(128, {.memory_latency = 128});
  const auto delayed = slow.run("a4_state_memory128", 0);
  require(delayed.values == baseline.values && delayed.cycles > baseline.cycles,
          "state memory latency had no effect");
  require(baseline.waited_for_write_ack, "state completion ignored writer acknowledgement tail");
}

void test_arithmetic_boundary() {
  require(rg::apply_pr_property(4095, 0, 17) == 0 && rg::apply_pr_property(4095, 65537, 17) == 0,
          "PR zero/large degree mismatch");
  bool rejected = false;
  try { rg::apply_pr_property(100000000u, 1, 0); }
  catch (const std::out_of_range&) { rejected = true; }
  require(rejected, "signed-overflow source domain was silently admitted");
}

void test_invalid_protocol() {
  const auto reject = [](const char* id, auto inject, const std::string& diagnostic) {
    StateWiring network(1);
    network.state.begin(0);
    inject(network);
    bool rejected = false;
    try { for (unsigned cycle = 0; cycle < 5; ++cycle) network.memory.scheduler.step(); }
    catch (const std::logic_error& error) {
      require(std::string{error.what()}.find(diagnostic) != std::string::npos,
              "protocol rejection had an unexpected reason");
      rejected = true;
    }
    require(rejected, "invalid state protocol was not rejected");
    std::cout << "STATE_REJECTION {\"id\":\"" << id << "\",\"expected_rejection\":true}\n";
  };
  reject("apply_early_end", [](auto& network) {
    require(network.state.indexed->try_push({{}, 0, true}), "inject Apply terminator");
  }, "Apply input terminated");
  reject("degree_extent", [](auto& network) {
    require(network.state.indexed->try_push({{}, 1, false}), "inject invalid degree index");
  }, "Apply degree index");
  reject("writer_early_end", [](auto& network) {
    require(network.state.applied->try_push({{}, 0, true}), "inject writer terminator");
  }, "property stream terminated");
  reject("writer_extent", [](auto& network) {
    require(network.state.applied->try_push({{}, 1, false}), "inject invalid writer index");
  }, "property-write index");
  reject("unknown_write_ack", [](auto& network) {
    require(network.state.writers.front().responses->try_push({
        .transaction_id = 999, .operation = spine::sim::MemoryOperation::kWrite, .success = true,
        .read_data = {}}), "inject unknown write ack");
  }, "unexpected property-write acknowledgement");
}
}  // namespace

int main() {
  try {
    emit_configuration();
    test_state_matrix();
    test_arithmetic_boundary();
    test_invalid_protocol();
    std::cout << "Original PR state checks passed (explicit signed-overflow boundary)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
