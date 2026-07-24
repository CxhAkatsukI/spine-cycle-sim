#include <algorithm>
#include <array>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/banked_memory.hpp"
#include "spine_sim/component.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_l0.hpp"
#include "spine_sim/spine_split.hpp"
#include "spine_sim/spine_system.hpp"

namespace {

using spine::sim::AxiConfig;
using spine::sim::AxiMaster;
using spine::sim::AxiReadBeatResponse;
using spine::sim::AxiRequest;
using spine::sim::AxiResponse;
using spine::sim::AxiStats;
using spine::sim::BankedMemory;
using spine::sim::BankedMemoryConfig;
using spine::sim::ClockId;
using spine::sim::Component;
using spine::sim::CycleContext;
using spine::sim::decode_spine_level_edge;
using spine::sim::decode_spine_sort_edge;
using spine::sim::encode_spine_level_edge;
using spine::sim::encode_spine_sort_edge;
using spine::sim::Fifo;
using spine::sim::FifoStats;
using spine::sim::FixedAxiPort;
using spine::sim::FixedAxiPortConfig;
using spine::sim::load_spine_edge_slice;
using spine::sim::MemoryOperation;
using spine::sim::MockMemoryBackend;
using spine::sim::MockMemoryConfig;
using spine::sim::OnChipOperation;
using spine::sim::OnChipRequest;
using spine::sim::OnChipResponse;
using spine::sim::PartConvWord;
using spine::sim::PartConvWordKind;
using spine::sim::ReadAfterWritePolicy;
using spine::sim::Scheduler;
using spine::sim::SourceValueWord;
using spine::sim::spine_hot_shard;
using spine::sim::spine_dirty_identity;
using spine::sim::spine_level_layout;
using spine::sim::spine_metadata_layout;
using spine::sim::SpineActiveBins;
using spine::sim::SpineActiveRecord;
using spine::sim::SpineAxiInterfaceProfile;
using spine::sim::SpineAxiPortKind;
using spine::sim::SpineComputeCounters;
using spine::sim::SpineComputePorts;
using spine::sim::SpineDirtyIdentity;
using spine::sim::SpineDirtyStatus;
using spine::sim::SpineEdgeRecord;
using spine::sim::SpineEdgeSlice;
using spine::sim::SpineL0Config;
using spine::sim::SpineL0Counters;
using spine::sim::SpineL0Maintenance;
using spine::sim::SpineL0Ports;
using spine::sim::SpineL0State;
using spine::sim::SpineLevelLayout;
using spine::sim::SpineReaderCounters;
using spine::sim::SpineReaderPorts;
using spine::sim::SpineSplitReader;
using spine::sim::SpineSplitSsspCompute;
using spine::sim::SpineVerticalSliceSystem;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::vector<std::uint8_t> u64_payload(std::uint64_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] = static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

std::vector<std::uint8_t> u32_payload(std::uint32_t value) {
  std::vector<std::uint8_t> data(sizeof(value));
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[byte] =
        static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
  return data;
}

std::vector<SourceValueWord> source_protocol_reply(std::uint32_t source,
                                                   std::uint32_t value) {
  return {
      SourceValueWord{.source = source, .value = value},
      SourceValueWord{.kind = SourceValueWord::Kind::kProtocolAck,
                      .value = static_cast<std::uint32_t>(
                          spine::sim::SpineSourceProtocolStatus::kOk)},
  };
}

class EdgeCounter final : public Component {
 public:
  EdgeCounter(std::string name, ClockId clock)
      : Component(std::move(name), clock) {}
  void evaluate(const CycleContext &) override { ++evaluations; }
  void commit(const CycleContext &) override { ++commits; }
  std::uint64_t evaluations{};
  std::uint64_t commits{};
};

template <typename T>
class SequenceProducer final : public Component {
 public:
  SequenceProducer(std::string name, ClockId clock, Fifo<T> &output,
                   std::vector<T> values)
      : Component(std::move(name), clock),
        output_(output),
        values_(std::move(values)) {}

  void evaluate(const CycleContext &) override {
    accepted_ = index_ < values_.size() && output_.try_push(values_[index_]);
  }
  void commit(const CycleContext &) override {
    if (accepted_) {
      ++index_;
      accepted_ = false;
    }
  }
  [[nodiscard]] bool done() const noexcept { return index_ == values_.size(); }

 private:
  Fifo<T> &output_;
  std::vector<T> values_;
  std::size_t index_{};
  bool accepted_{};
};

template <typename T>
class SequenceConsumer final : public Component {
 public:
  SequenceConsumer(std::string name, ClockId clock, Fifo<T> &input,
                   std::uint64_t start_cycle = 0)
      : Component(std::move(name), clock),
        input_(input),
        start_cycle_(start_cycle) {}

  void evaluate(const CycleContext &context) override {
    accepted_ = false;
    if (context.domain_cycle >= start_cycle_) {
      accepted_ = input_.try_pop(staged_);
    }
  }
  void commit(const CycleContext &) override {
    if (accepted_) {
      values.push_back(staged_);
      accepted_ = false;
    }
  }
  std::vector<T> values;

 private:
  Fifo<T> &input_;
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
  require(consumer.values == std::vector<int>{7},
          "consumer missed committed value");
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
  require(reverse == forward,
          "component registration order changed FIFO behavior");
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

BankedMemoryConfig memory_config(
    ReadAfterWritePolicy policy = ReadAfterWritePolicy::kStall) {
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

void register_port(Scheduler &scheduler, Component &producer,
                   Fifo<OnChipRequest> &requests,
                   Fifo<OnChipResponse> &responses, Component &consumer) {
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
      {{.transaction_id = 10,
        .operation = OnChipOperation::kRead,
        .word_address = 2}});
  SequenceProducer<OnChipRequest> producer1(
      "producer1", core, req1,
      {{.transaction_id = 11,
        .operation = OnChipOperation::kRead,
        .word_address = 4}});
  SequenceConsumer<OnChipResponse> consumer0("consumer0", core, rsp0);
  SequenceConsumer<OnChipResponse> consumer1("consumer1", core, rsp1);

  register_port(scheduler, producer0, req0, rsp0, consumer0);
  register_port(scheduler, producer1, req1, rsp1, consumer1);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] {
        return consumer0.values.size() == 1 && consumer1.values.size() == 1;
      },
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

  SequenceProducer<OnChipRequest> writer("writer", core, write_req,
                                         {{.transaction_id = 20,
                                           .operation = OnChipOperation::kWrite,
                                           .word_address = 8,
                                           .write_data = 99}});
  SequenceProducer<OnChipRequest> reader("reader", core, read_req,
                                         {{.transaction_id = 21,
                                           .operation = OnChipOperation::kRead,
                                           .word_address = 8}});
  SequenceConsumer<OnChipResponse> write_sink("write-sink", core, write_rsp);
  SequenceConsumer<OnChipResponse> read_sink("read-sink", core, read_rsp);

  register_port(scheduler, writer, write_req, write_rsp, write_sink);
  register_port(scheduler, reader, read_req, read_rsp, read_sink);
  scheduler.add_component(memory);
  scheduler.run_until(
      [&] {
        return write_sink.values.size() == 1 && read_sink.values.size() == 1;
      },
      20);

  require(read_sink.values[0].read_data == 99,
          "RAW-protected read saw stale data");
  require(memory.inspect_word(8) == 99, "write did not update memory");
  require(memory.stats().raw_hazard_stalls >= 2, "RAW stalls were not counted");
}

void test_invalid_clock_and_capacity_are_rejected() {
  Scheduler scheduler;
  bool clock_failed = false;
  try {
    static_cast<void>(scheduler.add_clock_mhz("bad", 0.0));
  } catch (const std::invalid_argument &) {
    clock_failed = true;
  }
  require(clock_failed, "zero-frequency clock was accepted");

  const auto core = scheduler.add_clock_mhz("core", 100.0);
  BankedMemory memory("bram", core, memory_config());
  bool address_failed = false;
  try {
    memory.initialize_word(1024, 1);
  } catch (const std::out_of_range &) {
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
  SequenceProducer<AxiRequest> producer0("producer0", core, request0,
                                         {{.transaction_id = 100,
                                           .operation = MemoryOperation::kRead,
                                           .address = 0,
                                           .bytes = 64,
                                           .write_data = {}}});
  SequenceProducer<AxiRequest> producer1("producer1", core, request1,
                                         {{.transaction_id = 200,
                                           .operation = MemoryOperation::kWrite,
                                           .address = 4096,
                                           .bytes = 64,
                                           .write_data = {}}});
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
      [&] {
        return consumer0.values.size() == 1 && consumer1.values.size() == 1;
      },
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
    AxiMaster duplicate("duplicate", core, config, request1, response1,
                        backend);
  } catch (const std::invalid_argument &) {
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
  SequenceProducer<AxiRequest> producer("requester", core, requests,
                                        {{.transaction_id = 42,
                                          .operation = MemoryOperation::kRead,
                                          .address = 4032,
                                          .bytes = 1600,
                                          .write_data = {}}});
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
  require(
      axi.stats().requests_accepted == 1 && axi.stats().requests_completed == 1,
      "AXI request counters mismatch");
  require(axi.stats().bursts_accepted == 3,
          "AXI max-burst/4 KiB splitting produced the wrong burst count");
  require(axi.stats().four_kib_splits == 1, "AXI missed a 4 KiB split");
  require(axi.stats().beats_issued == 25 && axi.stats().beats_completed == 25,
          "AXI beat counters mismatch");
  require(axi.stats().read_bytes == 1600, "AXI byte counter mismatch");
  require(axi.stats().max_outstanding_bursts == 2,
          "AXI outstanding burst limit was not exercised");
  require(backend.stats().accepted == 25,
          "mock backend did not see every beat");
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
           .bytes = 64,
           .write_data = {}},
          {.transaction_id = 2,
           .operation = MemoryOperation::kWrite,
           .address = 64,
           .bytes = 64,
           .write_data = {}},
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

void test_axi_payload_round_trip_across_beats_and_bursts() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 4);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config());
  AxiConfig config = axi_config();
  config.fixed_channel = 0;
  AxiMaster axi("axi", core, config, requests, responses, backend);

  std::vector<std::uint8_t> read_pattern(1600);
  for (std::size_t index = 0; index < read_pattern.size(); ++index) {
    read_pattern[index] = static_cast<std::uint8_t>((index * 17 + 3) & 0xff);
  }
  std::vector<std::uint8_t> write_pattern(130);
  for (std::size_t index = 0; index < write_pattern.size(); ++index) {
    write_pattern[index] = static_cast<std::uint8_t>((index * 29 + 11) & 0xff);
  }
  backend.initialize_payload(0, 4032, read_pattern);

  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 42,
           .operation = MemoryOperation::kRead,
           .address = 4032,
           .bytes = read_pattern.size(),
           .write_data = {}},
          {.transaction_id = 43,
           .operation = MemoryOperation::kWrite,
           .address = 8192,
           .bytes = write_pattern.size(),
           .write_data = write_pattern},
      });
  SequenceConsumer<AxiResponse> consumer("response-sink", core, responses);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(consumer);
  scheduler.run_until([&consumer] { return consumer.values.size() == 2; }, 300);

  const auto read_response =
      std::find_if(consumer.values.begin(), consumer.values.end(),
                   [](const AxiResponse &response) {
                     return response.transaction_id == 42;
                   });
  require(read_response != consumer.values.end() &&
              read_response->read_data == read_pattern,
          "AXI failed to reassemble payload across beats and bursts");
  require(
      backend.inspect_payload(0, 8192, write_pattern.size()) == write_pattern,
      "AXI write payload did not reach backend storage");
  require(axi.stats().zero_filled_write_bytes == 0,
          "explicit AXI write payload was reported as zero-filled");
}

void test_axi_read_beat_stream_is_bounded_and_request_scoped() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("core", 141.0);
  Fifo<AxiRequest> requests("axi-requests", core, 4);
  Fifo<AxiResponse> responses("axi-responses", core, 4);
  Fifo<AxiReadBeatResponse> read_beats("axi-read-beats", core, 2);
  MockMemoryBackend backend("mock-hbm", core, mock_memory_config(1));
  AxiConfig config = axi_config();
  config.data_width_bytes = 16;
  config.beat_issues_per_cycle = 1;
  config.response_beats_per_cycle = 1;
  config.fixed_channel = 0;
  AxiMaster axi("axi", core, config, requests, responses, backend, &read_beats);

  std::vector<std::uint8_t> payload(128);
  for (std::size_t index = 0; index < payload.size(); ++index) {
    payload[index] = static_cast<std::uint8_t>((index * 13 + 7) & 0xffU);
  }
  backend.initialize_payload(0, 0, payload);
  SequenceProducer<AxiRequest> producer(
      "requester", core, requests,
      {
          {.transaction_id = 70,
           .operation = MemoryOperation::kRead,
           .address = 0,
           .bytes = 64,
           .stream_read_beats = true,
           .write_data = {}},
          {.transaction_id = 71,
           .operation = MemoryOperation::kRead,
           .address = 64,
           .bytes = 64,
           .stream_read_beats = false,
           .write_data = {}},
      });
  SequenceConsumer<AxiReadBeatResponse> beat_consumer("beat-consumer", core,
                                                      read_beats, 12);
  SequenceConsumer<AxiResponse> response_consumer("response-consumer", core,
                                                  responses);

  scheduler.add_component(producer);
  scheduler.add_component(requests);
  scheduler.add_component(axi);
  scheduler.add_component(backend);
  scheduler.add_component(responses);
  scheduler.add_component(read_beats);
  scheduler.add_component(response_consumer);
  scheduler.add_component(beat_consumer);
  scheduler.run_until(
      [&] {
        return response_consumer.values.size() == 2 &&
               beat_consumer.values.size() == 4;
      },
      100);

  require(axi.stats().read_beat_queue_stalls > 0 &&
              axi.stats().read_beats_streamed == 4 &&
              read_beats.stats().max_occupancy == 2,
          "AXI read-beat FIFO did not apply finite backpressure");
  for (std::size_t index = 0; index < beat_consumer.values.size(); ++index) {
    const AxiReadBeatResponse &beat = beat_consumer.values[index];
    require(
        beat.transaction_id == 70 && beat.parent_offset == index * 16 &&
            beat.address == index * 16 && beat.last == (index == 3) &&
            beat.read_data ==
                std::vector<std::uint8_t>(
                    payload.begin() + static_cast<std::ptrdiff_t>(index * 16),
                    payload.begin() +
                        static_cast<std::ptrdiff_t>((index + 1) * 16)),
        "AXI read-beat stream changed payload order or framing");
  }
  const auto streamed_parent = std::find_if(
      response_consumer.values.begin(), response_consumer.values.end(),
      [](const AxiResponse &response) {
        return response.transaction_id == 70;
      });
  const auto ordinary_parent = std::find_if(
      response_consumer.values.begin(), response_consumer.values.end(),
      [](const AxiResponse &response) {
        return response.transaction_id == 71;
      });
  require(
      streamed_parent != response_consumer.values.end() &&
          ordinary_parent != response_consumer.values.end() &&
          streamed_parent->read_data ==
              std::vector<std::uint8_t>(payload.begin(),
                                        payload.begin() + 64) &&
          ordinary_parent->read_data ==
              std::vector<std::uint8_t>(payload.begin() + 64, payload.end()),
      "AXI parent responses diverged from streamed/non-streamed payloads");
}

