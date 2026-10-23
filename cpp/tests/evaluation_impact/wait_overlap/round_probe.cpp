#include <iostream>

#include "../k4_config.hpp"
#include "../oracle.hpp"
#include "../progress.hpp"
#include "../../routed_regraph/round_execution.hpp"
#include "histogram.hpp"

namespace ei = evaluation_impact;

int main(int argc, char** argv) {
  try {
    ei::st::require(argc == 7, "usage: wait_probe INPUT OUTPUT LATENCY REVERSE ARM SAMPLE");
    const auto input = ei::st::Input::load(argv[1]);
    const auto output = std::filesystem::path(argv[2]);
    ei::st::require(std::filesystem::is_directory(output) && std::filesystem::is_empty(output),
                    "unique empty output required");
    const auto latency = routed_regraph_round_test::number(argv[3]);
    const auto reverse = routed_regraph_round_test::number(argv[4]);
    const auto sample = routed_regraph_round_test::number(argv[6]);
    const auto selected = ei::control(argv[5]);
    ei::st::require(latency > 0 && reverse <= 1 && sample <= 1 &&
        (selected.arm == "prefetch_ready_fullburst" || selected.arm == "prefetch_ready_capacity512"),
        "unsupported diagnostic control");
    const auto oracle = ei::closure(input, 128);
    using namespace spine::sim;
    Scheduler scheduler;
    const auto clock = scheduler.add_clock_mhz("core", 150);
    MockMemoryBackend backend("memory", clock, {32, latency, 1, 32, 32, true});
    scheduler.add_component(backend);
    auto config = ei::k4_configuration(selected);
    config.fixed_rounds = 1;
    config.compute.vertex_state_base = config.compute.source_state_base = 0;
    config.compute.source_state_buffer_stride = input.compact.aligned_vertices * 4ull;
    config.status_address = config.compute.source_state_buffer_stride;
    auto layout = GraSuPartitionedPmaLayout::build(input.compact.vertices, 65536, input.edges, {},
                                                 GraSuPmaWordAbi::kWeightedFullWord);
    RoutedReGraphSystem system(scheduler, clock, backend, std::move(layout), input.initial, config);
    ei::st::require(backend.traffic_stats_by_initiator().size() == ei::k4_physical_masters(selected),
                    "diagnostic physical topology changed");
    system.register_components(reverse);
    ei::wait_overlap::Histogram histogram;
    std::uint64_t cycles = 0;
    for (; cycles < 2'000'000 && !system.done(); ++cycles) {
      scheduler.step();
      system.advance_if_complete();
      if (sample) histogram.observe(system.observation());
    }
    if (!system.done() || system.failed()) throw std::runtime_error(system.failure() + system.diagnostic());
    const auto state = system.encoded_state();
    ei::st::require(system.rounds().size() == 1 && state == oracle.states.front() &&
        system.rounds().front().active_vertices == oracle.active.front(), "one-round oracle mismatch");
    for (unsigned copy = 0; copy < 2; ++copy) {
      ei::st::require(system.source_state(copy, 1) == state, "one-round replica mismatch");
      ei::wt::write_words(output / ("replica" + std::to_string(copy) + ".u32le"), state);
    }
    ei::wt::write_words(output / "primary.u32le", state);
    const auto c = system.counters();
    const auto traffic = backend.traffic_stats();
    ei::st::require(c.live_edges == input.edges.size() && c.axi_requests == c.axi_completions &&
        c.axi_beats == c.axi_completed_beats && backend.outstanding() == 0 &&
        c.packets * 8 == c.live_edges + c.dummy_edges &&
        c.apply_reads == input.compact.aligned_vertices / 16 && c.apply_writes == c.apply_reads &&
        c.source_writes == c.apply_reads * 2 && c.status_writes == 1 &&
        traffic.writes.bytes == input.compact.aligned_vertices * 12ull + 4 &&
        traffic.reads.bytes == (c.extent_reads + c.row_reads + c.segment_reads + c.source_lines + c.apply_reads) * 64,
        "one-round physical conservation failed");
    ei::write_progress(system, output);
    if (sample) histogram.write(output / "wait_overlap.csv");
    std::cout << "WAIT_RESULT {\"cycles\":" << cycles << ",\"read_bytes\":" << traffic.reads.bytes
        << ",\"write_bytes\":" << traffic.writes.bytes << ",\"requests\":" << c.axi_requests
        << ",\"beats\":" << c.axi_beats << ",\"active\":" << oracle.active.front()
        << ",\"passed\":true}\n";
    system.unregister_components();
    scheduler.remove_component(backend);
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
