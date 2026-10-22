#pragma once

#include <filesystem>
#include <fstream>

#include "spine_sim/routed_regraph.hpp"

namespace evaluation_impact {
inline void write_wait_observations(const spine::sim::RoutedReGraphSystem& system,
                                    const std::filesystem::path& directory) {
  const auto observations = system.observation();
  std::ofstream frontends(directory / "frontend_waits.csv");
  std::ofstream sources(directory / "source_waits.csv");
  std::ofstream backend(directory / "backend_waits.csv");
  for (auto* stream : {&frontends, &sources, &backend})
    stream->exceptions(std::ios::failbit | std::ios::badbit);
  frontends << "worker,packets,emitted,source_waits,edge_waits,output_stalls,pipeline_stalls,"
               "request_stalls,source_lines,gather_reset,gather_merge,gather_drain,"
               "gather_output_stalls,gather_conflicts,gather_rows\n";
  for (std::size_t i = 0; i < observations.frontends.size(); ++i) {
    const auto& f = observations.frontends[i];
    frontends << i << ',' << f.packets << ',' << f.emitted << ',' << f.source_waits << ','
        << f.edge_waits << ',' << f.output_stalls << ',' << f.pipeline_stalls << ','
        << f.request_stalls << ',' << f.source_lines << ',' << f.gather_reset << ','
        << f.gather_merge << ',' << f.gather_drain << ',' << f.gather_output_stalls << ','
        << f.gather_conflicts << ',' << f.gather_rows << '\n';
  }
  sources << "service,blocks,lines,terminators,parents,completions,output_stalls,issue_stalls,max_pending\n";
  for (std::size_t i = 0; i < observations.sources.size(); ++i) {
    const auto& s = observations.sources[i];
    sources << i << ',' << s.blocks << ',' << s.lines << ',' << s.terminators << ','
        << s.parents << ',' << s.completions << ',' << s.output_stalls << ','
        << s.issue_stalls << ',' << s.max_pending << '\n';
  }
  const auto& b = observations.backend;
  backend << "merger_output_stalls,apply_output_stalls,apply_read_stalls,apply_pipeline_stalls,"
             "apply_write_stalls,writeback_pipeline_stalls,writeback_write_stalls,"
             "apply_max_reads,apply_max_pipeline,apply_max_writes,writeback_max_pipeline,"
             "writeback_max_writes\n";
  backend << b.merger_output_stalls << ',' << b.apply_output_stalls << ',' << b.apply_read_stalls
      << ',' << b.apply_pipeline_stalls << ',' << b.apply_write_stalls << ','
      << b.writeback_pipeline_stalls << ',' << b.writeback_write_stalls << ','
      << b.apply_max_reads << ',' << b.apply_max_pipeline << ',' << b.apply_max_writes << ','
      << b.writeback_max_pipeline << ',' << b.writeback_max_writes << '\n';
  frontends.close(); sources.close(); backend.close();
}
}  // namespace evaluation_impact
