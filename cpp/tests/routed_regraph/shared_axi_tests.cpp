#include "spine_sim/shared_axi_port.hpp"

#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using namespace spine::sim;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

class Client final : public Component {
public:
  Client(ClockId clock, std::size_t index, std::size_t depth, bool pressure)
      : Component("client", clock), requests("requests", clock, depth),
        responses("responses", clock, depth), beats("beats", clock, depth),
        index_(index), pressure_(pressure) {}

  AxiEndpoint endpoint() { return {requests, responses, &beats}; }
  bool done() const { return completed_ == kRequests && received_beats_ == kStreamBeats; }
  static constexpr std::size_t kRequests = 12, kStreamBeats = 32;
  static std::uint64_t address(std::size_t client, std::size_t request) {
    return 0x10000 + client * 0x10000 + request * 0x1000;
  }
  static std::uint8_t payload(std::size_t client, std::size_t request) {
    return static_cast<std::uint8_t>(client * 32 + request + 1);
  }
  void evaluate(const CycleContext &context) override {
    issued_ = false;
    response_.reset();
    beat_.reset();
    if (sent_ < kRequests) {
      const bool write = sent_ % 3 == 1, stream = sent_ % 3 == 2;
      const std::size_t bytes = stream ? 512 : 64;
      issued_ = requests.try_push(AxiRequest{
          .transaction_id = sent_ + 1, .operation = write ? MemoryOperation::kWrite : MemoryOperation::kRead,
          .address = address(index_, sent_), .bytes = bytes, .stream_read_beats = stream,
          .target_channel = index_ % 2,
          .write_data = write ? std::vector<std::uint8_t>(bytes, payload(index_, sent_)) : std::vector<std::uint8_t>{}});
    }
    if (!pressure_ || index_ != 0 || (context.domain_cycle >= 400 && context.domain_cycle % 7 == 0)) {
      AxiResponse response;
      if (responses.try_pop(response)) response_ = std::move(response);
    }
    if (!pressure_ || index_ != 1 || (context.domain_cycle >= 700 && context.domain_cycle % 5 == 0)) {
      AxiReadBeatResponse beat;
      if (beats.try_pop(beat)) beat_ = std::move(beat);
    }
  }
  void commit(const CycleContext &) override {
    if (issued_) ++sent_;
    if (response_) {
      const auto id = response_->transaction_id;
      require(id > 0 && id <= kRequests && !seen_[id - 1], "response ID lost, duplicated or misrouted");
      seen_[id - 1] = true;
      const auto request = id - 1;
      const bool write = request % 3 == 1;
      require(response_->success && response_->operation == (write ? MemoryOperation::kWrite : MemoryOperation::kRead),
              "response operation or status differs");
      if (!write) require(response_->read_data == std::vector<std::uint8_t>(request % 3 == 2 ? 512 : 64,
                                                                         payload(index_, request)),
                          "response payload differs across clients");
      ++completed_;
    }
    if (beat_) {
      const auto id = beat_->transaction_id;
      require(id > 0 && id <= kRequests && (id - 1) % 3 == 2, "stream response ID misrouted");
      auto &offset = offsets_[id - 1];
      require(beat_->success && beat_->parent_offset == offset &&
              beat_->address == address(index_, id - 1) + offset &&
              beat_->read_data == std::vector<std::uint8_t>(64, payload(index_, id - 1)) &&
              beat_->last == (offset == 448), "stream response order or payload differs");
      offset += 64;
      ++received_beats_;
    }
  }
  Fifo<AxiRequest> requests;
  Fifo<AxiResponse> responses;
  Fifo<AxiReadBeatResponse> beats;
private:
  std::size_t index_{};
  bool pressure_{}, issued_{};
  std::size_t sent_{}, completed_{}, received_beats_{};
  std::array<bool, kRequests> seen_{};
  std::array<std::size_t, kRequests> offsets_{};
  std::optional<AxiResponse> response_;
  std::optional<AxiReadBeatResponse> beat_;
};

