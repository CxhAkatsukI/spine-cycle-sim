#include "../../src/detail/grasu_regraph_compute.hpp"
#include "spine_sim/shared_axi_port.hpp"

#include <iostream>
#include <stdexcept>

namespace {
using namespace spine::sim;
using namespace spine::sim::detail;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

struct Context final : ReGraphReaderContext {
  AlgorithmIterationContext value;
  bool done() const noexcept override { return true; }
  AlgorithmIterationContext iteration_context() const noexcept override { return value; }
};

struct ClientQueues {
  Fifo<AxiRequest> requests;
  Fifo<AxiResponse> responses;
  ClientQueues(ClockId clock, std::size_t depth)
      : requests("requests", clock, depth), responses("responses", clock, depth) {}
  AxiEndpoint endpoint() { return {requests, responses}; }
};

struct Result {
  std::vector<std::vector<std::uint8_t>> states;
  std::vector<std::size_t> active;
  std::vector<float> errors;
  std::uint64_t reads{}, writes{}, degree_reads{}, source_writes{}, bus_reads{}, bus_writes{};
  bool operator==(const Result &) const = default;
};

Result run(GraphAlgorithmKind algorithm, bool split, bool shared, std::size_t depth, bool reverse) {
  constexpr std::size_t kVertices = 61, kPadded = 64;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 3, .latency_cycles = 23, .accepts_per_channel_per_cycle = 1,
      .max_outstanding_per_channel = 16, .response_queue_depth = 16,
      .registered_round_robin_arbitration = true});
  GraSuReGraphConfig config;
  config.partition_vertices = kPadded;
  config.split_pagerank_state = split;
  config.apply_request_window = 2;
  config.apply_pipeline_latency = 5;
  config.apply_pipeline_capacity = 4;
  config.hbm_wrapper_pipeline_latency = 3;
  config.hbm_wrapper_pipeline_capacity = 4;
  GraphAlgorithmPolicy policy({.kind = algorithm, .vertices = kVertices});
  const bool pagerank = algorithm == GraphAlgorithmKind::kFullPageRank ||
                        algorithm == GraphAlgorithmKind::kResidualPageRank;
  const bool auxiliary = split && algorithm == GraphAlgorithmKind::kResidualPageRank;
  std::vector<std::unique_ptr<FixedAxiPort>> physical;
  std::vector<std::unique_ptr<ClientQueues>> clients;
  std::vector<AxiEndpoint> endpoints;
  std::vector<std::unique_ptr<SharedAxiPort>> muxes;
  for (std::size_t index = 0; index < (shared ? 3U : 7U); ++index) {
    const auto channel = shared ? index : (index < 5 ? 0 : index - 4);
    physical.push_back(std::make_unique<FixedAxiPort>("port", clock, FixedAxiPortConfig{
        .memory_channels = 3, .channel = channel, .initiator_id = static_cast<std::uint32_t>(index + 1),
        .request_fifo_depth = depth, .response_fifo_depth = depth,
        .max_pending_requests = 4, .max_outstanding_bursts = 4}, backend));
  }
  for (std::size_t index = 0; index < 7; ++index) {
    clients.push_back(std::make_unique<ClientQueues>(clock, depth));
    endpoints.push_back(shared ? clients.back()->endpoint() : AxiEndpoint(*physical[index]));
  }
  if (shared) {
    // Deliberately stress all Apply clients on one master. This fixture is
    // not a claim that every PageRank HLS port uses this same mapping.
    muxes.push_back(std::make_unique<SharedAxiPort>("apply-mux", clock, *physical[0],
        std::vector<AxiEndpoint>(endpoints.begin(), endpoints.begin() + 5), 3));
    for (std::size_t index = 1; index < 3; ++index)
      muxes.push_back(std::make_unique<SharedAxiPort>("source-mux", clock, *physical[index],
          std::vector<AxiEndpoint>{endpoints[index + 4]}, 2));
  }
  Fifo<ReGraphMergedBurst> input("merged", clock, depth);
  Fifo<ReGraphAppliedBurst> output("applied", clock, depth);
  Context context;
  context.value.base = policy.initial_base_word();
  auto apply = make_regraph_apply("apply", clock, kVertices, policy, config, input, output,
      ReGraphApplyPorts{endpoints[0], endpoints[1],
          pagerank ? std::optional<AxiEndpoint>(endpoints[2]) : std::nullopt,
          auxiliary ? std::optional<AxiEndpoint>(endpoints[3]) : std::nullopt,
          auxiliary ? std::optional<AxiEndpoint>(endpoints[4]) : std::nullopt}, context);
  auto writer = make_regraph_writeback("writer", clock, config, policy, output, endpoints[5], endpoints[6]);
  for (std::size_t offset = 0; offset < kPadded; offset += 16) {
    std::array<std::uint32_t, 16> state{}, residual{}, degree{};
    for (std::size_t lane = 0; lane < 16; ++lane) {
      state[lane] = pagerank ? GraphAlgorithmPolicy::float_to_word(0.25F)
                             : encode_policy_value(policy, 100 + offset + lane, true);
      residual[lane] = GraphAlgorithmPolicy::float_to_word(lane % 2 ? -0.01F : 0.01F);
      degree[lane] = static_cast<std::uint32_t>(lane % 5);
    }
    backend.initialize_payload(0, config.vertex_state_base + offset * (auxiliary ? 4 : state_bytes_per_vertex(policy)),
                               auxiliary ? encode_words(state) : encode_state_words(policy, state, residual));
    backend.initialize_payload(0, config.residual_state_base + offset * 4, encode_words(residual));
    backend.initialize_payload(0, config.degree_base + offset * 4, encode_words(degree));
  }
  std::vector<Component *> components{&backend, &input, &output, apply.get(), writer.get()};
  for (auto &port : physical) {
    components.push_back(&port->requests());
    components.push_back(&port->responses());
    components.push_back(&port->read_beats());
    components.push_back(&port->master());
  }
  if (shared) {
    for (auto &client : clients) {
      components.push_back(&client->requests);
      components.push_back(&client->responses);
    }
    for (auto &mux : muxes) components.push_back(mux.get());
  }
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  Result result;
  for (std::size_t round = 1; round <= 2; ++round) {
    apply->start_partition(round, 0, kVertices, true);
    writer->start_partition(round, 0);
    std::size_t sent = 0, cycles = 0;
    for (; cycles < 20000; ++cycles) {
      if (sent < kPadded / 16 && cycles % 3 == 0 && !input.full()) {
        ReGraphMergedBurst burst{.offset = sent * 16};
        for (std::size_t lane = 0; lane < 16; ++lane)
          if (lane % 3) burst.candidates[lane] = pagerank ? GraphAlgorithmPolicy::float_to_word(0.1F)
                                                        : static_cast<std::uint32_t>(burst.offset + lane);
        if (input.try_push(burst)) ++sent;
      }
      scheduler.step();
      if (apply->done() && writer->done() &&
          std::all_of(physical.begin(), physical.end(), [](const auto &port) { return port->idle(); }) &&
          std::all_of(muxes.begin(), muxes.end(), [](const auto &mux) { return mux->idle(); })) break;
    }
    require(cycles < 20000 && sent == kPadded / 16 && backend.outstanding() == 0,
            "connected Apply/writeback timed out or leaked requests");
    result.states.push_back(backend.inspect_payload(0, config.vertex_state_base,
                                                    kPadded * (auxiliary ? 4 : state_bytes_per_vertex(policy))));
    if (auxiliary) result.states.push_back(backend.inspect_payload(0, config.residual_state_base, kPadded * 4));
    for (std::size_t channel = 1; channel < 3; ++channel)
      result.states.push_back(backend.inspect_payload(channel,
          config.source_state_base + (round & 1U) * config.source_state_buffer_stride, kPadded * 4));
    result.active.push_back(apply->active_vertices());
    result.errors.push_back(apply->iteration_error());
    if (algorithm == GraphAlgorithmKind::kWeightedSssp) {
      const auto &state = result.states[result.states.size() - 3];
      for (std::size_t vertex = 0; vertex < kPadded; ++vertex) {
        const auto expected = vertex >= kVertices ? kReGraphInfinity :
            ((vertex % 16) % 3 ? static_cast<std::uint32_t>(vertex) | (round == 1 ? kReGraphActive : 0)
                              : static_cast<std::uint32_t>(100 + vertex));
        require(decode_u32(state, vertex * 4) == expected, "SSSP complete state differs from scalar expected values");
      }
    }
  }
  result.reads = apply->reads();
  result.writes = apply->writes();
  result.degree_reads = apply->degree_reads();
  result.source_writes = writer->source_writes();
  result.bus_reads = backend.traffic_stats().reads.bytes;
  result.bus_writes = backend.traffic_stats().writes.bytes;
  require(result.reads == 8 * (auxiliary ? 2U : 1U) && result.writes == result.reads &&
          result.degree_reads == (pagerank ? 8U : 0U) && result.source_writes == 16,
          "connected Apply/writeback request conservation failed");
  const auto &traffic = backend.traffic_stats_by_initiator();
  const auto active_masters = std::count_if(traffic.begin(), traffic.end(), [](const auto &entry) {
    return entry.second.reads.requests + entry.second.writes.requests != 0;
  });
  require(traffic.size() == physical.size() &&
          active_masters == (shared ? 3 : (4 + (pagerank ? 1 : 0) + (auxiliary ? 2 : 0))),
          "connected backend did not use the declared number of masters");
  for (auto *component : components) scheduler.remove_component(*component);
  return result;
}
} // namespace

int main() {
  try {
    std::size_t cases = 0;
    for (auto kind : {GraphAlgorithmKind::kWeightedSssp, GraphAlgorithmKind::kConnectedComponents,
                      GraphAlgorithmKind::kFullPageRank, GraphAlgorithmKind::kResidualPageRank})
      for (bool split : {false, true}) {
        if (split && kind != GraphAlgorithmKind::kResidualPageRank) continue;
        const auto direct = run(kind, split, false, 4, false);
        ++cases;
        for (auto depth : {1U, 4U})
          for (bool reverse : {false, true}) {
            require(run(kind, split, true, depth, reverse) == direct,
                    "shared Apply/writeback changed final state, activation or traffic");
            ++cases;
          }
      }
    std::cout << "PASS: " << cases << " connected Apply/writeback full-state and traffic cases\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
