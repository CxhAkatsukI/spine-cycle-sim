#include <iostream>

#include "diagnostics.hpp"

namespace cg = common_g;
namespace {
struct Observation {
  std::uint64_t cycles{}, reads{}, writes{}, cache{}, ddr{}, row_reads{}, probes{};
  std::vector<std::uint8_t> state;
  cg::Diagnostics diagnostics;
};

Observation original(const cg::Fixture& fixture, unsigned latency, unsigned maximum, bool forward, bool diagnose) {
  cg::g::Timing timing;
  timing.cache_forward_pending = forward;
  cg::System system(16, latency, 32, false, timing);
  fixture.initialize(system);
  system.begin(fixture.batches[0].updates);
  Observation result;
  for (; result.cycles < maximum && !system.finished(); ++result.cycles) {
    system.memory.scheduler.step();
    if (diagnose) result.diagnostics.sample(system, result.cycles + 1);
  }
  if (!system.finished()) throw std::runtime_error("original G cycle limit");
  result.state = fixture.verify(system, fixture.batches[0], {});
  const auto traffic = system.memory.backend->traffic_stats();
  result.reads = traffic.reads.bytes; result.writes = traffic.writes.bytes;
  for (const auto* search : system.searches) {
    if (search->counters().reads != search->counters().acknowledgements)
      throw std::runtime_error("original G search requests not drained");
    for (const auto& request : search->requests()) {
      if (request.kind) ++result.probes;
      else ++result.row_reads;
    }
  }
  for (unsigned half = 0; half < 2; ++half) {
    for (const auto* pe : system.cache[half]) result.cache += pe->counters().updates;
    for (const auto* pe : system.ddr[half]) result.ddr += pe->counters().updates;
  }
  for (const auto& link : system.memory.links) {
    const auto& stats = link.master->stats();
    if (stats.requests_accepted != stats.requests_completed || stats.beats_issued != stats.beats_completed || stats.zero_filled_write_bytes)
      throw std::runtime_error("original G AXI requests not conserved");
  }
  if (diagnose) result.diagnostics.finish(system);
  return result;
}

Observation current(const cg::Fixture& fixture, unsigned latency, unsigned maximum, const std::string& arm, bool diagnose) {
  using namespace spine::sim;
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {4, latency, 1, 32, 64, true});
  scheduler.add_component(backend);
  GraSuNativeConfig config;
  config.memory_channels = 4;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  config.compact_parallel_search = arm != "current";
  config.compact_parallel_hot = arm == "parallel_hot";
  config.compact_cached_hot = arm == "cached_hot" || arm.starts_with("cached_hot64");
  config.compact_search_contexts = arm.starts_with("cached_hot64") ? 64 : 16;
  if (arm == "cached_hot64_m32" || arm == "cached_hot64_m32_finite") config.compact_metadata_credits = 32;
  config.compact_finite_search = arm == "cached_hot64_m32_finite";
  if (arm == "cached_hot64_m64") config.compact_metadata_credits = 64;
  GraSuPmaUpdateSystem system(scheduler, clock, backend, cg::layout(fixture), cg::updates(fixture.batches[0]), config);
  system.register_components();
  Observation result;
  for (; result.cycles < maximum && !system.done() && !system.failed(); ++result.cycles) {
    scheduler.step();
    if (diagnose) result.diagnostics.sample(system, result.cycles + 1);
  }
  if (!system.done() || system.failed()) throw std::runtime_error("current G failed: " + system.failure());
  for (unsigned index = 0; index < cg::kSegments; ++index) {
    const auto words = system.inspect_segment(index);
    const auto bytes = cg::g::encode_segments(std::span(&words, 1));
    result.state.insert(result.state.end(), bytes.begin(), bytes.end());
  }
  const auto counters = system.counters();
  const auto traffic = backend.traffic_stats();
  result.reads = traffic.reads.bytes; result.writes = traffic.writes.bytes;
  result.cache = counters.cache_updates; result.ddr = counters.ddr_updates;
  result.row_reads = counters.row_reads; result.probes = counters.binary_probes;
  if (result.reads != counters.update_read_bytes + counters.row_read_bytes + counters.binary_read_bytes + counters.pma_read_bytes ||
      result.writes != counters.pma_write_bytes || backend.outstanding() != 0)
    throw std::runtime_error("current G payload ledger mismatch");
  if (diagnose) result.diagnostics.finish(system);
  system.unregister_components(); scheduler.remove_component(backend);
  return result;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 5 && argc != 6) throw std::invalid_argument("usage: common G INPUT OUTPUT LATENCY ARM [DIAGNOSTICS_JSON]");
    cg::Fixture fixture(argv[1]);
    if (fixture.batches.size() != 1) throw std::runtime_error("one matched batch required");
    const auto latency = std::stoul(argv[3]);
    if (latency != 64 && latency != 128) throw std::invalid_argument("undeclared memory latency");
    const std::string arm(argv[4]);
    if (arm != "original" && arm != "original_forwarded" && arm != "current" &&
        arm != "parallel" && arm != "parallel_hot" && arm != "cached_hot" && arm != "cached_hot64" &&
        arm != "cached_hot64_m32" && arm != "cached_hot64_m64" && arm != "cached_hot64_m32_finite")
      throw std::invalid_argument("unknown common G arm");
    constexpr unsigned maximum = 128000000;
    auto result = arm == "original" || arm == "original_forwarded"
        ? original(fixture, latency, maximum, arm == "original_forwarded", argc == 6)
        : current(fixture, latency, maximum, arm, argc == 6);
    if (result.state != cg::expected(fixture) || result.cache + result.ddr != fixture.batches[0].updates.size())
      throw std::runtime_error("common G full state or update ledger mismatch");
    cg::write_file(argv[2], result.state);
    if (argc == 6) result.diagnostics.write(argv[5]);
    std::cout << "COMMON_G_RESULT {\"arm\":\"" << arm << "\",\"cycles\":" << result.cycles
              << ",\"read_bytes\":" << result.reads << ",\"write_bytes\":" << result.writes
              << ",\"cache_updates\":" << result.cache << ",\"ddr_updates\":" << result.ddr
              << ",\"row_reads\":" << result.row_reads << ",\"binary_probes\":" << result.probes
              << ",\"state_pass\":true,\"timing_kind\":\"declared_prediction\"}\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
