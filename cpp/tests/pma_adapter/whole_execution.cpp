#include <iostream>

#include "verification.hpp"

namespace pt = pma_adapter_test;

int main(int argc, char** argv) {
  try {
    pt::wt::require(argc == 7, "usage: pma_r_execution INPUT_DIR OUTPUT_DIR STATE_PARENTS LATENCY REVERSE MAX_CYCLES");
    const pt::ac::Input input(argv[1]);
    const auto parents = std::stoul(argv[3]);
    const auto latency = std::stoull(argv[4]);
    pt::PmaWiring model(pt::PmaSource(input), parents, latency, std::stoul(argv[5]) != 0, 16);
    model.initialize(); model.begin();
    const auto observation = pt::execute(model, std::stoull(argv[6]));
    const auto cycles = observation.cycles, checked = observation.checked;
    pt::wt::require(std::filesystem::is_directory(argv[2]), "PMA/R capture directory missing");
    pt::capture_state(model, argv[2]);
    std::uint64_t valid = 0, dummy = 0, physical = 0, rows = 0, row_bytes = 0, pma_bytes = 0;
    std::uint64_t sources = 0, requests = 0, acknowledgements = 0, ends = 0, stalls = 0;
    std::array<std::uint64_t, 4> routes{};
    for (const auto& path : model.paths) {
      const auto& p = path.components; const auto& c = p.reader->counters();
      valid += p.gather->counters().valid_updates; dummy += p.gather->counters().dummy_updates;
      physical += c.physical_edges; rows += c.row_word_reads; row_bytes += c.row_bus_bytes; pma_bytes += c.pma_bus_bytes;
      sources += p.source->counters().read_bytes; requests += c.parent_requests; acknowledgements += c.acknowledgements;
      ends += p.source->counters().partition_terminators; stalls += c.output_stalls;
      for (unsigned route = 0; route < 4; ++route) routes[route] += c.segment_reads[route];
      pt::wt::require(c.tasks == input.graph.partitions && c.final_bursts == c.tasks && c.parent_requests == c.acknowledgements &&
          c.parent_requests == p.edge_port.master->stats().requests_accepted &&
          c.physical_edges == c.valid_edges + c.dummy_edges && path.starts.size() == input.graph.partitions &&
          path.completions.size() == input.graph.partitions && p.source->counters().rounds == p.source->counters().acknowledgements,
          "PMA/R task/request/reader conservation mismatch");
    }
    const auto degree = input.graph.published_vertices * 4ull, writes = degree * 4;
    const auto traffic = model.memory.backend->traffic_stats();
    pt::wt::require(valid == input.graph.logical_edges && valid + dummy == physical && pma_bytes == physical * 4 &&
        rows == (input.graph.vertices + 1ull) * input.tasks.size() && row_bytes == rows * 64 &&
        traffic.reads.bytes == row_bytes + pma_bytes + sources + degree && traffic.writes.bytes == writes &&
        ends == input.graph.partitions * 4 && model.writer->counters().acknowledgements == input.graph.published_vertices / 16 * 4 &&
        model.apply->counters().degree_responses == input.graph.published_vertices / 16, "PMA/R complete memory/traversal ledger mismatch");
    std::cout << "PMA_R_EXECUTION {\"kind\":\"schedule_informed_finite_PMA_original_A4_iteration\",\"passed\":true,\"iterations\":1,\"argument\":0,\"cycles\":" << cycles
              << ",\"clock_mhz\":210,\"little\":4,\"big\":0,\"memory_latency\":" << latency << ",\"state_parent_credits\":" << parents
              << ",\"input_parent_credits\":16,\"outstanding_bursts\":16"
              << ",\"checked_sum_words\":" << checked << ",\"checked_replica_words\":" << input.graph.aligned_vertices * 4ull
              << ",\"logical_edges\":" << valid << ",\"physical_edges\":" << physical << ",\"dummy_edges\":" << dummy
              << ",\"row_word_reads\":" << rows << ",\"row_bus_bytes\":" << row_bytes << ",\"pma_bus_bytes\":" << pma_bytes
              << ",\"source_read_bytes\":" << sources << ",\"degree_read_bytes\":" << degree << ",\"property_write_bytes\":" << writes
              << ",\"read_bytes\":" << traffic.reads.bytes << ",\"write_bytes\":" << traffic.writes.bytes
              << ",\"input_requests\":" << requests << ",\"input_acknowledgements\":" << acknowledgements << ",\"input_output_stalls\":" << stalls
              << ",\"overlapped_task_starts\":" << model.overlapped_task_starts << ",\"contended_channel_cycles\":" << model.memory.backend->arbitration_stats()->contended_cycles
              << ",\"segment_reads\":[" << routes[0] << ',' << routes[1] << ',' << routes[2] << ',' << routes[3]
              << "],\"queues_and_requests_conserved\":true,\"timing_calibrated_to_FPGA\":false";
    const pt::pa::Timing timing;
    std::cout << ",\"timing\":{\"minimum_read_cycles\":" << timing.minimum_read_cycles
              << ",\"segment_issue_interval\":" << timing.segment_issue_interval << ",\"row_decode_cycles\":" << timing.row_decode_cycles
              << ",\"source_restart_cycles\":" << timing.source_restart_cycles << ",\"output_latency\":" << timing.output_latency
              << ",\"segment_capacity\":" << timing.segment_capacity << "},\"paths\":[";
    for (unsigned index = 0; index < 4; ++index) {
      const auto& path = model.paths[index];
      pt::wt::require(observation.reader_finishes[index].size() == path.starts.size() &&
          observation.compute_starts[index].size() == path.starts.size() &&
          observation.frontend_finishes[index].size() == path.starts.size(), "PMA/R stage-window trace incomplete");
      if (index) std::cout << ',';
      std::cout << "{\"kernel\":" << index;
      for (const auto& field : std::array<std::pair<const char*, const std::vector<std::uint64_t>*>, 5>{{
          {"starts", &path.starts}, {"reader_finishes", &observation.reader_finishes[index]},
          {"compute_starts", &observation.compute_starts[index]}, {"frontend_finishes", &observation.frontend_finishes[index]},
          {"completions", &path.completions}}}) {
        std::cout << ",\"" << field.first << "\":[";
        for (unsigned task = 0; task < field.second->size(); ++task) {
          if (task) std::cout << ',';
          std::cout << (*field.second)[task];
        }
        std::cout << ']';
      }
      std::cout << '}';
    }
    std::cout << "],\"publication_finishes\":[";
    pt::wt::require(observation.publication_finishes.size() == input.graph.partitions, "PMA/R publication trace incomplete");
    for (unsigned part = 0; part < observation.publication_finishes.size(); ++part) {
      if (part) std::cout << ',';
      std::cout << observation.publication_finishes[part];
    }
    std::cout << "]}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
