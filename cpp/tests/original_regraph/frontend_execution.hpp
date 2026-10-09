#pragma once

#include <iostream>

#include "frontend_wiring.hpp"

namespace original_regraph_frontend_test {

struct Observation {
  std::uint64_t cycles{};
  std::uint64_t edge_bytes{};
  std::uint64_t source_bytes{};
  std::uint64_t normal_requests{};
  std::uint64_t source_loaded{};
  std::uint64_t source_discarded{};
  std::uint64_t scatter_stalls{};
  std::uint64_t edge_stalls{};
  std::uint64_t source_response_stalls{};
  std::uint64_t axi_stalls{};
  std::uint64_t axi_beats{};
  std::uint64_t checked_words{};
  std::uint64_t first_merged{};
  std::uint64_t last_scatter_done{};
  std::vector<std::vector<std::uint32_t>> request_rounds;
  bool completed{};
  bool operator==(const Observation&) const = default;
};

inline Observation execute(Wiring& network, const std::vector<std::vector<rg::EdgeBurst>>& edges) {
  network.begin(edges);
  Observation observation;
  std::vector<std::size_t> received(edges.size(), 0);
  std::vector<bool> completed(edges.size(), false);
  std::vector<std::uint32_t> sums(rg::kLittleVertices, 0);
  for (const auto& pipeline : edges) {
    for (const auto& burst : pipeline) {
      for (const auto update : oracle(burst, network.options.destination_offset)) {
        if (!(update.destination & rg::kDummyDestination)) sums[update.destination] += update.value;
      }
    }
  }
  for (std::uint64_t cycle = 0; cycle < network.options.max_cycles; ++cycle) {
    if (cycle >= network.options.sink_start && cycle % network.options.sink_interval == 0) {
      if (network.merged_output && !network.merged_output->empty()) {
        rg::PropertyLine line;
        require(network.merged_output->try_pop(line), "merged consumer ownership");
        if (!observation.first_merged) observation.first_merged = cycle + 1;
        for (const auto word : line) {
          require(observation.checked_words < sums.size() && sums[observation.checked_words] == word,
                  "memory/frontend/Gather composition differs from per-edge sum");
          ++observation.checked_words;
        }
      } else if (!network.merged_output) {
        for (std::size_t index = 0; index < network.paths.size(); ++index) {
          auto* queue = network.paths[index].updates;
          if (queue->empty()) continue;
          rg::UpdateBurst update;
          require(queue->try_pop(update), "update consumer ownership");
          require(received[index] < edges[index].size(), "excess Scatter output");
          const auto expected = oracle(edges[index][received[index]++], network.options.destination_offset);
          for (unsigned lane = 0; lane < 8; ++lane) {
            require(update[lane].destination == expected[lane].destination &&
                    update[lane].value == expected[lane].value, "Scatter differs from source oracle");
          }
          observation.checked_words += 8;
        }
      }
    }
    network.scheduler.step();
    for (std::size_t index = 0; index < network.paths.size(); ++index) {
      if (!completed[index] && network.paths[index].scatter->finished()) {
        completed[index] = true;
        observation.last_scatter_done = cycle + 1;
      }
    }
    if (network.drained()) { observation.completed = true; observation.cycles = cycle + 1; break; }
  }
  if (!observation.completed) observation.cycles = network.options.max_cycles;
  for (std::size_t index = 0; index < network.paths.size(); ++index) {
    const auto& path = network.paths[index];
    const auto& scatter = path.scatter->counters();
    const auto& source = path.source->counters();
    observation.edge_bytes += path.reader->counters().read_bytes;
    observation.source_bytes += source.read_bytes;
    observation.normal_requests += source.rounds;
    observation.source_loaded += scatter.source_lines_loaded;
    observation.source_discarded += scatter.source_lines_discarded;
    observation.request_rounds.emplace_back();
    for (const auto request : path.scatter->request_trace()) {
      if (!request.end) observation.request_rounds.back().push_back(request.round);
    }
    observation.scatter_stalls += path.scatter->pipeline().output_stalls;
    observation.edge_stalls += path.reader->pipeline().output_stalls;
    observation.source_response_stalls += source.response_stalls;
    for (const auto* master : {path.edge_port.master, path.source_port.master}) {
      observation.axi_stalls += master->stats().backend_submit_stalls +
          master->stats().read_beat_queue_stalls + master->stats().read_reorder_stalls;
      observation.axi_beats += master->stats().beats_completed;
      require(master->stats().max_outstanding_bursts <= network.options.outstanding,
              "AXI outstanding budget exceeded");
      if (observation.completed) {
        require(master->stats().requests_accepted == master->stats().requests_completed &&
                master->stats().beats_issued == master->stats().beats_completed,
                "AXI request/beat conservation failed");
      }
    }
    if (observation.completed) {
      require(path.reader->counters().read_bytes == edges[index].size() * 64 &&
              path.reader->counters().acknowledgements == 1, "edge memory extent/ack mismatch");
      require(source.rounds == source.acknowledgements && source.partition_terminators == 1 &&
              source.response_lines == source.rounds * rg::kSourceWindowLines &&
              source.response_lines == scatter.source_lines_loaded + scatter.source_lines_discarded &&
              source.rounds == scatter.source_round_requests && scatter.end_requests == 1 &&
              scatter.end_responses == 1 && scatter.bursts == edges[index].size(),
              "source protocol/Scatter conservation failed");
      std::vector<std::uint32_t> expected_rounds{0};
      for (const auto& burst : edges[index]) {
        const auto round = (burst[0].source & 0x7fffffffu) / rg::kSourceWindowVertices;
        for (const auto needed : {round, round + 1}) {
          if (needed > expected_rounds.back()) expected_rounds.push_back(needed);
        }
      }
      require(source.rounds == expected_rounds.size() &&
              path.scatter->request_trace().size() == source.rounds + 1 &&
              path.scatter->request_trace().back().end && scatter.trace_dropped == 0,
              "source request trace incomplete");
      require(path.scatter->request_trace().back().round == expected_rounds.back(),
              "source termination round mismatch");
      for (std::size_t round = 0; round < source.rounds; ++round) {
        require(path.scatter->request_trace()[round] == rg::SourceRequest{expected_rounds[round], false},
                "source request sequence mismatch");
      }
    }
  }
  if (observation.completed) {
    require(network.backend->traffic_stats().reads.bytes == observation.edge_bytes + observation.source_bytes &&
            network.backend->traffic_stats().writes.bytes == 0 &&
            network.backend->stats().accepted == observation.axi_beats,
            "physical memory traffic/beat conservation failed");
    if (network.options.gather) require(observation.checked_words == rg::kLittleVertices, "partial merged output");
  }
  return observation;
}

inline Observation run(const char* id, const std::vector<unsigned>& rounds, Options options = {}) {
  Wiring wiring(options);
  std::vector<std::vector<rg::EdgeBurst>> edges;
  for (std::size_t index = 0; index < options.little; ++index) edges.push_back(fixture(rounds, index));
  const auto row = execute(wiring, edges);
  std::cout << "FRONTEND_CASE {\"id\":\"" << id << "\",\"completed\":" << (row.completed ? "true" : "false")
            << ",\"cycles\":" << row.cycles << ",\"edge_bytes\":" << row.edge_bytes
            << ",\"source_bytes\":" << row.source_bytes << ",\"normal_requests\":" << row.normal_requests
            << ",\"source_loaded\":" << row.source_loaded << ",\"source_discarded\":" << row.source_discarded
            << ",\"scatter_stalls\":" << row.scatter_stalls << ",\"edge_stalls\":" << row.edge_stalls
            << ",\"source_response_stalls\":" << row.source_response_stalls << ",\"axi_stalls\":" << row.axi_stalls
            << ",\"axi_beats\":" << row.axi_beats << ",\"checked_words\":" << row.checked_words
            << ",\"first_merged\":" << row.first_merged << ",\"last_scatter_done\":" << row.last_scatter_done
            << ",\"little\":" << options.little << ",\"fifo_depth\":" << options.fifo_depth
            << ",\"memory_latency\":" << options.memory_latency << ",\"outstanding\":" << options.outstanding
            << ",\"gather\":" << (options.gather ? "true" : "false") << ",\"request_rounds\":[";
  for (std::size_t pipeline = 0; pipeline < row.request_rounds.size(); ++pipeline) {
    if (pipeline) std::cout << ',';
    std::cout << '[';
    for (std::size_t index = 0; index < row.request_rounds[pipeline].size(); ++index) {
      if (index) std::cout << ',';
      std::cout << row.request_rounds[pipeline][index];
    }
    std::cout << ']';
  }
  std::cout << "]}\n";
  return row;
}

}  // namespace original_regraph_frontend_test
