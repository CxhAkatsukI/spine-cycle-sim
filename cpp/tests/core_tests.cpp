#include <cstdint>
#include <exception>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/banked_memory.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"

namespace {

using spine::sim::AxiConfig;
using spine::sim::AxiMaster;
using spine::sim::AxiRequest;
using spine::sim::AxiResponse;
using spine::sim::BankedMemory;
using spine::sim::BankedMemoryConfig;
using spine::sim::ClockId;
using spine::sim::Component;
using spine::sim::CycleContext;
using spine::sim::Fifo;
using spine::sim::MemoryOperation;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::OnChipOperation;
using spine::sim::OnChipRequest;
using spine::sim::OnChipResponse;
using spine::sim::ReadAfterWritePolicy;
using spine::sim::Scheduler;

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

class EdgeCounter final : public Component {
 public:
  EdgeCounter(std::string name, ClockId clock) : Component(std::move(name), clock) {}
  void evaluate(const CycleContext&) override { ++evaluations; }
  void commit(const CycleContext&) override { ++commits; }
  std::uint64_t evaluations{};
  std::uint64_t commits{};
};

template <typename T>
class SequenceProducer final : public Component {
 public:
  SequenceProducer(std::string name, ClockId clock, Fifo<T>& output,
                   std::vector<T> values)
      : Component(std::move(name), clock),
        output_(output),
        values_(std::move(values)) {}

  void evaluate(const CycleContext&) override {
    accepted_ = index_ < values_.size() && output_.try_push(values_[index_]);
  }
  void commit(const CycleContext&) override {
    if (accepted_) {
      ++index_;
      accepted_ = false;
    }
  }
  [[nodiscard]] bool done() const noexcept { return index_ == values_.size(); }

 private:
  Fifo<T>& output_;
  std::vector<T> values_;
  std::size_t index_{};
  bool accepted_{};
};

template <typename T>
class SequenceConsumer final : public Component {
 public:
  SequenceConsumer(std::string name, ClockId clock, Fifo<T>& input,
                   std::uint64_t start_cycle = 0)
      : Component(std::move(name), clock), input_(input), start_cycle_(start_cycle) {}

  void evaluate(const CycleContext& context) override {
    accepted_ = false;
    if (context.domain_cycle >= start_cycle_) {
      accepted_ = input_.try_pop(staged_);
    }
  }
  void commit(const CycleContext&) override {
    if (accepted_) {
      values.push_back(staged_);
      accepted_ = false;
    }
  }
  std::vector<T> values;

 private:
  Fifo<T>& input_;
  std::uint64_t start_cycle_{};
  T staged_{};
  bool accepted_{};
};

void test_multiclock_scheduler() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  const auto hbm = scheduler.add_clock_mhz("hbm", 250.0);
  EdgeCounter core_counter("core-counter", core);
  EdgeCounter hbm_counter("hbm-counter", hbm);
  scheduler.add_component(core_counter);
  scheduler.add_component(hbm_counter);

  scheduler.run_events(6);

  require(core_counter.evaluations == 2, "100 MHz edge count mismatch");
  require(hbm_counter.evaluations == 5, "250 MHz edge count mismatch");
  require(core_counter.evaluations == core_counter.commits,
          "evaluate/commit count mismatch");
  require(scheduler.now_fs() == 16'000'000, "unexpected absolute timestamp");
}

void test_fifo_has_no_same_cycle_fallthrough() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 1);
  SequenceProducer<int> producer("producer", core, fifo, {7});
  SequenceConsumer<int> consumer("consumer", core, fifo);
  scheduler.add_component(consumer);
  scheduler.add_component(fifo);
  scheduler.add_component(producer);

  scheduler.step();
  require(consumer.values.empty(), "FIFO allowed same-cycle fall-through");
  require(fifo.size() == 1, "producer value was not committed");
  scheduler.step();
  require(consumer.values == std::vector<int>{7}, "consumer missed committed value");
  require(fifo.stats().pushes == 1 && fifo.stats().pops == 1,
          "FIFO activity counters mismatch");
}

std::vector<int> run_fifo_order_case(bool producer_first) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 2);
  SequenceProducer<int> producer("producer", core, fifo, {3, 5, 8});
  SequenceConsumer<int> consumer("consumer", core, fifo);
  if (producer_first) {
    scheduler.add_component(producer);
    scheduler.add_component(fifo);
    scheduler.add_component(consumer);
  } else {
    scheduler.add_component(consumer);
    scheduler.add_component(fifo);
    scheduler.add_component(producer);
  }
  scheduler.run_until([&consumer] { return consumer.values.size() == 3; }, 12);
  return consumer.values;
}

