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
                  std::size_t contexts = 16, bool finite = false, bool stalled = true,
                  bool routed = false) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  const auto banks = routed ? 3U : 1U;
  MockMemoryBackend backend("memory", clock, {banks, 64, 1, 4, 64, true});
  const FixedAxiPortConfig cfg{.memory_channels = banks, .channel = 0,
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
  backend.initialize_payload(routed ? 1 : 0, 0x2000, bytes({invalid_row ? 0ULL : 64ULL}));
  backend.initialize_payload(routed ? 2 : 0, 0x4000, bytes(heads));
  if (routed) {
    // Wrong-bank payloads must not accidentally let an ignored route pass.
    backend.initialize_payload(0, 0x2000, bytes({0}));
    backend.initialize_payload(0, 0x4000, bytes({0, 0, 0, 0}));
    backend.initialize_payload(1, 0x4000, bytes({0, 0, 0, 0}));
  }
  const SearchMetadataChannels channels = routed ? SearchMetadataChannels{1, 2} : SearchMetadataChannels{};
  auto search = finite
      ? make_finite_search("search", clock, 1, count, 0, 0x2000, 0x4000, updates, metadata, output, channels)
      : make_parallel_search("search", clock, 1, count, 0,
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
    if ((!stalled || (cycles > 2000 && cycles % 7 == 0)) && output.try_pop(update)) {
      require(update.global_index == 1 + received * 4 && update.source == 0 &&
          update.partition == 0 && update.segment_head_slot == (received % 4) * 16 &&
          update.destination == 11 + (received % 4) * 10 && update.weight == 7 &&
          update.delete_op == bool(received & 1) &&
          update.last_binary_head == heads[(received % 4) < 2 ? 1 : 3],
          "ordered weighted search packet mismatch");
      ++received;
    }
    scheduler.step();
    if (search->done() && output.empty() && updates.idle() && metadata.idle()) break;
  }
  if (invalid_row) {
    require(search->failed(), "empty source row was not rejected");
    return cycles;
  }
  if (!search->done() || received != count || backend.outstanding() != 0)
    throw std::runtime_error("bounded search did not close: count=" + std::to_string(count) +
        " finite=" + std::to_string(finite) + " stalled=" + std::to_string(stalled) +
        " cycles=" + std::to_string(cycles) + " received=" + std::to_string(received) +
        " failure=" + search->failure());
  require(search->row_reads() == count, "search row ledger mismatch");
  require(search->binary_probes() == count * 2, "search binary ledger mismatch");
  require(metadata.master().stats().read_bytes == count * 24,
          "metadata routing changed accepted bytes");
  if (stalled && count > 1) require(output.stats().push_stalls != 0, "output backpressure not exercised");
  if (finite) {
    const auto channels = search->channels();
    require(channels.size() == 339, "finite search channel topology mismatch");
    std::size_t bits = 0;
    for (const auto& channel : channels) {
      require(channel.occupancy == 0 && channel.stats.pushes == channel.stats.pops &&
          channel.stats.max_occupancy <= channel.depth, "finite search channel did not conserve/drain");
      bits += channel.depth * channel.token_bits;
    }
    require(bits == 38608, "finite search declared FIFO bit budget mismatch");
  }
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

void metadata_budget_configuration(unsigned credits, bool parallel, bool valid) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, 3, 1, 32, 64, true});
  GraSuNativeConfig config;
  config.compact_parallel_search = parallel;
  config.compact_metadata_credits = credits;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  const auto layout = GraSuPartitionedPmaLayout::build(8, 65536, {}, {});
  bool rejected = false;
  try {
    GraSuPmaUpdateSystem system(scheduler, clock, backend, layout, {}, config);
    const auto ports = system.port_observations();
    require(ports.size() == (parallel ? 18 : 22), "metadata control added masters");
    for (const auto& port : ports) {
      const auto limit = credits && port.name.starts_with("grasu-row") ? credits : 16;
      require(port.config.max_pending_requests == limit &&
          port.config.max_outstanding_bursts == limit &&
          port.config.read_reorder_capacity == limit &&
          port.config.beat_issues_per_cycle == 1 &&
          port.config.response_beats_per_cycle == 1,
          "metadata control changed unrelated credits or issue bandwidth");
    }
  } catch (const std::invalid_argument& error) {
    rejected = std::string(error.what()).find("metadata credits") != std::string::npos;
  }
  require(rejected != valid, "invalid metadata budget admission");
}

void finite_geometry_configuration(bool parallel, unsigned contexts, unsigned credits, bool valid) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {32, 3, 1, 32, 64, true});
  GraSuNativeConfig config;
  config.compact_finite_search = true;
  config.compact_parallel_search = parallel;
  config.compact_search_contexts = contexts;
  config.compact_metadata_credits = credits;
  config.pma_word_abi = GraSuPmaWordAbi::kWeightedFullWord;
  const auto layout = GraSuPartitionedPmaLayout::build(8, 65536, {}, {});
  bool rejected = false;
  try { GraSuPmaUpdateSystem system(scheduler, clock, backend, layout, {}, config); }
  catch (const std::invalid_argument& error) {
    rejected = std::string(error.what()).find("finite search requires") != std::string::npos;
  }
  require(rejected != valid, "finite search geometry admission mismatch");
}

