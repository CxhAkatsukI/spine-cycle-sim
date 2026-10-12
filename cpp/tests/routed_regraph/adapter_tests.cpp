#include "adapter_fixture.hpp"
#include "adapter_timing_matrix.hpp"

#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace {
using namespace routed_adapter_test;

void require(bool value, const char *message) {
  if (!value) throw std::runtime_error(message);
}

class Sink final : public Component {
public:
  Sink(ClockId clock, Fifo<ReGraphPmaPacket> &input, std::uint64_t start, std::uint64_t interval)
      : Component("sink", clock), input_(input), start_(start), interval_(interval) {}
  void evaluate(const CycleContext &context) override {
    staged_.reset();
    if (context.domain_cycle >= start_ && context.domain_cycle % interval_ == 0 && !input_.empty()) {
      ReGraphPmaPacket packet;
      if (input_.try_pop(packet)) staged_ = packet;
    }
  }
  void commit(const CycleContext &) override {
    if (staged_) packets.push_back(*staged_);
  }
  std::vector<ReGraphPmaPacket> packets;
private:
  Fifo<ReGraphPmaPacket> &input_;
  std::uint64_t start_, interval_;
  std::optional<ReGraphPmaPacket> staged_;
};

struct Options {
  ReGraphPmaAdapterConfig adapter;
  std::size_t depth{8};
  std::uint64_t memory_latency{20}, sink_start{}, sink_interval{1};
  bool reverse{};
  unsigned partitions{1};
};
struct Result {
  std::uint64_t cycles{}, stream_done{}, adapter_done{};
  ReGraphPmaAdapterCounters counters;
  bool restarted_with_pending_output{};
  bool early_stream_notice{};
};