void test_fifo_is_registration_order_independent() {
  const auto forward = run_fifo_order_case(true);
  const auto reverse = run_fifo_order_case(false);
  require(forward == std::vector<int>({3, 5, 8}), "forward order lost data");
  require(reverse == forward, "component registration order changed FIFO behavior");
}

void test_fifo_backpressure_is_counted() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<int> fifo("fifo", core, 1);
  SequenceProducer<int> producer("producer", core, fifo, {1, 2});
  SequenceConsumer<int> consumer("consumer", core, fifo, 3);
  scheduler.add_component(producer);
  scheduler.add_component(consumer);
  scheduler.add_component(fifo);

  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 10);
  require(consumer.values == std::vector<int>({1, 2}), "FIFO reordered values");
  require(fifo.stats().push_stalls >= 2, "full FIFO stalls were not counted");
  require(fifo.stats().max_occupancy == 1, "FIFO max occupancy mismatch");
}

BankedMemoryConfig memory_config(ReadAfterWritePolicy policy =
                                     ReadAfterWritePolicy::kStall) {
  return BankedMemoryConfig{
      .banks = 1,
      .capacity_words = 1024,
      .read_ports_per_bank = 1,
      .write_ports_per_bank = 1,
      .latency_cycles = 2,
      .max_outstanding_per_port = 4,
      .raw_policy = policy,
  };
}

void register_port(Scheduler& scheduler, Component& producer,
                   Fifo<OnChipRequest>& requests,
                   Fifo<OnChipResponse>& responses, Component& consumer) {
  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
}

void test_banked_memory_conflict_and_round_robin() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  memory.initialize_word(2, 22);
  memory.initialize_word(4, 44);

  Fifo<OnChipRequest> req0("req0", core, 2);
  Fifo<OnChipResponse> rsp0("rsp0", core, 2);
  Fifo<OnChipRequest> req1("req1", core, 2);
  Fifo<OnChipResponse> rsp1("rsp1", core, 2);
  memory.attach_port(req0, rsp0);
  memory.attach_port(req1, rsp1);

  SequenceProducer<OnChipRequest> producer0(
      "producer0", core, req0,
      {{.transaction_id = 10, .operation = OnChipOperation::kRead, .word_address = 2}});
  SequenceProducer<OnChipRequest> producer1(
      "producer1", core, req1,
      {{.transaction_id = 11, .operation = OnChipOperation::kRead, .word_address = 4}});
  SequenceConsumer<OnChipResponse> consumer0("consumer0", core, rsp0);
  SequenceConsumer<OnChipResponse> consumer1("consumer1", core, rsp1);

  register_port(scheduler, producer0, req0, rsp0, consumer0);
  register_port(scheduler, producer1, req1, rsp1, consumer1);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] { return consumer0.values.size() == 1 && consumer1.values.size() == 1; },
      16);

  require(consumer0.values[0].read_data == 22, "port 0 read data mismatch");
  require(consumer1.values[0].read_data == 44, "port 1 read data mismatch");
  require(memory.stats().accepted_reads == 2, "read acceptance mismatch");
  require(memory.stats().read_bank_conflict_stalls >= 1,
          "same-bank conflict was not counted");
  require(memory.stats().max_outstanding >= 2,
          "outstanding request depth was not observed");
}

void test_banked_memory_stalls_read_after_write() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  memory.initialize_word(8, 1);

  Fifo<OnChipRequest> write_req("write-req", core, 2);
  Fifo<OnChipResponse> write_rsp("write-rsp", core, 2);
  Fifo<OnChipRequest> read_req("read-req", core, 2);
  Fifo<OnChipResponse> read_rsp("read-rsp", core, 2);
  memory.attach_port(write_req, write_rsp);
  memory.attach_port(read_req, read_rsp);

  SequenceProducer<OnChipRequest> writer(
      "writer", core, write_req,
      {{.transaction_id = 20,
        .operation = OnChipOperation::kWrite,
        .word_address = 8,
        .write_data = 99}});
  SequenceProducer<OnChipRequest> reader(
      "reader", core, read_req,
      {{.transaction_id = 21, .operation = OnChipOperation::kRead, .word_address = 8}});
  SequenceConsumer<OnChipResponse> write_sink("write-sink", core, write_rsp);
  SequenceConsumer<OnChipResponse> read_sink("read-sink", core, read_rsp);

  register_port(scheduler, writer, write_req, write_rsp, write_sink);
  register_port(scheduler, reader, read_req, read_rsp, read_sink);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] { return write_sink.values.size() == 1 && read_sink.values.size() == 1; },
      20);

  require(read_sink.values[0].read_data == 99, "RAW-protected read saw stale data");
  require(memory.inspect_word(8) == 99, "write did not update memory");
  require(memory.stats().raw_hazard_stalls >= 2, "RAW stalls were not counted");
}

