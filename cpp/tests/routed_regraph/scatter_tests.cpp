#include "adapter_fixture.hpp"
#include "../../src/detail/routed_regraph_scatter.hpp"

#include <iostream>

namespace {
using namespace spine::sim;
using namespace spine::sim::detail;
using routed_adapter_test::Data;
using routed_adapter_test::bytes;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

std::uint32_t source_word(GraphAlgorithmKind kind, std::size_t vertex) {
  if (kind == GraphAlgorithmKind::kWeightedSssp || kind == GraphAlgorithmKind::kConnectedComponents)
    return static_cast<std::uint32_t>(vertex + 23) | (vertex % 3 != 2 ? 0x80000000U : 0U);
  return GraphAlgorithmPolicy::float_to_word(vertex % 3 == 2 ? 0.0F : vertex % 2 ? -0.25F : 0.125F);
}

class Sink final : public Component {
public:
  Sink(ClockId clock, Fifo<PmaEdgeBatch> &input) : Component("sink", clock), input_(input) {}
  void evaluate(const CycleContext &context) override {
    staged_.reset();
    PmaEdgeBatch batch;
    if (context.domain_cycle % 7 == 0 && input_.try_pop(batch)) staged_ = batch;
  }
  void commit(const CycleContext &) override { if (staged_) received.push_back(*staged_); }
  std::vector<PmaEdgeBatch> received;
private:
  Fifo<PmaEdgeBatch> &input_;
  std::optional<PmaEdgeBatch> staged_;
};

struct Result {
  std::uint64_t cycles{};
  RoutedScatterCounters counters;
  bool operator==(const Result &) const = default;
};

Result run(GraphAlgorithmKind kind, ReGraphPmaFormat format, std::size_t vertices,
           bool stop, std::size_t depth, bool reverse, bool dummy_only = false,
           bool expect_request_deadlock = false) {
  Data data(vertices, vertices > 4096, false, format);
  if (dummy_only) {
    for (auto &bank : data.pma) for (auto &word : bank) word |= 0x80000000U;
    for (auto &packet : data.expected) {
      for (auto &source : packet.sources) source |= 0x80000000U;
      for (auto &destination : packet.destinations) destination |= 0x80000000U;
    }
  }
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{.channels = 6,
      .latency_cycles = 19, .accepts_per_channel_per_cycle = 1, .max_outstanding_per_channel = 16,
      .response_queue_depth = 16, .registered_round_robin_arbitration = true});
  FixedAxiPort adapter_memory("adapter-master", clock, FixedAxiPortConfig{
      .memory_channels = 6, .channel = 0, .initiator_id = 1}, backend);
  FixedAxiPort source_memory("source-master", clock, FixedAxiPortConfig{
      .memory_channels = 6, .channel = 5, .initiator_id = 2,
      .read_beat_fifo_depth = depth, .stream_read_beats = true, .max_outstanding_bursts = 4}, backend);
  Fifo<ReGraphPmaPacket> raw("raw", clock, depth);
  Fifo<PmaEdgeBatch> updates("updates", clock, depth);
  // The routed xclbin connects request streams at depth 16. Depth one can
  // deadlock when Scatter jumps windows before the old response block drains.
  Fifo<ReGraphSourceCacheRequest> requests("source-requests", clock, expect_request_deadlock ? 1 : 16),
      idle_requests("idle-requests", clock, 16);
  Fifo<ReGraphSourceCacheResponse> responses("source-responses", clock, depth), idle_responses("idle-responses", clock, depth);
  ReGraphPmaAdapter adapter("adapter", clock, ReGraphPmaAdapterConfig{
      .format = format, .stop_after_last = stop}, adapter_memory, raw);
  GraphAlgorithmPolicy policy({.kind = kind, .vertices = vertices});
  RoutedScatter scatter("scatter", clock, policy, format, raw, {&requests, &responses}, updates,
                        RoutedScatterTiming{.latency = depth == 1 ? 1U : 4U,
                                            .initiation_interval = 1, .capacity = depth == 1 ? 1U : 5U});
  RoutedSourceService source("dedicated-source", clock, {{&requests, &responses}},
                          AxiEndpoint(source_memory), 4);
  Sink sink(clock, updates);
  backend.initialize_payload(data.partition.row_channel, data.partition.row_base, bytes(data.rows));
  for (std::size_t bank = 0; bank < 4; ++bank)
    backend.initialize_payload(data.partition.pma_channel[bank], data.partition.pma_base[bank], bytes(data.pma[bank]));
  const auto allocation = (vertices / 4096 + 2) * 4096;
  std::vector<std::uint32_t> words(allocation);
  for (std::size_t vertex = 0; vertex < words.size(); ++vertex) words[vertex] = source_word(kind, vertex);
  backend.initialize_payload(5, 0x100000, bytes(words));
  std::vector<Component *> components{&backend, &adapter_memory.requests(), &adapter_memory.responses(),
      &adapter_memory.read_beats(), &adapter_memory.master(), &source_memory.requests(),
      &source_memory.responses(), &source_memory.read_beats(), &source_memory.master(),
      &raw, &updates, &requests, &responses, &idle_requests, &idle_responses, &adapter, &scatter, &source, &sink};
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  const RoutedScatterPartition partition{.physical_slots = data.partition.slots,
      .destination_base = data.partition.destination_base,
      .destination_vertices = data.partition.destination_vertices, .iteration = {.base = 17, .dangling_share = 23}};
  source.start_round({{0x100000, 5, allocation}}, {2});
  scatter.start_partition(partition);
  adapter.start_partition(data.partition);
  bool early_done = false, restarted_with_input = false;
  unsigned adapters = 1, scatters = 1;
  Result result;
  for (; result.cycles < 300000; ++result.cycles) {
    scheduler.step();
    early_done |= scatter.done() && !scatter.finished();
    if (adapter.done() && adapter_memory.idle() && adapters < 2) {
      adapter.start_partition(data.partition);
      ++adapters;
    }
    if (scatter.finished() && updates.empty() && scatters < 2) {
      restarted_with_input |= !raw.empty();
      scatter.start_partition(partition);
      ++scatters;
    }
    if (adapters == 2 && scatters == 2 && adapter.done() && scatter.finished() &&
        source.done() && raw.empty() && updates.empty() && adapter_memory.idle() && source_memory.idle()) {
      ++result.cycles; break;
    }
  }
  if (expect_request_deadlock) {
    require(result.cycles == 300000 && scatter.counters().packets == 6 &&
            scatter.counters().source_requests == 3 && source.counters().blocks[0] == 2 &&
            requests.size() == 1 && responses.size() == 1 && !scatter.finished(),
            "depth-one source-request deadlock signature changed");
    result.counters = scatter.counters();
    for (auto *component : components) scheduler.remove_component(*component);
    return result;
  }
  if (result.cycles == 300000) {
    std::cerr << "timeout kind=" << static_cast<int>(kind) << " vertices=" << vertices << " stop=" << stop
              << " depth=" << depth << " reverse=" << reverse << " adapters=" << adapters << " scatters=" << scatters
              << " adapter_packets=" << adapter.counters().packets << " scatter_packets=" << scatter.counters().packets
              << " source_requests=" << scatter.counters().source_requests << " source_lines=" << scatter.counters().source_lines
              << " service_blocks=" << source.counters().blocks[0] << " raw_size=" << raw.size()
              << " request_size=" << requests.size() << " response_size=" << responses.size() << '\n';
    throw std::runtime_error("connected raw adapter/Scatter/source service timed out");
  }
  require(early_done, "Gather input completion incorrectly waits for source end drain");
  if (vertices < 4096 && stop) require(restarted_with_input, "independent adapter run-ahead was not exercised");
  require(scatter.iteration_context().base == 17 && scatter.iteration_context().dangling_share == 23,
          "Scatter lost iteration context");
  require(sink.received.size() == data.expected.size() * 2, "Scatter lost or duplicated packets");
  for (std::size_t index = 0; index < sink.received.size(); ++index) {
    const auto &expected = data.expected[index % data.expected.size()];
    const auto &actual = sink.received[index];
    require(actual.per_lane_source && actual.lanes == 8, "Scatter output shape differs");
    for (std::size_t lane = 0; lane < 8; ++lane) {
      const auto encoded = source_word(kind, expected.sources[lane] & 0x7fffffffU);
      const bool pr = kind == GraphAlgorithmKind::kFullPageRank || kind == GraphAlgorithmKind::kResidualPageRank;
      const auto payload = pr ? encoded : encoded & 0x7fffffffU;
      const bool active = pr ? GraphAlgorithmPolicy::word_to_float(encoded) != 0.0F : (encoded >> 31) != 0;
      const auto raw_destination = expected.destinations[lane];
      const auto destination = format == ReGraphPmaFormat::kDestination
          ? (raw_destination & 0x7fffffffU) - data.partition.destination_base : raw_destination & 0x7ffffU;
      const auto weight = format == ReGraphPmaFormat::kDestination ? 1 : (raw_destination >> 19) & 0xfffU;
      require(actual.source_payloads[lane] == payload && actual.source_actives[lane] == active &&
              actual.valid[lane] == ((raw_destination >> 31) == 0) &&
              actual.destinations[lane] == destination && actual.weights[lane] == weight,
              "Scatter payload, activation, dummy, destination or weight differs");
    }
  }
  result.counters = scatter.counters();
  const auto &counter = result.counters;
  require(counter.packets == sink.received.size() && counter.emitted == counter.packets &&
          counter.end_requests == 2 && counter.end_responses == 2 &&
          counter.source_requests == source.counters().blocks[0] &&
          counter.source_lines + counter.discarded_lines == counter.source_requests * 256 &&
          counter.buffer_write_bytes == counter.source_lines * 64 * 8 &&
          source.counters().memory_parents == source.counters().memory_completions &&
          counter.max_inflight <= (depth == 1 ? 1U : 5U) && backend.outstanding() == 0,
          "Scatter source/packet/finite-pipeline conservation failed");
  require(adapter.counters().packets == counter.packets &&
          source_memory.master().stats().requests_accepted == counter.source_requests &&
          source_memory.master().stats().requests_completed == counter.source_requests,
          "connected adapter/source conservation failed");
  for (auto *component : components) scheduler.remove_component(*component);
  return result;
}