Result run(const Data &data, Options options) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("core", 150);
  MockMemoryBackend backend("memory", clock, MockMemoryConfig{
      .channels = 32, .latency_cycles = options.memory_latency,
      .accepts_per_channel_per_cycle = 1, .max_outstanding_per_channel = 32,
      .response_queue_depth = 32, .registered_round_robin_arbitration = true});
  FixedAxiPort memory("shared", clock, FixedAxiPortConfig{
      .memory_channels = 32, .channel = 0, .initiator_id = 1,
      .data_width_bytes = 64, .max_burst_beats = 16,
      .request_fifo_depth = 16, .response_fifo_depth = 16,
      .read_beat_fifo_depth = 16, .read_reorder_capacity = 16,
      .max_pending_requests = 16, .max_outstanding_bursts = 16}, backend);
  Fifo<ReGraphPmaPacket> output("edges", clock, options.depth);
  ReGraphPmaAdapter adapter("adapter", clock, options.adapter, memory, output);
  struct Notice {
    ReGraphPmaAdapter *adapter;
    bool early_stream{};
  } notice{&adapter};
  adapter.bind_completion_notifier(&notice, [](void *owner) noexcept {
    auto &value = *static_cast<Notice *>(owner);
    value.early_stream |= value.adapter->stream_complete() && !value.adapter->done();
  });
  Sink sink(clock, output, options.sink_start, options.sink_interval);
  backend.initialize_payload(data.partition.row_channel, data.partition.row_base, bytes(data.rows));
  for (std::size_t bank = 0; bank < 4; ++bank)
    backend.initialize_payload(data.partition.pma_channel[bank], data.partition.pma_base[bank], bytes(data.pma[bank]));
  if (options.reverse) {
    scheduler.add_component(sink);
    scheduler.add_component(adapter);
    scheduler.add_component(output);
    memory.register_components(scheduler);
    scheduler.add_component(backend);
  } else {
    scheduler.add_component(backend);
    memory.register_components(scheduler);
    scheduler.add_component(output);
    scheduler.add_component(adapter);
    scheduler.add_component(sink);
  }
  adapter.start_partition(data.partition);
  bool rejected = false;
  try { adapter.start_partition(data.partition); } catch (const std::logic_error &) { rejected = true; }
  require(rejected, "active adapter restart accepted");
  Result result;
  unsigned started = 1;
  for (; result.cycles < 200000; ++result.cycles) {
    scheduler.step();
    if (adapter.stream_complete() && !result.stream_done) result.stream_done = result.cycles + 1;
    if (adapter.done() && !result.adapter_done) result.adapter_done = result.cycles + 1;
    if (adapter.done() && memory.idle()) {
      if (started < options.partitions) {
        result.restarted_with_pending_output |= !output.empty();
        adapter.start_partition(data.partition);
        ++started;
      } else if (output.empty()) { ++result.cycles; break; }
    }
  }
  require(adapter.done() && memory.idle() && backend.outstanding() == 0, "adapter timed out or leaked requests");
  std::vector<ReGraphPmaPacket> expected;
  for (unsigned partition = 0; partition < options.partitions; ++partition)
    expected.insert(expected.end(), data.expected.begin(), data.expected.end());
  require(sink.packets == expected, "routed adapter packet words or last differ");
  result.counters = adapter.counters();
  result.early_stream_notice = notice.early_stream;
  const auto &count = result.counters;
  const auto visited = options.adapter.stop_after_last
      ? (data.expected.empty() ? 0 : data.last_source + 1) : data.partition.vertices;
  const auto prefetched_rows = options.adapter.prefetch_rows
      ? std::min(data.partition.vertices, (visited + 7) / 8 * 8) : visited;
  const auto expected_reads = options.adapter.row_line_reads ? (prefetched_rows + 7) / 8 : prefetched_rows;
  const auto extents = options.adapter.row_line_reads && !data.partition.vertices ? 0U : 1U;
  const auto requests = (extents + expected_reads + data.partition.slots / 16) * options.partitions;
  require(count.extent_reads == extents * options.partitions && count.row_reads == expected_reads * options.partitions &&
          count.rows_visited == visited * options.partitions,
          "extent or row accounting differs from the bounded prefetch/stop contract");
  std::size_t empty_rows = 0;
  for (std::size_t row = 0; row < visited; ++row)
    empty_rows += data.rows[row * 2] == data.rows[row * 2 + 1];
  require(count.empty_rows == empty_rows * options.partitions &&
          count.empty_exit_cycles == count.empty_rows * options.adapter.empty_segment_exit_cycles,
          "empty exit charged an occupied/skipped row, or did not retire fully");
  require(count.responses == requests && count.packets * 8 == data.partition.slots * options.partitions &&
          count.live_edges + count.dummy_edges == count.packets * 8 &&
          count.segment_reads == data.partition.slots / 16 * options.partitions, "adapter packet/read conservation failed");
  require(memory.master().stats().requests_accepted == requests &&
          memory.master().stats().requests_completed == requests &&
          backend.traffic_stats().reads.bytes == requests * 64 &&
          backend.traffic_stats().writes.bytes == 0, "shared AXI traffic conservation failed");
  require(count.max_pending_reads <= options.adapter.pending_read_capacity &&
          count.max_buffered_segments <= options.adapter.segment_buffer_capacity &&
          output.stats().max_occupancy <= options.depth, "adapter exceeded a finite capacity");
  scheduler.remove_component(sink);
  adapter.unbind_completion_notifier(&notice);
  scheduler.remove_component(adapter);
  scheduler.remove_component(output);
  memory.unregister_components(scheduler);
  scheduler.remove_component(backend);
  return result;
}
} // namespace

