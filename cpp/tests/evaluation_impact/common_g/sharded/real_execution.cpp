#include "candidate.hpp"
#include "real_fixture.hpp"

#include <iostream>

int main(int argc, char **argv) {
  namespace sg = sharded_g_test;
  try {
    if (argc != 7) throw std::invalid_argument("usage: real G CASE LATENCY ARM STATE GRAPH UPDATES");
    const std::string name(argv[1]), arm(argv[3]);
    const auto latency = std::stoul(argv[2]);
    sg::require(latency == 64 || latency == 128, "undeclared memory latency");
    sg::require(arm == "original-prepared-shards" || arm == "candidate-four-banks" ||
                    arm == "candidate-runtime-23", "unknown arm");
    const sg::RealFixture fixture(argv[5], argv[6]);
    const auto observation = arm == "original-prepared-shards" ? sg::original(fixture, latency) :
        arm == "candidate-four-banks" ? sg::candidate_four_banks(fixture, latency) : sg::candidate_sharded(fixture, latency);
    sg::require(observation.ddr == 0 && observation.cache == fixture.updates.size() &&
                    observation.rows == fixture.updates.size() && observation.probes == fixture.probes,
                "real operation/search ledger mismatch");
    const auto pma = fixture.touched() * 2 * sg::kCache * 64;
    sg::require(observation.pma_reads == pma && observation.pma_writes == pma,
                "real complete cache cost omitted");
    sg::save_state(argv[4], fixture.expected);
    std::cout << "REAL_G_RESULT {\"case\":\"" << name << "\",\"arm\":\"" << arm
        << "\",\"latency\":" << latency << ",\"vertices\":" << fixture.vertices
        << ",\"live_edges\":" << fixture.live_edges << ",\"physical_updates\":" << fixture.updates.size()
        << ",\"total_shards\":" << fixture.by_shard.size() << ",\"updated_shards\":" << fixture.touched()
        << ",\"cycles\":" << observation.cycles << ",\"read_bytes\":" << observation.reads
        << ",\"write_bytes\":" << observation.writes << ",\"cache_updates\":" << observation.cache
        << ",\"ddr_updates\":" << observation.ddr << ",\"row_reads\":" << observation.rows
        << ",\"binary_probes\":" << observation.probes
        << ",\"multi_segment_updates\":" << fixture.multi_segment_updates
        << ",\"pma_read_bytes\":" << observation.pma_reads << ",\"pma_write_bytes\":" << observation.pma_writes
        << ",\"full_payload_pass\":true,\"timing_kind\":\"declared_prediction\"}\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