void test_spine_l0_real_slice_vertical_path() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });

  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports;
  SpineL0Ports ports;
  for (std::size_t family = 0; family < graph_ports.size(); ++family) {
    graph_ports[family] = std::make_unique<FixedAxiPort>(
        "graph" + std::to_string(family), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = family,
            .initiator_id = static_cast<std::uint32_t>(family),
        },
        backend);
    ports.graph[family] = graph_ports[family].get();
  }
  FixedAxiPort sorted("sorted-edges", core,
                      FixedAxiPortConfig{
                          .memory_channels = 32,
                          .channel = 16,
                          .initiator_id = 16,
                      },
                      backend);
  FixedAxiPort metadata("metadata", core,
                        FixedAxiPortConfig{
                            .memory_channels = 32,
                            .channel = 20,
                            .initiator_id = 20,
                        },
                        backend);
  FixedAxiPort result("result", core,
                      FixedAxiPortConfig{
                          .memory_channels = 32,
                          .channel = 21,
                          .initiator_id = 21,
                      },
                      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  const auto workload = load_spine_edge_slice(fixture);
  SpineL0State state;
  SpineL0Maintenance maintenance("spine-l0-maintenance", core, SpineL0Config{},
                                 workload, ports, state);

  FixedAxiPort active_bins("active-bins", core,
                           FixedAxiPortConfig{
                               .memory_channels = 32,
                               .channel = 18,
                               .initiator_id = 18,
                           },
                           backend);
  FixedAxiPort vertex_state("vertex-state", core,
                            FixedAxiPortConfig{
                                .memory_channels = 32,
                                .channel = 17,
                                .initiator_id = 117,
                            },
                            backend);
  FixedAxiPort active_out("active-out", core,
                          FixedAxiPortConfig{
                              .memory_channels = 32,
                              .channel = 19,
                              .initiator_id = 119,
                          },
                          backend);
  FixedAxiPort active_bitmap("active-bitmap", core,
                             FixedAxiPortConfig{
                                 .memory_channels = 32,
                                 .channel = 22,
                                 .initiator_id = 122,
                             },
                             backend);
  FixedAxiPort compute_result("compute-result", core,
                              FixedAxiPortConfig{
                                  .memory_channels = 32,
                                  .channel = 21,
                                  .initiator_id = 121,
                              },
                              backend);
  Fifo<PartConvWord> edge_stream("edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("value-axis", core, 32);
  SpineReaderPorts reader_ports;
  reader_ports.graph = ports.graph;
  reader_ports.task_scratch = &sorted;
  reader_ports.active_bins = &active_bins;
  reader_ports.metadata = &metadata;
  reader_ports.result = &result;
  SpineSplitReader reader("spine-split-reader", core, maintenance, reader_ports,
                          {2}, edge_stream, value_stream);
  SpineSplitSsspCompute compute("spine-split-compute", core, workload.vertices,
                                2, 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &compute_result,
                                },
                                edge_stream, value_stream);

  scheduler.add_component(maintenance);
  scheduler.add_component(reader);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  active_bins.register_components(scheduler);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  compute_result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] { return maintenance.done() && reader.done() && compute.done(); },
      30'000);

  require(!maintenance.failed(), "Spine L0 real-slice path reported failure");
  const auto &counters = maintenance.counters();
  require(counters.sorted_scan_passes == 20,
          "Spine L0 did not execute the expected HLS scan passes");
  require(counters.sorted_edge_visits == 200,
          "Spine L0 edge-visit count does not close against scan passes");
  require(counters.sorted_read_bytes == 3'200,
          "Spine sorted-edge HBM byte count mismatch");
  require(counters.hot_cold_count_edge_visits == 10 &&
              counters.family_precount_edge_visits == 160 &&
              counters.l0_write_edge_visits == 10,
          "Spine source-shaped scan classes do not close");
  require(counters.unique_sources == 1 && counters.active_families == 1,
          "Amazon top1 family/source structure mismatch");
  require(counters.persisted_edges == 10 && counters.persisted_rows == 1,
          "Spine L0 persisted payload shape mismatch");
  require(counters.family_edges[0] == 10 && counters.family_rows[0] == 1,
          "Spine family0 metadata mismatch");
  require(counters.pages_stamped == 1,
          "Spine L0 source-page stamp count mismatch");
  require(counters.persistent_read_bytes == 32 &&
              counters.persistent_write_bytes == 32,
          "Spine dirty-frontier HBM byte count mismatch");
  require(counters.dirty_bitmap_reads == 1 &&
              counters.dirty_bitmap_writes == 1 &&
              counters.dirty_list_reads == 1 &&
              counters.dirty_list_appends == 1 &&
              counters.dirty_duplicates_suppressed == 9 &&
              counters.dirty_generation_advances == 1 &&
              counters.dirty_count == 1 && counters.dirty_generation == 1,
          "Spine dirty-frontier operation ledger mismatch");
  require(counters.graph_write_bytes == 144,
          "Spine L0 graph layout write byte count mismatch");
  require(counters.graph_index_payload_write_bytes == 64 &&
              counters.graph_edge_payload_write_bytes == 80,
          "Spine L0 graph write payload ledger mismatch");
  require(counters.metadata_read_bytes == 2'984 &&
              counters.metadata_write_bytes == 1'224,
          "Spine L0 metadata byte ledger mismatch");
  require(counters.result_write_bytes == 384,
          "Spine maintenance result byte count mismatch");
  require(state.cold_levels[0][0] == workload.edges,
          "Spine L0 logical payload differs from the real input slice");
  for (std::size_t family = 1; family < graph_ports.size(); ++family) {
    require(state.cold_levels[family][0].empty(),
            "Spine L0 wrote an inactive destination family");
  }
  require(
      counters.end_cycle > counters.start_cycle + counters.sorted_edge_visits,
      "Spine timing did not include memory/control work");

  require(!reader.failed() && !compute.failed(),
          "Spine split reader/compute path reported failure");
  const auto &reader_counters = reader.counters();
  require(reader_counters.source_requests == 1 &&
              reader_counters.source_responses == 1 &&
              reader_counters.source_request_windows == 1 &&
              reader_counters.source_protocol_markers == 3 &&
              reader_counters.source_protocol_acks == 1 &&
              reader_counters.source_protocol_status == 0 &&
              reader_counters.dirty_status == 0 &&
              reader_counters.diagnostic_words == 10 &&
              reader_counters.done_words == 1 &&
              !reader_counters.done_overflow,
          "Spine source-value protocol did not close");
  require(
      reader_counters.tiles_emitted == 5 && reader_counters.edges_emitted == 10,
      "Spine reader tile/edge stream shape mismatch");
  require(reader_counters.active_bin_read_bytes == 0 &&
              reader_counters.dirty_list_read_bytes == 16 &&
              reader_counters.dirty_bitmap_read_bytes == 16 &&
              reader_counters.metadata_read_bytes == 2'928 &&
              reader_counters.metadata_write_bytes == 16 &&
              reader_counters.result_write_bytes == 64 &&
              reader_counters.level_cache_read_bytes == 2'880 &&
              reader_counters.row_lookup_metadata_bytes == 8 &&
              reader_counters.graph_read_bytes == 184,
          "Spine reader memory byte ledger mismatch");
  require(reader_counters.graph_index_payload_read_bytes == 24 &&
              reader_counters.graph_edge_payload_read_bytes == 160 &&
              reader_counters.graph_construction_payload_read_bytes == 80 &&
              reader_counters.graph_replay_payload_read_bytes == 80 &&
              reader_counters.graph_index_bitmap_misses == 0,
          "Spine reader graph index payload ledger mismatch");
  require(reader_counters.range_task_active_records == 1 &&
              reader_counters.range_task_family_probes == 16 &&
              reader_counters.range_task_level_checks == 176 &&
              reader_counters.range_task_row_lookups == 1 &&
              reader_counters.range_task_construction_payloads == 10 &&
              reader_counters.range_task_count == 5 &&
              reader_counters.range_task_replay_payloads == 10 &&
              reader_counters.range_task_clear_cycles == 256 &&
              reader_counters.range_task_prefix_cycles == 256 &&
              reader_counters.range_task_scatter_cycles == 5 &&
              reader_counters.range_task_verify_cycles == 256 &&
              reader_counters.range_task_path == 1,
          "Spine exact range-task work ledger mismatch");

  const auto &compute_counters = compute.counters();
  require(compute_counters.source_requests == 1 &&
              compute_counters.source_responses == 1 &&
              compute_counters.source_protocol_markers == 3 &&
              compute_counters.source_protocol_acks == 1 &&
              compute_counters.source_protocol_status == 0 &&
              compute_counters.source_count == 1 &&
              compute_counters.source_generation == 1 &&
              compute_counters.diagnostic_words == 10 &&
              compute_counters.done_words == 1 &&
              !compute_counters.done_overflow &&
              compute_counters.range_task_path ==
                  reader_counters.range_task_path &&
              compute_counters.range_task_count ==
                  reader_counters.range_task_count &&
              compute_counters.range_task_row_lookups ==
                  reader_counters.range_task_row_lookups &&
              compute_counters.range_task_construction_payloads ==
                  reader_counters.range_task_construction_payloads &&
              compute_counters.range_task_replay_payloads ==
                  reader_counters.range_task_replay_payloads &&
              compute_counters.range_task_active_records ==
                  reader_counters.range_task_active_records &&
              compute_counters.range_task_family_probes ==
                  reader_counters.range_task_family_probes &&
              compute_counters.range_task_family_skips ==
                  reader_counters.range_task_family_skips &&
              compute_counters.dirty_count == 1 &&
              compute_counters.dirty_generation == 1,
          "Spine compute source protocol ledger mismatch");
  require(compute_counters.touched_tiles == 5 &&
              compute_counters.fast_path_tiles == 5 &&
              compute_counters.full_path_tiles == 0,
          "Spine tiny-tile path selection mismatch");
  require(compute_counters.processed_edges == 10 &&
              compute_counters.gathered_vertex_words == 10 &&
              compute_counters.scattered_vertex_words == 10,
          "Spine tiny-tile work counters mismatch");
  require(compute_counters.vertex_read_bytes == 44 &&
              compute_counters.vertex_write_bytes == 40 &&
              compute_counters.active_out_write_bytes == 80 &&
              compute_counters.bitmap_bytes == 16 &&
              compute_counters.result_write_bytes == 384,
          "Spine compute memory byte ledger mismatch");
  require(compute.next_active().size() == 10,
          "Spine SSSP next frontier size mismatch");
  for (const auto &edge : workload.edges) {
    require(compute.values()[edge.dst] == 1,
            "Spine SSSP result differs from the expected fanout distance");
  }
  require(edge_stream.stats().pushes == 35 && edge_stream.stats().pops == 35,
          "Spine forward AXIS transfer count mismatch");
  require(value_stream.stats().pushes == 2 && value_stream.stats().pops == 2,
          "Spine reverse AXIS transfer count mismatch");
  require(edge_stream.stats().max_occupancy <= 32 &&
              value_stream.stats().max_occupancy <= 32,
          "Spine AXIS occupancy exceeded the configured depth");
  std::cout << "EVIDENCE spine_vertical_slice e2e_cycles="
            << scheduler.clock(core).completed_cycles << " maintenance_cycles="
            << counters.end_cycle - counters.start_cycle << " reader_cycles="
            << reader_counters.end_cycle - reader_counters.start_cycle
            << " compute_cycles="
            << compute_counters.end_cycle - compute_counters.start_cycle
            << " edge_axis_max_occupancy=" << edge_stream.stats().max_occupancy
            << '\n';
}

