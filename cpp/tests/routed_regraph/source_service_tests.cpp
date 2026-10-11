#include "../../src/detail/routed_regraph_source.hpp"
#include "spine_sim/shared_axi_port.hpp"

#include <iostream>

namespace {
using namespace spine::sim;
using namespace spine::sim::detail;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

std::uint32_t word(std::size_t worker, std::size_t vertex) {
  return static_cast<std::uint32_t>(0x80000000u | (worker << 24) | vertex);
}

class Worker final : public Component {
public:
  Worker(ClockId clock, std::size_t index, std::size_t depth, bool pressure)
      : Component("worker", clock), requests("requests", clock, depth),
        responses("responses", clock, depth), index_(index), pressure_(pressure),
        plan_(index ? std::vector<ReGraphSourceCacheRequest>{{1, false}, {0, true}, {0, false}, {3, false}, {0, true}}
                    : std::vector<ReGraphSourceCacheRequest>{{0, false}, {2, false}, {0, true}, {1, false}, {0, true}}) {}
  void reset() { sent_ = received_ = line_ = 0; }
  bool done() const { return sent_ == plan_.size() && received_ == plan_.size(); }
  void evaluate(const CycleContext &context) override {
    issued_ = sent_ < plan_.size() && requests.try_push(plan_[sent_]);
    response_.reset();
    if (!pressure_ || (context.domain_cycle > 200 && context.domain_cycle % (index_ + 3) == 0)) {
      ReGraphSourceCacheResponse response;
      if (responses.try_pop(response)) response_ = response;
    }
  }
  void commit(const CycleContext &) override {
    if (issued_) ++sent_;
    if (!response_) return;
    require(received_ < plan_.size(), "extra source response");
    const auto &expected = plan_[received_];
    require(response_->end == expected.end, "source terminator moved or lost");
    if (expected.end) { ++received_; return; }
    require(response_->source_round == expected.source_round && response_->line == line_ &&
            response_->vertices == 16, "source response order or address differs");
    for (std::size_t vertex = 0; vertex < 16; ++vertex)
      require(response_->words[vertex] == word(index_, expected.source_round * 4096 + line_ * 16 + vertex),
              "source response payload differs");
    if (++line_ == 256) { line_ = 0; ++received_; }
  }
  Fifo<ReGraphSourceCacheRequest> requests;
  Fifo<ReGraphSourceCacheResponse> responses;
private:
  std::size_t index_;
  bool pressure_, issued_{};
  std::vector<ReGraphSourceCacheRequest> plan_;
  std::size_t sent_{}, received_{}, line_{};
  std::optional<ReGraphSourceCacheResponse> response_;
};

class Writer final : public Component {
public:
  explicit Writer(ClockId clock) : Component("writer", clock), requests("writes", clock, 1),
      responses("write-responses", clock, 1) {}
  void reset() { sent_ = completed_ = 0; seen_ = {}; }
  bool done() const { return completed_ == 32; }
  void evaluate(const CycleContext &) override {
    issued_ = false;
    if (sent_ < 32) issued_ = requests.try_push(AxiRequest{.transaction_id = sent_ + 1,
        .operation = MemoryOperation::kWrite, .address = 0x800000 + sent_ * 64,
        .bytes = 64, .target_channel = 0,
        .write_data = std::vector<std::uint8_t>(64, static_cast<std::uint8_t>(sent_))});
    received_ = responses.try_pop(response_);
  }
  void commit(const CycleContext &) override {
    if (issued_) ++sent_;
    if (received_) {
      require(response_.success && response_.operation == MemoryOperation::kWrite &&
              response_.transaction_id > 0 && response_.transaction_id <= 32 &&
              !seen_[response_.transaction_id - 1], "source/writeback shared master lost write response");
      seen_[response_.transaction_id - 1] = true;
      ++completed_;
    }
  }
  Fifo<AxiRequest> requests;
  Fifo<AxiResponse> responses;
private:
  std::size_t sent_{}, completed_{};
  bool issued_{}, received_{};
  AxiResponse response_;
  std::array<bool, 32> seen_{};
};

struct Result {
  std::uint64_t cycles{};
  RoutedSourceCounters counters;
  bool operator==(const Result &) const = default;
};

Result run(std::size_t depth, std::size_t capacity, bool pressure, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{.channels = 2,
      .latency_cycles = 23, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 16, .response_queue_depth = 16,
      .registered_round_robin_arbitration = true});
  FixedAxiPort memory("physical", clock, FixedAxiPortConfig{
      .memory_channels = 2, .channel = 0, .initiator_id = 1,
      .request_fifo_depth = 2, .response_fifo_depth = 2, .read_beat_fifo_depth = depth,
      .read_reorder_capacity = 16, .stream_read_beats = true,
      .max_pending_requests = 4, .max_outstanding_bursts = 4}, backend);
  Fifo<AxiRequest> requests("logical", clock, depth);
  Fifo<AxiResponse> responses("logical-parents", clock, depth);
  Fifo<AxiReadBeatResponse> beats("logical-beats", clock, depth);
  AxiEndpoint endpoint(requests, responses, &beats);
  Worker a(clock, 0, depth, pressure), b(clock, 1, depth, pressure);
  Writer writer(clock);
  SharedAxiPort mux("mux", clock, memory, {endpoint, AxiEndpoint(writer.requests, writer.responses)}, capacity);
  RoutedSourceService service("source-pair", clock, {{&a.requests, &a.responses}, {&b.requests, &b.responses}},
                           endpoint, capacity);
  const std::vector<RoutedSourceRegion> regions{{0x10000, 0, 16384}, {0x100000, 1, 16384}};
  for (std::size_t worker = 0; worker < 2; ++worker) {
    std::vector<std::uint8_t> bytes;
    for (std::size_t vertex = 0; vertex < 16384; ++vertex)
      for (std::size_t byte = 0; byte < 4; ++byte)
        bytes.push_back(static_cast<std::uint8_t>(word(worker, vertex) >> (8 * byte)));
    backend.initialize_payload(regions[worker].channel, regions[worker].base, bytes);
  }
  std::vector<Component *> components{&backend, &memory.requests(), &memory.responses(), &memory.read_beats(),
      &memory.master(), &requests, &responses, &beats, &mux, &a, &b, &a.requests, &a.responses,
      &b.requests, &b.responses, &writer, &writer.requests, &writer.responses, &service};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  Result result;
  for (unsigned round = 0; round < 2; ++round) {
    a.reset(); b.reset(); writer.reset();
    service.start_round(regions, {2, 2});
    bool rejected = false;
    try { service.start_round(regions, {2, 2}); } catch (const std::logic_error &) { rejected = true; }
    require(rejected, "active source service restart was accepted");
    auto lines = service.counters().lines;
    std::optional<std::size_t> emitting;
    for (; result.cycles < 100000; ++result.cycles) {
      scheduler.step();
      for (std::size_t worker = 0; worker < 2; ++worker) {
        if (lines[worker] == service.counters().lines[worker]) continue;
        require(!emitting || *emitting == worker, "pairwise source blocks were interleaved");
        emitting = worker;
        ++lines[worker];
        require(lines[worker] == service.counters().lines[worker], "multiple lines emitted per cycle");
        if (lines[worker] % 256 == 0) emitting.reset();
      }
      if (service.done() && a.done() && b.done() && writer.done() && mux.idle() && memory.idle()) {
        ++result.cycles;
        break;
      }
    }
    require(result.cycles < 100000, "source pair timed out");
  }
  result.counters = service.counters();
  require(result.counters.blocks == std::array<std::uint64_t, 2>{6, 6} &&
          result.counters.lines == std::array<std::uint64_t, 2>{1536, 1536} &&
          result.counters.terminators == std::array<std::uint64_t, 2>{4, 4} &&
          result.counters.memory_parents == 12 && result.counters.memory_completions == 12 &&
          result.counters.max_pending <= capacity, "source block/line/parent conservation failed");
  require(memory.master().stats().requests_accepted == 12 + 64 &&
          memory.master().stats().requests_completed == 12 + 64 &&
          backend.traffic_stats().reads.bytes == 12 * kRoutedSourceBytes &&
          backend.traffic_stats().writes.bytes == 64 * 64 && backend.outstanding() == 0 &&
          backend.traffic_stats_by_initiator().size() == 1, "source/writeback traffic conservation failed");
  for (std::size_t write = 0; write < 32; ++write)
    require(backend.inspect_payload(0, 0x800000 + write * 64, 64) ==
            std::vector<std::uint8_t>(64, static_cast<std::uint8_t>(write)), "writeback payload differs");
  if (pressure) require(result.counters.output_stalls > 0, "source pressure was not exercised");
  for (auto *component : components) scheduler.remove_component(*component);
  return result;
}