struct Result {
  std::uint64_t cycles{};
  SharedAxiPortCounters counters;
  bool operator==(const Result &) const = default;
};

Result run(std::size_t clients, std::size_t depth, std::size_t capacity,
           bool pressure, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 2, .latency_cycles = 29, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 16, .response_queue_depth = 16,
      .registered_round_robin_arbitration = true});
  FixedAxiPort memory("shared", clock, FixedAxiPortConfig{
      .memory_channels = 2, .channel = 0, .initiator_id = 1,
      .data_width_bytes = 64, .max_burst_beats = 4,
      .request_fifo_depth = 2, .response_fifo_depth = 2, .read_beat_fifo_depth = 2,
      .read_reorder_capacity = 16, .stream_read_beats = true,
      .max_pending_requests = 4, .max_outstanding_bursts = 4}, backend);
  std::vector<std::unique_ptr<Client>> workers;
  std::vector<AxiEndpoint> endpoints;
  for (std::size_t client = 0; client < clients; ++client) {
    workers.push_back(std::make_unique<Client>(clock, client, depth, pressure));
    endpoints.push_back(workers.back()->endpoint());
    for (std::size_t request = 0; request < Client::kRequests; ++request)
      backend.fill_payload(client % 2, Client::address(client, request), 512,
                           request % 3 == 1 ? 0xcc : Client::payload(client, request));
  }
  SharedAxiPort mux("mux", clock, memory, endpoints, capacity);
  std::vector<Component *> components{&backend, &memory.requests(), &memory.master(),
                                     &memory.responses(), &memory.read_beats(), &mux};
  for (auto &client : workers) {
    components.push_back(&client->requests);
    components.push_back(&client->responses);
    components.push_back(&client->beats);
    components.push_back(client.get());
  }
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  Result result;
  for (; result.cycles < 30000; ++result.cycles) {
    scheduler.step();
    if (std::all_of(workers.begin(), workers.end(), [](const auto &client) { return client->done(); }) &&
        mux.idle() && memory.idle()) { ++result.cycles; break; }
  }
  require(result.cycles < 30000 && backend.outstanding() == 0, "shared master timed out or leaked requests");
  result.counters = mux.counters();
  require(result.counters.accepted == clients * Client::kRequests &&
          result.counters.completed == result.counters.accepted &&
          result.counters.read_beats == clients * Client::kStreamBeats &&
          result.counters.max_pending <= capacity &&
          memory.master().stats().requests_accepted == result.counters.accepted &&
          memory.master().stats().requests_completed == result.counters.completed,
          "shared master request or beat conservation failed");
  require(backend.traffic_stats().reads.bytes == clients * (4 * 64 + 4 * 512) &&
          backend.traffic_stats().writes.bytes == clients * 4 * 64,
          "shared master bus byte accounting differs");
  require(backend.traffic_stats_by_initiator().size() == 1,
          "shared master accidentally created independent physical ports");
  for (std::size_t client = 0; client < clients; ++client)
    for (std::size_t request = 1; request < Client::kRequests; request += 3)
      require(backend.inspect_payload(client % 2, Client::address(client, request), 64) ==
                  std::vector<std::uint8_t>(64, Client::payload(client, request)), "write payload differs");
  for (auto *component : components) scheduler.remove_component(*component);
  return result;
}

