#include <algorithm>
#include <iostream>
#include <numeric>

#include "spine_sim/grasu_update/search.hpp"
#include "spine_sim/grasu.hpp"

using namespace spine::sim;
using namespace spine::sim::grasu_update_detail;

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

std::vector<std::uint8_t> bytes(const std::vector<std::uint64_t>& words) {
  std::vector<std::uint8_t> result;
  for (auto word : words)
    for (unsigned byte = 0; byte < 8; ++byte) result.push_back(word >> (byte * 8));
  return result;
}

std::uint64_t run(unsigned count, bool reverse, bool invalid_row = false,
                  std::size_t contexts = 16) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {1, 64, 1, 4, 64, true});
  const FixedAxiPortConfig cfg{.memory_channels = 1, .channel = 0,
      .initiator_id = 1, .data_width_bytes = 8, .request_fifo_depth = 2,
      .response_fifo_depth = 2, .max_pending_requests = 4,
      .max_outstanding_bursts = 4};
  FixedAxiPort updates("updates", clock, cfg, backend);
  auto second = cfg; second.initiator_id = 2;
  FixedAxiPort metadata("metadata", clock, second, backend);
  Fifo<LocatedUpdate> output("output", clock, 1);
  std::vector<std::uint64_t> input, heads;
  for (unsigned index = 0; index < 4; ++index)
    heads.push_back(encode_grasu_pma_edge(10 + index * 10, 7));
  for (unsigned index = 0; index < count; ++index)
    input.push_back((std::uint64_t(index & 1) << 63) |
        encode_grasu_pma_edge(11 + (index % 4) * 10, 7));
  backend.initialize_payload(0, 0, bytes(input));
  backend.initialize_payload(0, 0x2000, bytes({invalid_row ? 0ULL : 64ULL}));
  backend.initialize_payload(0, 0x4000, bytes(heads));
  auto search = make_parallel_search("search", clock, 1, count, 0,
                                    0x2000, 0x4000, updates, metadata, output, contexts);
  if (reverse) {
    scheduler.add_component(*search); scheduler.add_component(output);
    metadata.register_components(scheduler); updates.register_components(scheduler);
    scheduler.add_component(backend);
  } else {
    scheduler.add_component(backend);
    updates.register_components(scheduler); metadata.register_components(scheduler);
    scheduler.add_component(output); scheduler.add_component(*search);
  }
  unsigned received = 0;
  std::uint64_t cycles = 0;
  for (; cycles < 200000 && !search->failed(); ++cycles) {
    LocatedUpdate update;
    if (cycles > 2000 && cycles % 7 == 0 && output.try_pop(update)) {
      require(update.global_index == 1 + received * 4 && update.source == 0 &&
          update.partition == 0 && update.segment_head_slot == (received % 4) * 16 &&
          update.destination == 11 + (received % 4) * 10 && update.weight == 7 &&
          update.delete_op == bool(received & 1), "ordered weighted search packet mismatch");
      ++received;
    }
    scheduler.step();
    if (search->done() && output.empty() && updates.idle() && metadata.idle()) break;
  }
  if (invalid_row) {
    require(search->failed(), "empty source row was not rejected");
    return cycles;
  }
  require(search->done() && received == count && backend.outstanding() == 0,
          "bounded search did not close");
  require(search->row_reads() == count, "search row ledger mismatch");
  if (count > 1) require(output.stats().push_stalls != 0, "output backpressure not exercised");
  for (auto* port : {&updates, &metadata}) {
    const auto& stats = port->master().stats();
    require(stats.requests_accepted == stats.requests_completed &&
        stats.beats_issued == stats.beats_completed, "AXI search requests not conserved");
  }
  return cycles;
}

void reject_unsupported_configuration(unsigned kind) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, 3, 1, 32, 64, true});
  GraSuNativeConfig config;
  config.compact_parallel_search = true;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  if (kind == 0) config.pma_word_abi = GraSuPmaWordAbi::kNormalizedWeighted;
  if (kind == 1) {
    config.explicit_runtime_regions = true;
    config.binary_channels[0] = 1;
  }
  const auto vertices = kind == 2 ? 131072U : 8U;
  const auto layout = GraSuPartitionedPmaLayout::build(vertices, 65536, {}, {});
  bool rejected = false;
  try {
    GraSuPmaUpdateSystem system(scheduler, clock, backend, layout, {}, config);
  } catch (const std::invalid_argument& error) {
    rejected = std::string(error.what()).find("one full-word destination window") != std::string::npos;
  }
  require(rejected, "unsupported parallel-search composition accepted");
}
}  // namespace

int main() {
  try {
    for (const auto contexts : {16U, 64U}) {
      for (const auto count : {0U, 1U, 16U, 17U, 63U, 64U, 65U, 257U})
        require(run(count, false, false, contexts) == run(count, true, false, contexts),
                "registration order changed cycles");
      run(1, false, true, contexts);
    }
    bool rejected = false;
    try { run(1, false, false, 17); }
    catch (const std::invalid_argument&) { rejected = true; }
    require(rejected, "unsupported context count accepted");
    for (unsigned kind = 0; kind < 3; ++kind) reject_unsupported_configuration(kind);
    std::cout << "parallel search finite/backpressure/order/weight/error tests pass\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