void test_spine_dirty_mark_preserves_persistent_state() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 5,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const SpineAxiInterfaceProfile profile;
  std::array<std::unique_ptr<FixedAxiPort>, 16> graph_ports;
  SpineL0Ports ports;
  for (std::size_t family = 0; family < graph_ports.size(); ++family) {
    graph_ports[family] = std::make_unique<FixedAxiPort>(
        "dirty-graph" + std::to_string(family), core,
        profile.port_config(SpineAxiPortKind::kGraph, 32, family,
                            static_cast<std::uint32_t>(family)),
        backend);
    ports.graph[family] = graph_ports[family].get();
  }
  FixedAxiPort sorted(
      "dirty-sorted", core,
      profile.port_config(SpineAxiPortKind::kSortedEdges, 32, 16, 16),
      backend);
  FixedAxiPort metadata(
      "dirty-metadata", core,
      profile.port_config(SpineAxiPortKind::kMetadata, 32, 20, 20), backend);
  FixedAxiPort result(
      "dirty-result", core,
      profile.port_config(SpineAxiPortKind::kMaintenanceResult, 32, 21, 21),
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice workload{
      .vertices = 8,
      .edges =
          {
              {.src = 2, .dst = 4, .weight = 1, .diff = 1},
              {.src = 3, .dst = 5, .weight = 1, .diff = 1},
          },
      .case_name = "persistent_dirty_duplicate_and_append",
  };
  SpineL0Config config;
  SpineL0State state;
  SpineL0Maintenance maintenance("dirty-maintenance", core, config, workload,
                                 ports, state);

  const std::vector<std::uint32_t> old_sources{2};
  const SpineDirtyIdentity old_identity = spine_dirty_identity(7, old_sources);
  const auto layout = spine_metadata_layout(config);
  std::vector<std::uint8_t> metadata_payload;
  for (const std::uint64_t word :
       {static_cast<std::uint64_t>(old_identity.count),
        static_cast<std::uint64_t>(old_identity.generation),
        old_identity.hash_sum, old_identity.hash_xor}) {
    const std::vector<std::uint8_t> bytes = u64_payload(word);
    metadata_payload.insert(metadata_payload.end(), bytes.begin(), bytes.end());
  }
  metadata.initialize_payload(
      config.metadata_base + layout.dirty_count_word * sizeof(std::uint64_t),
      metadata_payload);
  std::vector<std::uint8_t> bitmap(16, 0);
  bitmap[0] = 1U << 2;
  sorted.initialize_payload(config.persistent_dirty_bitmap_base, bitmap);
  std::vector<std::uint8_t> list(16, 0);
  const std::vector<std::uint8_t> source_two = u32_payload(2);
  std::copy(source_two.begin(), source_two.end(), list.begin());
  sorted.initialize_payload(config.persistent_dirty_list_base, list);

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle();
      },
      200'000);

  require(!maintenance.failed(),
          "persistent dirty duplicate/append maintenance failed");
  const auto &counters = maintenance.counters();
  const std::vector<std::uint32_t> expected_sources{2, 3};
  const SpineDirtyIdentity expected =
      spine_dirty_identity(8, expected_sources);
  std::cout << "EVIDENCE spine_dirty_persistent_state cycles="
            << scheduler.clock(core).completed_cycles
            << " bitmap_reads=" << counters.dirty_bitmap_reads
            << " bitmap_writes=" << counters.dirty_bitmap_writes
            << " list_appends=" << counters.dirty_list_appends
            << " duplicates=" << counters.dirty_duplicates_suppressed
            << " final_count=" << counters.dirty_count
            << " final_generation=" << counters.dirty_generation << '\n';
  require(counters.unique_sources == 2 && counters.dirty_bitmap_reads == 2 &&
              counters.dirty_bitmap_writes == 1 &&
              counters.dirty_list_reads == 1 &&
              counters.dirty_list_appends == 1 &&
              counters.dirty_duplicates_suppressed == 1 &&
              counters.dirty_generation_advances == 1 &&
              counters.dirty_count == expected.count &&
              counters.dirty_generation == expected.generation &&
              counters.dirty_hash_sum == expected.hash_sum &&
              counters.dirty_hash_xor == expected.hash_xor,
          "persistent dirty operation/state ledger diverged from HLS");
  require(counters.persistent_read_bytes == 48 &&
              counters.persistent_write_bytes == 32 &&
              counters.sorted_scan_passes == 20 &&
              counters.sorted_edge_visits == 40 &&
              counters.sorted_read_beats_received == 40,
          "persistent dirty memory/scan ledger diverged from HLS");

  const std::vector<std::uint8_t> final_bitmap = backend.inspect_payload(
      16, config.persistent_dirty_bitmap_base, 16);
  const std::vector<std::uint8_t> final_list = backend.inspect_payload(
      16, config.persistent_dirty_list_base, 16);
  require((final_bitmap[0] & ((1U << 2) | (1U << 3))) ==
              ((1U << 2) | (1U << 3)) &&
              final_list[0] == 2 && final_list[4] == 3,
          "persistent dirty bitmap/list payload was not preserved and appended");
  const std::vector<std::uint8_t> final_metadata = backend.inspect_payload(
      20,
      config.metadata_base + layout.dirty_count_word * sizeof(std::uint64_t),
      4 * sizeof(std::uint64_t));
  require(final_metadata ==
              [&] {
                std::vector<std::uint8_t> bytes;
                for (const std::uint64_t word :
                     {static_cast<std::uint64_t>(expected.count),
                      static_cast<std::uint64_t>(expected.generation),
                      expected.hash_sum, expected.hash_xor}) {
                  const auto encoded = u64_payload(word);
                  bytes.insert(bytes.end(), encoded.begin(), encoded.end());
                }
                return bytes;
              }(),
          "persistent dirty metadata payload did not close");
}

void test_spine_reusable_system_matches_vertical_slice() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  const auto workload = load_spine_edge_slice(fixture);
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 2);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 30'000);

  std::cout << "EVIDENCE spine_reusable_streamed_maintenance cycles="
            << scheduler.clock(core).completed_cycles << " scan_passes="
            << system.maintenance_counters().sorted_scan_passes
            << " scan_response_stalls="
            << system.maintenance_counters().sorted_scan_response_stall_cycles
            << " scan_ii_stalls="
            << system.maintenance_counters().sorted_scan_ii_stall_cycles
            << '\n';

  require(!system.failed(), "reusable Spine vertical-slice system failed");
  require(system.maintenance_counters().sorted_scan_passes == 20,
          "reusable Spine system changed maintenance work");
  require(system.reader_counters().graph_read_bytes == 184,
          "reusable Spine system changed reader memory work");
  require(system.compute_counters().processed_edges == 10,
          "reusable Spine system changed compute work");
  require(system.compute().next_active().size() == 10,
          "reusable Spine system changed the SSSP frontier");
}

void test_spine_host_active_requires_exact_dirty_coverage() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "amazon_top1_exact.slice";
  SpineVerticalSliceSystem system(
      scheduler, core, backend, load_spine_edge_slice(fixture), 2);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 30'000);

  require(system.reader_counters().acknowledgement_eligible,
          "successful DEVICE_DIRTY reader should be ACK eligible");
  system.restart_read_compute({2});
  scheduler.run_until([&] { return system.done() && system.idle(); }, 30'000);
  require(!system.failed() &&
              system.reader_counters().dirty_status ==
                  static_cast<std::uint32_t>(
                      spine::sim::SpineDirtyStatus::kCoverageMismatch) &&
              !system.reader_counters().host_coverage_match &&
              !system.reader_counters().acknowledgement_eligible,
          "HOST_ACTIVE accepted an unpublished dirty handoff");

  const std::vector<std::uint32_t> covered_sources{2};
  system.restart_read_compute(
      {2}, spine::sim::spine_dirty_identity(1, covered_sources));
  scheduler.run_until([&] { return system.done() && system.idle(); }, 30'000);
  require(!system.failed() && system.reader_counters().dirty_status == 0 &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().acknowledgement_eligible &&
              system.reader_counters().dirty_hash_sum ==
                  spine::sim::spine_dirty_hash_sum_term(2) &&
              system.reader_counters().dirty_hash_xor ==
                  spine::sim::spine_dirty_hash_xor_term(2),
          "HOST_ACTIVE rejected an exact generation/count/hash handoff");
}

void test_spine_device_dirty_source_request_windows() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineEdgeSlice workload{
      .vertices = 64,
      .edges = {},
      .case_name = "device_dirty_request_window_17",
  };
  for (std::uint32_t source = 0; source < 17; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 32 + source,
        .weight = 1,
        .diff = 1,
    });
  }
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  require(!system.failed() && reader.source_requests == 17 &&
              reader.source_responses == 17 &&
              reader.source_request_windows == 2 &&
              reader.source_protocol_markers == 3 &&
              reader.source_protocol_acks == 1 &&
              reader.source_protocol_status == 0 && reader.dirty_status == 0 &&
              reader.diagnostic_words == 10 && reader.done_words == 1 &&
              !reader.done_overflow,
          "reader did not execute two ordered 16-credit source windows");
  require(compute.source_requests == 17 && compute.source_responses == 17 &&
              compute.source_protocol_markers == 3 &&
              compute.source_protocol_acks == 1 &&
              compute.source_protocol_status == 0 &&
              compute.source_count == 17 && compute.source_generation == 1 &&
              compute.diagnostic_words == 10 && compute.done_words == 1 &&
              !compute.done_overflow && compute.dirty_count == 17 &&
              compute.dirty_generation == 1,
          "compute did not validate the 17-source protocol transcript");
  require(system.edge_stream_stats().max_occupancy > 1 &&
              system.edge_stream_stats().max_occupancy <= 32 &&
              system.value_stream_stats().max_occupancy <= 32,
          "source request window did not exercise finite AXIS buffering");
}

void test_spine_host_active_gate_runs_tiled_fallback() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 327'681,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 1, .diff = 1},
              {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
              {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
              {.src = 0, .dst = 196'608, .weight = 4, .diff = 1},
              {.src = 0, .dst = 262'144, .weight = 5, .diff = 1},
          },
      .case_name = "host_active_gate_forced_dense",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 200'000);
  require(!system.failed(),
          "fallback fixture failed its DEVICE_DIRTY seed round");

  SpineActiveBins bins;
  SpineActiveRecord enabled;
  enabled.source = 0;
  enabled.source_value = 0;
  enabled.level_masks[0] = 1;
  bins.bins[0].push_back(enabled);
  SpineActiveRecord disabled;
  disabled.source = 0;
  disabled.source_value = 0;
  bins.bins[0].resize(16'385, disabled);
  const SpineDirtyIdentity coverage =
      spine::sim::spine_dirty_identity(1, std::vector<std::uint32_t>{0});
  system.restart_read_compute_bins(bins, coverage);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);

  const auto &reader = system.reader_counters();
  const auto &compute = system.compute_counters();
  require(!system.failed() && reader.range_task_path == 2 &&
              reader.range_task_fallback_reason == 1 &&
              reader.range_task_error == 0 && !reader.done_overflow &&
              reader.range_task_active_records == 16'385 &&
              reader.range_task_count == 0 && reader.fallback_partitions == 1 &&
              reader.fallback_forced_dense_partitions == 1 &&
              reader.fallback_active_record_reads == 16'385 * 7ULL &&
              reader.fallback_active_record_read_bytes ==
                  16'385 * 7ULL * spine::sim::kSpineActiveRecordBytes &&
              reader.fallback_row_lookups == 7 &&
              reader.fallback_endpoint_reads == 2 &&
              reader.fallback_lower_bound_reads > 0 &&
              reader.fallback_replay_edges == 5 && reader.tiles_emitted == 6 &&
              reader.edges_emitted == 5 && reader.host_coverage_match &&
              reader.acknowledgement_eligible,
          "HOST_ACTIVE active-gate fallback did not match the HLS work shape");
  require(compute.range_task_path == 2 &&
              compute.range_task_fallback_reason == 1 &&
              compute.range_task_error == 0 && !compute.done_overflow &&
              compute.forced_dense_tiles == 6 && compute.full_path_tiles == 6 &&
              compute.processed_edges == 5 &&
              compute.swept_vertex_words == 2ULL * workload.vertices,
          "force-dense fallback was not honored by split compute");
}

void test_spine_device_dirty_limit_hands_off_to_host() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 8'192,
      .edges = {},
      .case_name = "device_dirty_4097_host_handoff",
  };
  for (std::uint32_t source = 0; source < 4'097; ++source) {
    workload.edges.push_back(SpineEdgeRecord{
        .src = source,
        .dst = 6'000,
        .weight = 1,
        .diff = -1,
    });
  }
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);

  require(system.failed() && system.recoverable_host_handoff() &&
              system.reader_counters().dirty_count == 4'097 &&
              system.reader_counters().dirty_status ==
                  static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost) &&
              system.reader_counters().range_task_path == 2 &&
              system.reader_counters().range_task_fallback_reason == 4 &&
              system.reader_counters().range_task_error == 0 &&
              system.reader_counters().dirty_list_read_bytes == 0 &&
              system.compute_counters().done_overflow,
          "DEVICE_DIRTY did not expose a recoverable 4097-source handoff");

  const std::vector<std::uint32_t> sources =
      system.restart_device_dirty_host_fallback();
  require(sources.size() == 4'097 && sources.front() == 0 &&
              sources.back() == 4'096 && !system.failed(),
          "host handoff did not recover the exact dirty-source list");
  scheduler.run_until([&] { return system.done() && system.idle(); },
                      5'000'000);
  require(!system.failed() && system.reader_counters().dirty_count == 4'097 &&
              system.reader_counters().dirty_generation == 1 &&
              system.reader_counters().host_coverage_match &&
              system.reader_counters().acknowledgement_eligible &&
              system.reader_counters().range_task_active_records == 4'097 &&
              system.reader_counters().range_task_path == 1 &&
              !system.compute_counters().done_overflow,
          "HOST_ACTIVE did not complete the DEVICE_DIRTY handoff");

  system.start_dirty_ack();
  scheduler.run_until([&] { return system.dirty_ack_done() && system.idle(); },
                      1'000'000);
  require(!system.failed() && system.dirty_ack_counters().status == 0 &&
              system.dirty_ack_counters().captured.count == 4'097 &&
              system.dirty_ack_counters().result.count == 0 &&
              system.dirty_ack_counters().result.generation == 2 &&
              system.dirty_ack_counters().cleared_sources == 4'097,
          "ACK_DIRTY did not close the recovered host handoff");
}

