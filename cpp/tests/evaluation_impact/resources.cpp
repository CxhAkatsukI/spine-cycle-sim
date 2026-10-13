#include <iostream>
#include <set>

#include "../original_regraph/whole_graph/compact_source.hpp"
#include "../original_regraph/whole_graph/compute_wiring.hpp"
#include "spine_sim/routed_regraph.hpp"

namespace wt = original_regraph_whole_test;
namespace rg = spine::sim::original_regraph;
using namespace spine::sim;

namespace {
template <typename Range>
void numbers(const Range& values) {
  bool first = true;
  std::cout << '[';
  for (auto value : values) {
    if (!first) std::cout << ',';
    std::cout << value;
    first = false;
  }
  std::cout << ']';
}

std::set<std::uint32_t> registrations(const MemoryBackend& backend) {
  std::set<std::uint32_t> result;
  for (const auto& [initiator, stats] : backend.traffic_stats_by_initiator()) {
    wt::require(!stats.reads.requests && !stats.writes.requests,
                "constructor audit unexpectedly executed memory requests");
    result.insert(initiator);
  }
  return result;
}

void a4() {
  wt::Input input;
  input.vertices = input.aligned_vertices = input.published_vertices = 65536;
  input.partitions = 1;
  wt::ComputeOptions options;
  options.udf = rg::Udf::kWeightedSssp;
  options.memory = {150, 32, 32};
  options.apply_timing = rg::kSsspSchedulePostReadTiming;
  options.sssp_response_anchored = true;
  // No begin/initialize: this audit counts constructed resources, not work.
  wt::ComputeWiring<wt::CompactSource, rg::SsspApply> model(
      wt::CompactSource(input, rg::Udf::kWeightedSssp), 2, 64, false, 2, options);
  std::set<const AxiMaster*> pointers;
  std::set<std::uint32_t> initiators;
  std::set<std::size_t> banks, source_banks;
  auto emit = [&](const char* role, unsigned index, const wt::MemoryLink& link) {
    const auto& c = link.master->config();
    wt::require(c.fixed_channel.has_value(), "A4 audit expected fixed-channel port");
    wt::require(pointers.insert(link.master).second && initiators.insert(c.initiator_id).second,
                "A4 endpoint unexpectedly shares a master");
    banks.insert(*c.fixed_channel);
    if (std::string_view(role) == "source") source_banks.insert(*c.fixed_channel);
    std::cout << "RESOURCE_PORT {\"role\":\"" << role << "\",\"index\":" << index
              << ",\"initiator\":" << c.initiator_id << ",\"channel\":" << *c.fixed_channel
              << ",\"parent_credits\":" << c.max_pending_requests
              << ",\"burst_credits\":" << c.max_outstanding_bursts
              << ",\"data_width_bytes\":" << c.data_width_bytes
              << ",\"request_fifo\":" << link.requests->depth()
              << ",\"response_fifo\":" << link.responses->depth()
              << ",\"independent_read_write\":" << std::boolalpha << c.independent_read_write << "}\n";
  };
  for (unsigned index = 0; index < model.paths.size(); ++index) {
    emit("edge", index, model.paths[index].components.edge_port);
    emit("source", index, model.paths[index].components.source_port);
  }
  emit("apply_read", 0, model.degree);
  for (unsigned index = 0; index < model.writers.size(); ++index) emit("write", index, model.writers[index]);
  wt::require(registrations(*model.memory.backend) == initiators && model.memory.drained(),
              "A4 resource list differs from actual backend registration");
  std::cout << "RESOURCE_A4 {\"distinct_masters\":" << pointers.size() << ",\"registered_ids\":";
  numbers(initiators);
  std::cout << ",\"physical_banks\":"; numbers(banks);
  std::cout << ",\"source_banks\":"; numbers(source_banks);
  std::cout << ",\"clock_period_fs\":" << model.memory.scheduler.clock(model.memory.clock).period_fs
            << ",\"constructor_only\":true}\n";
}

void k4(bool candidate) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, {32, 64, 1, 32, 32, true});
  RoutedReGraphConfig config;
  config.independent_read_write = true;
  config.adapter.empty_segment_exit_cycles = 0;
  config.adapter.row_line_reads = config.adapter.cross_row_pipeline = true;
  auto& cross = config.adapter.cross_row;
  cross.directory_cache_rows = candidate ? 1024 : 8;
  cross.packet_pipeline = cross.bank_stream = cross.bank_read_beats = candidate;
  if (candidate) {
    cross.bank_fifo_lines = 256;
    cross.reader_pipeline_capacity = 2;
    cross.block_drain_cycles = 2;
  }
  config.adapter_stream_depth = config.gather_stream_depth = config.mux_stream_depth = 32;
  config.compute.apply_request_window = 16;
  config.compute.vertex_state_base = config.compute.source_state_base = 0;
  constexpr std::uint32_t vertices = 3 * 65536 + 2;
  config.compute.source_state_buffer_stride = 4 * 65536 * 4ull;
  config.status_address = config.compute.source_state_buffer_stride;
  std::vector<GraSuEdge> edges;
  for (unsigned p = 0; p < 4; ++p) edges.push_back({0, p * 65536 + 1, 1, false});
  AlgorithmInitialState initial;
  initial.primary.assign(vertices, GraphAlgorithmPolicy::kSsspInfinity);
  initial.primary[0] = 0;
  initial.active_vertices = {0};
  auto layout = GraSuPartitionedPmaLayout::build(vertices, 65536, edges, {}, GraSuPmaWordAbi::kWeightedFullWord);
  RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), std::move(initial), config);
  const auto ids = registrations(backend);
  wt::require(ids.size() == 9 && backend.outstanding() == 0 && scheduler.event_count() == 0,
              "K4 constructor did not register nine idle masters");
  std::cout << "RESOURCE_K4 {\"arm\":\"" << (candidate ? "candidate" : "cross_row")
            << "\",\"registered_ids\":"; numbers(ids);
  std::cout << ",\"clock_period_fs\":" << scheduler.clock(clock).period_fs
            << ",\"declared_parent_credits\":" << config.compute.max_pending_requests
            << ",\"declared_burst_credits\":" << config.compute.max_outstanding_bursts
            << ",\"declared_apply_window\":" << config.compute.apply_request_window
            << ",\"declared_source_banks\":[23,24],\"declared_primary_bank\":30"
            << ",\"declared_graph_bank_budget\":23,\"declared_shared_capacity\":" << config.shared_master_capacity
            << ",\"declared_directory_rows\":" << cross.directory_cache_rows
            << ",\"declared_bank_fifo_lines\":" << (candidate ? cross.bank_fifo_lines : 0)
            << ",\"constructor_only\":true,\"regions\":[";
  bool first = true;
  for (const auto& region : system.runtime_plan().regions) {
    if (!first) std::cout << ',';
    first = false;
    std::cout << "{\"shard\":" << region.shard << ",\"name\":\"" << region.name
              << "\",\"channel\":" << region.channel << ",\"allocated_bytes\":" << region.allocated_bytes << '}';
  }
  std::cout << "]}\n";
}
}  // namespace

int main() {
  try {
    a4(); k4(false); k4(true);
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