void test_invalid_clock_and_capacity_are_rejected() {
  Scheduler scheduler;
  bool clock_failed = false;
  try {
    static_cast<void>(scheduler.add_clock_mhz("bad", 0.0));
  } catch (const std::invalid_argument&) {
    clock_failed = true;
  }
  require(clock_failed, "zero-frequency clock was accepted");

  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  bool address_failed = false;
  try {
    memory.initialize_word(1024, 1);
  } catch (const std::out_of_range&) {
    address_failed = true;
  }
  require(address_failed, "out-of-capacity address was accepted");
}

AxiConfig axi_config() {
  return AxiConfig{
      .initiator_id = 0,
      .data_width_bytes = 64,
      .max_burst_beats = 16,
      .channels = 2,
      .channel_interleave_bytes = 64,
      .max_pending_requests = 4,
      .max_outstanding_bursts = 2,
      .address_accepts_per_cycle = 1,
      .beat_issues_per_cycle = 2,
      .response_beats_per_cycle = 2,
      .fixed_channel = std::nullopt,
  };
}

MockMemoryConfig mock_memory_config(std::uint64_t latency = 3) {
  return MockMemoryConfig{
      .channels = 2,
      .latency_cycles = latency,
      .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 32,
      .response_queue_depth = 16,
  };
}

struct TwoMasterResult {
  std::uint64_t cycles{};
  std::uint64_t backend_stalls{};
};

TwoMasterResult run_two_axi_masters(std::size_t second_channel) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  MockMemoryBackend backend("shared-hbm", core, mock_memory_config());

  Fifo<AxiRequest> request0("request0", core, 2);
  Fifo<AxiResponse> response0("response0", core, 2);
  Fifo<AxiRequest> request1("request1", core, 2);
  Fifo<AxiResponse> response1("response1", core, 2);
  AxiConfig config0 = axi_config();
  config0.initiator_id = 10;
  config0.fixed_channel = 0;
  AxiConfig config1 = axi_config();
  config1.initiator_id = 11;
  config1.fixed_channel = second_channel;
  AxiMaster axi0("axi0", core, config0, request0, response0, backend);
  AxiMaster axi1("axi1", core, config1, request1, response1, backend);
  SequenceProducer<AxiRequest> producer0(
      "producer0", core, request0,
      {{.transaction_id = 100,
        .operation = MemoryOperation::kRead,
        .address = 0,
        .bytes = 64}});
  SequenceProducer<AxiRequest> producer1(
      "producer1", core, request1,
      {{.transaction_id = 200,
        .operation = MemoryOperation::kWrite,
        .address = 4096,
        .bytes = 64}});
  SequenceConsumer<AxiResponse> consumer0("consumer0", core, response0);
  SequenceConsumer<AxiResponse> consumer1("consumer1", core, response1);

  scheduler.add_component(producer0);
  scheduler.add_component(producer1);
  scheduler.add_component(request0);
  scheduler.add_component(request1);
  scheduler.add_component(axi0);
  scheduler.add_component(axi1);
  scheduler.add_component(backend);
  scheduler.add_component(response0);
  scheduler.add_component(response1);
  scheduler.add_component(consumer0);
  scheduler.add_component(consumer1);
  scheduler.run_until(
      [&] { return consumer0.values.size() == 1 && consumer1.values.size() == 1; },
      100);

  require(consumer0.values[0].transaction_id == 100,
          "initiator 0 received the wrong AXI response");
  require(consumer1.values[0].transaction_id == 200,
          "initiator 1 received the wrong AXI response");
  require(axi0.stats().read_bytes == 64 && axi0.stats().write_bytes == 0,
          "initiator 0 activity was mixed with initiator 1");
  require(axi1.stats().read_bytes == 0 && axi1.stats().write_bytes == 64,
          "initiator 1 activity was mixed with initiator 0");
  return TwoMasterResult{
      .cycles = scheduler.clock(core).completed_cycles,
      .backend_stalls = axi0.stats().backend_submit_stalls +
                        axi1.stats().backend_submit_stalls,
  };
}