void reject_bad_finite_response(bool metadata_fault, unsigned fault) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("unused-memory", clock, {1, 1, 1, 1, 64, true});
  const FixedAxiPortConfig config{.memory_channels = 1, .channel = 0,
      .data_width_bytes = 8, .request_fifo_depth = 4, .response_fifo_depth = 4};
  FixedAxiPort updates("updates", clock, config, backend);
  auto metadata_config = config; metadata_config.initiator_id = 1;
  FixedAxiPort metadata("metadata", clock, metadata_config, backend);
  Fifo<LocatedUpdate> output("output", clock, 1);
  auto search = make_finite_search("search", clock, 0, 1, 0, 0x2000, 0x4000,
                                   updates, metadata, output);
  // Script responses at the AXI boundary; do not register either memory master.
  for (auto* port : {&updates, &metadata}) {
    scheduler.add_component(port->requests());
    scheduler.add_component(port->responses());
  }
  scheduler.add_component(output); scheduler.add_component(*search);
  for (unsigned cycle = 0; cycle < 1000 && !search->failed(); ++cycle) {
    for (auto* port : {&updates, &metadata}) {
      AxiRequest request;
      if (!port->requests().try_pop(request)) continue;
      const bool is_metadata = port == &metadata;
      const auto data = !is_metadata ? encode_grasu_pma_edge(11, 7) :
          request.address == 0x2000 ? 64ULL : encode_grasu_pma_edge(10, 7);
      AxiResponse response{.transaction_id = request.transaction_id,
          .operation = MemoryOperation::kRead, .read_data = bytes({data})};
      if (is_metadata == metadata_fault && (fault != 4 || !is_metadata || request.transaction_id == 1)) {
        if (fault == 0) response.transaction_id += 100;
        if (fault == 1) response.read_data.pop_back();
        if (fault == 2) response.success = false;
        if (fault == 3) response.operation = MemoryOperation::kWrite;
        if (fault == 4) {
          if (is_metadata) response.transaction_id = 0;
          else response.read_data = bytes({~std::uint64_t{0}});
        }
      }
      require(port->responses().try_push(response), "scripted response queue blocked");
    }
    scheduler.step();
  }
  require(search->failed() && !search->done(), "bad finite AXI response was accepted");
  const auto expected = fault == 0 || (fault == 4 && metadata_fault) ? "unowned" :
      fault == 4 ? "sentinel" : "malformed";
  require(search->failure().find(expected) != std::string::npos,
          "bad finite AXI response failed for an unrelated reason");
}

void reject_bad_metadata_channel(bool binary) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {3, 1, 1, 1, 64, true});
  const FixedAxiPortConfig config{.memory_channels = 3, .channel = 0};
  FixedAxiPort updates("updates", clock, config, backend);
  auto other = config; other.initiator_id = 1;
  FixedAxiPort metadata("metadata", clock, other, backend);
  Fifo<LocatedUpdate> output("output", clock, 1);
  bool rejected = false;
  try {
    make_finite_search("search", clock, 0, 1, 0, 0x2000, 0x4000, updates, metadata, output,
                       binary ? SearchMetadataChannels{0, 3} : SearchMetadataChannels{3, 0});
  } catch (const std::invalid_argument& error) {
    rejected = std::string(error.what()).find("metadata channel out of range") != std::string::npos;
  }
  require(rejected && backend.traffic_stats().reads.requests == 0,
          "invalid finite route was not rejected before traffic");
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
    for (const auto credits : {0U, 16U, 32U, 64U})
      metadata_budget_configuration(credits, true, true);
    metadata_budget_configuration(0, false, true);
    metadata_budget_configuration(32, false, false);
    metadata_budget_configuration(17, true, false);
    for (const auto count : {0U, 1U, 16U, 63U, 64U, 65U, 127U, 128U, 129U, 257U})
      for (const auto stalled : {false, true})
        require(run(count, false, false, 64, true, stalled) ==
                run(count, true, false, 64, true, stalled), "finite registration order changed cycles");
    run(1, false, true, 64, true);
    require(run(1, false, false, 64, true, false) > run(1, false, false, 64, false, false),
            "finite search stages added no single-update latency");
    finite_geometry_configuration(true, 64, 32, true);
    finite_geometry_configuration(false, 64, 32, false);
    finite_geometry_configuration(true, 16, 32, false);
    finite_geometry_configuration(true, 64, 16, false);
    finite_geometry_configuration(true, 64, 64, false);
    for (const auto metadata : {false, true})
      for (unsigned fault = 0; fault < 5; ++fault) reject_bad_finite_response(metadata, fault);
    for (const auto count : {0U, 1U, 63U, 64U, 65U, 129U, 257U})
      for (const auto stalled : {false, true})
        require(run(count, false, false, 64, true, stalled, true) ==
                run(count, true, false, 64, true, stalled, true),
                "banked finite search depends on registration order");
    run(1, false, true, 64, true, false, true);
    for (const auto binary : {false, true}) reject_bad_metadata_channel(binary);
    std::cout << "parallel search finite/backpressure/order/weight/error tests pass\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