void test_spine_device_task_limits_hand_off_to_tiled_fallback() {
  const auto run_case = [](const std::string &case_name,
                           std::uint32_t expected_reason,
                           SpineL0Config config) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("data", 141.0);
    MockMemoryBackend backend("hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 2,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 128,
                                  .response_queue_depth = 256,
                              });
    SpineEdgeSlice workload{
        .vertices = 131'073,
        .edges =
            {
                {.src = 0, .dst = 1, .weight = 1, .diff = 1},
                {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
                {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
            },
        .case_name = case_name,
    };
    SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0,
                                    4'096, std::move(config));
    system.register_components();
    scheduler.add_component(backend);
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);

    require(
        system.failed() && system.recoverable_host_handoff() &&
            system.reader_counters().dirty_count == 1 &&
            system.reader_counters().dirty_status ==
                static_cast<std::uint32_t>(SpineDirtyStatus::kRequiresHost) &&
            system.reader_counters().range_task_path == 2 &&
            system.reader_counters().range_task_fallback_reason ==
                expected_reason &&
            system.reader_counters().range_task_error == 0 &&
            system.compute_counters().done_overflow,
        case_name + " did not expose a recoverable DEVICE handoff");

    const std::vector<std::uint32_t> sources =
        system.restart_device_dirty_host_fallback();
    require(sources == std::vector<std::uint32_t>{0} && !system.failed(),
            case_name + " did not recover the dirty source");
    scheduler.run_until([&] { return system.done() && system.idle(); },
                        500'000);

    const auto &reader = system.reader_counters();
    const auto &compute = system.compute_counters();
    require(!system.failed() && reader.range_task_path == 2 &&
                reader.range_task_fallback_reason == expected_reason &&
                reader.range_task_error == 0 && !reader.done_overflow &&
                reader.host_coverage_match && reader.acknowledgement_eligible &&
                reader.fallback_partitions == 1 &&
                reader.fallback_active_record_reads == 4 &&
                reader.fallback_row_lookups == 4 &&
                reader.fallback_replay_edges == 3 &&
                reader.tiles_emitted == 3 && reader.edges_emitted == 3,
            case_name + " HOST tiled fallback work ledger diverged");
    require(compute.range_task_path == 2 &&
                compute.range_task_fallback_reason == expected_reason &&
                compute.range_task_error == 0 && !compute.done_overflow &&
                compute.processed_edges == 3 && compute.fast_path_tiles == 3 &&
                compute.full_path_tiles == 0,
            case_name + " compute did not consume the fallback edge stream");
  };

  SpineL0Config capacity;
  capacity.range_task_capacity = 2;
  run_case("device_capacity_host_tiled_fallback", 2, capacity);

  SpineL0Config payload;
  payload.range_task_payload_budget = 2;
  run_case("device_payload_host_tiled_fallback", 3, payload);
}

void test_spine_convergence_runner_records_host_handoff() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 2,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 131'073,
      .edges =
          {
              {.src = 0, .dst = 1, .weight = 1, .diff = 1},
              {.src = 0, .dst = 65'536, .weight = 2, .diff = 1},
              {.src = 0, .dst = 131'072, .weight = 3, .diff = 1},
          },
      .case_name = "convergence_runner_capacity_handoff",
  };
  SpineL0Config config;
  config.range_task_capacity = 2;
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0, 4'096,
                                  std::move(config));
  system.register_components();
  scheduler.add_component(backend);

  const auto result = system.run_sssp_to_convergence(4, 500'000);
  require(result.converged && !result.failed && result.rounds.size() == 2 &&
              result.host_handoffs.size() == 1,
          "convergence runner did not recover exactly one logical round");
  const auto &handoff = result.host_handoffs.front();
  require(handoff.logical_round == 0 && handoff.fallback_reason == 2 &&
              handoff.source_count == 1 &&
              handoff.host_list_read_bytes == spine::sim::kSpineSortWordBytes &&
              handoff.host_control_cycles == 0 && !handoff.host_control_timed &&
              handoff.device_attempt.reader.done_overflow &&
              handoff.device_attempt.compute.done_overflow &&
              handoff.device_attempt.end_cycle >
                  handoff.device_attempt.start_cycle,
          "host handoff evidence hid or misclassified the DEVICE attempt");
  require(result.rounds[0].reader.range_task_path == 2 &&
              result.rounds[0].reader.range_task_fallback_reason == 2 &&
              result.rounds[0].reader.fallback_replay_edges == 3 &&
              result.rounds[0].compute.processed_edges == 3 &&
              result.rounds[0].end_cycle - result.rounds[0].start_cycle >
                  handoff.device_attempt.end_cycle -
                      handoff.device_attempt.start_cycle &&
              result.rounds[1].active_in.size() == 3 &&
              result.rounds[1].active_out.empty(),
          "accepted round evidence did not include DEVICE plus HOST execution");
  require(system.compute().values()[1] == 1 &&
              system.compute().values()[65'536] == 2 &&
              system.compute().values()[131'072] == 3,
          "fallback convergence result diverged from weighted SSSP oracle");
}

void test_spine_dirty_ack_rejects_stale_and_malformed_candidates() {
  const auto run_case = [](std::uint32_t expected_generation,
                           SpineDirtyIdentity candidate,
                           SpineDirtyStatus expected_status) {
    Scheduler scheduler;
    const auto core = scheduler.add_clock_mhz("data", 141.0);
    MockMemoryBackend backend("hbm", core,
                              MockMemoryConfig{
                                  .channels = 32,
                                  .latency_cycles = 3,
                                  .accepts_per_channel_per_cycle = 1,
                                  .max_outstanding_per_channel = 64,
                                  .response_queue_depth = 128,
                              });
    FixedAxiPort scratch(
        "dirty-ack-scratch", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 16, .initiator_id = 916},
        backend);
    FixedAxiPort metadata(
        "dirty-ack-metadata", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 20, .initiator_id = 920},
        backend);
    FixedAxiPort result(
        "dirty-ack-result", core,
        FixedAxiPortConfig{
            .memory_channels = 32, .channel = 21, .initiator_id = 921},
        backend);
    const SpineL0Config config;
    const auto layout = spine::sim::spine_metadata_layout(config);
    const SpineDirtyIdentity captured =
        spine::sim::spine_dirty_identity(7, std::vector<std::uint32_t>{2});
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_count_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.count));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_generation_word *
                spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.generation));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_hash_sum_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.hash_sum));
    metadata.initialize_payload(
        config.metadata_base +
            layout.dirty_hash_xor_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(captured.hash_xor));
    std::vector<std::uint8_t> list_word(16, 0);
    list_word[0] = 2;
    scratch.initialize_payload(config.persistent_dirty_list_base, list_word);
    std::vector<std::uint8_t> bitmap_word(16, 0);
    bitmap_word[0] = 1U << 2;
    scratch.initialize_payload(config.persistent_dirty_bitmap_base,
                               bitmap_word);

    spine::sim::SpineDirtyAck ack(
        "dirty-ack", core, config,
        spine::sim::SpineDirtyAckPorts{
            .task_scratch = &scratch,
            .metadata = &metadata,
            .result = &result,
        });
    scheduler.add_component(ack);
    scratch.register_components(scheduler);
    metadata.register_components(scheduler);
    result.register_components(scheduler);
    scheduler.add_component(backend);
    ack.start(expected_generation, candidate);
    scheduler.run_until(
        [&] {
          return ack.done() && scratch.idle() && metadata.idle() &&
                 result.idle();
        },
        10'000);

    require(ack.failed() && ack.counters().status ==
                                static_cast<std::uint32_t>(expected_status) &&
                ack.counters().cleared_sources == 0 &&
                ack.counters().generation_advances == 0 &&
                backend.inspect_payload(16,
                                        config.persistent_dirty_bitmap_base,
                                        16) == bitmap_word &&
                backend.inspect_payload(
                    20,
                    config.metadata_base +
                        layout.dirty_generation_word *
                            spine::sim::kSpineMetadataWordBytes,
                    8) == u64_payload(7) &&
                backend.inspect_payload(21, 81 * 4, 4) ==
                    u32_payload(static_cast<std::uint32_t>(expected_status)) &&
                backend.inspect_payload(21, 83 * 4, 4) == u32_payload(7) &&
                backend.inspect_payload(21, 95 * 4, 4) == u32_payload(1),
            "failed dirty ACK changed owned frontier state");
  };

  const SpineDirtyIdentity exact =
      spine::sim::spine_dirty_identity(7, std::vector<std::uint32_t>{2});
  run_case(6, exact, SpineDirtyStatus::kStaleAck);
  SpineDirtyIdentity malformed = exact;
  ++malformed.hash_sum;
  run_case(7, malformed, SpineDirtyStatus::kMalformedAck);
}

void test_spine_compute_rejects_malformed_source_protocol() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  FixedAxiPort vertex_state(
      "protocol-vertex-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 17, .initiator_id = 817},
      backend);
  FixedAxiPort active_out(
      "protocol-active-out", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 19, .initiator_id = 819},
      backend);
  FixedAxiPort active_bitmap(
      "protocol-active-bitmap", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 22, .initiator_id = 822},
      backend);
  FixedAxiPort result(
      "protocol-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 821},
      backend);
  Fifo<PartConvWord> edge_stream("protocol-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("protocol-value-axis", core, 32);
  SequenceProducer<PartConvWord> producer(
      "malformed-protocol-reader", core, edge_stream,
      {
          PartConvWord{.kind = PartConvWordKind::kSourceRequest, .first = 0},
          PartConvWord{.kind = PartConvWordKind::kSourceCount, .first = 2},
          PartConvWord{.kind = PartConvWordKind::kSourceGeneration, .first = 9},
          PartConvWord{.kind = PartConvWordKind::kSourceRequestsDone},
          PartConvWord{.kind = PartConvWordKind::kDoneAll},
      });
  SequenceConsumer<SourceValueWord> consumer("malformed-protocol-host", core,
                                             value_stream);
  SpineSplitSsspCompute compute(
      "malformed-protocol-compute", core, 64, 0, 4096,
      SpineComputePorts{
          .vertex_state = &vertex_state,
          .active_out = &active_out,
          .active_bitmap = &active_bitmap,
          .result = &result,
      },
      edge_stream, value_stream);
  scheduler.add_component(producer);
  scheduler.add_component(consumer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               value_stream.empty() && vertex_state.idle() &&
               active_out.idle() && active_bitmap.idle() && result.idle();
      },
      100'000);

  require(compute.failed() && consumer.values.size() == 2 &&
              consumer.values[0].kind == SourceValueWord::Kind::kSourceValue &&
              consumer.values[1].kind == SourceValueWord::Kind::kProtocolAck &&
              consumer.values[1].value == static_cast<std::uint32_t>(
                                                spine::sim::
                                                    SpineSourceProtocolStatus::
                                                        kCount) &&
              compute.counters().source_protocol_status ==
                  static_cast<std::uint32_t>(
                      spine::sim::SpineSourceProtocolStatus::kCount),
          "compute accepted a source-count mismatch or returned the wrong ACK");
}

void test_spine_cold_l1_carry_and_reader() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "cold_l1_carry",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  require(!system.failed(), "cold L1 carry vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.target_level == 1 && maintenance.hot_target_level == -1,
          "cold carry selected the wrong binary target");
  require(maintenance.sorted_scan_passes == 19,
          "cold carry changed the HLS family-filter scan count");
  require(maintenance.carry_level_payload_reads == 1 &&
              maintenance.carry_new_batch_reads == 1 &&
              maintenance.carry_new_batch_read_bytes == 16 &&
              maintenance.carry_refill_wait_cycles > 0 &&
              maintenance.carry_max_buffered_heads == 2 &&
              maintenance.carry_merge_inputs == 2 &&
              maintenance.carry_outputs == 2,
          "cold carry merge ledger mismatch");
  std::cout << "EVIDENCE spine_carry_refill cycles="
            << maintenance.end_cycle - maintenance.start_cycle
            << " new_batch_reads=" << maintenance.carry_new_batch_reads
            << " level_reads=" << maintenance.carry_level_payload_reads
            << " refill_wait=" << maintenance.carry_refill_wait_cycles
            << " max_heads=" << maintenance.carry_max_buffered_heads << '\n';
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].size() == 2,
          "cold carry did not retire L0 into L1");
  require(system.reader_counters().occupied_levels == 1 &&
              system.reader_counters().edges_emitted == 2,
          "reader did not traverse the carried L1 payload");
  require(
      system.compute().values()[1] == 5 && system.compute().values()[2] == 3,
      "cold carry SSSP result mismatch");
}