void test_axi_multi_initiator_fixed_channel_isolation() {
  const TwoMasterResult separate = run_two_axi_masters(1);
  const TwoMasterResult contended = run_two_axi_masters(0);
  require(separate.backend_stalls == 0,
          "separate HBM channels unexpectedly contended");
  require(contended.backend_stalls > 0,
          "shared HBM channel contention was not visible");
  require(contended.cycles > separate.cycles,
          "shared HBM channel did not delay completion");
}

void test_axi_rejects_duplicate_initiator_id() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  MockMemoryBackend backend("shared-hbm", core, mock_memory_config());
  Fifo<AxiRequest> request0("request0", core, 2);
  Fifo<AxiResponse> response0("response0", core, 2);
  Fifo<AxiRequest> request1("request1", core, 2);
  Fifo<AxiResponse> response1("response1", core, 2);
  AxiConfig config = axi_config();
  config.initiator_id = 5;
  AxiMaster first("first", core, config, request0, response0, backend);
  bool failed = false;
  try {
    AxiMaster duplicate("duplicate", core, config, request1, response1, backend);
  } catch (const std::invalid_argument&) {
    failed = true;
  }
  require(failed, "duplicate memory initiator ID was accepted");
}

void test_axi_splits_bursts_and_uses_backend_online() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 2);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config());
  AxiMaster axi("axi", core, axi_config(), requests, responses, backend);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {{.transaction_id = 42,
        .operation = MemoryOperation::kRead,
        .address = 4032,
        .bytes = 1600}});
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses);

  scheduler.add_component(backend);
  scheduler.add_component(consumer);
  scheduler.add_component(responses);
  scheduler.add_component(axi);
  scheduler.add_component(requests);
  scheduler.add_component(producer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 1; }, 200);

  require(consumer.values[0].transaction_id == 42 && consumer.values[0].success,
          "AXI response mismatch");
  require(axi.stats().requests_accepted == 1 &&
              axi.stats().requests_completed == 1,
          "AXI request counters mismatch");
  require(axi.stats().bursts_accepted == 3,
          "AXI max-burst/4 KiB splitting produced the wrong burst count");
  require(axi.stats().four_kib_splits == 1, "AXI missed a 4 KiB split");
  require(axi.stats().beats_issued == 25 && axi.stats().beats_completed == 25,
          "AXI beat counters mismatch");
  require(axi.stats().read_bytes == 1600, "AXI byte counter mismatch");
  require(axi.stats().max_outstanding_bursts == 2,
          "AXI outstanding burst limit was not exercised");
  require(backend.stats().accepted == 25, "mock backend did not see every beat");
}

void test_axi_response_backpressure_is_lossless() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 100.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 1);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config(1));
  AxiMaster axi("axi", core, axi_config(), requests, responses, backend);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 1,
           .operation = MemoryOperation::kWrite,
           .address = 0,
           .bytes = 64},
          {.transaction_id = 2,
           .operation = MemoryOperation::kWrite,
           .address = 64,
           .bytes = 64},
      });
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses, 20);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 80);

  require(consumer.values[0].transaction_id == 1 &&
              consumer.values[1].transaction_id == 2,
          "AXI response backpressure reordered or lost requests");
  require(axi.stats().response_queue_stalls > 0,
          "AXI response FIFO backpressure was not counted");
  require(axi.stats().write_bytes == 128, "AXI write byte count mismatch");
}

}  // namespace

int main() {
  const std::vector<std::pair<std::string, std::function<void()>>> tests = {
      {"multiclock_scheduler", test_multiclock_scheduler},
      {"fifo_no_fallthrough", test_fifo_has_no_same_cycle_fallthrough},
      {"fifo_order_independent", test_fifo_is_registration_order_independent},
      {"fifo_backpressure", test_fifo_backpressure_is_counted},
      {"bank_conflict", test_banked_memory_conflict_and_round_robin},
      {"raw_hazard", test_banked_memory_stalls_read_after_write},
      {"invalid_config", test_invalid_clock_and_capacity_are_rejected},
      {"axi_online_backend", test_axi_splits_bursts_and_uses_backend_online},
      {"axi_response_backpressure", test_axi_response_backpressure_is_lossless},
      {"axi_multi_initiator", test_axi_multi_initiator_fixed_channel_isolation},
      {"axi_duplicate_initiator", test_axi_rejects_duplicate_initiator_id},
  };
  std::size_t failures = 0;
  for (const auto& [name, test] : tests) {
    try {
      test();
      std::cout << "PASS " << name << '\n';
    } catch (const std::exception& error) {
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
