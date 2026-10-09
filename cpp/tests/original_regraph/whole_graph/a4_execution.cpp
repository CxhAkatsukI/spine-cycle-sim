#include <iostream>

#include "wiring.hpp"

namespace wt = original_regraph_whole_test;

int main(int argc, char** argv) {
  try {
    wt::require(argc == 7 || argc == 8, "usage: a4_execution INPUT_DIR OUTPUT_DIR STATE_PARENTS LATENCY REVERSE MAX_CYCLES [INPUT_PARENTS]");
    const auto input = wt::Input::load(argv[1]);
    const auto state_parents = std::stoul(argv[3]);
    const auto latency = std::stoull(argv[4]), maximum = std::stoull(argv[6]);
    const auto input_parents = argc == 8 ? std::stoul(argv[7]) : 2;
    wt::Wiring model(input, state_parents, latency, std::stoul(argv[5]) != 0, input_parents);
    model.initialize();
    model.begin();
    std::uint64_t cycles = 0, checked_sum_words = 0;
    for (; cycles < maximum; ++cycles) {
      const auto pops = model.merged->stats().pops;
      const auto* front = model.merged->front();
      const auto packet = front ? std::optional<wt::rg::PropertyLine>(*front) : std::nullopt;
      model.memory.scheduler.step();
      if (model.merged->stats().pops != pops) {
        wt::require(packet.has_value() && model.merged->stats().pops == pops + 1,
                    "merged output monitoring missed a consumed line");
        for (const auto value : *packet) {
          wt::require(checked_sum_words < input.published_vertices && value == input.sums[checked_sum_words],
                      "complete pre-Apply sum differs from independent CSR oracle");
          ++checked_sum_words;
        }
      }
      model.advance(cycles + 1);
      if (model.finished()) { ++cycles; break; }
      if ((cycles + 1) % 1000000 == 0) {
        std::cout << "A4_PROGRESS cycles=" << cycles + 1 << " checked_sum_words=" << checked_sum_words << std::endl;
      }
    }
    wt::require(model.finished() && checked_sum_words == input.published_vertices,
                "complete A4 graph execution timed out or lost merged output");
    const auto directory = std::filesystem::path(argv[2]);
    wt::require(std::filesystem::is_directory(directory), "output directory missing");
    for (unsigned replica = 0; replica < 4; ++replica) {
      const auto payload = model.memory.backend->inspect_payload(replica * 2 + 1, wt::kOutputAddress,
                                                                  input.aligned_vertices * 4ull + 64);
      std::vector<std::uint32_t> actual(input.aligned_vertices);
      for (std::size_t vertex = 0; vertex < input.aligned_vertices; ++vertex) {
        std::uint32_t value = 0;
        for (unsigned byte = 0; byte < 4; ++byte) value |= std::uint32_t{payload[vertex * 4 + byte]} << (byte * 8);
        wt::require(value == input.expected[vertex], "full A4 state replica differs from independent CSR PR oracle");
        actual[vertex] = value;
      }
      wt::require(std::all_of(payload.end() - 64, payload.end(), [](auto byte) { return byte == 0xa5; }),
                  "A4 property writer changed its allocation guard");
      wt::write_words(directory / ("final_replica" + std::to_string(replica) + ".u32le"), actual);
    }
    std::uint64_t edge_bytes = 0, source_bytes = 0, valid = 0, dummy = 0, terminators = 0;
    for (const auto& path : model.paths) {
      const auto& p = path.components;
      edge_bytes += p.reader->counters().read_bytes; source_bytes += p.source->counters().read_bytes;
      valid += p.gather->counters().valid_updates; dummy += p.gather->counters().dummy_updates;
      terminators += p.source->counters().partition_terminators;
      wt::require(path.starts.size() == input.partitions && path.completions.size() == input.partitions &&
                  p.edge_port.master->stats().requests_accepted == input.partitions &&
                  p.source->counters().rounds == p.source->counters().acknowledgements,
                  "A4 partition/request conservation failed");
    }
    const auto traffic = model.memory.backend->traffic_stats();
    const auto degree_bytes = input.published_vertices * 4ull;
    const auto write_bytes = degree_bytes * 4;
    wt::require(valid == input.logical_edges && dummy == input.dummy_edges &&
        edge_bytes == input.physical_edges * 8 && traffic.reads.bytes == edge_bytes + source_bytes + degree_bytes &&
        traffic.writes.bytes == write_bytes && terminators == input.partitions * 4 &&
        model.writer->counters().acknowledgements == input.published_vertices / 16 * 4 &&
        model.apply->counters().degree_responses == input.published_vertices / 16,
        "A4 complete traversal or memory/writeback ledger mismatch");
    std::cout << "A4_EXECUTION {\"kind\":\"original_a4_graph_iteration\",\"passed\":true,\"iterations\":1,"
              << "\"vertices\":" << input.vertices << ",\"aligned_vertices\":" << input.aligned_vertices
              << ",\"published_vertices\":" << input.published_vertices << ",\"logical_edges\":" << valid
              << ",\"physical_edges\":" << input.physical_edges << ",\"dummy_edges\":" << dummy
              << ",\"partitions\":" << input.partitions << ",\"cycles\":" << cycles
              << ",\"clock_mhz\":210,\"little\":4,\"big\":0,\"argument\":0,\"memory_latency\":" << latency
              << ",\"state_parent_credits\":" << state_parents << ",\"outstanding_bursts\":16"
              << ",\"checked_sum_words\":" << checked_sum_words << ",\"checked_replica_words\":" << input.aligned_vertices * 4ull
              << ",\"edge_read_bytes\":" << edge_bytes << ",\"source_read_bytes\":" << source_bytes
              << ",\"degree_read_bytes\":" << degree_bytes << ",\"property_write_bytes\":" << write_bytes
              << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
              << ",\"overlapped_task_starts\":" << model.overlapped_task_starts
              << ",\"degree_peak_outstanding\":" << model.degree.master->stats().max_outstanding_bursts
              << ",\"degree_request_stalls\":" << model.degree.master->stats().request_queue_stalls
              << ",\"writer_peak_outstanding\":" << model.writers[0].master->stats().max_outstanding_bursts
              << ",\"contended_channel_cycles\":" << model.memory.backend->arbitration_stats()->contended_cycles
              << ",\"queues_and_requests_conserved\":true,\"paths\":[";
    for (unsigned index = 0; index < model.paths.size(); ++index) {
      if (index) std::cout << ',';
      const auto& path = model.paths[index];
      std::cout << "{\"kernel\":" << index << ",\"starts\":[";
      for (unsigned task = 0; task < path.starts.size(); ++task) { if (task) std::cout << ','; std::cout << path.starts[task]; }
      std::cout << "],\"completions\":[";
      for (unsigned task = 0; task < path.completions.size(); ++task) { if (task) std::cout << ','; std::cout << path.completions[task]; }
      std::cout << "]}";
    }
    std::cout << ']';
    if (argc == 8) std::cout << ",\"input_parent_credits\":" << input_parents;
    std::cout << "}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