void completion_lifetime() {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 1, .latency_cycles = 10, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 16, .response_queue_depth = 16});
  FixedAxiPort memory("shared", clock, FixedAxiPortConfig{
      .memory_channels = 1, .channel = 0, .initiator_id = 1, .stream_read_beats = true}, backend);
  Client client(clock, 0, 2, false);
  SharedAxiPort mux("mux", clock, memory, {client.endpoint()}, 1);
  // Drive physical responses directly to test parent-before-last-beat ordering.
  for (Component *component : std::vector<Component *>{&memory.requests(), &memory.responses(),
       &memory.read_beats(), &client.requests, &client.responses, &client.beats, &mux})
    scheduler.add_component(*component);
  require(client.requests.try_push(AxiRequest{.transaction_id = 77,
      .address = 0x1000, .bytes = 128, .stream_read_beats = true, .write_data = {}}), "request enqueue failed");
  scheduler.step();
  scheduler.step();
  AxiRequest request;
  require(memory.requests().try_pop(request), "mux failed to forward request");
  require(request.transaction_id != 77 && request.stream_read_beats, "physical ID or stream flag not routed");
  scheduler.step();
  require(memory.responses().try_push(AxiResponse{.transaction_id = request.transaction_id,
      .read_data = std::vector<std::uint8_t>(128, 1)}), "response enqueue failed");
  scheduler.step();
  scheduler.step();
  require(mux.pending() == 1 && mux.counters().completed == 0,
          "parent response released routing credit before the streamed beats");
  for (std::size_t offset : {0U, 64U}) {
    require(memory.read_beats().try_push(AxiReadBeatResponse{
        .transaction_id = request.transaction_id, .address = 0x1000 + offset,
        .parent_offset = offset, .last = offset == 64, .read_data = std::vector<std::uint8_t>(64, 1)}),
        "read beat enqueue failed");
    scheduler.step();
    scheduler.step();
    require(mux.pending() == (offset == 0 ? 1U : 0U), "stream lifetime released at wrong beat");
  }
  AxiResponse response;
  require(client.responses.try_pop(response) && response.transaction_id == 77, "logical parent ID not restored");
  for (std::size_t offset : {0U, 64U}) {
    AxiReadBeatResponse beat;
    require(client.beats.try_pop(beat) && beat.transaction_id == 77 && beat.parent_offset == offset,
            "logical beat ID not restored");
    scheduler.step();
  }
  require(mux.idle() && memory.idle(), "completion lifetime leaked a queue entry");
}

void invalid_wiring() {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  const auto other_clock = scheduler.add_clock_mhz("other", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 1, .latency_cycles = 10, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 16, .response_queue_depth = 16});
  FixedAxiPort memory("shared", clock, FixedAxiPortConfig{
      .memory_channels = 1, .channel = 0, .initiator_id = 1}, backend);
  Client client(clock, 0, 2, false), other(other_clock, 1, 2, false);
  const auto rejected = [&](std::vector<AxiEndpoint> ports, std::size_t capacity) {
    try { SharedAxiPort mux("invalid", clock, memory, std::move(ports), capacity); }
    catch (const std::invalid_argument &) { return true; }
    return false;
  };
  AxiEndpoint plain(client.requests, client.responses);
  require(rejected({}, 1), "empty shared port accepted");
  require(rejected({plain}, 0), "zero routing capacity accepted");
  require(rejected({plain, plain}, 2), "aliased client queues accepted");
  require(rejected({AxiEndpoint(other.requests, other.responses)}, 1), "cross-clock client accepted");
  require(rejected({AxiEndpoint(memory)}, 1), "physical queues also accepted as client queues");
  require(rejected({client.endpoint()}, 1), "stream client accepted on non-streaming physical port");
}
} // namespace

int main() {
  try {
    invalid_wiring();
    completion_lifetime();
    std::size_t cases = 0;
    for (auto clients : {1U, 2U, 4U})
      for (auto depth : {1U, 4U})
        for (auto capacity : {1U, 3U, 16U})
          for (bool pressure : {false, true}) {
            const auto forward = run(clients, depth, capacity, pressure, false);
            const auto reverse = run(clients, depth, capacity, pressure, true);
            require(forward == reverse, "shared master depends on component registration order");
            cases += 2;
          }
    std::cout << "PASS: " << cases << " shared-master pressure/order/conservation cases\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
