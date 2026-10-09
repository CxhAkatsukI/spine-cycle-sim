#include <iostream>

#include "verification.hpp"

namespace mt = original_regraph_mixed_test;

int main(int argc, char** argv) {
  try {
    mt::require(argc == 8, "usage: mixed INPUT OUTPUT STATE_PARENTS LATENCY REVERSE MAX_CYCLES ALLOW_PADDING");
    const auto input = mt::Input::load(argv[1], std::stoul(argv[7]) != 0);
    const auto parents = std::stoul(argv[3]);
    const auto latency = std::stoull(argv[4]), maximum = std::stoull(argv[6]);
    mt::Wiring model(input, parents, latency, std::stoul(argv[5]) != 0);
    model.begin();
    std::uint64_t cycles = 0, checked = 0, little_checked = 0, big_before_little_finished = 0;
    std::vector<bool> seen(input.published_vertices / 16);
    for (; cycles < maximum; ++cycles) {
      const auto pops = model.indexed->stats().pops;
      const auto* front = model.indexed->front();
      const auto packet = front ? std::optional<mt::rg::PropertyWrite>(*front) : std::nullopt;
      model.memory.scheduler.step();
      if (model.indexed->stats().pops != pops) {
        mt::require(packet && model.indexed->stats().pops == pops + 1, "mixed observer lost consumed indexed packet");
        if (!packet->end) {
          mt::require(packet->index < seen.size() && !seen[packet->index], "mixed duplicate/out-of-range write index");
          if (packet->index < input.dense * 4096) little_checked += 16;
          else if (little_checked < input.dense * 65536) ++big_before_little_finished;
          seen[packet->index] = true;
          for (unsigned word = 0; word < 16; ++word) {
            mt::require(packet->data[word] == input.sums[packet->index * 16 + word], "mixed pre-Apply sum differs from CSR oracle");
            ++checked;
          }
        }
      }
      model.advance(cycles + 1);
      if (model.finished()) { ++cycles; break; }
      if ((cycles + 1) % 1000000 == 0) std::cout << "MIXED_PROGRESS cycles=" << cycles + 1 << " checked=" << checked << std::endl;
    }
    mt::require(model.finished() && checked == input.published_vertices &&
        std::all_of(seen.begin(), seen.end(), [](auto value) { return value; }), "mixed whole iteration timed out or lost indexed data");
    const auto ledger = mt::verify(model, argv[2]);
    const auto traffic = model.memory.backend->traffic_stats();
    std::cout << "MIXED_EXECUTION {\"kind\":\"original_mixed_graph_iteration_padded_control\",\"passed\":true,\"iterations\":1"
        << ",\"vertices\":" << input.vertices << ",\"logical_edges\":" << input.logical_edges
        << ",\"aligned_vertices\":" << input.aligned_vertices << ",\"published_vertices\":" << input.published_vertices
        << ",\"allocation_vertices\":" << input.allocation_vertices << ",\"extra_padding_vertices\":" << input.allocation_vertices - input.aligned_vertices
        << ",\"original_host_capacity_pass\":" << (input.published_vertices <= input.aligned_vertices ? "true" : "false")
        << ",\"little\":11,\"big\":3,\"dense\":" << input.dense << ",\"sparse\":" << input.sparse
        << ",\"cycles\":" << cycles << ",\"clock_mhz\":210,\"argument\":0,\"memory_latency\":" << latency
        << ",\"state_parent_credits\":" << parents << ",\"physical_edges\":" << input.physical_edges
        << ",\"dummy_edges\":" << ledger.dummy << ",\"checked_sum_words\":" << checked
        << ",\"checked_replica_words\":" << input.allocation_vertices * 14ull << ",\"edge_read_bytes\":" << ledger.edge_bytes
        << ",\"little_source_bytes\":" << ledger.little_source_bytes << ",\"big_source_bytes\":" << ledger.big_source_bytes
        << ",\"big_logical_requests\":" << ledger.requests << ",\"big_cache_hits\":" << ledger.hits << ",\"big_reads\":" << ledger.reads
        << ",\"degree_read_bytes\":" << input.published_vertices * 4ull << ",\"read_bytes\":" << traffic.reads.bytes
        << ",\"write_bytes\":" << traffic.writes.bytes << ",\"big_before_little_finished\":" << big_before_little_finished
        << ",\"queues_and_requests_conserved\":true,\"paths\":[";
    bool comma = false;
    const auto emit = [&](const auto& paths, unsigned base) {
      for (unsigned index = 0; index < paths.size(); ++index) {
        if (comma) std::cout << ',';
        comma = true; const auto& path = paths[index];
        std::cout << "{\"kernel\":" << base + index << ",\"starts\":[";
        for (unsigned task = 0; task < path.starts.size(); ++task) { if (task) std::cout << ','; std::cout << path.starts[task]; }
        std::cout << "],\"completions\":[";
        for (unsigned task = 0; task < path.completions.size(); ++task) { if (task) std::cout << ','; std::cout << path.completions[task]; }
        std::cout << "]}";
      }
    };
    emit(model.little, 0); emit(model.big, 11); std::cout << "]}\n"; return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