void test_spine_carry_kway_refill_pipeline() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 7,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      {.src = 0, .dst = 1, .weight = 5, .diff = 1},
      {.src = 1, .dst = 2, .weight = 5, .diff = 1},
  };
  initial.cold_levels[0][1] = {
      {.src = 0, .dst = 3, .weight = 4, .diff = 1},
      {.src = 2, .dst = 4, .weight = 4, .diff = 1},
  };
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges =
          {
              {.src = 0, .dst = 5, .weight = 3, .diff = 1},
              {.src = 1, .dst = 6, .weight = 3, .diff = 1},
              {.src = 3, .dst = 7, .weight = 3, .diff = 1},
              {.src = 4, .dst = 8, .weight = 3, .diff = 1},
          },
      .case_name = "carry_kway_refill",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 200'000);

  require(!system.failed(), "L2 k-way carry vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  const auto &level = system.level_state().cold_levels[0][2];
  require(maintenance.target_level == 2 &&
              maintenance.carry_new_batch_reads == 4 &&
              maintenance.carry_new_batch_read_bytes == 64 &&
              maintenance.carry_level_payload_reads == 4 &&
              maintenance.carry_level_payload_read_bytes == 32 &&
              maintenance.carry_merge_inputs == 8 &&
              maintenance.carry_outputs == 8 &&
              maintenance.carry_max_buffered_heads == 5 &&
              maintenance.carry_refill_wait_cycles > 0,
          "L2 k-way carry request/refill ledger diverged");
  require(level.size() == 8 && level.front().src == 0 &&
              level.front().dst == 1 && level.back().src == 4 &&
              level.back().dst == 8,
          "L2 k-way carry winner order or output payload diverged");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].empty(),
          "L2 k-way carry did not retire lower levels");
  std::cout << "EVIDENCE spine_carry_kway target=2 inputs="
            << maintenance.carry_merge_inputs
            << " new_batch_reads=" << maintenance.carry_new_batch_reads
            << " level_reads=" << maintenance.carry_level_payload_reads
            << " refill_wait=" << maintenance.carry_refill_wait_cycles
            << " max_heads=" << maintenance.carry_max_buffered_heads << '\n';
}

void test_spine_independent_hot_and_cold_targets() {
  require(spine_hot_shard(17) == 5,
          "C++ hot hash diverges from the stable host/HLS hash");
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0Config config;
  config.hot_vertices = {17};
  SpineL0State initial;
  initial.hot_vertices.insert(17);
  initial.hot_enabled = true;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 7, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges =
          {
              SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1},
              SpineEdgeRecord{.src = 0, .dst = 17, .weight = 2, .diff = 1},
          },
      .case_name = "independent_hot_cold_targets",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, std::move(config), std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 150'000);

  require(!system.failed(), "mixed hot/cold vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.hot_enabled && maintenance.target_level == 1 &&
              maintenance.hot_target_level == 0,
          "cold and hot targets were not selected independently");
  require(maintenance.cold_input_edges == 1 &&
              maintenance.hot_input_edges == 1 &&
              maintenance.sorted_scan_passes == 36,
          "mixed hot/cold input scan ledger mismatch");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].size() == 2 &&
              system.level_state().hot_levels[5][0].size() == 1,
          "mixed hot/cold payloads reached the wrong level or shard");
  require(system.reader_counters().occupied_levels == 2 &&
              system.reader_counters().cold_edges_emitted == 2 &&
              system.reader_counters().hot_edges_emitted == 1,
          "reader did not combine cold and hot levels");
  require(system.compute().values()[1] == 7 &&
              system.compute().values()[2] == 3 &&
              system.compute().values()[17] == 2,
          "mixed hot/cold SSSP result mismatch");
}

void test_spine_fixed_level_layout_matches_stable_profile() {
  const SpineL0Config config;
  const auto cold_l0 = spine_level_layout(config, false, 0);
  const auto cold_l1 = spine_level_layout(config, false, 1);
  const auto cold_l10 = spine_level_layout(config, false, 10);
  const auto hot_l0 = spine_level_layout(config, true, 0);

  require(cold_l0.bitmap_offset_words == 0 && cold_l0.edge_capacity == 131'072,
          "cold L0 layout diverges from the stable HLS profile");
  require(
      cold_l1.bitmap_offset_words == 524'290 && cold_l1.edge_capacity == 16'384,
      "cold L1 layout diverges from the stable HLS profile");
  require(hot_l0.bitmap_offset_words ==
              cold_l10.edge_offset_words + cold_l10.edge_capacity,
          "hot level storage does not begin after the cold level region");
  SpineL0Config invalid_page = config;
  invalid_page.page_vertices = 128;
  bool invalid_page_rejected = false;
  try {
    (void)spine_level_layout(invalid_page, false, 0);
  } catch (const std::invalid_argument &) {
    invalid_page_rejected = true;
  }
  require(invalid_page_rejected,
          "fixed four-word bitmap accepted a non-256-vertex page");

  const SpineEdgeRecord edge{
      .src = 9, .dst = 0x12345678U, .weight = 0xabcdU, .diff = -7};
  const std::vector<std::uint8_t> payload = encode_spine_level_edge(edge);
  require(
      payload.size() == 8 && decode_spine_level_edge(payload, edge.src) == edge,
      "64-bit HLS CSR level payload does not round-trip");
  const std::vector<std::uint8_t> sort_payload = encode_spine_sort_edge(edge);
  require(
      sort_payload.size() == 16 && decode_spine_sort_edge(sort_payload) == edge,
      "128-bit HLS sorted edge payload does not round-trip");
}

void test_spine_carry_drops_signed_diff_cancellation() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineL0State initial;
  initial.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = -1}},
      .case_name = "signed_diff_cancellation",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(batch), 0,
                                  4096, SpineL0Config{}, std::move(initial));
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&] { return system.done() && system.idle(); }, 100'000);

  require(!system.failed(), "signed-diff cancellation vertical slice failed");
  const auto &maintenance = system.maintenance_counters();
  require(maintenance.target_level == 1 &&
              maintenance.carry_merge_inputs == 2 &&
              maintenance.carry_outputs == 0,
          "carry did not coalesce insertion and deletion to an empty payload");
  require(system.level_state().cold_levels[0][0].empty() &&
              system.level_state().cold_levels[0][1].empty(),
          "cancelled edge remained resident in a cold level");
  require(system.reader_counters().edges_emitted == 0 &&
              system.compute().next_active().empty(),
          "cancelled edge escaped into the reader/compute path");
}

struct ComputeTileObservation {
  SpineComputeCounters counters;
  FifoStats edge_stream;
  std::uint64_t cycles{};
  std::size_t next_active{};
  std::uint32_t duplicate_value{SpineSplitSsspCompute::kInfinity};
  bool distances_match{};
  bool failed{};
};

ComputeTileObservation run_compute_tile(std::size_t edge_count,
                                        bool duplicate_dst = false) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  FixedAxiPort vertex_state(
      "boundary-vertex-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 17, .initiator_id = 217},
      backend);
  FixedAxiPort active_out(
      "boundary-active-out", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 19, .initiator_id = 219},
      backend);
  FixedAxiPort active_bitmap(
      "boundary-active-bitmap", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 22, .initiator_id = 222},
      backend);
  FixedAxiPort result(
      "boundary-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 221},
      backend);
  Fifo<PartConvWord> edge_stream("boundary-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("boundary-value-axis", core, 32);
  std::vector<PartConvWord> words;
  words.reserve(edge_count + 3);
  words.push_back(
      PartConvWord{.kind = PartConvWordKind::kTileBegin, .first = 0});
  for (std::size_t index = 0; index < edge_count; ++index) {
    words.push_back(PartConvWord{
        .kind = PartConvWordKind::kEdge,
        .first = duplicate_dst ? 1U : static_cast<std::uint32_t>(index),
        .second =
            duplicate_dst ? static_cast<std::uint32_t>(5 - 2 * index) : 1U,
    });
  }
  words.push_back(PartConvWord{
      .kind = PartConvWordKind::kTileEnd, .first = 0, .second = 65'536});
  words.push_back(PartConvWord{.kind = PartConvWordKind::kDoneAll});
  SequenceProducer<PartConvWord> producer("boundary-reader", core, edge_stream,
                                          std::move(words));
  SpineSplitSsspCompute compute("boundary-compute", core, 65'536, 65'535, 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &result,
                                },
                                edge_stream, value_stream);

  scheduler.add_component(producer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               vertex_state.idle() && active_out.idle() &&
               active_bitmap.idle() && result.idle();
      },
      500'000);

  bool distances_match = true;
  if (!duplicate_dst) {
    for (std::size_t index = 0; index < edge_count; ++index) {
      distances_match = distances_match && compute.values()[index] == 1;
    }
  }
  return ComputeTileObservation{
      .counters = compute.counters(),
      .edge_stream = edge_stream.stats(),
      .cycles = scheduler.clock(core).completed_cycles,
      .next_active = compute.next_active().size(),
      .duplicate_value = compute.values()[1],
      .distances_match = distances_match,
      .failed = compute.failed(),
  };
}

void test_spine_full_tile_threshold_boundaries() {
  for (const std::size_t edge_count : {4095U, 4096U, 4097U, 4098U}) {
    const ComputeTileObservation observation = run_compute_tile(edge_count);
    require(!observation.failed && observation.distances_match &&
                observation.next_active == edge_count,
            "full-tile boundary changed the SSSP result");
    require(observation.counters.processed_edges == edge_count,
            "full-tile boundary lost or duplicated an edge");
    if (edge_count <= 4096) {
      require(observation.counters.fast_path_tiles == 1 &&
                  observation.counters.full_path_tiles == 0 &&
                  observation.counters.gathered_vertex_words == edge_count &&
                  observation.counters.swept_vertex_words == 0 &&
                  observation.counters.scattered_vertex_words == edge_count,
              "tiny boundary did not use gather/relax/sparse-store");
      require(observation.counters.vertex_read_bytes == edge_count * 4 &&
                  observation.counters.vertex_write_bytes == edge_count * 4,
              "tiny boundary vertex-memory bytes mismatch");
    } else {
      require(observation.counters.fast_path_tiles == 0 &&
                  observation.counters.full_path_tiles == 1 &&
                  observation.counters.full_buffer_replay_edges == 4096 &&
                  observation.counters.full_overflow_edges == 1 &&
                  observation.counters.full_stream_edges == edge_count - 4097,
              "full boundary did not load/replay/stream in HLS order");
      require(observation.counters.gathered_vertex_words == 0 &&
                  observation.counters.swept_vertex_words == 2 * 65'536 &&
                  observation.counters.scattered_vertex_words == 0 &&
                  observation.counters.vertex_read_bytes == 65'536 * 4 &&
                  observation.counters.vertex_write_bytes == 65'536 * 4,
              "full boundary tile sweep ledger mismatch");
    }
  }
}

void test_spine_full_tile_load_replay_backpressures_axis() {
  const ComputeTileObservation observation = run_compute_tile(8192);
  require(!observation.failed && observation.distances_match,
          "large full tile produced an incorrect SSSP result");
  require(observation.counters.full_buffer_replay_edges == 4096 &&
              observation.counters.full_overflow_edges == 1 &&
              observation.counters.full_stream_edges == 4095,
          "large full tile work did not partition at the finite buffer");
  require(observation.edge_stream.max_occupancy == 32 &&
              observation.edge_stream.push_stalls > 0,
          "full-tile load/replay did not backpressure the finite AXIS FIFO");
}

void test_spine_tiny_gather_preserves_duplicate_reads() {
  const ComputeTileObservation observation = run_compute_tile(2, true);
  require(!observation.failed && observation.duplicate_value == 3 &&
              observation.next_active == 1,
          "duplicate-destination tiny relaxation is incorrect");
  require(observation.counters.gathered_vertex_words == 2 &&
              observation.counters.vertex_read_bytes == 8 &&
              observation.counters.scattered_vertex_words == 1,
          "tiny gather incorrectly deduplicated repeated destination reads");
}

void test_spine_compute_consumes_vertex_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  FixedAxiPort vertex_state(
      "payload-vertex-state", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 17, .initiator_id = 317},
      backend);
  FixedAxiPort active_out(
      "payload-active-out", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 19, .initiator_id = 319},
      backend);
  FixedAxiPort active_bitmap(
      "payload-active-bitmap", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 22, .initiator_id = 322},
      backend);
  FixedAxiPort result(
      "payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 321},
      backend);
  Fifo<PartConvWord> edge_stream("payload-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("payload-value-axis", core, 32);
  SequenceProducer<PartConvWord> producer(
      "payload-reader", core, edge_stream,
      {
          {.kind = PartConvWordKind::kTileBegin, .first = 0},
          {.kind = PartConvWordKind::kEdge, .first = 1, .second = 10},
          {.kind = PartConvWordKind::kTileEnd, .first = 0, .second = 4},
          {.kind = PartConvWordKind::kDoneAll},
      });
  SpineSplitSsspCompute compute("payload-compute", core, 4, 0, 4096,
                                SpineComputePorts{
                                    .vertex_state = &vertex_state,
                                    .active_out = &active_out,
                                    .active_bitmap = &active_bitmap,
                                    .result = &result,
                                },
                                edge_stream, value_stream);

  // The compute mirror still contains infinity for vertex 1. Only HBM is 7.
  vertex_state.initialize_payload(4, {7, 0, 0, 0});
  scheduler.add_component(producer);
  scheduler.add_component(compute);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  vertex_state.register_components(scheduler);
  active_out.register_components(scheduler);
  active_bitmap.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return producer.done() && compute.done() && edge_stream.empty() &&
               vertex_state.idle() && active_out.idle() &&
               active_bitmap.idle() && result.idle();
      },
      10'000);

  require(!compute.failed() && compute.values()[1] == 7 &&
              compute.next_active().empty(),
          "compute ignored the HBM vertex payload and used its stale mirror");
  require(compute.counters().vertex_payload_read_bytes == 4 &&
              compute.counters().vertex_payload_write_bytes == 0,
          "compute vertex payload ledger does not match the HBM gather");
  require(vertex_state.master().stats().zero_filled_write_bytes == 0 &&
              active_out.master().stats().zero_filled_write_bytes == 0 &&
              active_bitmap.master().stats().zero_filled_write_bytes == 0 &&
              result.master().stats().zero_filled_write_bytes == 0,
          "migrated compute path issued an implicit zero-filled write");
}

