#pragma once

#include "device.hpp"
#include <iomanip>

namespace original_r_k4 {
inline void report(const std::filesystem::path& output, const Model& model, Binding binding,
                   const Schedule& schedule, const std::string& bdf, const Observation* observation,
                   bool verified) {
  require(bdf.find_first_not_of("0123456789abcdefABCDEF:.") == std::string::npos, "invalid observed BDF");
  require(!verified || observation != nullptr, "verified board report requires observations");
  const auto status = !observation ? "K4_BOARD_HOST_PREFLIGHT_PASS_NOT_FPGA" :
      verified ? "MATCHED_K4_A4_GUARDED_BOARD_CONTROL_PASS" : "K4_BOARD_EXECUTED_NOT_VERIFIED";
  std::ofstream json(output / "result.json");
  json << std::setprecision(17) << "{\n\"schema_version\":1,\n\"status\":\"" << status
       << "\",\n\"binding\":\"" << (binding == Binding::author_initial ? "author_initial" : "csr_degree")
       << "\",\n\"bdf\":\"" << bdf << "\",\n\"vertices\":" << model.original.vertices
       << ",\n\"logical_edges\":" << model.original.logical_edges
       << ",\n\"a4_published_vertices\":" << model.original.published
       << ",\n\"capacity_vertices\":" << model.original.aligned
       << ",\n\"partitions\":" << model.preparation.graph.shards.size()
       << ",\n\"graph_channels\":23,\n\"cache_segments\":131072,\n\"partition_vertices\":65536,\n\"row_line_read\":true"
       << ",\n\"iterations\":1,\n\"damping_numerator\":108,\n\"damping_denominator\":128"
       << ",\n\"base\":0,\n\"dangling_share\":0,\n\"rank_initial\":0,\n\"updates\":0"
       << ",\n\"g_skipped\":true,\n\"source_prepare_skipped\":true,\n\"default_profile_equivalence\":false"
       << ",\n\"publication_match\":false,\n\"same_resource_claim\":false,\n\"convergence_measured\":false"
       << ",\n\"host_inclusive_measured\":false,\n\"board_programmed\":" << (observation ? "true" : "false")
       << ",\n\"hardware_timing_measured\":" << (observation ? "true" : "false")
       << ",\n\"complete_buffers_verified\":" << (verified ? "true" : "false")
       << ",\n\"enqueue_to_completion_ms\":";
  if (observation) json << observation->enqueue_to_completion_ms; else json << "null";
  json << ",\n\"event_union_ns\":";
  if (observation) json << observation->window.busy_ns; else json << "null";
  json << ",\n\"event_span_ns\":";
  if (observation) json << observation->window.span_ns; else json << "null";
  json << ",\n\"worker_partitions\":[";
  for (unsigned worker = 0; worker < 4; ++worker) json << (worker ? "," : "") << schedule.worker_partitions[worker];
  json << "],\n\"commands\":[";
  for (std::size_t index = 0; index < schedule.commands.size(); ++index) {
    const auto& command = schedule.commands[index];
    json << (index ? "," : "") << "{\"role\":\"" << name(command.role) << "\",\"ordinal\":" << command.partition
         << ",\"lane\":" << command.worker << ",\"waits\":[";
    for (std::size_t wait = 0; wait < command.waits.size(); ++wait)
      json << (wait ? "," : "") << command.waits[wait];
    json << "]}";
  }
  json << "],\n\"events\":[";
  if (observation) for (std::size_t index = 0; index < observation->events.size(); ++index) {
    const auto& event = observation->events[index]; const auto& time = observation->times.at(index);
    json << (index ? "," : "") << "{\"role\":\"" << event.role << "\",\"ordinal\":" << event.ordinal
         << ",\"lane\":" << event.lane << ",\"queued_ns\":" << time.queued << ",\"submitted_ns\":" << time.submitted
         << ",\"start_ns\":" << time.start << ",\"end_ns\":" << time.end << "}";
  }
  json << "],\n\"buffers\":";
  describe_buffers(json, model);
  json << "\n}\n";
  json.close(); require(json.good(), "could not save K4 control observation");
}
}  // namespace original_r_k4