void rejects_zero_packets() {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  Fifo<ReGraphPmaPacket> raw("raw", clock, 1);
  Fifo<PmaEdgeBatch> output("output", clock, 1);
  Fifo<ReGraphSourceCacheRequest> requests("requests", clock, 1);
  Fifo<ReGraphSourceCacheResponse> responses("responses", clock, 1);
  RoutedScatter scatter("scatter", clock, GraphAlgorithmPolicy({.vertices = 16}), ReGraphPmaFormat::kWeighted,
                        raw, {&requests, &responses}, output);
  bool rejected = false;
  try { scatter.start_partition({.physical_slots = 0, .destination_vertices = 16}); }
  catch (const std::invalid_argument &) { rejected = true; }
  require(rejected, "zero packet HLS deadlock was silently modeled as free completion");
}
} // namespace

int main() {
  try {
    std::size_t count = 0;
    const std::vector<std::pair<GraphAlgorithmKind, ReGraphPmaFormat>> modes{
      {GraphAlgorithmKind::kWeightedSssp, ReGraphPmaFormat::kWeighted},
      {GraphAlgorithmKind::kWeightedSssp, ReGraphPmaFormat::kUnitWeight},
      {GraphAlgorithmKind::kConnectedComponents, ReGraphPmaFormat::kDestination},
      {GraphAlgorithmKind::kFullPageRank, ReGraphPmaFormat::kDestination},
      {GraphAlgorithmKind::kResidualPageRank, ReGraphPmaFormat::kDestination}};
    for (const auto &[kind, format] : modes)
      for (std::size_t vertices : {65U, 8193U})
        for (bool stop : {false, true})
          for (std::size_t depth : {1U, 8U}) {
            require(run(kind, format, vertices, stop, depth, false) ==
                    run(kind, format, vertices, stop, depth, true), "Scatter depends on component registration order");
            count += 2;
          }
    run(GraphAlgorithmKind::kWeightedSssp, ReGraphPmaFormat::kWeighted, 1, true, 1, false, true);
    run(GraphAlgorithmKind::kWeightedSssp, ReGraphPmaFormat::kWeighted, 8193, false, 1, false, false, true);
    run(GraphAlgorithmKind::kWeightedSssp, ReGraphPmaFormat::kWeighted, 8193, false, 1, true, false, true);
    rejects_zero_packets();
    std::cout << "PASS: " << count << " connected adapter/Scatter/source cases; dummy, empty-input and depth-one deadlock gates PASS\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