void protocol_edges(bool early_parent) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  Fifo<ReGraphSourceCacheRequest> ar("ar", clock, 4), br("br", clock, 1);
  Fifo<ReGraphSourceCacheResponse> ao("ao", clock, 300), bo("bo", clock, 1);
  Fifo<AxiRequest> requests("memory-requests", clock, 1);
  Fifo<AxiResponse> parents("memory-parents", clock, 1);
  Fifo<AxiReadBeatResponse> beats("memory-beats", clock, 1);
  RoutedSourceService service("source", clock, {{&ar, &ao}, {&br, &bo}}, {requests, parents, &beats}, 1);
  for (Component *component : std::vector<Component *>{&ar, &br, &ao, &bo, &requests, &parents, &beats, &service})
    scheduler.add_component(*component);
  const std::vector<RoutedSourceRegion> regions{{0x10000, 0, 4096}, {0, 0, 0}};
  service.start_round(regions, {1, 0});
  require(ar.try_push({0, false}), "request enqueue failed");
  scheduler.step(); scheduler.step(); scheduler.step();
  AxiRequest request;
  require(requests.try_pop(request) && request.bytes == 16384 && request.stream_read_beats,
          "source block was not one declared AXI parent");
  require(ar.try_push({0, true}), "end enqueue failed");
  scheduler.step();
  const auto parent = [&] {
    require(parents.try_push(AxiResponse{.transaction_id = request.transaction_id,
        .read_data = std::vector<std::uint8_t>(16384)}), "parent enqueue failed");
    scheduler.step(); scheduler.step();
  };
  if (early_parent) parent();
  require(!service.done(), "parent completion prematurely ended source service");
  for (std::size_t line = 0; line < 256; ++line) {
    require(beats.try_push(AxiReadBeatResponse{.transaction_id = request.transaction_id,
        .address = 0x10000 + line * 64, .parent_offset = line * 64, .last = line == 255,
        .read_data = std::vector<std::uint8_t>(64)}), "beat enqueue failed");
    scheduler.step(); scheduler.step();
  }
  scheduler.step(); scheduler.step();
  require(service.counters().terminators[0] == 1, "end response incorrectly waits for parent completion");
  require(service.done() == early_parent, "parent and last-line lifetime are conflated");
  if (!early_parent) parent();
  require(service.done(), "source completion did not drain parent");
  ReGraphSourceCacheResponse response;
  while (ao.try_pop(response)) scheduler.step();
  service.start_round(regions, {0, 0});
  require(service.done(), "zero-invocation worker should not read source memory");
  service.start_round(regions, {1, 0});
  require(ar.try_push({1, false}), "out-of-bound request enqueue failed");
  scheduler.step();
  bool rejected = false;
  try { scheduler.step(); } catch (const std::out_of_range &) { rejected = true; }
  require(rejected, "source allocation overrun was silently zero padded");
}
} // namespace

int main() {
  try {
    std::size_t count = 0;
    for (std::size_t depth : {1U, 8U})
      for (std::size_t capacity : {1U, 4U})
        for (bool pressure : {false, true}) {
          require(run(depth, capacity, pressure, false) == run(depth, capacity, pressure, true),
                  "source pair depends on component registration order");
          count += 2;
        }
    protocol_edges(false);
    protocol_edges(true);
    std::cout << "PASS: " << count << " pairwise source/shared-writeback cases; completion and bounds PASS\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
