#include "routed_regraph_report.hpp"

#include <fstream>

namespace spine::sim::sst_adapter {
void write_routed_regraph_report(const std::string &path, const RoutedReGraphFixture &fixture,
                                const RoutedReGraphSystem &system, const SstMemoryBackend &backend,
                                std::uint64_t observed_cycles, const std::string &profile_id) {
  const auto state = system.encoded_state();
  std::uint64_t mismatches = 0;
  for (std::size_t v = 0; v < state.size(); ++v) {
    const auto expected = v < fixture.expected.size()
        ? (fixture.expected[v] == 0xffffffffU ? 0x7ffffffeU : fixture.expected[v]) : 0U;
    mismatches += state[v] != expected;
  }
  const bool replicas_equal = system.source_state(0, system.rounds().size() & 1U) == state &&
                              system.source_state(1, system.rounds().size() & 1U) == state;
  const auto c = system.counters();
  const auto expected_beats = c.extent_reads + c.row_reads + c.segment_reads + c.source_lines +
      c.apply_reads + c.apply_writes + c.source_writes + c.status_writes;
  std::uint64_t slots = 0, edges = 0;
  for (const auto &part : fixture.layout.partitions) {
    slots += part.segments.size() * 16;
    for (const auto &segment : part.segments)
      for (auto word : segment) edges += !(word & 0x80000000U);
  }
  const auto rounds = system.rounds().size(), padded = state.size();
  const bool closed = c.axi_requests == c.axi_completions && c.axi_beats == c.axi_completed_beats &&
      c.axi_beats == expected_beats && backend.accepted() == c.axi_beats && backend.outstanding() == 0 &&
      c.segment_reads * 16 == rounds * slots && c.live_edges == rounds * edges &&
      c.packets * 8 == c.live_edges + c.dummy_edges && c.source_lines == c.source_blocks * 256 &&
      c.gather_rows == rounds * padded / 2 && c.mux_rows == c.gather_rows &&
      c.apply_reads == rounds * padded / 16 && c.apply_writes == c.apply_reads &&
      c.source_writes == c.apply_reads * 2 && c.status_writes == rounds &&
      c.source_terminators == rounds * fixture.layout.partitions.size();
  const bool success = system.done() && !system.failed() && !mismatches && replicas_equal && closed &&
                       system.rounds().size() == fixture.expected_rounds;
  std::ofstream output(path);
  if (!output) throw std::invalid_argument("cannot write routed SST result");
  output << "{\"schema_version\":1,\"profile_id\":\"" << profile_id << "\","
      "\"boundary\":\"resident_compute_no_host_launch_gaps\","
      "\"evidence\":\"simulator_prediction_not_hardware_timing_admission\","
      "\"success\":" << (success ? "true" : "false") << ",\"done\":" << (system.done() ? "true" : "false")
      << ",\"failed\":" << (system.failed() ? "true" : "false") << ",\"mismatches\":" << mismatches
      << ",\"replicas_equal\":" << (replicas_equal ? "true" : "false")
      << ",\"ledger_closed\":" << (closed ? "true" : "false")
      << ",\"observed_cycles\":" << observed_cycles << ",\"expected_rounds\":" << fixture.expected_rounds
      << ",\"vertices\":" << fixture.layout.vertices << ",\"partitions\":" << fixture.layout.partitions.size()
      << ",\"pma_slots\":" << slots << ",\"live_edges_per_round\":" << edges
      << ",\"counters\":{";
  bool first = true;
  const auto field = [&](const char *name, std::uint64_t value) {
    if (!first) output << ',';
    first = false;
    output << '"' << name << "\":" << value;
  };
#define COUNTER(name) field(#name, c.name)
  COUNTER(extent_reads); COUNTER(row_reads); COUNTER(segment_reads); COUNTER(packets);
  COUNTER(live_edges); COUNTER(dummy_edges); COUNTER(source_blocks); COUNTER(source_lines);
  COUNTER(source_terminators); COUNTER(gather_rows); COUNTER(mux_rows); COUNTER(apply_reads);
  COUNTER(apply_writes); COUNTER(source_writes); COUNTER(status_writes); COUNTER(axi_requests);
  COUNTER(axi_completions); COUNTER(axi_beats); COUNTER(axi_completed_beats);
  COUNTER(start_cycle); COUNTER(end_cycle);
#undef COUNTER
  output << "},\"backend_reads\":" << backend.traffic_stats().reads.requests
      << ",\"backend_writes\":" << backend.traffic_stats().writes.requests
      << ",\"arbitration\":" << backend.arbitration_json() << ",\"rounds\":[";
  first = true;
  for (const auto &r : system.rounds()) {
    if (!first) output << ',';
    first = false;
    output << "{\"start\":" << r.start << ",\"apply_done\":" << r.apply_done
        << ",\"writeback_done\":" << r.writeback_done << ",\"status_done\":" << r.status_done
        << ",\"end\":" << r.end << ",\"active_vertices\":" << r.active_vertices << '}';
  }
  output << "],\"invocations\":[";
  first = true;
  for (const auto &r : system.invocations()) {
    if (!first) output << ',';
    first = false;
    output << "{\"round\":" << r.round << ",\"partition\":" << r.partition
        << ",\"worker\":" << r.worker << ",\"stage\":\"" << (r.adapter ? "adapter" : "gather")
        << "\",\"start\":" << r.start << ",\"end\":" << r.end << '}';
  }
  output << "]}\n";
  output.flush();
  if (!output) throw std::runtime_error("routed SST result write failed");
  std::vector<std::uint32_t> external(fixture.layout.vertices);
  for (std::size_t v = 0; v < external.size(); ++v)
    external[fixture.internal_to_external[v]] = state[v] & 0x7fffffffU;
  std::ofstream values(path + ".values.txt");
  for (std::size_t v = 0; v < external.size(); ++v) values << v << ' ' << external[v] << '\n';
  values.flush();
  if (!values) throw std::runtime_error("routed SST value write failed");
}
} // namespace spine::sim::sst_adapter
