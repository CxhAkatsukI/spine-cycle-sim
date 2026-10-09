#pragma once

#include <iostream>

#include "big_frontend_wiring.hpp"

namespace original_regraph_big_frontend_test {
struct Observation {
  std::uint64_t cycles{}, logical_requests{}, reads{}, cache_hits{}, edge_bytes{}, source_bytes{};
  std::uint64_t capacity_stalls{}, response_stalls{}, scatter_stalls{}, fork_stalls{};
  std::vector<rg::CachelineRequest> requests;
  std::vector<rg::UpdateBurst> updates;
  std::vector<rg::CachelineResponse> responses;
};

inline Observation execute(Network& network, unsigned fixture_id) {
  const auto input = fixture(fixture_id);
  const auto before = network.source->counters();
  const auto before_scatter = network.scatter->counters();
  const auto scatter_stalls = network.scatter->pipeline().output_stalls;
  const auto fork_stalls = network.fork->output_stalls();
  const auto physical_before = network.memory.backend->traffic_stats().reads.bytes;
  const auto trace_start = network.sender->trace().size();
  network.begin(input);
  Observation result;
  for (std::uint64_t cycle = 0; cycle < 1000000; ++cycle) {
    if (cycle >= network.options.sink_start && cycle % network.options.sink_interval == 0 && !network.output->empty()) {
      rg::UpdateBurst value;
      require(network.output->try_pop(value), "Big sink ownership");
      result.updates.push_back(value);
    }
    const auto pops = network.responses->stats().pops;
    const auto head = network.responses->front() ? std::optional{*network.responses->front()} : std::nullopt;
    network.memory.scheduler.step();
    if (network.responses->stats().pops != pops) {
      require(head.has_value() && network.responses->stats().pops == pops + 1, "Big response observation scope");
      result.responses.push_back(*head);
    }
    if (network.drained()) { result.cycles = cycle + 1; break; }
  }
  require(result.cycles != 0, "Big memory/frontend cycle timeout");
  const auto expected = updates(input, network.options.destination_offset);
  require(result.updates.size() == expected.size(), "Big Scatter output extent");
  for (std::size_t burst = 0; burst < expected.size(); ++burst) for (unsigned lane = 0; lane < 8; ++lane) {
    require(result.updates[burst][lane].value == expected[burst][lane].value &&
            result.updates[burst][lane].destination == expected[burst][lane].destination,
            "Big Scatter differs from per-edge oracle");
  }
  result.requests = {network.sender->trace().begin() + trace_start, network.sender->trace().end()};
  require(result.requests == requests(input) && network.sender->trace_dropped() == 0, "Big generated request protocol mismatch");
  require(result.responses.size() == result.requests.size(), "Big observed response extent");
  const auto& current = network.source->counters();
  result.logical_requests = current.requests - before.requests;
  result.reads = current.reads - before.reads;
  result.cache_hits = current.cache_hits - before.cache_hits;
  result.source_bytes = current.read_bytes - before.read_bytes;
  result.edge_bytes = input.size() * 64;
  result.capacity_stalls = current.capacity_stalls - before.capacity_stalls;
  result.response_stalls = current.output_stalls - before.output_stalls;
  result.scatter_stalls = network.scatter->pipeline().output_stalls - scatter_stalls;
  result.fork_stalls = network.fork->output_stalls() - fork_stalls;
  std::uint64_t expected_reads = 0;
  std::optional<std::uint32_t> previous;
  for (const auto request : result.requests) {
    if (request.end) { previous.reset(); continue; }
    if (!previous || *previous != request.line) ++expected_reads;
    previous = request.line;
  }
  require(result.reads == expected_reads && result.logical_requests + 1 == result.requests.size() &&
          result.reads + result.cache_hits == result.logical_requests && result.source_bytes == result.reads * 64 &&
          current.responses - before.responses == result.logical_requests &&
          current.acknowledgements - before.acknowledgements == result.reads &&
          current.partition_ends - before.partition_ends == 1 && current.max_live <= network.options.live,
          "Big source request/cache/read/response conservation");
  const auto& scatter = network.scatter->counters();
  require(scatter.initial_lines - before_scatter.initial_lines == 8 &&
          scatter.lane_lines - before_scatter.lane_lines == result.logical_requests - 1 &&
          scatter.source_lookups - before_scatter.source_lookups == input.size() * 8,
          "Big lane/lookup conservation");
  require(network.memory.backend->traffic_stats().reads.bytes - physical_before == result.edge_bytes + result.source_bytes &&
          network.memory.backend->traffic_stats().writes.bytes == 0, "Big physical byte conservation");
  for (const auto* master : {network.edge_port.master, network.source_port.master}) {
    const auto& stats = master->stats();
    require(stats.requests_accepted == stats.requests_completed && stats.beats_issued == stats.beats_completed &&
            stats.max_outstanding_bursts <= network.options.outstanding, "Big AXI conservation/capacity");
  }
  return result;
}

inline void report(const char* id, const Observation& row) {
  std::cout << "BIG_FRONTEND {\"id\":\"" << id << "\",\"cycles\":" << row.cycles
      << ",\"logical_requests\":" << row.logical_requests << ",\"reads\":" << row.reads
      << ",\"cache_hits\":" << row.cache_hits << ",\"edge_bytes\":" << row.edge_bytes
      << ",\"source_bytes\":" << row.source_bytes << ",\"capacity_stalls\":" << row.capacity_stalls
      << ",\"response_stalls\":" << row.response_stalls << ",\"scatter_stalls\":" << row.scatter_stalls
      << ",\"fork_stalls\":" << row.fork_stalls << ",\"checked_tuples\":" << row.updates.size() * 8 << "}\n";
}
}  // namespace original_regraph_big_frontend_test
