#include "observed.hpp"

#include <iostream>
#include <iterator>

int main(int argc, char **argv) {
  namespace sg = sharded_g_test;
  try {
    if (argc != 7) throw std::invalid_argument("usage: metadata G CASE LATENCY ARM STATE GRAPH UPDATES");
    const std::string name(argv[1]), arm(argv[3]), state(argv[4]);
    const auto latency = std::stoul(argv[2]);
    sg::require(latency == 64 || latency == 128, "undeclared memory latency");
    const bool observed = arm == "candidate-runtime-23" || arm == "runtime-row-copies" ||
        arm == "runtime-binary-copies" || arm == "runtime-both-copies";
    sg::require(observed || arm == "original-prepared-shards" || arm == "candidate-four-banks", "unknown arm");
    const sg::RealFixture fixture(argv[5], argv[6]);
    sg::MetadataObservation sample;
    const auto work = observed ? (sample = sg::observe_runtime(fixture, latency, arm)).work :
        arm == "original-prepared-shards" ? sg::original(fixture, latency) : sg::candidate_four_banks(fixture, latency);
    sg::require(work.ddr == 0 && work.cache == fixture.updates.size() &&
                    work.rows == fixture.updates.size() && work.probes == fixture.probes,
                "metadata operation/search ledger mismatch");
    const auto pma = fixture.touched() * 2 * sg::kCache * 64;
    sg::require(work.pma_reads == pma && work.pma_writes == pma, "metadata complete cache cost omitted");
    sg::save_state(state, fixture.expected);
    std::cout << "METADATA_G_RESULT {\"case\":\"" << name << "\",\"arm\":\"" << arm
        << "\",\"latency\":" << latency << ",\"vertices\":" << fixture.vertices
        << ",\"live_edges\":" << fixture.live_edges << ",\"physical_updates\":" << fixture.updates.size()
        << ",\"total_shards\":" << fixture.by_shard.size() << ",\"updated_shards\":" << fixture.touched()
        << ",\"cycles\":" << work.cycles << ",\"read_bytes\":" << work.reads
        << ",\"write_bytes\":" << work.writes << ",\"cache_updates\":" << work.cache
        << ",\"ddr_updates\":" << work.ddr << ",\"row_reads\":" << work.rows
        << ",\"binary_probes\":" << work.probes << ",\"multi_segment_updates\":" << fixture.multi_segment_updates
        << ",\"pma_read_bytes\":" << work.pma_reads << ",\"pma_write_bytes\":" << work.pma_writes
        << ",\"full_payload_pass\":true,\"timing_kind\":\"declared_prediction\",\"diagnostics\":";
    if (observed) {
      sample.diagnostics.write(state + ".diagnostics.json");
      std::ifstream input(state + ".diagnostics.json");
      sg::require(input.is_open(), "cannot open diagnostic payload");
      const std::string payload{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
      sg::require(!input.bad() && !payload.empty(), "cannot read diagnostic payload");
      std::cout << payload << ",\"resources\":{\"extra_metadata_bytes\":" << sample.extra_metadata_bytes
          << ",\"row_allocated_bytes\":" << sample.row_bytes << ",\"binary_allocated_bytes\":" << sample.binary_bytes
          << ",\"allocated_bytes\":" << sample.allocated_bytes << ",\"channel_span_bytes\":" << sample.channel_span_bytes
          << ",\"used_channels\":" << sample.used_channels << ",\"row_channels\":[";
      for (std::size_t i = 0; i < 4; ++i) std::cout << (i ? "," : "") << sample.config.row_channels[i];
      std::cout << "],\"binary_channels\":[";
      for (std::size_t i = 0; i < 4; ++i) std::cout << (i ? "," : "") << sample.config.binary_channels[i];
      std::cout << "]}";
    } else std::cout << "null,\"resources\":null";
    std::cout << "}\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