void test_spine_reader_consumes_graph_edge_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "reader-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(400 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "reader-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 416},
      backend);
  FixedAxiPort metadata(
      "reader-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 420},
      backend);
  FixedAxiPort result(
      "reader-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 421},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice batch{
      .vertices = 512,
      .edges =
          {
              SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1},
              SpineEdgeRecord{.src = 130, .dst = 2, .weight = 7, .diff = 1},
              SpineEdgeRecord{.src = 256, .dst = 3, .weight = 9, .diff = 1},
          },
      .case_name = "reader_graph_payload_antibypass",
  };
  SpineL0State state;
  const SpineL0Config config;
  SpineL0Maintenance maintenance("reader-payload-maintenance", core, config,
                                 std::move(batch), ports, state);
  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      50'000);

  require(!maintenance.failed(), "reader payload setup maintenance failed");
  require(state.cold_levels[0][0].size() == 3 &&
              state.cold_levels[0][0][0].dst == 1 &&
              state.cold_levels[0][0][0].weight == 5,
          "reader payload anti-bypass setup changed logical level state");

  const auto set_device_dirty_source = [&](std::uint32_t source) {
    const auto meta = spine::sim::spine_metadata_layout(config);
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_count_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(1));
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_hash_sum_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(spine::sim::spine_dirty_hash_sum_term(source)));
    metadata.initialize_payload(
        config.metadata_base +
            meta.dirty_hash_xor_word * spine::sim::kSpineMetadataWordBytes,
        u64_payload(spine::sim::spine_dirty_hash_xor_term(source)));
    std::vector<std::uint8_t> list_word(spine::sim::kSpineSortWordBytes, 0);
    for (std::size_t byte = 0; byte < sizeof(source); ++byte) {
      list_word[byte] =
          static_cast<std::uint8_t>((source >> (byte * 8)) & 0xffU);
    }
    sorted.initialize_payload(config.persistent_dirty_list_base, list_word);
  };
  set_device_dirty_source(0);

  const SpineLevelLayout layout = spine_level_layout(config, false, 0);
  require(backend.inspect_payload(
              0, layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
              spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}),
          "maintenance bitmap payload does not match the HLS index layout");
  require(
      backend.inspect_payload(
          0, layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
          spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({0, 0, 0, 0, 2, 0, 0, 0}),
      "maintenance page-base payload does not match the HLS index layout");
  require(backend.inspect_payload(0,
                                  (layout.bitmap_offset_words + 2) *
                                      spine::sim::kSpineGraphWordBytes,
                                  spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({4, 0, 0, 0, 0, 0, 0, 0}),
          "maintenance bitmap rank word does not contain source 130");
  require(
      backend.inspect_payload(
          0, layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
          spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({0, 0, 0, 0, 1, 0, 0, 0}),
      "maintenance row-offset payload does not match the HLS index layout");
  require(
      backend.inspect_payload(0,
                              (layout.row_offset_offset_words + 1) *
                                  spine::sim::kSpineGraphWordBytes,
                              spine::sim::kSpineGraphWordBytes) ==
          std::vector<std::uint8_t>({2, 0, 0, 0, 3, 0, 0, 0}),
      "maintenance terminal row offset does not match the HLS index layout");
  require(backend.inspect_payload(
              0, layout.mask_offset_words * spine::sim::kSpineGraphWordBytes,
              spine::sim::kSpineGraphWordBytes) ==
              std::vector<std::uint8_t>({1, 0, 1, 0, 1, 0, 0, 0}),
          "maintenance row partition mask does not match the HLS index layout");
  graph_ports[0]->initialize_payload(
      layout.edge_offset_words * spine::sim::kSpineGraphWordBytes,
      encode_spine_level_edge(
          SpineEdgeRecord{.src = 0, .dst = 2, .weight = 2, .diff = 1}));

  FixedAxiPort active_bins(
      "reader-payload-active-bins", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 18, .initiator_id = 418},
      backend);
  Fifo<PartConvWord> edge_stream("reader-payload-edge-axis", core, 32);
  Fifo<SourceValueWord> value_stream("reader-payload-value-axis", core, 4);
  SpineReaderPorts reader_ports;
  reader_ports.graph = ports.graph;
  reader_ports.task_scratch = &sorted;
  reader_ports.active_bins = &active_bins;
  reader_ports.metadata = &metadata;
  reader_ports.result = &result;
  SpineSplitReader reader("reader-payload-reader", core, maintenance,
                          reader_ports, {0}, edge_stream, value_stream);
  SequenceProducer<SourceValueWord> source_values(
      "reader-payload-source-values", core, value_stream,
      source_protocol_reply(0, 10));
  SequenceConsumer<PartConvWord> edge_words("reader-payload-edge-words", core,
                                            edge_stream);
  scheduler.add_component(reader);
  scheduler.add_component(source_values);
  scheduler.add_component(edge_words);
  scheduler.add_component(edge_stream);
  scheduler.add_component(value_stream);
  active_bins.register_components(scheduler);
  scheduler.run_until(
      [&] {
        return reader.done() && source_values.done() && edge_stream.empty() &&
               value_stream.empty() && active_bins.idle() && metadata.idle() &&
               graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> edges;
  for (const PartConvWord &word : edge_words.values) {
    if (word.kind == PartConvWordKind::kEdge) {
      edges.push_back(word);
    }
  }
  require(!reader.failed(), "reader graph payload anti-bypass path failed");
  require(edges.size() == 1 && edges[0].first == 2 && edges[0].second == 12,
          "reader ignored HBM graph edge payload and used logical state");
  require(reader.counters().graph_edge_payload_read_bytes == 16 &&
              reader.counters().graph_construction_payload_read_bytes == 8 &&
              reader.counters().graph_replay_payload_read_bytes == 8,
          "reader graph edge payload ledger does not close");

  const std::size_t first_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_missing_bitmap(
      "reader-payload-source-values-missing-bitmap", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_missing_bitmap);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_missing_bitmap.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> second_run_edges;
  for (std::size_t index = first_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      second_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && second_run_edges.empty(),
          "reader ignored HBM bitmap payload and emitted a missing row");
  require(reader.counters().graph_index_bitmap_misses == 1 &&
              reader.counters().graph_index_payload_read_bytes == 8 &&
              reader.counters().graph_edge_payload_read_bytes == 0,
          "reader bitmap anti-bypass ledger mismatch");

  const std::size_t second_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}));
  graph_ports[0]->initialize_payload(
      layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 2, 0, 0, 0}));
  SequenceProducer<SourceValueWord> source_values_shifted_page_base(
      "reader-payload-source-values-shifted-page-base", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_shifted_page_base);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_shifted_page_base.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> third_run_edges;
  for (std::size_t index = second_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      third_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && third_run_edges.size() == 1 &&
              third_run_edges[0].first == 2 && third_run_edges[0].second == 17,
          "reader ignored the HBM page-base payload");
  require(reader.counters().graph_index_payload_read_bytes == 32 &&
              reader.counters().graph_edge_payload_read_bytes == 16,
          "reader page-base anti-bypass ledger mismatch");

  const std::size_t third_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.page_base_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({0, 0, 0, 0, 2, 0, 0, 0}));
  graph_ports[0]->initialize_payload(
      layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_empty_row(
      "reader-payload-source-values-empty-row", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_empty_row);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_empty_row.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> fourth_run_edges;
  for (std::size_t index = third_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      fourth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && fourth_run_edges.empty(),
          "reader ignored the HBM row-offset payload");
  require(reader.counters().graph_index_payload_read_bytes == 24 &&
              reader.counters().graph_edge_payload_read_bytes == 0,
          "reader row-offset anti-bypass ledger mismatch");

  const std::size_t fourth_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.row_offset_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({0, 0, 0, 0, 1, 0, 0, 0}));
  SequenceProducer<SourceValueWord> source_values_ranked(
      "reader-payload-source-values-ranked", core, value_stream,
      source_protocol_reply(130, 20));
  scheduler.add_component(source_values_ranked);
  set_device_dirty_source(130);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_ranked.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> fifth_run_edges;
  for (std::size_t index = fourth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      fifth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && fifth_run_edges.size() == 1 &&
              fifth_run_edges[0].first == 2 && fifth_run_edges[0].second == 27,
          "reader bitmap rank did not select source 130's row");
  require(reader.counters().graph_index_bitmap_words == 3 &&
              reader.counters().graph_index_payload_read_bytes == 48 &&
              reader.counters().graph_edge_payload_read_bytes == 16,
          "reader bitmap-rank payload ledger mismatch");

  const std::size_t fifth_run_words = edge_words.values.size();
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>(spine::sim::kSpineGraphWordBytes, 0));
  SequenceProducer<SourceValueWord> source_values_changed_rank(
      "reader-payload-source-values-changed-rank", core, value_stream,
      source_protocol_reply(130, 20));
  scheduler.add_component(source_values_changed_rank);
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_changed_rank.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);

  std::vector<PartConvWord> sixth_run_edges;
  for (std::size_t index = fifth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      sixth_run_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && sixth_run_edges.size() == 1 &&
              sixth_run_edges[0].first == 2 && sixth_run_edges[0].second == 22,
          "reader ignored HBM bitmap-prefix changes when computing rank");

  const auto metadata_layout = spine::sim::spine_metadata_layout(config);
  const std::uint64_t slice0_base = config.metadata_base;
  set_device_dirty_source(0);
  graph_ports[0]->initialize_payload(
      layout.bitmap_offset_words * spine::sim::kSpineGraphWordBytes,
      std::vector<std::uint8_t>({1, 0, 0, 0, 0, 0, 0, 0}));

  const std::size_t sixth_run_words = edge_words.values.size();
  metadata.initialize_payload(
      slice0_base + 7 * spine::sim::kSpineMetadataWordBytes, u64_payload(0));
  SequenceProducer<SourceValueWord> source_values_metadata_unoccupied(
      "reader-payload-source-values-metadata-unoccupied", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_metadata_unoccupied);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_metadata_unoccupied.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::size_t seventh_edges = 0;
  for (std::size_t index = sixth_run_words; index < edge_words.values.size();
       ++index) {
    seventh_edges += edge_words.values[index].kind == PartConvWordKind::kEdge;
  }
  require(!reader.failed() && seventh_edges == 0 &&
              reader.counters().occupied_levels == 0 &&
              reader.active_source_ids() == std::vector<std::uint32_t>({0}),
          "reader bypassed dirty-list or occupied metadata payload");

  metadata.initialize_payload(
      slice0_base + 7 * spine::sim::kSpineMetadataWordBytes, u64_payload(1));
  metadata.initialize_payload(
      config.metadata_base +
          metadata_layout.page_epoch_base * spine::sim::kSpineMetadataWordBytes,
      u64_payload(0));
  const std::size_t seventh_run_words = edge_words.values.size();
  SequenceProducer<SourceValueWord> source_values_stale_page(
      "reader-payload-source-values-stale-page", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_stale_page);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_stale_page.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::size_t eighth_edges = 0;
  for (std::size_t index = seventh_run_words; index < edge_words.values.size();
       ++index) {
    eighth_edges += edge_words.values[index].kind == PartConvWordKind::kEdge;
  }
  require(!reader.failed() && eighth_edges == 0 &&
              reader.counters().graph_index_epoch_misses == 1 &&
              reader.counters().graph_index_payload_read_bytes == 0,
          "reader ignored a stale page epoch or issued a gated graph read");

  metadata.initialize_payload(
      config.metadata_base +
          metadata_layout.page_epoch_base * spine::sim::kSpineMetadataWordBytes,
      u64_payload(1));
  metadata.initialize_payload(
      slice0_base + 6 * spine::sim::kSpineMetadataWordBytes,
      u64_payload(layout.edge_offset_words + 1));
  const std::size_t eighth_run_words = edge_words.values.size();
  SequenceProducer<SourceValueWord> source_values_shifted_edge_base(
      "reader-payload-source-values-shifted-edge-base", core, value_stream,
      source_protocol_reply(0, 10));
  scheduler.add_component(source_values_shifted_edge_base);
  reader.reset_round({130});
  scheduler.run_until(
      [&] {
        return reader.done() && source_values_shifted_edge_base.done() &&
               edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle() && graph_ports[0]->idle();
      },
      50'000);
  std::vector<PartConvWord> ninth_edges;
  for (std::size_t index = eighth_run_words; index < edge_words.values.size();
       ++index) {
    if (edge_words.values[index].kind == PartConvWordKind::kEdge) {
      ninth_edges.push_back(edge_words.values[index]);
    }
  }
  require(!reader.failed() && ninth_edges.size() == 1 &&
              ninth_edges[0].first == 2 && ninth_edges[0].second == 17,
          "reader ignored the HBM level edge-offset metadata");

  const std::size_t ninth_run_words = edge_words.values.size();
  metadata.initialize_payload(
      config.metadata_base + metadata_layout.hot_enabled_word *
                                 spine::sim::kSpineMetadataWordBytes,
      u64_payload(0));
  reader.reset_round({0});
  scheduler.run_until(
      [&] {
        return reader.done() && edge_stream.empty() && value_stream.empty() &&
               active_bins.idle() && metadata.idle();
      },
      50'000);
  require(reader.failed() && reader.counters().range_task_error == 1,
          "reader accepted an invalid metadata control payload");
  require(edge_words.values.size() ==
                  ninth_run_words + spine::sim::kSpineReaderDiagnosticWords +
                      1 &&
              reader.counters().diagnostic_words == 10 &&
              reader.counters().done_words == 1 &&
              reader.counters().done_overflow,
          "reader error path did not emit the complete terminal transcript");
  const PartConvWord &status_word = edge_words.values[ninth_run_words];
  const PartConvWord &done_word = edge_words.values.back();
  require(status_word.kind == PartConvWordKind::kDiagnostic &&
              status_word.first == static_cast<std::uint32_t>(
                                       spine::sim::SpineDiagnosticKind::
                                           kTaskStatus) &&
              ((status_word.second >> 16) & 0xffU) == 1 &&
              done_word.kind == PartConvWordKind::kDoneAll &&
              done_word.second == 1,
          "reader error diagnostics or DONE overflow payload mismatch");
}

void test_spine_maintenance_consumes_sorted_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "sorted-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(500 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "sorted-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 516},
      backend);
  FixedAxiPort metadata(
      "sorted-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 520},
      backend);
  FixedAxiPort result(
      "sorted-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 521},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}},
      .case_name = "sorted_payload_antibypass",
  };
  SpineL0State state;
  SpineL0Maintenance maintenance("sorted-payload-maintenance", core,
                                 SpineL0Config{}, std::move(batch), ports,
                                 state);
  sorted.initialize_payload(
      0, encode_spine_sort_edge(
             SpineEdgeRecord{.src = 0, .dst = 2, .weight = 2, .diff = 1}));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      50'000);

  require(!maintenance.failed(),
          "sorted payload anti-bypass maintenance failed");
  require(state.cold_levels[0][0].size() == 1 &&
              state.cold_levels[0][0][0].dst == 2 &&
              state.cold_levels[0][0][0].weight == 2,
          "maintenance ignored HBM sorted payload and used logical workload");
  require(maintenance.counters().sorted_payload_read_bytes ==
                  maintenance.counters().sorted_read_bytes &&
              maintenance.counters().sorted_payload_read_bytes > 0,
          "sorted payload read ledger does not close");
}

