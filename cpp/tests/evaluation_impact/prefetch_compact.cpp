#include <iostream>
#include "k4_config.hpp"
#include "../original_regraph/sssp/real_input.hpp"
#include "../routed_regraph/round_execution.hpp"
#include "prefetch_compact/sink.hpp"

namespace {
using namespace evaluation_impact::prefetch_compact;

void run(const original_regraph_sssp_real_test::Input& input, std::uint64_t latency,
         bool reverse, std::uint64_t maximum, std::uint64_t sink_period, bool dual, bool full_burst) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  auto config = evaluation_impact::k4_configuration(evaluation_impact::control("bank_stream"));
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  const auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                                     GraSuPmaWordAbi::kWeightedFullWord);
  check(layout.partitions.size() == 4, "candidate diagnostic requires the frozen four-shard input");
  RoutedReGraphSystem resident(scheduler, clock, backend, layout, input.initial, config);
  const auto& plan = resident.runtime_plan();
  std::array<std::unique_ptr<FixedAxiPort>, 4> memories;
  std::array<std::unique_ptr<FixedAxiPort>, 4> odd_memories;
  std::array<std::unique_ptr<Fifo<Segment>>, 4> segments;
  std::array<std::unique_ptr<Fifo<ReGraphPmaPacket>>, 4> packets;
  std::array<std::unique_ptr<Reader>, 4> readers;
  std::array<std::unique_ptr<Compactor>, 4> compactors;
  std::array<std::unique_ptr<Sink>, 4> sinks;
  std::array<std::size_t, 4> slots{};
  std::vector<Component*> components{&backend};
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto& part = layout.partitions[worker];
    const auto row = find_grasu_regraph_runtime_region(plan, worker, "row");
    slots[worker] = plan.shards[worker].pma_slot_count;
    ReGraphPmaPartition p{.vertices = layout.vertices, .slots = slots[worker],
        .cache_segments_per_half = config.compute.cache_segments_per_half,
        .destination_base = part.destination_base, .destination_vertices = part.destination_vertices,
        .row_base = row.channel_offset_bytes, .row_channel = row.channel};
    for (std::size_t bank = 0; bank < 4; ++bank) {
      const auto region = find_grasu_regraph_runtime_region(plan, worker, "pma" + std::to_string(bank));
      p.pma_base[bank] = region.channel_offset_bytes;
      p.pma_channel[bank] = region.channel;
    }
    memories[worker] = std::make_unique<FixedAxiPort>("candidate-master", clock,
        FixedAxiPortConfig{.memory_channels = 32, .channel = 0,
            .initiator_id = 1000 + static_cast<std::uint32_t>(worker), .stream_read_beats = true,
            .max_pending_requests = 16, .max_outstanding_bursts = 16,
            .response_beats_per_cycle = config.compute.response_beats_per_cycle,
            .independent_read_write = config.independent_read_write}, backend);
    auto& memory = *memories[worker];
    if (dual) {
      odd_memories[worker] = std::make_unique<FixedAxiPort>("candidate-odd-master", clock,
          FixedAxiPortConfig{.memory_channels = 32, .channel = 0,
              .initiator_id = 1004 + static_cast<std::uint32_t>(worker), .stream_read_beats = true,
              .max_pending_requests = 16, .max_outstanding_bursts = 16,
              .response_beats_per_cycle = config.compute.response_beats_per_cycle,
              .independent_read_write = config.independent_read_write}, backend);
      auto& odd = *odd_memories[worker];
      components.insert(components.end(), {&odd.requests(), &odd.responses(), &odd.read_beats(), &odd.master()});
    }
    segments[worker] = std::make_unique<Fifo<Segment>>("candidate-segments", clock, 16);
    packets[worker] = std::make_unique<Fifo<ReGraphPmaPacket>>("candidate-packets", clock, 32);
    readers[worker] = std::make_unique<Reader>(clock, memory, *segments[worker], p, 71,
        odd_memories[worker].get(), full_burst ? RefillPolicy::kFullBurst : RefillPolicy::kAvailableSpace);
    compactors[worker] = std::make_unique<Compactor>(clock, *segments[worker], *packets[worker],
                                                   p.destination_vertices);
    sinks[worker] = std::make_unique<Sink>(clock, *packets[worker], p, sink_period);
    components.insert(components.end(), {&memory.requests(), &memory.responses(), &memory.read_beats(),
        &memory.master(), segments[worker].get(), packets[worker].get(), readers[worker].get(),
        compactors[worker].get(), sinks[worker].get()});
  }
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  std::uint64_t cycles = 0;
  for (; cycles < maximum; ++cycles) {
    scheduler.step();
    bool done = true;
    for (std::size_t worker = 0; worker < 4; ++worker)
      done &= readers[worker]->done() && compactors[worker]->done() && memories[worker]->idle() &&
          (!odd_memories[worker] || odd_memories[worker]->idle()) &&
          segments[worker]->empty() && packets[worker]->empty() && sinks[worker]->finished();
    if (done) { ++cycles; break; }
  }
  check(cycles < maximum && backend.outstanding() == 0, "candidate diagnostic timed out");
  std::vector<Edge> observed, expected;
  for (const auto& edge : input.edges) expected.push_back({edge.source, edge.destination, edge.weight});
  std::uint64_t reads = 0, requests = 0, live = 0, output_packets = 0, beats = 0, submit_stalls = 0;
  std::cout << "PREFETCH_COMPACT {\"schema_version\":" << (full_burst ? 4 : dual ? 3 : 2)
      << ",\"cycles\":" << cycles << ",\"workers\":[";
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto& r = readers[worker]->stats();
    const auto& c = compactors[worker]->stats();
    const auto& axi = memories[worker]->master().stats();
    const auto odd = odd_memories[worker] ? odd_memories[worker]->master().stats() : AxiStats{};
    check(r.segments * 16 == slots[worker] && r.responses == r.requests &&
        r.beats * 64 == r.bytes && axi.requests_accepted + odd.requests_accepted == r.requests &&
        axi.requests_completed + odd.requests_completed == r.requests &&
        axi.beats_completed + odd.beats_completed == r.beats &&
        r.max_parents <= (dual ? 32U : 16U) && r.max_parents_per_port[0] <= 16 &&
        r.max_parents_per_port[1] <= 16 && (!dual || r.max_parents_per_port[1] > 0) &&
        r.max_bank_lines <= 256 && r.max_pipeline <= 2 &&
        c.input_segments == r.segments && c.live_edges + c.input_dummy == slots[worker] &&
        c.packets == sinks[worker]->packets && c.live_edges == sinks[worker]->edges.size() &&
        c.output_dummy == sinks[worker]->dummy && c.packets * 8 == c.live_edges + c.output_dummy &&
        c.max_lanes <= 32 && c.max_pipeline <= 2 && segments[worker]->stats().max_occupancy <= 16 &&
        packets[worker]->stats().max_occupancy <= 32, "candidate finite/conservation gate failed");
    check(!full_burst || (r.short_pma_requests <= 4 && r.pma_requests <= r.requests),
        "full-burst parent fragmentation gate failed");
    reads += r.bytes; requests += r.requests; live += c.live_edges; output_packets += c.packets;
    beats += r.beats; submit_stalls += axi.backend_submit_stalls + odd.backend_submit_stalls;
    observed.insert(observed.end(), sinks[worker]->edges.begin(), sinks[worker]->edges.end());
    if (worker) std::cout << ',';
    std::cout << "{\"worker\":" << worker << ",\"sink_done\":" << sinks[worker]->end
        << ",\"read_bytes\":" << r.bytes << ",\"requests\":" << r.requests
        << ",\"physical_slots\":" << slots[worker] << ",\"live_edges\":" << c.live_edges
        << ",\"packets\":" << c.packets << ",\"input_dummy\":" << c.input_dummy
        << ",\"output_dummy\":" << c.output_dummy << ",\"max_parents\":" << r.max_parents
        << ",\"max_bank_lines\":" << r.max_bank_lines << ",\"max_lanes\":" << c.max_lanes
        << ",\"read_beats\":" << r.beats << ",\"backend_submit_stalls\":"
        << axi.backend_submit_stalls + odd.backend_submit_stalls
        << ",\"selector_wait\":" << r.selector_wait
        << ",\"reader_pipeline_peak\":" << r.max_pipeline
        << ",\"publisher_pipeline_peak\":" << c.max_pipeline
        << ",\"reader_output_stalls\":" << r.output_stalls
        << ",\"publisher_output_stalls\":" << c.output_stalls;
    if (dual) std::cout << ",\"parents_per_port\":[" << r.max_parents_per_port[0] << ','
        << r.max_parents_per_port[1] << ']';
    if (full_burst) std::cout << ",\"pma_requests\":" << r.pma_requests
        << ",\"short_pma_requests\":" << r.short_pma_requests;
    std::cout << '}';
  }
  std::sort(observed.begin(), observed.end()); std::sort(expected.begin(), expected.end());
  check(observed == expected && live == input.edges.size(), "candidate differs from independent weighted CSR");
  const auto traffic = backend.traffic_stats();
  check(traffic.reads.bytes == reads && traffic.writes.bytes == 0, "candidate physical traffic mismatch");
  const auto* arbitration = backend.arbitration_stats();
  check(arbitration && backend.stats().accepted == beats && arbitration->unique_intents == beats &&
      arbitration->grants == beats && arbitration->consumed_grants == beats &&
      arbitration->request_waits == submit_stalls, "candidate arbitration ledger mismatch");
  std::cout << "],\"read_bytes\":" << reads << ",\"requests\":" << requests
      << ",\"live_edges\":" << live << ",\"packets\":" << output_packets
      << ",\"transport\":{\"accepted_beats\":" << backend.stats().accepted
      << ",\"intents\":" << arbitration->unique_intents << ",\"grants\":" << arbitration->grants
      << ",\"consumed_grants\":" << arbitration->consumed_grants
      << ",\"request_waits\":" << arbitration->request_waits
      << ",\"contended_cycles\":" << arbitration->contended_cycles
      << ",\"capacity_blocked_cycles\":" << arbitration->capacity_blocked_cycles
      << ",\"max_contenders\":" << arbitration->max_contenders << '}';
  if (dual) std::cout << ",\"physical_masters\":8,\"masters_per_frontend\":2";
  if (full_burst) {
    if (!dual) std::cout << ",\"physical_masters\":4,\"masters_per_frontend\":1";
    std::cout << ",\"refill_policy\":\"full-burst\"";
  }
  std::cout << ",\"passed\":true}\n";
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
}
}  // namespace

int main(int argc, char** argv) {
  try {
    check(argc == 6 || argc == 7,
        "usage: prefetch_compact INPUT LATENCY REVERSE MAX_CYCLES SINK_PERIOD "
        "[dual-port|full-burst|dual-port-full-burst]");
    const auto latency = routed_regraph_round_test::number(argv[2]);
    const auto reverse = routed_regraph_round_test::number(argv[3]);
    const auto maximum = routed_regraph_round_test::number(argv[4]);
    const auto period = routed_regraph_round_test::number(argv[5]);
    check(latency > 0 && reverse <= 1 && maximum > 0 && period > 0, "invalid candidate bound");
    const auto mode = argc == 7 ? std::string(argv[6]) : std::string{};
    check(mode.empty() || mode == "dual-port" || mode == "full-burst" || mode == "dual-port-full-burst",
        "unknown candidate reader topology/policy");
    run(original_regraph_sssp_real_test::Input::load(argv[1]), latency, reverse, maximum, period,
        mode == "dual-port" || mode == "dual-port-full-burst",
        mode == "full-burst" || mode == "dual-port-full-burst");
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