int main(int argc, char **argv) {
  try {
    if (argc == 2 && (std::string_view(argv[1]) == "--rtl-matrix" ||
                     std::string_view(argv[1]) == "--rtl-continuous-matrix")) {
      const bool continuous = std::string_view(argv[1]) == "--rtl-continuous-matrix";
      timing_matrix([continuous](const Data &data, bool candidate, unsigned latency, unsigned stall) {
        Options options;
        options.adapter.row_line_reads = true;
        options.adapter.cross_row_pipeline = candidate;
        options.adapter.cross_row.continuous_directory = candidate && continuous;
        options.memory_latency = latency;
        options.sink_start = stall;
        options.depth = 32;
        return run(data, options);
      });
      return 0;
    }
    const bool continuous = argc == 2 && std::string_view(argv[1]) == "--continuous-directory";
    require(argc == 1 || continuous, "unknown adapter test argument");
    std::size_t cases = 0;
    for (const auto format : {ReGraphPmaFormat::kWeighted, ReGraphPmaFormat::kDestination, ReGraphPmaFormat::kUnitWeight})
      for (const auto vertices : {0U, 1U, 8U, 9U, 65U, 1025U})
        for (bool at_end : {false, true})
          for (bool empty : {false, true})
            for (bool prefetch : {false, true})
              for (bool stop : {false, true}) {
                Options options;
                options.adapter.format = format;
                options.adapter.prefetch_rows = prefetch;
                options.adapter.stop_after_last = stop;
                const Data fixture(vertices, at_end, empty, format);
                const auto prior = run(fixture, options);
                options.adapter.empty_segment_exit_cycles = 73;
                const auto corrected = run(fixture, options);
                require(corrected.cycles == prior.cycles + 73 * prior.counters.empty_rows,
                        "isolated empty-row correction is not exactly additive");
                ++cases;
              }
    const Data data(65, false, false, ReGraphPmaFormat::kWeighted);
    const auto baseline = run(data, {});
    Options reversed;
    reversed.reverse = true;
    const auto reverse = run(data, reversed);
    require(reverse.cycles == baseline.cycles, "registration order changed adapter timing");
    Options delayed;
    delayed.memory_latency = 200;
    require(run(data, delayed).cycles > baseline.cycles, "memory latency was bypassed");
    Options pressured;
    pressured.depth = 1;
    pressured.sink_start = 1000;
    pressured.sink_interval = 73;
    const auto pressure = run(data, pressured);
    require(pressure.cycles > baseline.cycles && pressure.counters.output_stalls, "FIFO backpressure was bypassed");
    Options serial;
    serial.adapter.pending_read_capacity = 1;
    require(run(data, serial).cycles > baseline.cycles, "outstanding budget was bypassed");
    Options old;
    old.adapter.stop_after_last = false;
    const auto trailing = run(data, old);
    require(trailing.adapter_done > trailing.stream_done && trailing.cycles > baseline.cycles,
            "adapter and edge-stream completion were incorrectly coupled");
    const auto empty_tail = run(Data(65, false, true, ReGraphPmaFormat::kWeighted), old);
    require(empty_tail.early_stream_notice && empty_tail.adapter_done > empty_tail.stream_done,
            "empty stream completion did not wake its consumer before trailing rows completed");
    for (const auto cache : {0U, 1U, 4U}) run(Data(9, true, false, ReGraphPmaFormat::kWeighted, cache), {});
    Options chained;
    chained.partitions = 2;
    chained.depth = 32;
    chained.sink_start = 2000;
    require(run(data, chained).restarted_with_pending_output,
            "adapter restart was serialized behind previous gather/AXIS drain");
    for (auto options : {Options{}, reversed, delayed, pressured, serial, old, chained}) {
      options.adapter.empty_segment_exit_cycles = 73;
      const auto corrected = run(data, options);
      options.reverse = !options.reverse;
      const auto reordered = run(data, options);
      require(corrected.cycles == reordered.cycles &&
              corrected.counters.empty_exit_cycles == reordered.counters.empty_exit_cycles,
              "empty-row exit changed with component registration order");
    }
    old.adapter.empty_segment_exit_cycles = 73;
    const auto corrected_tail = run(Data(65, false, true, ReGraphPmaFormat::kWeighted), old);
    require(corrected_tail.early_stream_notice && corrected_tail.stream_done == empty_tail.stream_done &&
            corrected_tail.adapter_done == empty_tail.adapter_done + 65 * 73,
            "empty exit incorrectly delayed early stream completion or skipped the tail");
    std::cout << "Routed shared-master PMA adapter PASS cases=" << cases
              << " pressure_latency_registration_and_completion_checks=PASS\n";
    std::size_t wide_cases = 0;
    for (const auto format : {ReGraphPmaFormat::kWeighted, ReGraphPmaFormat::kDestination, ReGraphPmaFormat::kUnitWeight})
      for (const auto vertices : {0U, 1U, 7U, 8U, 9U, 15U, 16U, 17U, 65U, 1025U})
        for (bool at_end : {false, true})
          for (bool empty : {false, true})
            for (bool stop : {false, true}) {
              Options options;
              options.adapter.format = format;
              options.adapter.stop_after_last = stop;
              const Data fixture(vertices, at_end, empty, format);
              const auto narrow = run(fixture, options);
              options.adapter.row_line_reads = true;
              const auto wide = run(fixture, options);
              require(wide.counters.row_reads <= narrow.counters.row_reads &&
                      wide.counters.segment_reads == narrow.counters.segment_reads &&
                      wide.counters.rows_visited == narrow.counters.rows_visited,
                      "whole-line reads changed PMA scan or source traversal");
              options.reverse = true;
              require(run(fixture, options).cycles == wide.cycles,
                      "whole-line timing depends on registration order");
              ++wide_cases;
            }
    for (auto options : {Options{}, delayed, pressured, serial, old, chained}) {
      options.adapter.row_line_reads = true;
      const auto wide = run(data, options);
      options.reverse = true;
      const auto reordered = run(data, options);
      require(wide.cycles == reordered.cycles, "whole-line pressure or chained order differs");
    }
    Options wide;
    wide.adapter.row_line_reads = true;
    const auto wide_baseline = run(data, wide);
    wide.memory_latency = 200;
    require(run(data, wide).cycles > wide_baseline.cycles, "whole-line memory latency bypassed");
    wide.memory_latency = 20;
    wide.depth = 1;
    wide.sink_start = 1000;
    wide.sink_interval = 73;
    require(run(data, wide).counters.output_stalls > 0, "whole-line backpressure bypassed");
    std::cout << "Whole-line directory PASS cases=" << wide_cases
              << " exact_packets_tail_extent_pressure_chained_and_conservation=PASS\n";
    std::size_t cross_cases = 0;
    for (const auto format : {ReGraphPmaFormat::kWeighted, ReGraphPmaFormat::kDestination, ReGraphPmaFormat::kUnitWeight})
      for (const auto vertices : {0U, 1U, 7U, 8U, 9U, 15U, 16U, 17U, 65U, 1025U})
        for (bool at_end : {false, true})
          for (bool empty : {false, true}) {
            Options options;
            options.adapter.format = format;
            options.adapter.row_line_reads = options.adapter.cross_row_pipeline = true;
            options.adapter.cross_row.continuous_directory = continuous;
            const Data fixture(vertices, at_end, empty, format);
            const auto cross = run(fixture, options);
            options.reverse = true;
            require(run(fixture, options).cycles == cross.cycles,
                    "cross-row registration order changed timing");
            ++cross_cases;
          }
    for (const auto format : {ReGraphPmaFormat::kWeighted, ReGraphPmaFormat::kDestination, ReGraphPmaFormat::kUnitWeight})
      for (const auto stride : {1U, 7U})
        for (const auto segments : {1U, 3U, 20U}) {
          const Data dense(17, true, false, format, 4, stride, segments);
          Options options;
          options.adapter.format = format;
          options.adapter.row_line_reads = options.adapter.cross_row_pipeline = true;
          options.adapter.cross_row.continuous_directory = continuous;
          const auto base = run(dense, options);
          require(base.counters.max_pending_reads > 1, "cross-row overlap was not exercised");
          for (unsigned stress = 0; stress < 5; ++stress) {
            auto test = options;
            if (stress == 0) test.adapter.pending_read_capacity = 1;
            if (stress == 1) test.adapter.cross_row.loaded_fifo_capacity = 1;
            if (stress == 2) test.adapter.cross_row.reader_pipeline_capacity = 1;
            if (stress == 3) test.memory_latency = 200;
            if (stress == 4) { test.depth = 1; test.sink_start = 1000; test.sink_interval = 73; }
            const auto result = run(dense, test);
            require(result.cycles >= base.cycles, "cross-row stress bypassed a finite constraint");
            if (stress == 4) require(result.counters.output_stalls > 0, "cross-row output pressure lost");
            test.reverse = true;
            require(run(dense, test).cycles == result.cycles, "cross-row stress registration differs");
            ++cross_cases;
          }
        }
    chained.adapter.row_line_reads = chained.adapter.cross_row_pipeline = true;
    chained.adapter.cross_row.continuous_directory = continuous;
    require(run(data, chained).restarted_with_pending_output, "cross-row restart waited for AXIS tail");
    std::cout << (continuous ? "Continuous-directory structural model PASS cases=" :
                              "Cross-row structural model PASS cases=") << cross_cases
              << " exact_packets_credits_pipeline_loaded_fifo_latency_pressure_restart=PASS\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