void test_spine_carry_merge_consumes_level_payload_from_hbm() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  std::vector<std::unique_ptr<FixedAxiPort>> graph_ports;
  graph_ports.reserve(16);
  SpineL0Ports ports;
  for (std::size_t index = 0; index < ports.graph.size(); ++index) {
    graph_ports.push_back(std::make_unique<FixedAxiPort>(
        "carry-payload-graph" + std::to_string(index), core,
        FixedAxiPortConfig{
            .memory_channels = 32,
            .channel = index,
            .initiator_id = static_cast<std::uint32_t>(600 + index),
        },
        backend));
    ports.graph[index] = graph_ports.back().get();
  }
  FixedAxiPort sorted(
      "carry-payload-sorted", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 16, .initiator_id = 616},
      backend);
  FixedAxiPort metadata(
      "carry-payload-metadata", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 20, .initiator_id = 620},
      backend);
  FixedAxiPort result(
      "carry-payload-result", core,
      FixedAxiPortConfig{
          .memory_channels = 32, .channel = 21, .initiator_id = 621},
      backend);
  ports.sorted_edges = &sorted;
  ports.metadata = &metadata;
  ports.result = &result;

  SpineL0State state;
  state.cold_levels[0][0] = {
      SpineEdgeRecord{.src = 0, .dst = 1, .weight = 5, .diff = 1}};
  SpineEdgeSlice batch{
      .vertices = 128,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 2, .weight = 3, .diff = 1}},
      .case_name = "carry_payload_antibypass",
  };
  SpineL0Maintenance maintenance("carry-payload-maintenance", core,
                                 SpineL0Config{}, std::move(batch), ports,
                                 state);
  const SpineLevelLayout cold_l0 =
      spine_level_layout(SpineL0Config{}, false, 0);
  graph_ports[0]->initialize_payload(
      cold_l0.edge_offset_words * spine::sim::kSpineGraphWordBytes,
      encode_spine_level_edge(
          SpineEdgeRecord{.src = 0, .dst = 4, .weight = 2, .diff = 1}));

  scheduler.add_component(maintenance);
  for (auto &port : graph_ports) {
    port->register_components(scheduler);
  }
  sorted.register_components(scheduler);
  metadata.register_components(scheduler);
  result.register_components(scheduler);
  scheduler.add_component(backend);
  scheduler.run_until(
      [&] {
        return maintenance.done() && sorted.idle() && metadata.idle() &&
               result.idle() &&
               std::all_of(graph_ports.begin(), graph_ports.end(),
                           [](const auto &port) { return port->idle(); });
      },
      100'000);

  require(!maintenance.failed(),
          "carry payload anti-bypass maintenance failed");
  const auto &level = state.cold_levels[0][1];
  require(level.size() == 2 && level[0].dst == 2 && level[0].weight == 3 &&
              level[1].dst == 4 && level[1].weight == 2,
          "carry merge ignored HBM level payload and used logical level state");
  require(maintenance.counters().carry_level_payload_reads == 1 &&
              maintenance.counters().carry_level_payload_read_bytes == 8 &&
              maintenance.counters().carry_new_batch_reads == 1 &&
              maintenance.counters().carry_new_batch_read_bytes == 16,
          "carry level payload read ledger does not close");
}

void test_spine_hls_metadata_and_active_record_abi() {
  const SpineL0Config config;
  const auto layout = spine::sim::spine_metadata_layout(config);
  require(layout.page_count == 65'536 && layout.slice_count == 32 * 11 &&
              layout.slice_words == 32 * 11 * 8 &&
              layout.active_bin_offset_base == layout.slice_words &&
              layout.active_bin_count_base == layout.slice_words + 16 &&
              layout.dirty_count_word == layout.dirty_base &&
              layout.dirty_hash_xor_word == layout.dirty_base + 3 &&
              layout.dirty_candidate_generation_word ==
                  layout.dirty_base + 4 &&
              layout.dirty_candidate_valid_word == layout.dirty_base + 8 &&
              layout.dirty_host_generation_word == layout.dirty_base + 9 &&
              layout.dirty_host_valid_word == layout.dirty_base + 13 &&
              layout.dirty_last_status_word == layout.dirty_base + 15,
          "Spine metadata layout diverged from the production HLS ABI");

  const std::uint64_t control = spine::sim::spine_metadata_control_word(true);
  require(spine::sim::spine_metadata_control_valid(control) &&
              !spine::sim::spine_metadata_control_valid(control ^ (1ULL << 32)),
          "Spine metadata control validation is not fail closed");

  spine::sim::SpineActiveRecord record{
      .source = 0x04030201U,
      .source_value = 0x08070605U,
      .hot_shard_mask = 0x5aa5U,
  };
  for (std::size_t level = 0; level < record.level_masks.size(); ++level) {
    record.level_masks[level] = static_cast<std::uint16_t>(0x100U + level);
  }
  const auto encoded = spine::sim::encode_spine_active_record(record);
  require(encoded.size() == spine::sim::kSpineActiveRecordBytes &&
              encoded[0] == 0x01 && encoded[4] == 0x05 && encoded[8] == 0x00 &&
              encoded[9] == 0x01 && encoded[30] == 0xa5 &&
              encoded[31] == 0x5a &&
              spine::sim::decode_spine_active_record(encoded) == record,
          "Spine 256-bit active-record codec diverged from the HLS bit layout");
}

std::vector<std::uint32_t> sorted_vertices(
    std::vector<std::uint32_t> vertices) {
  std::sort(vertices.begin(), vertices.end());
  return vertices;
}

void test_spine_multiround_weighted_sssp_converges() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "weighted_chain_shortcut.slice";
  SpineVerticalSliceSystem system(scheduler, core, backend,
                                  load_spine_edge_slice(fixture), 0);
  system.register_components();
  scheduler.add_component(backend);
  const auto result = system.run_sssp_to_convergence(16, 200'000);

  require(result.converged && !result.failed && result.rounds.size() == 6,
          "weighted SSSP did not converge in the oracle round count");
  require(result.dirty_ack.has_value() && result.dirty_ack->status == 0 &&
              result.dirty_ack->captured ==
                  spine::sim::spine_dirty_identity(
                      1, std::vector<std::uint32_t>{0, 1, 2, 3, 4}) &&
              result.dirty_ack->candidate == result.dirty_ack->captured &&
              result.dirty_ack->result == SpineDirtyIdentity{
                                              .generation = 2,
                                          } &&
              result.dirty_ack->candidate_write_bytes == 40 &&
              result.dirty_ack->metadata_read_bytes == 72 &&
              result.dirty_ack->metadata_write_bytes == 64 &&
              result.dirty_ack->list_read_bytes == 160 &&
              result.dirty_ack->bitmap_read_bytes == 160 &&
              result.dirty_ack->bitmap_write_bytes == 80 &&
              result.dirty_ack->result_write_bytes == 384 &&
              result.dirty_ack->validated_sources == 5 &&
              result.dirty_ack->cleared_sources == 5 &&
              result.dirty_ack->generation_advances == 1,
          "weighted SSSP dirty ACK work ledger does not match HLS");
  const std::vector<std::vector<std::uint32_t>> expected_inputs = {
      {0}, {1, 2, 5}, {1, 3}, {3, 4}, {4, 5}, {5}};
  const std::vector<std::vector<std::uint32_t>> expected_outputs = {
      {1, 2, 5}, {1, 3}, {3, 4}, {4, 5}, {5}, {}};
  const std::vector<std::vector<std::uint32_t>> expected_reader_sources = {
      {0, 1, 2, 3, 4}, {1, 2}, {1, 3}, {3, 4}, {4}, {}};
  const std::vector<std::uint64_t> expected_requests = {5, 0, 0, 0, 0, 0};
  const std::vector<std::uint64_t> expected_edges = {8, 3, 2, 2, 1, 0};
  for (std::size_t round = 0; round < result.rounds.size(); ++round) {
    const auto &evidence = result.rounds[round];
    require(sorted_vertices(evidence.active_in) == expected_inputs[round] &&
                sorted_vertices(evidence.active_out) == expected_outputs[round],
            "weighted SSSP frontier diverged from the round oracle");
    require(sorted_vertices(evidence.reader_sources) ==
                expected_reader_sources[round],
            "weighted SSSP HLS reader-source set mismatch");
    require(evidence.reader.source_requests == expected_requests[round] &&
                evidence.reader.source_responses == expected_requests[round] &&
                evidence.compute.processed_edges == expected_edges[round],
            "weighted SSSP round work ledger mismatch");
    require(evidence.compute.full_path_tiles == 0 &&
                evidence.edge_axis.max_occupancy <= 32 &&
                evidence.end_cycle > evidence.start_cycle,
            "weighted SSSP round violated tile/FIFO/timing invariants");
    require(evidence.reader.metadata_write_bytes == 16 &&
                evidence.reader.result_write_bytes == 64,
            "weighted SSSP reader result side effects do not match HLS");
    if (round != 0) {
      require(evidence.reader.dirty_count == 0 &&
                  evidence.reader.dirty_generation == 2,
              "HOST_ACTIVE round did not observe acknowledged generation");
    }
  }
  require(system.compute().values() ==
              std::vector<std::uint32_t>({0, 3, 2, 7, 8, 10}),
          "weighted SSSP final distances diverge from the dual oracle");
  require(system.maintenance_counters().sorted_scan_passes == 20 &&
              system.level_state().cold_levels[0][0].size() == 8,
          "multi-round SSSP repeated maintenance or mutated graph levels");
}

struct SpineMemoryWindowObservation {
  std::uint64_t cycles{};
  std::vector<std::uint32_t> values;
  std::vector<std::uint32_t> next_active;
  SpineL0Counters maintenance;
  SpineReaderCounters reader;
  AxiStats sorted_axi;
  std::uint64_t backend_requests{};
};

SpineMemoryWindowObservation run_spine_memory_window(std::size_t window) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 12,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  const std::filesystem::path fixture =
      std::filesystem::path(SPINE_SOURCE_DIR) / "tests" / "data" /
      "weighted_chain_shortcut.slice";
  SpineL0Config config;
  config.memory_request_window = window;
  SpineVerticalSliceSystem system(scheduler, core, backend,
                                  load_spine_edge_slice(fixture), 0, 4096,
                                  config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      1'000'000);
  return SpineMemoryWindowObservation{
      .cycles = scheduler.clock(core).completed_cycles,
      .values = system.compute().values(),
      .next_active = system.compute().next_active(),
      .maintenance = system.maintenance_counters(),
      .reader = system.reader_counters(),
      .sorted_axi = system.axi_stats(SpineAxiPortKind::kSortedEdges),
      .backend_requests = backend.stats().accepted,
  };
}

void test_spine_memory_request_window_hides_latency() {
  const SpineMemoryWindowObservation serialized = run_spine_memory_window(1);
  const SpineMemoryWindowObservation pipelined = run_spine_memory_window(32);

  std::cout << "EVIDENCE spine_memory_window serialized_cycles="
            << serialized.cycles << " pipelined_cycles=" << pipelined.cycles
            << " maintenance_max_inflight="
            << pipelined.maintenance.max_memory_requests_inflight
            << " reader_max_inflight="
            << pipelined.reader.max_memory_requests_inflight
            << " dependency_stalls="
            << pipelined.maintenance.memory_dependency_stall_cycles << '\n';

  require(serialized.values == pipelined.values &&
              serialized.next_active == pipelined.next_active,
          "memory request window changed Spine functional results");
  require(serialized.backend_requests == pipelined.backend_requests &&
              serialized.maintenance.memory_tasks ==
                  pipelined.maintenance.memory_tasks &&
              serialized.reader.graph_read_bytes ==
                  pipelined.reader.graph_read_bytes &&
              serialized.reader.metadata_read_bytes ==
                  pipelined.reader.metadata_read_bytes,
          "memory request window changed the Spine memory work ledger");
  require(serialized.maintenance.max_memory_requests_inflight == 1,
          "serialized compatibility profile overlapped maintenance tasks");
  require(pipelined.maintenance.max_memory_requests_inflight > 1,
          "coarse what-if did not overlap maintenance tasks");
  require(serialized.reader.edge_pipeline_max_inflight > 1 &&
              pipelined.reader.edge_pipeline_max_inflight > 1,
          "source-faithful II=1 edge loops did not exercise concurrency");
  require(pipelined.maintenance.memory_requests_issued ==
                  pipelined.maintenance.memory_requests_completed &&
              pipelined.reader.memory_requests_issued ==
                  pipelined.reader.memory_requests_completed,
          "pipelined profile did not retire every issued memory request");
  require(pipelined.cycles < serialized.cycles,
          "pipelined request window did not hide backend latency");
}

