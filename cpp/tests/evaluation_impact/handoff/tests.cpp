#include "execution.hpp"

#include <iostream>

namespace ht = handoff_test;
using namespace spine::sim;

namespace {
void rejection_tests() {
  const std::array<const char *, 7> labels{"row", "segment", "extent", "source0-reservation",
      "placement", "inflight", "missing-row"};
  for (unsigned kind = 0; kind < labels.size(); ++kind) {
    auto f = ht::fixture(129, false);
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("reject", 150);
    MockMemoryBackend backend("memory", clock, {32, 7, 1, 16, 32, false});
    const auto plan = build_grasu_regraph_runtime_plan(f.layout, f.physical_counts, 1);
    auto native = ht::shard_config(plan, 0, 1);
    if (kind != 6) initialize_grasu_pma_layout_payloads(backend, f.layout.partitions[0], native);
    else backend.initialize_payload(native.pma_channels[0], native.pma_bases[0], std::vector<std::uint8_t>(64, 0xff));
    if (kind == 0) backend.initialize_payload(native.row_channels[0], native.row_offset_base, {1});
    if (kind == 1) backend.initialize_payload(native.pma_channels[0], native.pma_bases[0], {0});
    if (kind == 2) {
      backend.initialize_payload(native.row_channels[0], native.row_offset_base + f.vertices * 8, {0});
    }
    if (kind == 3) {
      f.before.erase(f.before.begin());
      f.layout = GraSuPartitionedPmaLayout::build(f.vertices, 65536, f.before, {}, GraSuPmaWordAbi::kWeightedFullWord);
    }
    const auto bytes = backend.inspect_payload(native.pma_channels[0], native.pma_bases[0], 64);
    RoutedReGraphConfig config;
    config.reuse_resident_pma = true;
    config.compute.cache_segments_per_half = 1;
    config.compute.runtime_physical_updates_per_shard = f.physical_counts;
    if (kind == 4) config.compute.runtime_physical_updates_per_shard = {32768};
    if (kind == 5) {
      backend.register_initiator(999);
      ht::require(backend.try_submit({.initiator_id = 999, .request_id = 1,
          .channel = native.row_channels[0], .operation = MemoryOperation::kRead,
          .address = native.row_offset_base, .bytes = 8, .write_data = {}}), "inflight fixture rejected");
      ht::require(backend.outstanding() != 0, "inflight fixture has no pending request");
    }
    const auto traffic_before = backend.traffic_stats();
    bool rejected = false;
    std::string reason;
    try { RoutedReGraphSystem r(scheduler, clock, backend, f.layout, f.warm, config); }
    catch (const std::exception &error) { rejected = true; reason = error.what(); }
    ht::require(rejected, "invalid resident handoff admitted");
    ht::require(backend.inspect_payload(native.pma_channels[0], native.pma_bases[0], 64) == bytes,
                "rejected resident handoff repaired or rewrote memory");
    ht::require(backend.traffic_stats().reads.requests == traffic_before.reads.requests &&
                backend.traffic_stats().writes.requests == traffic_before.writes.requests,
                "rejected handoff issued traffic");
    std::cout << "HANDOFF_REJECTION {\"case\":\"" << labels[kind] << "\",\"rejected\":true}\n";
    std::cout << "REJECTION_REASON " << labels[kind] << ": " << reason << '\n';
  }
  std::cout << "PASS: seven resident payload/extent/reservation/placement/drain rejections\n";
}
} // namespace

int main() {
  try {
    for (auto [vertices, cache, empty] : {std::tuple{129U, 1U, false},
        std::tuple{65569U, 1U, false}, std::tuple{131105U, 8U, false}, std::tuple{65569U, 1U, true}}) {
      const auto forward = ht::run(vertices, cache, empty, false);
      ht::require(forward == ht::run(vertices, cache, empty, true), "handoff cycles/state/traffic depend on registration order");
    }
    rejection_tests();
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
