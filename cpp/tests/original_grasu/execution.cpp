#include <iostream>

#include "fixture.hpp"

namespace {
using namespace grasu_test;
unsigned number(const char* text) {
  std::size_t used{}; const auto value = std::stoul(text, &used);
  if (used != std::string(text).size() || value > 100000000) throw std::invalid_argument("G argument bound");
  return static_cast<unsigned>(value);
}
}

int main(int argc, char** argv) {
  try {
    if (argc != 9) throw std::invalid_argument("usage: G fixture capture depth latency credits reverse max_cycles trace");
    const std::filesystem::path capture(argv[2]);
    if (!std::filesystem::is_directory(capture) || !std::filesystem::is_empty(capture))
      throw std::invalid_argument("G capture must be an empty existing directory");
    const auto reverse = number(argv[6]), trace_enabled = number(argv[8]);
    if (reverse > 1 || trace_enabled > 1) throw std::invalid_argument("G boolean argument");
    Fixture fixture(argv[1]);
    System model(number(argv[3]), number(argv[4]), number(argv[5]), reverse);
    fixture.initialize(model);
    std::ofstream trace(capture / "search.tsv");
    trace << "batch\tkernel\tlane\tkind\taddress\tvalue\n";
    std::vector<std::uint64_t> cycles;
    std::vector<std::array<std::uint64_t, 10>> windows;
    std::array<std::size_t, 4> trace_offsets{};
    std::uint64_t total_updates = 0;
    for (std::size_t batch = 0; batch < fixture.batches.size(); ++batch) {
      const auto start = model.memory.scheduler.event_count();
      model.begin(fixture.batches[batch].updates);
      std::array<std::uint64_t, 10> ends{};
      while (!model.finished() && model.memory.scheduler.event_count() - start < number(argv[7])) {
        model.memory.scheduler.step();
        const auto now = model.memory.scheduler.event_count() - start;
        for (unsigned kernel = 0; kernel < 4; ++kernel)
          if (!ends[kernel] && model.searches[kernel]->finished()) ends[kernel] = now;
        for (unsigned half = 0; half < 2; ++half) {
          if (!ends[4 + half] && model.stores[half]->finished()) ends[4 + half] = now;
          for (unsigned subpath = 0; subpath < 2; ++subpath)
            if (!ends[6 + half * 2 + subpath] && model.ddr[half][subpath]->finished())
              ends[6 + half * 2 + subpath] = now;
        }
      }
      if (!model.finished()) throw std::runtime_error("G finite model exceeded cycle bound");
      cycles.push_back(model.memory.scheduler.event_count() - start); windows.push_back(ends);
      total_updates += fixture.batches[batch].updates.size();
      const auto merged = fixture.verify(model, fixture.batches[batch], batch + 1 == fixture.batches.size() ? capture : std::filesystem::path{});
      if (batch + 1 == fixture.batches.size()) write_file(capture / "merged.u32le", merged);
      for (unsigned kernel = 0; kernel < 4; ++kernel) {
        const auto& rows = model.searches[kernel]->requests();
        for (auto index = trace_offsets[kernel]; index < rows.size(); ++index) if (trace_enabled) {
          const auto& row = rows[index];
          trace << batch << '\t' << kernel << '\t' << row.lane << '\t' << row.kind << '\t' << row.address << '\t' << row.value << '\n';
        }
        trace_offsets[kernel] = rows.size();
      }
    }
    if (!trace) throw std::runtime_error("G search trace write failure");
    std::uint64_t pe_updates = 0, cache_updates = 0, ddr_updates = 0, search_reads = 0;
    for (auto* search : model.searches) {
      search_reads += search->counters().reads;
      if (search->counters().reads != search->counters().acknowledgements ||
          search->counters().ends != 128 * fixture.batches.size()) throw std::runtime_error("G search conservation");
    }
    std::uint64_t reader_updates = 0, merged_updates = 0;
    for (unsigned kernel = 0; kernel < 4; ++kernel) {
      const auto& reader = model.readers[kernel]->counters();
      reader_updates += reader.updates; merged_updates += model.searches[kernel]->counters().updates;
      if (reader.reads != reader.updates || reader.ends != fixture.batches.size() * 64)
        throw std::runtime_error("G edge reader conservation");
    }
    if (reader_updates != total_updates || merged_updates != total_updates) throw std::runtime_error("G search/reader update conservation");
    for (unsigned half = 0; half < 2; ++half) {
      const auto& hot = model.stores[half]->counters();
      if (hot.reads != fixture.batches.size() * g::kHotSegments || hot.writes != hot.reads ||
          hot.acknowledgements != fixture.batches.size() * 2) throw std::runtime_error("G hot memory conservation");
      if (model.cache_dispatch[half]->counters().ends != fixture.batches.size() * 16 ||
          model.ddr_dispatch[half]->counters().ends != fixture.batches.size() * 32) throw std::runtime_error("G PE sentinel conservation");
      for (auto* pe : model.cache[half]) {
        const auto& c = pe->counters(); cache_updates += c.updates;
        if (c.reads != c.updates || c.writes != c.updates || c.ends != fixture.batches.size())
          throw std::runtime_error("G hot PE conservation");
      }
      for (auto* core : model.ddr[half]) {
        const auto& c = core->counters(); ddr_updates += c.updates;
        if (c.reads != c.updates || c.writes != c.updates || c.acknowledgements != c.updates * 2 ||
            c.ends != fixture.batches.size() * 16) throw std::runtime_error("G DDR conservation");
      }
    }
    pe_updates = cache_updates + ddr_updates;
    if (pe_updates != total_updates || model.dispatch->counters().updates != total_updates ||
        model.dispatch->counters().ends != fixture.batches.size() * 4) throw std::runtime_error("G dispatch conservation");
    const auto& traffic = model.memory.backend->traffic_stats();
    const auto fixed = fixture.batches.size() * 2ull * g::kHotSegments * 64;
    if (traffic.reads.bytes != fixed + total_updates * 8 + search_reads * 8 + ddr_updates * 64 ||
        traffic.writes.bytes != fixed + ddr_updates * 64) throw std::runtime_error("G physical payload ledger differs");
    std::uint64_t reads = 0, writes = 0, completed = 0, requests = 0, beats = 0, finished_beats = 0, stalls = 0;
    std::ofstream ports(capture / "ports.tsv");
    ports << "initiator\tbank\twidth\tparents\tcompleted\tbeats\tfinished_beats\treads\twrites\tbackend_stalls\n";
    for (unsigned index = 0; index < model.memory.links.size(); ++index) {
      const auto& link = model.memory.links[index]; const auto& c = link.master->stats();
      reads += c.read_bytes; writes += c.write_bytes; completed += c.requests_completed; requests += c.requests_accepted;
      beats += c.beats_issued; finished_beats += c.beats_completed; stalls += c.backend_submit_stalls;
      if (c.requests_accepted != c.requests_completed || c.beats_issued != c.beats_completed ||
          c.max_outstanding_bursts > 16 || c.zero_filled_write_bytes) throw std::runtime_error("G AXI conservation");
      ports << index + 1 << '\t' << link.bank << '\t' << link.width << '\t' << c.requests_accepted << '\t' << c.requests_completed
            << '\t' << c.beats_issued << '\t' << c.beats_completed << '\t' << c.read_bytes << '\t' << c.write_bytes << '\t' << c.backend_submit_stalls << '\n';
    }
    if (!ports || reads != traffic.reads.bytes || writes != traffic.writes.bytes || !model.memory.drained())
      throw std::runtime_error("G aggregate memory conservation");
    const g::Timing timing;
    std::cout << "G_FINITE_RESULT {\"status\":\"SOURCE16_STATE_AND_FINITE_LEDGER_PASS\",\"timing_kind\":\"declared_prediction\","
              << "\"fifo_depth\":" << number(argv[3]) << ",\"memory_latency\":" << number(argv[4]) << ",\"bank_credits\":" << number(argv[5]) << ","
              << "\"timing\":{\"search_control\":" << timing.search_control << ",\"cache_interval\":" << timing.cache_interval
              << ",\"cache_latency\":" << timing.cache_latency << ",\"ddr_compute\":" << timing.ddr_compute
              << ",\"ddr_sweep_minimum\":" << timing.ddr_sweep_minimum << ",\"ddr_restart\":" << timing.ddr_restart << "},"
              << "\"batches\":" << fixture.batches.size() << ",\"updates\":" << total_updates << ",\"cache_updates\":" << cache_updates
              << ",\"ddr_updates\":" << ddr_updates << ",\"search_reads\":" << search_reads << ",\"read_bytes\":" << reads
              << ",\"write_bytes\":" << writes << ",\"parents\":" << requests << ",\"completed\":" << completed
              << ",\"beats\":" << beats << ",\"finished_beats\":" << finished_beats << ",\"backend_stalls\":" << stalls
              << ",\"contended_bank_cycles\":" << model.memory.backend->arbitration_stats()->contended_cycles << ",\"predicted_cycles\":[";
    for (std::size_t index = 0; index < cycles.size(); ++index) std::cout << (index ? "," : "") << cycles[index];
    std::cout << "],\"component_done_windows\":[";
    for (std::size_t batch = 0; batch < windows.size(); ++batch) {
      std::cout << (batch ? ",[" : "[");
      for (unsigned index = 0; index < 10; ++index) std::cout << (index ? "," : "") << windows[batch][index];
      std::cout << "]";
    }
    std::cout << "],\"fpga_timing_match\":null,\"publication_timing_match\":null}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