void test_spine_axi_interface_profile_matches_hls_rtl() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 3,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 64,
                                .response_queue_depth = 128,
                            });
  SpineEdgeSlice workload{
      .vertices = 2,
      .edges = {SpineEdgeRecord{.src = 0, .dst = 1, .weight = 1, .diff = 1}},
      .case_name = "axi_profile",
  };
  SpineVerticalSliceSystem system(scheduler, core, backend, workload, 0);

  const auto require_shape = [&](SpineAxiPortKind kind,
                                 std::uint32_t expected_bytes,
                                 std::size_t expected_pending) {
    const auto &config = system.axi_config(kind);
    require(config.data_width_bytes == expected_bytes &&
                config.max_burst_beats == 16 &&
                config.max_pending_requests == expected_pending &&
                config.max_outstanding_bursts == 16 &&
                config.address_accepts_per_cycle == 1 &&
                config.beat_issues_per_cycle == 1 &&
                config.response_beats_per_cycle == 1,
            "Spine AXI interface shape diverged from the accepted HLS RTL");
  };
  require(system.axi_profile().profile_id == "hls_split_9c08763",
          "Spine did not select the source-shaped AXI profile by default");
  require_shape(SpineAxiPortKind::kGraph, 8, 7);
  require_shape(SpineAxiPortKind::kSortedEdges, 16, 7);
  require_shape(SpineAxiPortKind::kActiveBins, 32, 7);
  require_shape(SpineAxiPortKind::kMetadata, 8, 7);
  require_shape(SpineAxiPortKind::kMaintenanceResult, 4, 4);
  require_shape(SpineAxiPortKind::kVertexState, 4, 7);
  require_shape(SpineAxiPortKind::kActiveOut, 8, 4);
  require_shape(SpineAxiPortKind::kActiveBitmap, 8, 7);
  require_shape(SpineAxiPortKind::kComputeResult, 4, 4);

  const SpineAxiInterfaceProfile legacy =
      SpineAxiInterfaceProfile::legacy_uniform64();
  const auto legacy_graph =
      legacy.port_config(SpineAxiPortKind::kGraph, 32, 0, 0);
  const auto legacy_sorted =
      legacy.port_config(SpineAxiPortKind::kSortedEdges, 32, 16, 16);
  require(legacy.profile_id == "legacy_uniform64" &&
              legacy_graph.data_width_bytes == 64 &&
              legacy_sorted.response_beats_per_cycle == 4,
          "legacy uniform-64 AXI profile is not explicit and reproducible");
}

SpineMemoryWindowObservation run_spine_edge_pipeline(std::size_t depth,
                                                     std::size_t capacity) {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 24,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 512,
      .edges = {},
      .case_name = "edge_pipeline_256",
  };
  for (std::uint32_t dst = 1; dst <= 256; ++dst) {
    workload.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = dst, .weight = 1, .diff = 1});
  }
  SpineL0Config config;
  config.memory_request_window = 1;
  config.reader_edge_pipeline_depth = depth;
  config.reader_edge_response_capacity = capacity;
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(workload),
                                  0, 4096, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      1'000'000);
  return SpineMemoryWindowObservation{
      .cycles = scheduler.clock(core).completed_cycles,
      .values = system.compute().values(),
      .next_active = system.compute().next_active(),
      .maintenance = system.maintenance_counters(),
      .reader = system.reader_counters(),
      .sorted_axi = system.axi_stats(SpineAxiPortKind::kSortedEdges),
      .backend_requests = backend.stats().accepted,
  };
}

void test_spine_edge_pipeline_is_ordered_bounded_and_latency_hiding() {
  const SpineMemoryWindowObservation serialized = run_spine_edge_pipeline(1, 1);
  const SpineMemoryWindowObservation capacity_two =
      run_spine_edge_pipeline(32, 2);
  const SpineMemoryWindowObservation pipelined =
      run_spine_edge_pipeline(32, 32);

  std::cout << "EVIDENCE spine_edge_pipeline serialized_cycles="
            << serialized.cycles << " capacity2_cycles=" << capacity_two.cycles
            << " pipelined_cycles=" << pipelined.cycles
            << " max_inflight=" << pipelined.reader.edge_pipeline_max_inflight
            << " max_buffered=" << pipelined.reader.edge_pipeline_max_buffered
            << " credit_stalls="
            << pipelined.reader.edge_pipeline_credit_stall_cycles
            << " maintenance_scan_buffer="
            << pipelined.maintenance.max_sorted_scan_buffered_edges
            << " maintenance_reorder_stalls="
            << pipelined.maintenance.sorted_scan_reorder_full_stall_cycles
            << " axi_beat_fifo_stalls="
            << pipelined.sorted_axi.read_beat_queue_stalls << '\n';

  require(serialized.values == capacity_two.values &&
              serialized.values == pipelined.values &&
              serialized.next_active == capacity_two.next_active &&
              serialized.next_active == pipelined.next_active,
          "edge-pipeline credits changed the functional result or order");
  require(serialized.backend_requests == capacity_two.backend_requests &&
              serialized.backend_requests == pipelined.backend_requests &&
              serialized.reader.graph_read_bytes ==
                  pipelined.reader.graph_read_bytes,
          "edge-pipeline credits changed the memory work ledger");
  require(serialized.reader.construction_pipeline_requests == 256 &&
              serialized.reader.construction_pipeline_retires == 256 &&
              serialized.reader.replay_pipeline_requests == 256 &&
              serialized.reader.replay_pipeline_retires == 256 &&
              pipelined.reader.construction_pipeline_requests == 256 &&
              pipelined.reader.construction_pipeline_retires == 256 &&
              pipelined.reader.replay_pipeline_requests == 256 &&
              pipelined.reader.replay_pipeline_retires == 256,
          "edge-pipeline issue/retire ledger did not close");
  require(serialized.reader.edge_pipeline_max_inflight == 1 &&
              capacity_two.reader.edge_pipeline_max_inflight <= 2 &&
              pipelined.reader.edge_pipeline_max_inflight > 2 &&
              pipelined.reader.edge_pipeline_max_inflight <= 32,
          "edge-pipeline request or response capacity was not enforced");
  require(serialized.reader.edge_pipeline_credit_stall_cycles > 0 &&
              capacity_two.reader.edge_pipeline_credit_stall_cycles > 0 &&
              pipelined.cycles < capacity_two.cycles &&
              capacity_two.cycles < serialized.cycles,
          "edge-pipeline credits did not hide backend latency monotonically");
  require(pipelined.maintenance.max_sorted_scan_buffered_edges == 32 &&
              pipelined.maintenance.sorted_scan_reorder_full_stall_cycles > 0 &&
              pipelined.sorted_axi.read_beat_queue_stalls > 0,
          "large maintenance scan bypassed finite beat/reorder backpressure");
}

void test_spine_edge_pipeline_propagates_axis_backpressure() {
  Scheduler scheduler;
  const auto core = scheduler.add_clock_mhz("data", 141.0);
  MockMemoryBackend backend("hbm", core,
                            MockMemoryConfig{
                                .channels = 32,
                                .latency_cycles = 8,
                                .accepts_per_channel_per_cycle = 1,
                                .max_outstanding_per_channel = 128,
                                .response_queue_depth = 256,
                            });
  SpineEdgeSlice workload{
      .vertices = 8'193,
      .edges = {},
      .case_name = "edge_pipeline_axis_backpressure",
  };
  for (std::uint32_t dst = 1; dst <= 8'192; ++dst) {
    workload.edges.push_back(
        SpineEdgeRecord{.src = 0, .dst = dst, .weight = 1, .diff = 1});
  }
  SpineL0Config config;
  config.reader_edge_pipeline_depth = 32;
  config.reader_edge_response_capacity = 32;
  SpineVerticalSliceSystem system(scheduler, core, backend, std::move(workload),
                                  0, 4096, config);
  system.register_components();
  scheduler.add_component(backend);
  scheduler.run_until([&system] { return system.done() && system.idle(); },
                      2'000'000);

  const SpineReaderCounters &reader = system.reader_counters();
  const SpineComputeCounters &compute = system.compute_counters();
  std::cout << "EVIDENCE spine_edge_pipeline_backpressure cycles="
            << scheduler.clock(core).completed_cycles
            << " axis_stalls=" << reader.edge_pipeline_axis_stall_cycles
            << " axis_max=" << system.edge_stream_stats().max_occupancy << '\n';
  require(!system.failed() && reader.edges_emitted == 8'192 &&
              reader.construction_pipeline_requests == 8'192 &&
              reader.construction_pipeline_retires == 8'192 &&
              reader.replay_pipeline_requests == 8'192 &&
              reader.replay_pipeline_retires == 8'192,
          "backpressured edge pipeline lost or duplicated work");
  require(reader.edge_pipeline_axis_stall_cycles > 0 &&
              system.edge_stream_stats().max_occupancy == 32 &&
              system.edge_stream_stats().push_stalls > 0,
          "compute pause did not propagate through AXIS to edge retirement");
  require(compute.full_path_tiles == 1 &&
              compute.full_buffer_replay_edges == 4'096 &&
              compute.full_overflow_edges == 1 &&
              compute.full_stream_edges == 4'095,
          "backpressure fixture did not exercise the full-tile transition");
  require(std::all_of(system.compute().values().begin() + 1,
                      system.compute().values().end(),
                      [](std::uint32_t value) { return value == 1; }),
          "backpressured replay changed the final distances");
}

}  // namespace

int main(int argc, char **argv) {
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
      {"axi_payload_round_trip",
       test_axi_payload_round_trip_across_beats_and_bursts},
      {"axi_read_beat_stream",
       test_axi_read_beat_stream_is_bounded_and_request_scoped},
      {"axi_multi_initiator", test_axi_multi_initiator_fixed_channel_isolation},
      {"axi_duplicate_initiator", test_axi_rejects_duplicate_initiator_id},
      {"spine_l0_real_slice", test_spine_l0_real_slice_vertical_path},
      {"spine_dirty_persistent_state",
       test_spine_dirty_mark_preserves_persistent_state},
      {"spine_reusable_system",
       test_spine_reusable_system_matches_vertical_slice},
      {"spine_host_dirty_coverage",
       test_spine_host_active_requires_exact_dirty_coverage},
      {"spine_device_dirty_request_windows",
       test_spine_device_dirty_source_request_windows},
      {"spine_host_active_gate_fallback",
       test_spine_host_active_gate_runs_tiled_fallback},
      {"spine_device_dirty_host_handoff",
       test_spine_device_dirty_limit_hands_off_to_host},
      {"spine_device_task_limit_handoffs",
       test_spine_device_task_limits_hand_off_to_tiled_fallback},
      {"spine_convergence_host_handoff",
       test_spine_convergence_runner_records_host_handoff},
      {"spine_dirty_ack_rejections",
       test_spine_dirty_ack_rejects_stale_and_malformed_candidates},
      {"spine_source_protocol_error",
       test_spine_compute_rejects_malformed_source_protocol},
      {"spine_cold_l1_carry", test_spine_cold_l1_carry_and_reader},
      {"spine_carry_kway_refill", test_spine_carry_kway_refill_pipeline},
      {"spine_hot_cold_targets", test_spine_independent_hot_and_cold_targets},
      {"spine_fixed_level_layout",
       test_spine_fixed_level_layout_matches_stable_profile},
      {"spine_signed_diff_cancellation",
       test_spine_carry_drops_signed_diff_cancellation},
      {"spine_full_tile_boundaries", test_spine_full_tile_threshold_boundaries},
      {"spine_full_tile_axis_backpressure",
       test_spine_full_tile_load_replay_backpressures_axis},
      {"spine_tiny_duplicate_gather",
       test_spine_tiny_gather_preserves_duplicate_reads},
      {"spine_compute_hbm_payload",
       test_spine_compute_consumes_vertex_payload_from_hbm},
      {"spine_reader_hbm_graph_payload",
       test_spine_reader_consumes_graph_edge_payload_from_hbm},
      {"spine_maintenance_hbm_sorted_payload",
       test_spine_maintenance_consumes_sorted_payload_from_hbm},
      {"spine_carry_hbm_level_payload",
       test_spine_carry_merge_consumes_level_payload_from_hbm},
      {"spine_hls_metadata_active_abi",
       test_spine_hls_metadata_and_active_record_abi},
      {"spine_multiround_weighted_sssp",
       test_spine_multiround_weighted_sssp_converges},
      {"spine_memory_request_window",
       test_spine_memory_request_window_hides_latency},
      {"spine_axi_interface_profile",
       test_spine_axi_interface_profile_matches_hls_rtl},
      {"spine_edge_pipeline",
       test_spine_edge_pipeline_is_ordered_bounded_and_latency_hiding},
      {"spine_edge_pipeline_backpressure",
       test_spine_edge_pipeline_propagates_axis_backpressure},
  };
  const std::string filter = argc > 1 ? argv[1] : "";
  std::size_t failures = 0;
  std::size_t executed = 0;
  for (const auto &[name, test] : tests) {
    if (!filter.empty() && name.find(filter) == std::string::npos) {
      continue;
    }
    ++executed;
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
  std::cout << executed << " test(s) passed\n";
  return 0;
}
