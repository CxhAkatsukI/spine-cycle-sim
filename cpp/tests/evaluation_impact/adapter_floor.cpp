#include <iostream>

#include "k4_config.hpp"
#include "../original_regraph/sssp/real_input.hpp"
#include "../routed_regraph/round_execution.hpp"

namespace {
using namespace spine::sim;
using original_regraph_sssp_real_test::require;

// A diagnostic consumer, not ReGraph: one physical packet each cycle, no compute.
class Sink final : public Component {
public:
  Sink(ClockId clock, Fifo<ReGraphPmaPacket>& input, ReGraphPmaPartition partition)
      : Component("diagnostic-sink", clock), input_(input), partition_(partition) {}
  void evaluate(const CycleContext&) override {
    staged_.reset();
    ReGraphPmaPacket value;
    if (input_.try_pop(value)) staged_ = value;
  }
  void commit(const CycleContext& context) override {
    if (!staged_) return;
    require(!finished_, "packet after TLAST");
    ++packets;
    for (std::size_t lane = 0; lane < 8; ++lane) {
      const auto source = staged_->sources[lane], word = staged_->destinations[lane];
      require((source >> 31) == (word >> 31), "unpaired dummy flags");
      if (source >> 31) continue;
      const auto local = word & 0x7ffffU, weight = (word >> 19) & 0xfffU;
      require(source < partition_.vertices && local < partition_.destination_vertices && weight,
              "live packet outside weighted partition ABI");
      edges.push_back((std::uint64_t{source} << 32) |
          ((std::uint64_t{weight} << 19) | (local + partition_.destination_base)));
    }
    if (staged_->last) { finished_ = true; end = context.domain_cycle + 1; }
  }
  [[nodiscard]] bool finished() const noexcept { return finished_; }
  std::vector<std::uint64_t> edges;
  std::uint64_t packets{}, end{};
private:
  Fifo<ReGraphPmaPacket>& input_;
  ReGraphPmaPartition partition_;
  std::optional<ReGraphPmaPacket> staged_;
  bool finished_{};
};

void run(const original_regraph_sssp_real_test::Input& input,
         std::uint64_t latency, bool reverse, std::uint64_t maximum) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
  auto config = evaluation_impact::k4_configuration(evaluation_impact::control("bank_stream"));
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  const auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                                     GraSuPmaWordAbi::kWeightedFullWord);
  require(layout.partitions.size() == 4, "floor diagnostic requires this four-shard input");
  // Reuse the exact resident initializer/runtime map, but never register or run R.
  RoutedReGraphSystem resident(scheduler, clock, backend, layout, input.initial, config);
  const auto& plan = resident.runtime_plan();
  std::array<ReGraphPmaPartition, 4> partitions;
  std::array<std::unique_ptr<FixedAxiPort>, 4> memories;
  std::array<std::unique_ptr<Fifo<ReGraphPmaPacket>>, 4> outputs;
  std::array<std::unique_ptr<ReGraphPmaAdapter>, 4> adapters;
  std::array<std::unique_ptr<Sink>, 4> sinks;
  std::array<std::uint64_t, 4> ends{};
  std::vector<Component*> components{&backend};
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto& part = layout.partitions[worker];
    const auto row = find_grasu_regraph_runtime_region(plan, worker, "row");
    auto& p = partitions[worker];
    // Admission adds source-0 dummy reservations; the runtime plan owns that extent.
    p = {.vertices = layout.vertices, .slots = plan.shards[worker].pma_slot_count,
         .cache_segments_per_half = config.compute.cache_segments_per_half,
         .destination_base = part.destination_base, .destination_vertices = part.destination_vertices,
         .row_base = row.channel_offset_bytes, .row_channel = row.channel};
    for (std::size_t bank = 0; bank < 4; ++bank) {
      const auto region = find_grasu_regraph_runtime_region(plan, worker, "pma" + std::to_string(bank));
      p.pma_base[bank] = region.channel_offset_bytes;
      p.pma_channel[bank] = region.channel;
    }
    memories[worker] = std::make_unique<FixedAxiPort>("diagnostic-master" + std::to_string(worker), clock,
        FixedAxiPortConfig{.memory_channels = 32, .channel = 0,
            .initiator_id = 1000 + static_cast<std::uint32_t>(worker),
            .stream_read_beats = config.adapter.cross_row.bank_read_beats,
            .max_pending_requests = config.compute.max_pending_requests,
            .max_outstanding_bursts = config.compute.max_outstanding_bursts,
            .response_beats_per_cycle = config.compute.response_beats_per_cycle,
            .independent_read_write = config.independent_read_write}, backend);
    auto& memory = *memories[worker];
    outputs[worker] = std::make_unique<Fifo<ReGraphPmaPacket>>("diagnostic-edges", clock,
                                                            config.adapter_stream_depth);
    adapters[worker] = std::make_unique<ReGraphPmaAdapter>("diagnostic-adapter", clock,
                                                        config.adapter, memory, *outputs[worker]);
    sinks[worker] = std::make_unique<Sink>(clock, *outputs[worker], p);
    components.insert(components.end(), {&memory.requests(), &memory.responses(), &memory.read_beats(),
        &memory.master(), outputs[worker].get(), adapters[worker].get(), sinks[worker].get()});
  }
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto* component : components) scheduler.add_component(*component);
  for (std::size_t worker = 0; worker < 4; ++worker) adapters[worker]->start_partition(partitions[worker]);
  std::uint64_t cycles = 0;
  for (; cycles < maximum; ++cycles) {
    scheduler.step();
    bool done = true;
    for (std::size_t worker = 0; worker < 4; ++worker) {
      if (adapters[worker]->done() && !ends[worker]) ends[worker] = cycles + 1;
      done &= adapters[worker]->done() && memories[worker]->idle() &&
          outputs[worker]->empty() && sinks[worker]->finished();
    }
    if (done) { ++cycles; break; }
  }
  require(cycles < maximum && backend.outstanding() == 0, "adapter floor timeout or memory leak");
  std::vector<std::uint64_t> observed, expected;
  for (const auto& edge : input.edges)
    expected.push_back((std::uint64_t{edge.source} << 32) |
        ((std::uint64_t{edge.weight} << 19) | edge.destination));
  std::uint64_t reads = 0, requests = 0, live = 0;
  std::cout << "ADAPTER_FLOOR {\"cycles\":" << cycles << ",\"workers\":[";
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto& count = adapters[worker]->counters();
    const auto& axi = memories[worker]->master().stats();
    const auto bytes = (count.extent_reads + count.row_reads + count.segment_reads) * 64;
    const auto reqs = count.extent_reads + count.directory_requests + count.pma_requests;
    require(ends[worker] && count.output_stalls == 0 && sinks[worker]->packets == count.packets &&
        count.packets * 8 == partitions[worker].slots && count.live_edges == sinks[worker]->edges.size() &&
        count.live_edges + count.dummy_edges == count.packets * 8 &&
        count.segment_reads * 16 == partitions[worker].slots && count.responses == reqs &&
        axi.requests_accepted == reqs && axi.requests_completed == reqs &&
        axi.beats_completed * 64 == bytes &&
        count.max_pending_reads <= config.adapter.pending_read_capacity &&
        count.max_buffered_segments <= config.adapter.segment_buffer_capacity &&
        outputs[worker]->stats().max_occupancy <= config.adapter_stream_depth,
        "adapter floor packet/physical/finite-resource conservation failed");
    reads += bytes; requests += reqs; live += count.live_edges;
    observed.insert(observed.end(), sinks[worker]->edges.begin(), sinks[worker]->edges.end());
    if (worker) std::cout << ',';
    std::cout << "{\"worker\":" << worker << ",\"adapter_done\":" << ends[worker]
        << ",\"sink_done\":" << sinks[worker]->end << ",\"live_edges\":" << count.live_edges
        << ",\"packets\":" << count.packets << ",\"read_bytes\":" << bytes
        << ",\"requests\":" << reqs << ",\"output_stalls\":" << count.output_stalls << '}';
  }
  std::sort(observed.begin(), observed.end()); std::sort(expected.begin(), expected.end());
  require(observed == expected && live == input.edges.size(), "adapter floor differs from independent CSR");
  const auto traffic = backend.traffic_stats();
  require(traffic.reads.bytes == reads && traffic.writes.bytes == 0,
          "unregistered R fixture caused traffic, or reads/writes do not conserve");
  std::cout << "],\"read_bytes\":" << reads << ",\"requests\":" << requests
      << ",\"live_edges\":" << live << ",\"passed\":true}\n";
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
}
}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 5, "usage: adapter_floor INPUT LATENCY REVERSE MAX_CYCLES");
    const auto latency = routed_regraph_round_test::number(argv[2]);
    const auto reverse = routed_regraph_round_test::number(argv[3]);
    const auto maximum = routed_regraph_round_test::number(argv[4]);
    require(latency > 0 && reverse <= 1 && maximum > 0, "invalid floor bound");
    run(original_regraph_sssp_real_test::Input::load(argv[1]), latency, reverse, maximum);
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
